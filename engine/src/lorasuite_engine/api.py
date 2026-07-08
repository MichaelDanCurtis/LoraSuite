import os
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from lorasuite_engine.exports import create_runcomfy_image_export
from lorasuite_engine.instagram_browser import (
    InstagramBrowserScanError,
    scan_instagram_url_with_browser_cookies,
)
from lorasuite_engine.ingress import IngressService
from lorasuite_engine.models import SourceKind
from lorasuite_engine.social_helper import scan_instagram_helper_payload
from lorasuite_engine.vault import VaultService


class LocalImportRequest(BaseModel):
    paths: list[Path]


class RunComfyImageExportRequest(BaseModel):
    frames: list[Path]
    output_dir: Path
    caption_template: str
    source_segment_ids: list[str]


class LocalIngressScanRequest(BaseModel):
    roots: list[Path]
    recursive: bool = True


class InstagramHelperScanRequest(BaseModel):
    payload: dict[str, Any]
    include_video_posters_as_image_candidates: bool = True


class InstagramBrowserScanRequest(BaseModel):
    url: str
    browser: str = "chrome"


class IngressJobRequest(BaseModel):
    source_kind: SourceKind
    candidate_ids: list[str]
    options: dict[str, object] = Field(default_factory=dict)


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.state.vault_root = vault_root or default_vault_root()

    def ingress_service() -> IngressService:
        return IngressService(app.state.vault_root)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    @app.post("/vault/import/local")
    def import_local(request: LocalImportRequest) -> dict[str, list[dict]]:
        result = VaultService(app.state.vault_root).import_local_paths(request.paths)
        return result.model_dump(mode="json")

    @app.post("/exports/runcomfy-image")
    def export_runcomfy_image(request: RunComfyImageExportRequest) -> dict[str, object]:
        try:
            package = create_runcomfy_image_export(
                frames=request.frames,
                output_dir=request.output_dir,
                caption_template=request.caption_template,
                source_segment_ids=request.source_segment_ids,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return package.model_dump(mode="json")

    @app.post("/ingress/local/scan")
    def scan_local_ingress(request: LocalIngressScanRequest) -> dict[str, object]:
        result = ingress_service().scan_local_roots(
            request.roots,
            recursive=request.recursive,
        )
        return result.model_dump(mode="json")

    @app.post("/ingress/instagram/helper-scan")
    def scan_instagram_helper(request: InstagramHelperScanRequest) -> dict[str, object]:
        try:
            result = scan_instagram_helper_payload(
                request.payload,
                app.state.vault_root,
                include_video_posters_as_image_candidates=(
                    request.include_video_posters_as_image_candidates
                ),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        ingress_service().store_candidates(result.candidates)
        return result.model_dump(mode="json")

    @app.post("/ingress/instagram/browser-scan")
    def scan_instagram_browser(request: InstagramBrowserScanRequest) -> dict[str, object]:
        try:
            result = scan_instagram_url_with_browser_cookies(
                request.url,
                app.state.vault_root,
                browser=request.browser,
            )
        except InstagramBrowserScanError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        ingress_service().store_candidates(result.candidates)
        return result.model_dump(mode="json")

    @app.get("/ingress/candidates")
    def list_ingress_candidates(source_kind: SourceKind | None = None) -> dict[str, object]:
        candidates = ingress_service().list_candidates(source_kind)
        return {
            "candidates": [
                candidate.model_dump(mode="json") for candidate in candidates
            ],
            "errors": [],
        }

    @app.post("/ingress/jobs")
    def create_ingress_job(
        request: IngressJobRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        job = ingress_service().create_job(request.source_kind, request.candidate_ids)
        background_tasks.add_task(ingress_service().process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/ingress/jobs")
    def list_ingress_jobs() -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in ingress_service().list_jobs()]

    @app.get("/ingress/jobs/{job_id}")
    def get_ingress_job(job_id: str) -> dict[str, object]:
        job = ingress_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Ingress job not found")
        return job.model_dump(mode="json")

    return app
