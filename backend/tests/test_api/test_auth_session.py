"""Audit follow-up: auth session, logout, deletion, AI feedback endpoint tests.

Covers scenarios from the pre-launch audit:
- POST /auth/logout (revoke refresh token)
- POST /users/me/deletion-request (soft-delete + reject after)
- POST /ai/feedback (record feedback)
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _login():
    resp = client.post("/api/v1/auth/login", json={"code": "test_code_001"})
    assert resp.status_code == 200
    data = resp.json()
    return data["access_token"], data["refresh_token"]


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_token():
    """POST /auth/logout should succeed and subsequent refresh with same token fails."""
    token, refresh_token = _login()

    # Logout
    resp = client.post("/api/v1/auth/logout", headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["message"] == "已退出登录"

    # Using the same refresh_token should now fail
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


def test_deletion_soft_deletes_user():
    """POST /users/me/deletion-request should soft-delete and reject subsequent requests."""
    token, _ = _login()

    # Request deletion
    resp = client.post("/api/v1/users/me/deletion-request", headers=_auth_header(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "deleted_at" in data
    assert data["deleted_at"] > 0

    # Subsequent requests with same token should be rejected
    resp = client.get("/api/v1/users/me", headers=_auth_header(token))
    assert resp.status_code == 401


def test_deletion_idempotent():
    """Second deletion request should return 400."""
    token, _ = _login()
    resp = client.post("/api/v1/users/me/deletion-request", headers=_auth_header(token))
    assert resp.status_code == 200

    resp = client.post("/api/v1/users/me/deletion-request", headers=_auth_header(token))
    assert resp.status_code == 400


def test_ai_feedback_records():
    """POST /ai/feedback should record feedback without error."""
    token, _ = _login()

    resp = client.post(
        "/api/v1/ai/feedback",
        headers=_auth_header(token),
        json={"source": "dashboard", "feedback_type": "内容有误"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "反馈已提交，感谢您的帮助"
