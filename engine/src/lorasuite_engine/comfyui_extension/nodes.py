from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


EMPTY_CHOICE = "No LoraSuite artifacts installed"
_HASH_CACHE: dict[str, tuple[int, int, str]] = {}


def _comfy_modules():
    import comfy.sd
    import comfy.utils
    import folder_paths

    return folder_paths, comfy.sd, comfy.utils


def _artifact_choices() -> list[str]:
    folder_paths, _comfy_sd, _comfy_utils = _comfy_modules()
    choices = [
        name
        for name in folder_paths.get_filename_list("loras")
        if _handoff_path(name) is not None
    ]
    return choices or [EMPTY_CHOICE]


def _handoff_path(lora_name: str) -> Path | None:
    if lora_name == EMPTY_CHOICE:
        return None
    folder_paths, _comfy_sd, _comfy_utils = _comfy_modules()
    lora_path = Path(folder_paths.get_full_path_or_raise("loras", lora_name))
    candidates = [
        lora_path.with_suffix(lora_path.suffix + ".lorasuite-handoff.json"),
        lora_path.with_suffix(lora_path.suffix + ".lorasuite.json"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def _manifest(lora_name: str) -> dict[str, Any]:
    handoff_path = _handoff_path(lora_name)
    if handoff_path is None:
        raise ValueError(f"{lora_name} is not a registered LoraSuite artifact")
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    if payload.get("format") == "lorasuite.comfy-handoff.v1":
        expected_sha = str((payload.get("artifact") or {}).get("checkpoint_sha256") or "")
        if expected_sha:
            actual_sha = _checkpoint_sha256(lora_name)
            if actual_sha != expected_sha:
                raise ValueError(
                    f"{lora_name} no longer matches its LoraSuite checkpoint SHA-256"
                )
        return payload
    return {
        "format": "lorasuite.legacy-sidecar",
        "artifact": {
            "id": payload.get("artifact_id", ""),
            "project_id": "",
            "checkpoint_sha256": payload.get("checkpoint_sha256", ""),
            "checkpoint_name": lora_name,
        },
        "inference": {
            "trigger_token": payload.get("trigger_token", ""),
            "sample_prompts": [],
            "recommended_strength": 1.0,
        },
        "evaluation_report": {},
    }


def _checkpoint_sha256(lora_name: str) -> str:
    folder_paths, _comfy_sd, _comfy_utils = _comfy_modules()
    path = Path(folder_paths.get_full_path_or_raise("loras", lora_name))
    stat = path.stat()
    key = str(path.resolve(strict=False))
    cached = _HASH_CACHE.get(key)
    if cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
        return cached[2]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _HASH_CACHE[key] = (stat.st_size, stat.st_mtime_ns, value)
    return value


def _artifact_values(lora_name: str) -> tuple[str, str, str, str]:
    manifest = _manifest(lora_name)
    inference = manifest.get("inference") or {}
    prompts = inference.get("sample_prompts") or []
    artifact = manifest.get("artifact") or {}
    return (
        str(inference.get("trigger_token") or ""),
        str(prompts[0]) if prompts else "",
        str(artifact.get("id") or ""),
        json.dumps(manifest, sort_keys=True),
    )


class LoraSuiteArtifactInfo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"artifact": (_artifact_choices(),)}}

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("trigger_token", "sample_prompt", "artifact_id", "manifest_json")
    FUNCTION = "describe"
    CATEGORY = "LoraSuite"
    DESCRIPTION = "Reads the canonical LoraSuite artifact manifest without loading model weights."

    def describe(self, artifact: str):
        return _artifact_values(artifact)


class _LoraCache:
    def __init__(self):
        self.loaded_lora = None

    def apply(self, model, clip, lora_name: str, strength_model: float, strength_clip: float):
        folder_paths, comfy_sd, comfy_utils = _comfy_modules()
        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        lora = None
        metadata = None
        if self.loaded_lora is not None and self.loaded_lora[0] == lora_path:
            lora = self.loaded_lora[1]
            metadata = self.loaded_lora[2]
        if lora is None:
            lora, metadata = comfy_utils.load_torch_file(
                lora_path,
                safe_load=True,
                return_metadata=True,
            )
            self.loaded_lora = (lora_path, lora, metadata)
        return comfy_sd.load_lora_for_models(
            model,
            clip,
            lora,
            strength_model,
            strength_clip,
            lora_metadata=metadata,
        )


class LoraSuiteArtifactLoader(_LoraCache):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "artifact": (_artifact_choices(),),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
                "strength_clip": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("model", "clip", "trigger_token", "sample_prompt", "artifact_id", "manifest_json")
    FUNCTION = "load"
    CATEGORY = "LoraSuite"
    DESCRIPTION = "Loads a registered LoraSuite artifact and exposes its trigger and evaluation contract."

    def load(self, model, clip, artifact: str, strength_model: float, strength_clip: float):
        model_lora, clip_lora = self.apply(
            model,
            clip,
            artifact,
            strength_model,
            strength_clip,
        )
        return (model_lora, clip_lora, *_artifact_values(artifact))


class LoraSuiteArtifactLoaderModelOnly(_LoraCache):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "artifact": (_artifact_choices(),),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("model", "trigger_token", "sample_prompt", "artifact_id", "manifest_json")
    FUNCTION = "load"
    CATEGORY = "LoraSuite"
    DESCRIPTION = "Loads a model-only LoraSuite artifact for FLUX, video, and other model-only adapters."

    def load(self, model, artifact: str, strength_model: float):
        model_lora, _clip_lora = self.apply(model, None, artifact, strength_model, 0.0)
        return (model_lora, *_artifact_values(artifact))


class LoraSuiteEvaluationReport:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest_json": ("STRING", {"multiline": True}),
                "workflow_id": ("STRING", {"default": ""}),
                "verdict": (["review", "pass", "fail"],),
                "rating": ("INT", {"default": 0, "min": 0, "max": 5}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "notes": ("STRING", {"multiline": True, "default": ""}),
                "output_path": ("STRING", {"default": ""}),
                "engine_url": ("STRING", {"default": "http://127.0.0.1:8765"}),
                "submit": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report_status",)
    FUNCTION = "report"
    CATEGORY = "LoraSuite"
    OUTPUT_NODE = True
    DESCRIPTION = "Returns a human evaluation to the exact registered LoraSuite artifact."

    def report(
        self,
        manifest_json: str,
        workflow_id: str,
        verdict: str,
        rating: int,
        prompt: str,
        seed: int,
        notes: str,
        output_path: str,
        engine_url: str,
        submit: bool,
    ):
        if not submit:
            return ("Report staged; enable submit to send it to LoraSuite.",)
        manifest = json.loads(manifest_json)
        artifact = manifest.get("artifact") or {}
        report_contract = manifest.get("evaluation_report") or {}
        url = report_contract.get("url") or f"{engine_url.rstrip('/')}/comfyui/evaluation-reports"
        body = {
            "artifact_id": artifact.get("id", ""),
            "checkpoint_sha256": artifact.get("checkpoint_sha256", ""),
            "workflow_id": workflow_id,
            "verdict": verdict,
            "rating": rating,
            "prompt": prompt,
            "seed": seed,
            "output_paths": [output_path] if output_path.strip() else [],
            "notes": notes,
            "metrics": {},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LoraSuite report rejected ({error.code}): {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"LoraSuite engine unavailable: {error.reason}") from error
        return (f"Recorded {payload.get('id', 'evaluation report')}.",)


NODE_CLASS_MAPPINGS = {
    "LoraSuiteArtifactInfo": LoraSuiteArtifactInfo,
    "LoraSuiteArtifactLoader": LoraSuiteArtifactLoader,
    "LoraSuiteArtifactLoaderModelOnly": LoraSuiteArtifactLoaderModelOnly,
    "LoraSuiteEvaluationReport": LoraSuiteEvaluationReport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoraSuiteArtifactInfo": "LoraSuite Artifact Info",
    "LoraSuiteArtifactLoader": "LoraSuite Artifact Loader",
    "LoraSuiteArtifactLoaderModelOnly": "LoraSuite Artifact Loader (Model Only)",
    "LoraSuiteEvaluationReport": "LoraSuite Evaluation Report",
}
