from pathlib import Path

from fastapi import FastAPI


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.state.vault_root = vault_root or Path(".lorasuite/vault")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    return app
