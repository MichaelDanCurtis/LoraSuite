import os
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lorasuite_engine.exports import create_runcomfy_image_export
from lorasuite_engine.instagram_browser import (
    InstagramBrowserScanError,
    scan_instagram_url_with_browser_cookies,
)
from lorasuite_engine.ingress import IngressService
from lorasuite_engine.models import SourceKind, VideoBreakdownOptions
from lorasuite_engine.processing import ProcessingService
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
    limit: int = Field(default=24, ge=1, le=100)
    cursor: str | None = None
    scan_mode: Literal["all", "feed", "reels", "tagged"] = "all"


class IngressJobRequest(BaseModel):
    source_kind: SourceKind
    candidate_ids: list[str]
    options: dict[str, object] = Field(default_factory=dict)


class ProcessingJobRequest(BaseModel):
    job_type: Literal["video_breakdown"]
    source_media_item_ids: list[str]
    options: VideoBreakdownOptions = Field(default_factory=VideoBreakdownOptions)


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "tauri://localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.vault_root = vault_root or default_vault_root()

    def ingress_service() -> IngressService:
        return IngressService(app.state.vault_root)

    def processing_service() -> ProcessingService:
        return ProcessingService(app.state.vault_root)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    @app.get("/assets/file")
    def read_vault_asset(path: Path = Query(...)) -> FileResponse:
        asset_path = _validated_vault_asset_path(path, app.state.vault_root)
        if asset_path is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(asset_path)

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
                limit=request.limit,
                cursor=request.cursor,
                scan_mode=request.scan_mode,
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
        job = ingress_service().create_job(
            request.source_kind,
            request.candidate_ids,
            request.options,
        )
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

    @app.post("/processing/jobs")
    def create_processing_job(
        request: ProcessingJobRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        service = processing_service()
        job = service.create_video_breakdown_job(
            source_media_item_ids=request.source_media_item_ids,
            options=request.options,
        )
        background_tasks.add_task(service.process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/processing/jobs")
    def list_processing_jobs() -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in processing_service().list_jobs()]

    @app.get("/processing/jobs/{job_id}")
    def get_processing_job(job_id: str) -> dict[str, object]:
        job = processing_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Processing job not found")
        return job.model_dump(mode="json")

    return app


def _validated_vault_asset_path(path: Path, vault_root: Path) -> Path | None:
    try:
        resolved_path = Path(path).resolve(strict=True)
        resolved_vault = Path(vault_root).resolve(strict=True)
    except OSError:
        return None

    if not resolved_path.is_file() or not resolved_path.is_relative_to(resolved_vault):
        return None
    return resolved_path
