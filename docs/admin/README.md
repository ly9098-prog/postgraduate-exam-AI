# Admin 文档体系索引

> 本目录包含 2240AI 后台管理系统（Admin Dashboard）的所有设计文档。
> 当前文档版本：**v2.7（Admin 文档索引与重审回滚实现同步版，2026-10-25）**
> **当前状态：Admin Backend 已并入现有 FastAPI 后端，在 `/api/admin/v1` 命名空间实现；实际 route 文件位于 `backend/app/api/v1/admin_*.py`，由 `backend/app/api/admin/router.py` 聚合。ORM 使用 SQLAlchemy，迁移使用 Alembic，不采用独立 NestJS + Prisma + BullMQ 后端。Admin Frontend 使用 Next.js 16.2 + React 19.2；AI 配置、题目图片/公式卡、导入审核、系统任务与备份管理均已有对应实现。**
>
> - **更新时间**：2026-10-25
> - **变更原因**：同步 2026-08/09 的系统运维权限、JWT 隔离签名域、部署档案校验、任务/备份端点，以及当前 Admin 路由聚合结构。
> - **变更原因**：2026-10-23 随下游文档修订同步版本引用——ADMIN_API_SPEC 升 v2.9（批量答案补录端点）、REVIEW_FLOW 升 v2.3（§6 工作台过滤与 re_pending 页面登记）、AUDIT_LOG action 清单补全。
> - **变更原因**：2026-10-25 同步 REVIEW_FLOW 升 v2.4——已入库题目 `re_pending` 写入、重审工作台、单题/批量重审与版本回滚已实现；原先未接入导航的页面已接入 `/review`。

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
| Phase 7+ | ADMIN_API_SPEC, DB_SCHEMA_ADMIN, AUDIT_LOG, ADMIN_ARCHITECTURE | ADMIN_API_SPEC, DB_SCHEMA_ADMIN, AUDIT_LOG, CHANGELOG, ADMIN_ARCHITECTURE, ADMIN_UI_RULES, PHASE_PLAN, README |

---

## 文档状态

| 文档 | 版本 | 状态 |
|------|------|------|
| AUDIT_REPORT.md | v1.0 | 审计输出，永久参考 |
| ADMIN_ARCHITECTURE.md | v2.4 | 运维 RBAC 与安全边界同步 |
| PHASE_PLAN.md | v2.7 | 已完成能力与后续计划分离，并同步重审/回滚状态 |
| RBAC_RULES.md | v2.2 | Phase 7 AI 设置权限同步（未变化） |
| DB_SCHEMA_ADMIN.md | v2.7 | question_imports 答案状态与优先级字段登记（2026-10-23） |
| REDIS_PLAN.md | v2.1 | FastAPI 方案确认，可启动 |
| ADMIN_API_SPEC.md | v2.9 | 408 考试、题目 CSV 导入、生产 Base URL 与批量答案补录端点 |
| ADMIN_UI_RULES.md | v1.3 | Phase 7+ AI 模型与配置 UI 同步 |
| REVIEW_FLOW.md | v2.4 | 已入库题目重审、批量审核与版本回滚已实现（2026-10-24） |
| AUDIT_LOG.md | v2.5 | action 清单按代码写入值补全（2026-10-23） |
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
| Phase 7+ AI 解析设置页面配置接口实施 | 2026-06-10 Phase 7+ 扩展实现同步 | ADMIN_API_SPEC, DB_SCHEMA_ADMIN, AUDIT_LOG, CHANGELOG, ADMIN_ARCHITECTURE, ADMIN_UI_RULES, PHASE_PLAN, README |

---

## 相关链接

- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
- [[docs/admin/ADMIN_API_SPEC.md|ADMIN_API_SPEC]] — 管理 API 合约
- [[docs/admin/DB_SCHEMA_ADMIN.md|DB_SCHEMA_ADMIN]] — 管理端数据模型
- [[docs/admin/RBAC_RULES.md|RBAC_RULES]] — RBAC 与身份域
- [[docs/admin/AUDIT_LOG.md|AUDIT_LOG]] — 审计记录
