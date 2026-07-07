from fastapi.testclient import TestClient
import pytest

from lorasuite_engine.api import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(vault_root=tmp_path / "vault")
    with TestClient(app) as test_client:
        yield test_client
