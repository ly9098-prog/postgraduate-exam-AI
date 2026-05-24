"""Stage 15 部署 — 健康检查端点测试。"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_simple_health():
    """根路径健康检查返回 200。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "env" in data


def test_api_health_endpoint():
    """API 健康检查返回 200 并包含服务状态。"""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "services" in data
    assert "database" in data["services"]
    assert "redis" in data["services"]
    assert "version" in data
    assert "uptime" in data


def test_version_endpoint():
    """版本端点返回版本信息。"""
    resp = client.get("/api/v1/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "commit" in data
    assert "environment" in data


def test_version_contains_build_info():
    """版本端点包含构建信息字段。"""
    resp = client.get("/api/v1/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "1.0.0"
    assert data["environment"] == "development"
    assert "build_at" in data
