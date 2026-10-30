"""Private companion inbox, paired LM operations and reviewed local artifact export.

LM owns remote downloads. Local file import remains an action in LoraSuite,
never an extension capability. No cookies or automatic model activation.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request as URLRequest, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError
from lorasuite_engine.library_artifacts import ArtifactLibraryOptions, prepare_previews, finish_export

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from lorasuite_engine.curation import CurationService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.h3_lora import SafeFile, adapter_pairs
from lorasuite_engine.local_origins import is_local_ui_origin
from lorasuite_engine.models import RequestedOutput
from lorasuite_engine.safetensors_metadata import read_safetensors_metadata
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService

EXTENSION = re.compile(r"chrome-extension://[a-p]{32}$")


def public_url(value: str) -> str:
    if not value:
        return ""
    u = urlsplit(value)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
        raise ValueError("Use an HTTP(S) URL without credentials")
    # Preserve numeric model/thread identifiers, never arbitrary signed URLs or token queries.
    from urllib.parse import parse_qs, urlencode
    params = parse_qs(u.query)
    query = urlencode({key: params[key][0] for key in ('modelVersionId', 'id', 't', 'p', 'topic', 'thread', 'page')
                       if key in params and re.fullmatch(r'[0-9]{1,20}', params[key][0])})
    return urlunsplit((u.scheme, u.netloc, u.path, query, ""))


class Capture(BaseModel):
    kind: Literal["image", "video", "audio", "model", "recipe", "page"]
    url: str = Field(min_length=1, max_length=4096)
    page_url: str = Field(min_length=1, max_length=4096)
    title: str = Field(default="", max_length=300)
    project_id: str = Field(min_length=1, max_length=100)
    requested_output: RequestedOutput

    _urls = field_validator("url", "page_url")(public_url)


class CaptureBatch(BaseModel):
    items: list[Capture] = Field(min_length=1, max_length=100)


class PairRequest(BaseModel):
    code: str = Field(min_length=20, max_length=100)


class ManagerConfig(BaseModel):
    port: int = Field(default=8188, ge=1024, le=65535)


class InboxArchive(BaseModel):
    archived: bool


class ImportFile(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    model_type: Literal["loras", "checkpoints", "embeddings"] = "loras"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("LoRA Manager redirected; check the configured port")


class LibraryBridge:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.state = self.root / "library_bridge.json"
        self.auth = self.root / "companion_pairing.json"

    def read(self):
        return json.loads(self.state.read_text()) if self.state.exists() else {"port": 8188, "items": []}

    def save(self, data):
        atomic_write_json(self.state, data)

    def issue_code(self):
        code = secrets.token_urlsafe(24)
        with json_file_lock(self.auth):
            data = json.loads(self.auth.read_text()) if self.auth.exists() else {}
            data.update(code_hash=self.digest(code), code_expires=time.time() + 120, attempts=0)
            self.write_auth(data)
        return {"code": code, "expires_in": 120}

    def write_auth(self, data):
        atomic_write_json(self.auth, data)
        self.auth.chmod(0o600)

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def pair(self, code, origin):
        if not EXTENSION.fullmatch(origin):
            raise ValueError("Pairing must come from a Chrome extension")
        with json_file_lock(self.auth):
            data = json.loads(self.auth.read_text()) if self.auth.exists() else {}
            if data.get("code_expires", 0) < time.time() or data.get("attempts", 0) >= 5:
                raise ValueError("Pairing code expired; create a new code in LoraSuite")
            data["attempts"] = data.get("attempts", 0) + 1
            self.write_auth(data)
            if not secrets.compare_digest(data.get("code_hash", ""), self.digest(code)):
                raise ValueError("Incorrect pairing code")
            token = secrets.token_urlsafe(32)
            self.write_auth({"origin": origin, "token_hash": self.digest(token), "expires": time.time() + 30 * 86400})
            return {"token": token, "expires_in": 30 * 86400}

    def authorize(self, token, origin):
        with json_file_lock(self.auth):
            data = json.loads(self.auth.read_text()) if self.auth.exists() else {}
        return bool(token and EXTENSION.fullmatch(origin) and data.get("origin") == origin
                    and data.get("expires", 0) > time.time()
                    and secrets.compare_digest(data.get("token_hash", ""), self.digest(token)))

    def enqueue(self, batch: CaptureBatch):
        projects = {p.id for p in CharacterProjectService(self.root).list_projects()}
        if any(item.project_id not in projects for item in batch.items):
            raise ValueError("Choose an existing LoraSuite project")
        with json_file_lock(self.state):
            data = self.read()
            keys = {(i["project_id"], i["requested_output"], i["kind"], i["url"]) for i in data["items"]}
            added = []
            active_count = sum(not i.get('archived', False) for i in data['items'])
            for item in batch.items:
                key = (item.project_id, item.requested_output.value, item.kind, item.url)
                if key in keys:
                    continue
                if active_count >= 2000:
                    raise ValueError("Active inbox limit reached (2,000); archive reviewed entries first")
                entry = {**item.model_dump(mode="json"), "id": secrets.token_hex(12), "status": "pending", "created_at": time.time()}
                data["items"].append(entry)
                added.append(entry)
                active_count += 1
                keys.add(key)
            self.save(data)
        return {"added": len(added), "duplicates": len(batch.items) - len(added), "items": added}

    def archive(self, item_id: str, archived: bool):
        with json_file_lock(self.state):
            data = self.read()
            item = next((item for item in data['items'] if item['id'] == item_id), None)
            if item is None:
                raise ValueError('Inbox entry not found')
            if not archived and item.get('archived') and sum(not i.get('archived', False) for i in data['items']) >= 2000:
                raise ValueError('Archive another entry before restoring this one')
            item['archived'] = archived
            self.save(data)
            return item

    def manager_api(self, endpoint: str, payload: dict | None = None, *, timeout: int = 30):
        """Internal LM API transport. Callers supply fixed routes, never page URLs."""
        if not endpoint.startswith('/') or endpoint.startswith('//') or '..' in endpoint.split('?')[0]:
            raise ValueError('Invalid LM API route')
        port = self.read()['port']
        request = URLRequest(f'http://127.0.0.1:{port}/api/lm{endpoint}',
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
        opener = build_opener(ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
        except HTTPError as error:
            # Do not relay upstream messages containing private paths or signed URLs.
            raise ValueError(f'LoRA Manager rejected the operation (HTTP {error.code}). Review its download history or settings.') from error
        if len(raw) > 2_000_000:
            raise ValueError('LoRA Manager response exceeded the bridge limit')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('success') is False or data.get('error'):
            raise ValueError('LoRA Manager could not complete the operation. Review its status and settings.')
        return data

    def manager_media_ready(self, path: str) -> bool:
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or not path.startswith('/example_images_static/') or '..' in path:
            return False
        request = URLRequest(f"http://127.0.0.1:{self.read()['port']}{path}")
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=5) as response:
                return response.headers.get_content_type().startswith(('image/', 'video/')) and bool(response.read(1))
        except OSError:
            return False

    def manager(self, category="loras", page=1, *, roots=False, search=""):
        if category not in {"loras", "checkpoints", "embeddings"}:
            raise ValueError("Unsupported library category")
        if not isinstance(page, int) or page < 1 or page > 100000 or len(search) > 200:
            raise ValueError("Invalid catalog query")
        port = self.read()["port"]
        endpoint = "roots" if roots else "list?" + urlencode({"page": page, "page_size": 24, "search": search})
        url = f"http://127.0.0.1:{port}/api/lm/{category}/{endpoint}"
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(URLRequest(url, headers={"Accept": "application/json"}), timeout=4) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("LoRA Manager response exceeded the bridge limit")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("roots" if roots else "items"), list):
            raise ValueError("Unexpected LoRA Manager API response; pinned bridge needs review")
        return data

    def catalog(self, category="loras", page=1, search=""):
        """Project only display fields from the upstream catalog; never activate a model.

        Upstream roots may include folders the user explicitly configured in LM.
        Missing or out-of-root entries remain visible but cannot be selected.
        No previews are fetched remotely and no Civitai credentials are forwarded.
        """
        data = self.manager(category, page, search=search)
        roots = [Path(p).expanduser().resolve() for p in self.manager(category, roots=True)["roots"] if isinstance(p, str)]
        items = []
        for source in data["items"]:
            if not isinstance(source, dict):
                raise ValueError("Unexpected model catalog entry")
            path = str(source.get("file_path") or "")[:4096]
            local = Path(path)
            available = False
            try:
                available = bool(path and local.is_absolute() and local.is_file()
                                 and any(local.resolve().is_relative_to(r) for r in roots))
            except (OSError, ValueError):
                pass
            civitai = source.get("civitai") if isinstance(source.get("civitai"), dict) else {}
            words = source.get("trainedWords") or source.get("trained_words") or civitai.get("trainedWords") or []
            if not words and "trainedWords" not in source and available:
                # Compatibility with the unmodified pinned LM: its list formatter
                # omits source-independent words. Read only our own bounded local
                # sidecar until the upstream catalog/persistence fix is released.
                sidecar = local.with_suffix('.metadata.json')
                try:
                    if any(sidecar.resolve().is_relative_to(r) for r in roots):
                        with sidecar.open('rb') as handle:
                            raw = handle.read(65537)
                        if len(raw) <= 65536:
                            metadata = json.loads(raw)
                            if metadata.get('metadata_source') == 'lorasuite':
                                words = metadata.get('trainedWords') or []
                except (OSError, ValueError, AttributeError):
                    pass
            if isinstance(words, str):
                words = [words]
            words = [word[:300] for word in words[:32] if isinstance(word, str)] if isinstance(words, list) else []
            items.append({"path": path, "name": str(source.get("model_name") or source.get("file_name") or local.stem)[:300],
                          "category": category, "base_model": str(source.get("base_model") or civitai.get("baseModel") or "Unknown")[:200],
                          "sha256": str(source.get("sha256") or "")[:64], "trigger_words": words,
                          "available": available, "selectable": available and local.suffix.lower() == ".safetensors",
                          "compatibility": "unverified"})
        total = data.get("total", len(items))
        pages = data.get("total_pages", 0)
        if not isinstance(total, int) or not isinstance(pages, int) or total < 0 or pages < 0:
            raise ValueError("Unexpected catalog pagination")
        return {"items": items, "page": page, "page_size": 24, "total": total, "total_pages": pages}

    def copy_model(self, path: Path, category: str, *, title="", expected_sha256="", base_model="Unknown", trigger_words=None, provenance=None):
        """Copy an explicitly approved model and create a non-destructive LM sidecar.

        Callers hold the bridge state lock. A pre-existing sidecar belongs to the
        user/LM and is never rewritten. The source model is never modified.
        """
        if category not in {"loras", "checkpoints", "embeddings"}:
            raise ValueError("Unsupported library category")
        if path.suffix.lower() != ".safetensors":
            raise ValueError("Only safetensors model files are supported; pickle checkpoints are not loaded")
        if path.stat().st_size > 8 * 1024**3:
            raise ValueError("Model import limit is 8 GiB; manage larger checkpoints directly in LoRA Manager")
        inspected = SafeFile(path)
        if not inspected.tensors:
            raise ValueError("Model file has no tensors")
        metadata = read_safetensors_metadata(path)
        h3_layout = False
        try:
            adapter_pairs(inspected)
            h3_layout = True
        except ValueError:
            pass
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if expected_sha256 and not secrets.compare_digest(digest, expected_sha256.lower()):
            raise ValueError("Training checkpoint changed since registration; revalidate the artifact first")
        target = self.root / "model_library" / category / f"{digest}.safetensors"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            partial = target.with_suffix(".partial")
            try:
                shutil.copyfile(path, partial)
                with partial.open("rb") as handle:
                    if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                        raise ValueError("Source changed during import")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        else:
            with target.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                    raise ValueError("Existing library file has changed; review it in LoRA Manager")
        sidecar = target.with_suffix(".metadata.json")
        with json_file_lock(sidecar):
            if not sidecar.exists():
                stat = target.stat()
                atomic_write_json(sidecar, {"file_name": target.stem, "model_name": title or path.stem,
                    "file_path": str(target), "size": stat.st_size, "modified": stat.st_mtime,
                    "sha256": digest, "base_model": base_model, "preview_url": "", "from_civitai": False,
                    "trainedWords": trigger_words or [], "skip_metadata_refresh": True,
                    "metadata_source": "lorasuite", "lorasuite_provenance": provenance or {}})
        return {"path": str(target), "sha256": digest, "model_type": category,
                "h3_fused_layout": h3_layout, "compatibility": "unverified",
                "metadata": {k: v[:2000] for k, v in metadata.items() if k in {"modelspec.title", "modelspec.license", "modelspec.trigger_phrase", "ss_base_model_version", "lorasuite.base_model"}}}

    def register_artifact(self, artifact_id: str, options: ArtifactLibraryOptions | None = None):
        from lorasuite_engine.model_registry import ModelRegistryService
        artifact = ModelRegistryService(self.root).get_artifact(artifact_id)
        if artifact is None:
            raise ValueError("Register and validate this training artifact in LoraSuite first")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", artifact.checkpoint_sha256):
            raise ValueError("Training artifact has no valid integrity hash; revalidate it first")
        previews = prepare_previews(options.preview_paths) if options else []
        provenance = {"artifact_id": artifact.id, "training_run_id": artifact.training_run_id,
                      "project_id": artifact.project_id, "snapshot_id": artifact.snapshot_id,
                      "dataset_fingerprint": artifact.dataset_fingerprint, "model_family": artifact.model_family}
        with json_file_lock(self.state):
            existing_sidecar = (self.root / "model_library/loras" / (artifact.checkpoint_sha256.lower() + ".metadata.json")).exists()
            result = self.copy_model(artifact.checkpoint_path.resolve(strict=True), "loras",
                                     title=artifact.checkpoint_name, expected_sha256=artifact.checkpoint_sha256,
                                     base_model=artifact.base_model or "Unknown",
                                     trigger_words=[artifact.trigger_token] if artifact.trigger_token else [], provenance=provenance)
            data = self.read()
            previous = data.get("training_exports", {}).get(artifact_id)
            if previous and previous.get("sha256") != result["sha256"]:
                previous = None
            receipt = {**(previous or {}), **result, "artifact_id": artifact_id, "provenance": provenance}
            if options is not None:
                receipt = finish_export(self, receipt, options, previews, previous, preserve_metadata=existing_sidecar)
            data.setdefault("training_exports", {})[artifact_id] = receipt
            self.save(data)
            return receipt

    def import_file(self, item_id, request: ImportFile):
        # Serialize approvals, making retry idempotent. No extension can invoke this.
        with json_file_lock(self.state):
            data = self.read()
            item = next((i for i in data["items"] if i["id"] == item_id), None)
            if item is None:
                raise ValueError("Inbox entry not found")
            if item.get('archived'):
                raise ValueError('Restore this inbox entry before importing it')
            if item["status"] == "imported":
                return item
            if not CharacterProjectService(self.root).get_project(item["project_id"]):
                raise ValueError("Destination project no longer exists")
            path = Path(request.path).expanduser().resolve(strict=True)
            if not path.is_file():
                raise ValueError("Choose a downloaded file")
            if item["kind"] == "model":
                item["result"] = self.copy_model(path, request.model_type, title=item["title"],
                                                 provenance={"page_url": item["page_url"], "inbox_id": item["id"]})
            elif item["kind"] in {"image", "video", "audio"}:
                from lorasuite_engine.vault import detect_media_type
                detected = detect_media_type(path)
                if not detected or detected.value != item["kind"]:
                    raise ValueError("Downloaded file type does not match the selected media lane")
                result = VaultService(self.root).import_local_paths([path])
                if result.errors or not result.media_items:
                    raise ValueError("Media import failed: " + str(result.errors))
                ids = [media.id for media in result.media_items]
                for media_id in ids:
                    VaultService(self.root).annotate_media_item(media_id, metadata={"browser_source_page": item["page_url"], "browser_source_url": item["url"], "browser_inbox_id": item["id"]})
                CurationService(self.root).add_to_handoff(ids, project_id=item["project_id"], requested_output=RequestedOutput(item["requested_output"]))
                item["result"] = {"media_item_ids": ids, "review_status": "pending"}
            else:
                raise ValueError("Recipes and pages are saved references only; no automatic workflow execution")
            item["status"] = "imported"
            self.save(data)
            return item


def library_router(root: Path):
    bridge = LibraryBridge(root)
    router = APIRouter(prefix="/library")

    def ui(request: Request):
        origin = request.headers.get("origin", "")
        if origin and not is_local_ui_origin(origin):
            raise HTTPException(403, "This operation is only available in the local LoraSuite UI")

    def extension(request: Request):
        bearer = request.headers.get("authorization", "")
        if not bridge.authorize(bearer.removeprefix("Bearer "), request.headers.get("origin", "")):
            raise HTTPException(401, "Pair this extension in LoraSuite's Model Library")

    @router.get("/status", dependencies=[Depends(ui)])
    def status():
        data = bridge.read()
        try:
            bridge.manager()
            roots = bridge.manager(roots=True)["roots"]
            ready, issue = True, ""
            export_root = (root / "model_library" / "loras").resolve()
            export_ready = any(export_root.is_relative_to(Path(p).resolve()) for p in roots)
            export_issue = "" if export_ready else "Add the training export folder in LoRA Manager to receive LoraSuite adapters."
        except Exception:
            ready, issue = False, "LoRA Manager is not available at the configured port, or its API is incompatible. Open it separately, then retry."
            export_ready, export_issue = False, "Connect to LoRA Manager to check the training export folder."
        return {"ready": ready, "issue": issue, "port": data["port"], "url": f"http://127.0.0.1:{data['port']}/loras",
                "model_root": str(root / "model_library"), "items": data["items"],
                "training_exports": list(data.get("training_exports", {}).values()), "export_ready": export_ready, "export_issue": export_issue}

    @router.post("/config", dependencies=[Depends(ui)])
    def configure(config: ManagerConfig):
        with json_file_lock(bridge.state):
            data = bridge.read()
            data["port"] = config.port
            bridge.save(data)
        return {"port": config.port}

    @router.get("/models", dependencies=[Depends(ui)])
    def models(category: Literal["loras", "checkpoints", "embeddings"] = "loras",
               page: int = Query(default=1, ge=1, le=100000), search: str = Query(default="", max_length=200)):
        try:
            return bridge.catalog(category, page, search)
        except Exception as error:
            raise HTTPException(502, "Could not read the LoRA Manager catalog. Check its connection and refresh.") from error

    @router.post("/training-artifacts/{artifact_id}", dependencies=[Depends(ui)])
    def register_artifact(artifact_id: str, payload: ArtifactLibraryOptions | None = None):
        try:
            return bridge.register_artifact(artifact_id, payload)
        except (OSError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/pairing-code", dependencies=[Depends(ui)])
    def code():
        return bridge.issue_code()

    @router.post("/revoke", dependencies=[Depends(ui)])
    def revoke():
        with json_file_lock(bridge.auth):
            bridge.write_auth({})
        return {"revoked": True}

    @router.post("/pair")
    def pair(payload: PairRequest, request: Request):
        try:
            return bridge.pair(payload.code, request.headers.get("origin", ""))
        except ValueError as error:
            raise HTTPException(403, str(error)) from error

    @router.get("/projects", dependencies=[Depends(extension)])
    def projects():
        return [{"id": p.id, "name": p.name} for p in CharacterProjectService(root).list_projects()]

    @router.get('/companion/context', dependencies=[Depends(extension)])
    def companion_context():
        # Connection facts only: never expose file paths, inbox or settings to
        # the extension. It uses the ordinary LM UI for download review/jobs.
        try:
            bridge.manager(roots=True)
            ready = True
        except Exception:
            ready = False
        return {'manager_ready': ready, 'manager_url': f"http://127.0.0.1:{bridge.read()['port']}/loras"}

    @router.post('/companion/operation', dependencies=[Depends(extension)])
    def retired_companion_operation():
        raise HTTPException(410, 'This companion connection is retired. Update the companion and connect it directly to LoRA Manager.')

    @router.post("/inbox", dependencies=[Depends(extension)])
    def capture(payload: CaptureBatch):
        try:
            return bridge.enqueue(payload)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/inbox/{item_id}/import", dependencies=[Depends(ui)])
    def approve(item_id: str, payload: ImportFile):
        try:
            return bridge.import_file(item_id, payload)
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from error

    @router.post('/inbox/{item_id}/archive', dependencies=[Depends(ui)])
    def archive(item_id: str, payload: InboxArchive):
        try:
            return bridge.archive(item_id, payload.archived)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    return router
