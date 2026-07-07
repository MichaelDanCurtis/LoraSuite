import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from lorasuite_engine.vault import VaultService


class LocalImportRequest(BaseModel):
    paths: list[Path]


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
        media_items = VaultService(app.state.vault_root).import_local_paths(request.paths)
        return {
            "media_items": [
                media_item.model_dump(mode="json") for media_item in media_items
            ]
        }

    return app
