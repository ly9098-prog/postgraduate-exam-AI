# 变更日志

> 记录项目重大变更。

---

## 2026-05-31

- **Redis-backed 图片导入状态完成**
  - `GET /api/v1/import/pipelines/{pipeline_id}` 按 legacy `get_pipeline_status` → Redis `import:image:pipeline:{pipeline_id}` → 同进程 `_image_pipeline_store` 查询，只有 legacy 与 image 状态都缺失时返回 404。
  - 图片状态写入先更新内存，再 best-effort 写入 Redis，TTL 86400 秒；Redis 支持跨 worker 短期状态共享与 TTL 内重启恢复。
  - `REDIS_URL` 未配置或 Redis 不可用时回退为同进程内存状态，不保证跨 worker / 重启恢复。
  - 图片导入终态为 `completed` / `failed`，非终态包括 `queued` / `ocr_running` / `parsing`；前端仅应在终态停止轮询。
  - 生产 Docker Compose 默认注入 `REDIS_URL=redis://redis:6379/0`。
  - 变更原因：同步已完成的 Redis-backed image import status 实现；受影响文档为 `docs/backend/API_SPEC.md`、`docs/architecture/OCR_FLOW.md`、`docs/ai/OCR_STRATEGY.md`。

## 2026-05-30

- **题库 Level 1 完全重复检测完成**
  - 导入阶段 `question_imports` 新增 `question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id` 字段；正式题库 `questions` 新增 `question_hash`。
  - 发布 / 审核通过阶段按 `subject + question_hash` 做完全匹配拦截，避免重复题进入正式题库。
  - 新增 Alembic migration `j1f2a3b4c5d6_add_duplicate_question_hash_fields.py`，并补充启动补列逻辑。
  - 审核队列、批次详情与 admin import schema 返回重复相关字段；日志统一使用 `[DuplicateCheck]`。
  - 变更原因：同步题库去重已实现状态；受影响文档为 `docs/backend/DB_SCHEMA.md`、`docs/ai/STANDARDIZATION_FLOW.md`、`docs/architecture/OCR_FLOW.md`、`docs/backend/API_SPEC.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/REVIEW_FLOW.md`。

- **Admin Phase 7: 后台 AI 解析设置与全局月度额度完成**

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
