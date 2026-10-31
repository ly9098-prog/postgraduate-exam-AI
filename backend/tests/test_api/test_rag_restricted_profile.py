from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import rag
from app.core.security import get_current_user


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(rag.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(app)


def test_rag_routes_hidden_in_restricted_environment(monkeypatch):
    monkeypatch.setattr(rag, "is_restricted_environment", lambda: True)
    client = _client()
    assert client.get("/api/v1/rag/search", params={"query": "auth"}).status_code == 404
    assert client.get("/api/v1/rag/context", params={"query": "auth"}).status_code == 404


def test_rag_routes_not_mounted_in_public_router_when_restricted(monkeypatch):
    import importlib

    from app.api.v1 import router as router_module
    from app.core import deployment_profile

    monkeypatch.setattr(deployment_profile, "is_restricted_environment", lambda: True)
    reloaded = importlib.reload(router_module)
    try:
        paths = {getattr(r, "path", "") for r in reloaded.public_api_router.routes}
        assert not any(p.startswith("/api/v1/rag") for p in paths)
    finally:
        monkeypatch.undo()
        importlib.reload(router_module)
