# Admin 文档体系索引

> 本目录包含 2240AI 后台管理系统（Admin Dashboard）的所有设计文档。
> 当前文档版本：**v2.3（Phase 7 AI 设置与月度额度同步版，2026-05-30）**
> **当前状态：Admin Backend 已确认并入现有 FastAPI 后端，在 `/api/admin/v1` 命名空间实现；ORM 使用 SQLAlchemy，迁移使用 Alembic，不再采用独立 NestJS + Prisma + BullMQ 后端方案。Phase 6 `admin-frontend` 已完成 Next.js Admin Dashboard 主要前端实现；Phase 7 已实现后台 AI 解析设置与全局月度额度控制。**
>
> - **更新时间**：2026-05-30
> - **变更原因**：同步 Phase 7 后台 AI 解析设置、全局月度额度、RBAC 权限、Admin API、DB schema 与前端入口实现。

---

## 文档列表

| 文档 | 内容 | 适用阶段 |
|------|------|---------|
| [AUDIT_REPORT.md](./AUDIT_REPORT.md) | **必读**：架构审计报告（v1 风险分析与 v2 修订依据） | 全阶段参考 |
| [ADMIN_ARCHITECTURE.md](./ADMIN_ARCHITECTURE.md) | 系统总体架构、双身份系统、模块拆分、数据流、权限流 | 全阶段参考 |
| [PHASE_PLAN.md](./PHASE_PLAN.md) | 分阶段开发计划（Phase 0-7），含验收标准与不可修改约定 | 全阶段参考 |
| [RBAC_RULES.md](./RBAC_RULES.md) | RBAC 设计：角色 / 权限 / 三层控制 / Super Admin 初始化 / role-version | Phase 1 |
| [DB_SCHEMA_ADMIN.md](./DB_SCHEMA_ADMIN.md) | 数据库设计：admin/subjects/question_versions/audit_logs 等 | Phase 0 |
| [REDIS_PLAN.md](./REDIS_PLAN.md) | Redis 设计：JWT黑名单 / 权限缓存 / 双维度限流 / 防穿透 | Phase 0 |
| [ADMIN_API_SPEC.md](./ADMIN_API_SPEC.md) | API 规范：Stripe 风格响应 / 完整接口 / 错误处理 / 分页 | Phase 1+ |
| [../frontend/ADMIN_UI_RULES.md](../frontend/ADMIN_UI_RULES.md) | Admin Dashboard UI 规则：登录、壳子、权限门禁、页面状态、危险操作确认 | Phase 6 |
| [REVIEW_FLOW.md](./REVIEW_FLOW.md) | 题目审核：状态机（含 re_pending）/ 版本快照 / 权限矩阵 | Phase 3 |
| [AUDIT_LOG.md](./AUDIT_LOG.md) | 审计日志：分级写入策略 / 分区归档 / Action 命名 | Phase 1+ |
| [DEEPSEEK_DEV_RULES.md](./DEEPSEEK_DEV_RULES.md) | DeepSeek 强制约束：A-I 八类禁止项 / 必须人工 Review 模块 | 全阶段强制 |

---

## 各阶段必读文档

| Phase | 开始前必读 | 完成后必须更新 |
|-------|-----------|-------------|
| Phase 0 | AUDIT_REPORT, ADMIN_ARCHITECTURE, DB_SCHEMA_ADMIN, REDIS_PLAN, DEEPSEEK_DEV_RULES | ADMIN_ARCHITECTURE, DB_SCHEMA_ADMIN |
| Phase 1 | RBAC_RULES, ADMIN_API_SPEC, AUDIT_LOG, DEEPSEEK_DEV_RULES | RBAC_RULES, ADMIN_API_SPEC |
| Phase 2 | RBAC_RULES, ADMIN_API_SPEC, DB_SCHEMA_ADMIN | DB_SCHEMA_ADMIN, RBAC_RULES |
| Phase 3 | REVIEW_FLOW, AUDIT_LOG, ADMIN_API_SPEC | ADMIN_API_SPEC, REVIEW_FLOW |
| Phase 4 | ADMIN_API_SPEC, ADMIN_ARCHITECTURE | ADMIN_ARCHITECTURE |
| Phase 5 | AUDIT_LOG, REDIS_PLAN | AUDIT_LOG, ADMIN_API_SPEC, REDIS_PLAN, README |
| Phase 6 | 全部文档，ADMIN_UI_RULES | ADMIN_ARCHITECTURE，docs/frontend/ADMIN_UI_RULES.md |

---

## 文档状态

| 文档 | 版本 | 状态 |
|------|------|------|
| AUDIT_REPORT.md | v1.0 | 审计输出，永久参考 |
| ADMIN_ARCHITECTURE.md | v2.2 | Phase 6 前端实现同步 |
| PHASE_PLAN.md | v2.4 | Phase 7 AI 设置与月度额度同步 |
| RBAC_RULES.md | v2.2 | Phase 7 AI 设置权限同步 |
| DB_SCHEMA_ADMIN.md | v2.2 | Phase 7 AI 设置与月度用量表同步 |
| REDIS_PLAN.md | v2.1 | FastAPI 方案确认，可启动 |
| ADMIN_API_SPEC.md | v2.3 | Phase 7 AI 设置接口同步 |
| ADMIN_UI_RULES.md | v1.2 | Phase 7 AI 设置页面同步 |
| REVIEW_FLOW.md | v2.0 | 已修订，可启动 |
| AUDIT_LOG.md | v2.1 | Phase 7 AI 设置审计 Action 同步 |
| DEEPSEEK_DEV_RULES.md | v2.1 | FastAPI 方案确认，可启动 |

---

## 主要修订点（v1 → v2）

| 修订点 | 来源 | 影响文档 |
|--------|------|---------|
| Admin Backend 并入现有 FastAPI | 2026-05-29 维护者确认 / PROJECT_RULES | ADMIN_ARCHITECTURE, PHASE_PLAN, ADMIN_API_SPEC, DEEPSEEK_DEV_RULES |
| ORM 从 Prisma 收敛为 SQLAlchemy | 2026-05-29 维护者确认 / PROJECT_RULES | DB_SCHEMA_ADMIN, RBAC_RULES, REDIS_PLAN |
| 迁移从 Prisma migration 收敛为 Alembic | 2026-05-29 维护者确认 / PROJECT_RULES | DB_SCHEMA_ADMIN, PHASE_PLAN, DEEPSEEK_DEV_RULES |
| 不创建 NestJS/Prisma/BullMQ 独立后端或新微服务 | 2026-05-29 维护者确认 / PROJECT_RULES | ADMIN_ARCHITECTURE, PHASE_PLAN, REDIS_PLAN, DEEPSEEK_DEV_RULES |
| FastAPI dependencies 替代 NestJS Guards/Decorators | 2026-05-29 维护者确认 | RBAC_RULES, ADMIN_ARCHITECTURE, DEEPSEEK_DEV_RULES |
| Phase 1 审计日志同步写入，队列延后 | 2026-05-29 维护者确认 | AUDIT_LOG, ADMIN_ARCHITECTURE, PHASE_PLAN, REDIS_PLAN |
| AdminUser 用户名/密码/RBAC 是后台专用例外，AppUser 仍仅微信 openid | 2026-05-29 维护者确认 / PROJECT_RULES | ADMIN_ARCHITECTURE, DB_SCHEMA_ADMIN, RBAC_RULES, ADMIN_API_SPEC |
| 删除 normal_user 角色 | 审计 C1 | RBAC_RULES, DB_SCHEMA_ADMIN, ADMIN_ARCHITECTURE |
| AppUser / AdminUser 双身份隔离 | 审计 C1 | ADMIN_ARCHITECTURE, ADMIN_API_SPEC |
| JWT Payload 移除 permissions[] | 审计 C2 | ADMIN_ARCHITECTURE, RBAC_RULES |
| super_admin 走 role_permissions 表（消除硬编码） | 审计 C3 | RBAC_RULES |
| 删除 super_admin 初始化方案 B | 审计 C4 | RBAC_RULES |
| audit_log 分级写入（critical 同步事务内） | 审计 C5 | AUDIT_LOG（新）|
| 编辑后 re_pending 状态 + question_versions | 审计 C6 | REVIEW_FLOW, DB_SCHEMA_ADMIN |
| 新增 subjects 表 | 审计 I1 | DB_SCHEMA_ADMIN, PHASE_PLAN |
| 明确不实现 question_banks | 审计 I2 | PHASE_PLAN, DEEPSEEK_DEV_RULES |
| 批量操作单条独立事务 + failedItems | 审计 I3 | REVIEW_FLOW, ADMIN_API_SPEC |
| TTL 抖动 + 防穿透锁 | 审计 I4 | REDIS_PLAN |
| 双维度登录限流 | 审计 I5 | REDIS_PLAN, RBAC_RULES |
| role-version 机制 | 审计 I6 | REDIS_PLAN, RBAC_RULES |
| audit_log 分区与归档 | 审计 I7 | AUDIT_LOG, DB_SCHEMA_ADMIN |
| Stripe 风格响应 | 审计 I8 | ADMIN_API_SPEC |
| 用户级 nbf 强制失效 | 审计 I9 | REDIS_PLAN, RBAC_RULES |
| liveness / readiness 分级健康检查 | 审计 I10 | ADMIN_API_SPEC, PHASE_PLAN |
| requestId 作为全链路 traceId | 2026-05-29 trace 调试方案审计修订 | ADMIN_API_SPEC, AUDIT_LOG, PHASE_PLAN, DB_SCHEMA_ADMIN, DEEPSEEK_DEV_RULES, ADMIN_ARCHITECTURE |
| Admin Dashboard UI 规则补齐 | 2026-05-29 auditor 审计缺口 | ADMIN_UI_RULES, README |
| Phase 6 Next.js Admin Dashboard 主要前端实现完成 | 2026-05-30 Phase 6 实现同步 | ADMIN_ARCHITECTURE, PHASE_PLAN, ADMIN_UI_RULES, CHANGELOG |
| Phase 7 后台 AI 解析设置与全局月度额度完成 | 2026-05-30 Phase 7 实现同步 | README, PHASE_PLAN, ADMIN_API_SPEC, RBAC_RULES, DB_SCHEMA_ADMIN, AUDIT_LOG, ADMIN_UI_RULES, CHANGELOG |
