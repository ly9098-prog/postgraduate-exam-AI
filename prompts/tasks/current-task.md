当前任务（2026-05-30）：仅维护 Admin Phase 7 文档同步，不修改业务代码。

背景：后台管理系统 Phase 7（后台 AI 解析设置与全局月度额度）已完成主要实现，并已通过：

- `python3 -m compileall backend/app`
- `npm --prefix admin-frontend run lint`

`npm --prefix admin-frontend run build` 因 Google Fonts 网络获取失败未完成，需后续复验。

同步范围：

- `docs/admin/README.md`
- `docs/admin/PHASE_PLAN.md`
- `docs/admin/ADMIN_API_SPEC.md`
- `docs/admin/RBAC_RULES.md`
- `docs/admin/DB_SCHEMA_ADMIN.md`
- `docs/admin/AUDIT_LOG.md`
- `docs/frontend/ADMIN_UI_RULES.md`
- `docs/project/CHANGELOG.md`
- `prompts/tasks/current-task.md`

已同步要点：

- 后端新增 `admin_ai_settings` / `admin_ai_usage_monthly` 模型与 Alembic migration `i0e1f2a3b4c5_add_admin_ai_settings.py`。
- 新增 `/api/admin/v1/ai-settings` GET/PATCH 与 `/api/admin/v1/ai-settings/usage` GET。
- 新增 `ai_setting:read` / `ai_setting:write` 权限，并在 bootstrap / migration 中 seed。
- `create_import_enrich_task` 前通过 `ensure_ai_parse_allowed` 执行全局关闭与月度额度拦截。
- `super_admin` 只绕过额度，不绕过全局关闭。
- 前端新增独立 `/ai-settings` 页面和侧边栏入口。

# 待同步内容

- 需在可联网环境或完成字体本地化后复验 `npm --prefix admin-frontend run build`。
