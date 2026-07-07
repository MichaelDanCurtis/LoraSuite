import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from lorasuite_engine.exports import create_runcomfy_image_export
from lorasuite_engine.vault import VaultService


class LocalImportRequest(BaseModel):
    paths: list[Path]


class RunComfyImageExportRequest(BaseModel):
    frames: list[Path]
    output_dir: Path
    caption_template: str
    source_segment_ids: list[str]


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.state.vault_root = vault_root or default_vault_root()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    @app.post("/vault/import/local")
    def import_local(request: LocalImportRequest) -> dict[str, list[dict]]:
        result = VaultService(app.state.vault_root).import_local_paths(request.paths)
        return result.model_dump(mode="json")

    @app.post("/exports/runcomfy-image")
    def export_runcomfy_image(request: RunComfyImageExportRequest) -> dict[str, object]:
        package = create_runcomfy_image_export(
            frames=request.frames,
            output_dir=request.output_dir,
            caption_template=request.caption_template,
            source_segment_ids=request.source_segment_ids,
        )
        return package.model_dump(mode="json")

    return app
