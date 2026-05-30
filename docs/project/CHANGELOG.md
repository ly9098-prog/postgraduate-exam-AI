# 变更日志

> 记录项目重大变更。

---

## 2026-05-30

- **Admin Phase 7: 后台 AI 解析设置与全局月度额度完成**
  - 后端新增 `admin_ai_settings`、`admin_ai_usage_monthly` 模型与 Alembic migration `i0e1f2a3b4c5_add_admin_ai_settings.py`。
  - 新增 `GET/PATCH /api/admin/v1/ai-settings` 与 `GET /api/admin/v1/ai-settings/usage`。
  - 新增 `ai_setting:read`、`ai_setting:write` 权限，并在 bootstrap / migration seed 中覆盖。
  - `create_import_enrich_task` 创建任务前通过 `ensure_ai_parse_allowed` 执行全局关闭与月度额度拦截；`super_admin` 只绕过额度，不绕过全局关闭。
  - 前端新增 `/ai-settings` 独立页面与侧边栏入口。
  - 已通过 `python3 -m compileall backend/app` 与 `npm --prefix admin-frontend run lint`；Next build 因 Google Fonts 网络获取失败未完成。
  - 变更原因：同步 Admin Phase 7 已实现状态；受影响文档为 `docs/admin/README.md`、`docs/admin/PHASE_PLAN.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/RBAC_RULES.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/AUDIT_LOG.md`、`docs/frontend/ADMIN_UI_RULES.md`。

- **Admin Phase 6: Next.js Admin Dashboard 前端主要实现完成**
  - 新增 `admin-frontend`，使用 Next.js 16、React 19、React Query、TanStack Table、Zustand、Recharts 与 Tailwind CSS 4。
  - 页面覆盖 `/dashboard`、`/login`、`/app-users`、`/admin-users`、`/questions`、`/review`、`/roles`、`/audit-logs`。
  - Phase 6 前端仅消费 `/api/admin/v1`，不修改后端 API、DB schema 或权限语义。
  - 修复 build/lint 问题，并同步 audit-log 查询参数别名：`pageSize`、`resourceType`、`from`、`to`。
  - 已通过 `npm --prefix admin-frontend run lint` 与 `npm --prefix admin-frontend run build`。
  - 变更原因：同步 Admin Phase 6 前端实现状态与文档边界；受影响文档为 `docs/admin/README.md`、`docs/admin/PHASE_PLAN.md`、`docs/frontend/ADMIN_UI_RULES.md`。

## 2026-05-29

- **Admin Phase 5: 审计日志与统计后端完成**
  - 新增 `GET /api/admin/v1/audit-logs` 与 `GET /api/admin/v1/audit-logs/{id}`，支持多维过滤、分页、默认近 183 天与 1 年跨度限制。
  - 新增 `GET /api/admin/v1/dashboard/overview`、`/daily`、`/questions-stats`，覆盖总览、每日趋势与题目分布统计。
  - Dashboard overview 使用现有 FastAPI `app.core.cache`，支持 TTL 抖动与防穿透锁；Redis 不可用时降级直查 DB。
  - 变更原因：同步 Admin Phase 5 后端实现状态与实际 FastAPI/SQLAlchemy 方案；受影响文档为 `docs/admin/*` API、审计日志与 Redis 规划。

## 2026-05-24

- **Stage 11: 刷题系统重构** — PracticeRecord 从会话级改为逐题记录
  - 新增 `GET /practice/questions` 支持随机/顺序模式 + 知识点筛选
  - 新增 `POST /practice/submit` 单题提交（大小写不敏感判题）
  - 新增 `POST /practice/batch-submit` 批量提交
  - 新增 `GET /practice/stats` 刷题统计（含连续天数）
  - 新增 `GET /questions/{id}/detail` 含答案详情（答后可见）
  - 答错自动同步错题本，错题重做触发 SM-2 更新
  - 小程序刷题页支持随机/顺序模式切换
- 文档结构重构：将 `/docs` 和 `/prompts` 按职责分类，建立 AI 工程化文档体系
- 新增导入管线开发 Prompt（stage1-9）
- 新增 features/ 目录架构设计

## 2026-05-22

- CURRENT_ARCHITECTURE.md 基于代码真实状态更新
- 记录 API 端点总数（47个）和已知技术债务

## 更早

- MVP 核心功能开发完成
- 各阶段开发文档归档到 `docs/achieve/`
