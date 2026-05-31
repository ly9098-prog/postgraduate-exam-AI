# Bugs History

## 2026-05-31 — users.is_banned 缺列导致登录/用户查询失败

- **现象**：接口查询 `users` 时返回 `UndefinedColumnError: column users.is_banned does not exist`，导致按 openid 查询用户失败。
- **原因**：`User` 模型已包含封禁字段，但历史数据库表结构未完成对应迁移；开发环境 `create_all()` 不会补齐既有表缺失列。
- **处理**：在 `backend/app/core/database.py` 的开发环境 `init_db()` 中增加旧表修复逻辑，自动补齐 `is_banned`、`banned_reason`、`banned_at`、`banned_by` 和 `ix_users_is_banned`。
- **验证**：`PYTHONPATH=backend pytest backend/tests/test_api/test_admin_app_users.py backend/tests/test_services/test_admin_app_user_service.py -q` 通过；手工构造旧 SQLite `users` 表验证启动修复可补齐字段和索引。
- **生产说明**：生产 PostgreSQL 仍应执行 `alembic upgrade head`，对应迁移为 `backend/alembic/versions/g7b8c9d0e1f2_users_add_banned.py`。
