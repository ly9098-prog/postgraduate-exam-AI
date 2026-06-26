from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_auth
from app.core.admin_security import AdminPrincipal, create_admin_token, hash_admin_password
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Role

client = TestClient(app)


class _FakeDb:
    def __init__(self):
        self.commit = AsyncMock()


async def _override_db():
    yield _FakeDb()


def _role():
    return Role(id=1, name="super_admin", display_name="超级管理员", is_system=True)


def _admin_user(password="old-password"):
    return AdminUser(
        id=1,
        username="admin",
        password_hash=hash_admin_password(password),
        display_name="Admin",
        email="admin@example.com",
        is_active=True,
        role_id=1,
    )


def test_admin_login_success(monkeypatch):
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]
    token = create_admin_token(user)
    refresh_token = "refresh-token"

    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
    monkeypatch.setattr(admin_auth, "build_admin_login_response", AsyncMock(return_value=(token, refresh_token, user, role, permissions)))
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "old-password"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == token
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "admin"
    assert data["role"]["name"] == "super_admin"
    assert data["permissions"] == permissions
    assert resp.cookies.get("admin_refresh_token") == refresh_token
    assert user.last_login_at is not None
    assert user.last_login_ip == "testclient"


def test_admin_login_failure_returns_401(monkeypatch):
    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(side_effect=ValueError("用户名或密码错误")))
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "wrong-password"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"


def test_admin_me_rejects_app_token():
    from app.core.security import create_token

    token = create_token(1)

    resp = client.get("/api/admin/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401


def test_admin_me_returns_current_admin(monkeypatch):
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]

    async def override_current_admin():
        return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})

    monkeypatch.setattr(admin_auth, "get_admin_me_response", AsyncMock(return_value={"user": user, "role": role, "permissions": permissions}))
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/auth/me")
    finally:
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "admin"
    assert resp.json()["role"]["name"] == "super_admin"
    assert resp.json()["permissions"] == permissions


def test_admin_logout_blacklists_token(monkeypatch):
    user = _admin_user()
    payload = {"jti": "token-id", "exp": 4102444800}
    blacklist = AsyncMock()

    async def override_current_admin():
        return AdminPrincipal(user, payload)

    monkeypatch.setattr(admin_auth, "blacklist_admin_token", blacklist)
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.post("/api/admin/v1/auth/logout")
    finally:
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    blacklist.assert_awaited_once_with("token-id", 4102444800)


def test_admin_change_password_success(monkeypatch):
    user = _admin_user()
    change_password = AsyncMock()

    async def override_current_admin():
        return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})

    monkeypatch.setattr(admin_auth, "change_admin_password", change_password)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.post(
            "/api/admin/v1/auth/change-password",
            json={"old_password": "old-password", "new_password": "new-password"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    change_password.assert_awaited_once()


# ============================================================
# 补充测试：密码长度校验与 bcrypt 安全
# ============================================================

from app.core.admin_security import BCRYPT_MAX_BYTES, verify_admin_password


class TestPasswordHashAndVerify:
    """hash / verify 基础行为"""

    def test_normal_password_hash_and_verify(self):
        """正常长度密码注册（hash）和登录（verify）成功"""
        password = "SecureP@ss123"
        hashed = hash_admin_password(password)

        assert hashed.startswith("$2b$")
        assert verify_admin_password(password, hashed)

    def test_wrong_password_verify_fails(self):
        """错误密码 verify 返回 False"""
        hashed = hash_admin_password("correct-password")
        assert not verify_admin_password("wrong-password", hashed)

    def test_hashed_password_not_double_hashed(self):
        """verify 接受明文密码，不是 hash 值；hash 值本身不应被当作明文再次 hash"""
        password = "my-plain-password"
        hashed = hash_admin_password(password)

        # 明文密码可以 verify
        assert verify_admin_password(password, hashed)

        # hash 值本身不应能 verify（不是二次 hash）
        assert not verify_admin_password(hashed, hashed)

    def test_hash_produces_unique_salts(self):
        """同一密码两次 hash 产生不同结果（不同 salt）"""
        password = "same-password"
        h1 = hash_admin_password(password)
        h2 = hash_admin_password(password)

        assert h1 != h2  # 不同 salt
        assert verify_admin_password(password, h1)
        assert verify_admin_password(password, h2)


class TestPasswordByteLengthValidation:
    """bcrypt 72 字节限制的防御"""

    def test_oversized_password_hash_raises_value_error(self):
        """超长密码 hash 不触发 bcrypt 底层异常，而是抛出 ValueError"""
        long_password = "a" * 200  # 200 bytes > 72

        try:
            hash_admin_password(long_password)
            raise AssertionError("Expected ValueError")
        except ValueError as exc:
            assert "72" in str(exc)

    def test_oversized_password_verify_raises_value_error(self):
        """超长密码 verify 不触发 bcrypt 底层异常，而是抛出 ValueError"""
        hashed = hash_admin_password("short-password")
        long_password = "b" * 200

        try:
            verify_admin_password(long_password, hashed)
            raise AssertionError("Expected ValueError")
        except ValueError as exc:
            assert "72" in str(exc)

    def test_boundary_72_bytes_succeeds(self):
        """恰好 72 bytes 的密码可以正常 hash 和 verify"""
        password_72 = "a" * 72  # 72 ASCII chars = 72 bytes
        assert len(password_72.encode("utf-8")) == 72

        hashed = hash_admin_password(password_72)
        assert verify_admin_password(password_72, hashed)

    def test_boundary_73_bytes_fails(self):
        """73 bytes 的密码应被拒绝"""
        password_73 = "a" * 73
        assert len(password_73.encode("utf-8")) == 73

        try:
            hash_admin_password(password_73)
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass


class TestMultiBytePasswordHandling:
    """多字节字符（中文、特殊字符）按 UTF-8 字节长度处理"""

    def test_chinese_password_within_byte_limit(self):
        """中文密码在 72 bytes 内可以正常 hash/verify（每个中文字符 3 bytes）"""
        # 20 个中文字符 = 60 bytes < 72
        password = "密码测试" * 5  # 20 chars = 60 bytes
        assert len(password.encode("utf-8")) == 60

        hashed = hash_admin_password(password)
        assert verify_admin_password(password, hashed)

    def test_chinese_password_exceeding_byte_limit(self):
        """中文密码超过 72 bytes 应被拒绝"""
        # 25 个中文字符 = 75 bytes > 72
        password = "密" * 25
        assert len(password.encode("utf-8")) == 75

        try:
            hash_admin_password(password)
            raise AssertionError("Expected ValueError")
        except ValueError as exc:
            assert "72" in str(exc)

    def test_special_characters_password(self):
        """特殊字符密码正常处理"""
        password = "p@$$w0rd!#%^&*()"
        assert len(password.encode("utf-8")) <= 72

        hashed = hash_admin_password(password)
        assert verify_admin_password(password, hashed)

    def test_mixed_multibyte_boundary(self):
        """混合 ASCII + 中文在边界值正确处理"""
        # 60 ASCII + 4 中文 = 60 + 12 = 72 bytes（恰好）
        password = "a" * 60 + "密" * 4
        assert len(password.encode("utf-8")) == 72

        hashed = hash_admin_password(password)
        assert verify_admin_password(password, hashed)

        # 再加一个中文 = 75 bytes（超出）
        password_over = password + "密"
        assert len(password_over.encode("utf-8")) == 75

        try:
            hash_admin_password(password_over)
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass


class TestOversizedPasswordAPIResponse:
    """API 层对超长密码返回 400"""

    def test_login_with_oversized_password_returns_400(self, monkeypatch):
        """登录时超长密码返回 400 而非 500（密码 ≤128 字符但 >72 bytes）"""
        monkeypatch.setattr(
            admin_auth, "authenticate_admin",
            AsyncMock(side_effect=ValueError("密码长度不能超过72字节")),
        )
        app.dependency_overrides[get_db] = _override_db
        try:
            # 100 ASCII chars = 100 bytes > 72, but 100 chars ≤ 128 schema max
            resp = client.post(
                "/api/admin/v1/auth/login",
                json={"username": "admin", "password": "a" * 100},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 400
        assert "72" in resp.json()["detail"]

    def test_login_with_oversized_password_not_401(self, monkeypatch):
        """超长密码返回 400 而非 401（区分验证错误和认证失败）"""
        monkeypatch.setattr(
            admin_auth, "authenticate_admin",
            AsyncMock(side_effect=ValueError("密码长度不能超过72字节")),
        )
        app.dependency_overrides[get_db] = _override_db
        try:
            # 80 ASCII chars = 80 bytes > 72, but 80 chars ≤ 128 schema max
            resp = client.post(
                "/api/admin/v1/auth/login",
                json={"username": "admin", "password": "x" * 80},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 400
        assert resp.status_code != 401
