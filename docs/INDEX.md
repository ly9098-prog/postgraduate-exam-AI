# 文档总索引（docs-maintainer 使用）

> 本文件是 docs-maintainer agent 的文档维护入口，用于快速判断“改了什么后应该同步哪些文档”。
> 2026-11-04：项目知识以本目录为唯一权威正文来源，直接使用普通文件工具检索。Windows 侧 `C:\Users\Devil\wikis\postgraduate-ai-wiki` 自该日起只读归档，不继续维护项目正文，其内容须先与本目录、代码和运行时配置核对。
> 维护原则：只同步已完成或已确认的实现，不提前替代码设计文档，不修改业务代码。

---

## 1. 使用规则

### 什么时候查本索引

- 完成一个开发阶段后，需要同步开发记录、变更日志或阶段归档
- 新增 / 修改 API、数据库字段、导入流程、AI/OCR 逻辑、前端规则后
- 用户明确要求“同步文档 / 整理文档 / 更新记录”时
- 审计或修复后需要把结论沉淀到长期文档时

### 维护边界

- 只维护 `/docs/`、必要时维护 `/prompts/` 中与当前实现一致的内容
- 不修改业务代码、不重构、不新增实现
- 不把临时排查过程写进长期文档，除非形成可复用规则或已确认结论
- 不制造与代码不一致的“未来设计”；未实现内容必须标注为计划 / 待验证

---

## 2. 文档分区

| 分区 | 用途 | 典型维护时机 |
|------|------|--------------|
| `docs/project/` | 项目规则、路线图、MVP、变更日志、Bug 追踪、发布检查、测试策略、部署计划 | 阶段完成、范围调整、规则变化 |
| `docs/backend/` | API、数据库、存储设计、同步策略、API 合约 | 后端接口、模型、迁移、存储链路变化 |
| `docs/frontend/` | UI 规则、组件规范、设计系统、渲染不变性 | 小程序页面、组件、交互规则变化 |
| `docs/architecture/` | 系统架构、OCR（流程/策略/使用说明/双环境）、记忆系统、复习算法 | 跨模块流程、架构约束、核心算法变化 |
| `docs/ai/` | AI 管线、AI 调试规则、OCR 策略、标准化流程 | AI 标准化、Prompt、OCR/PDF 导入链路变化 |
| `docs/admin/` | 后台管理系统设计与实施文档 | Admin 后台 API、RBAC、审计日志、审核流变化 |
| `docs/debug/` | 调试体系与排查规则、调试历史 | 形成稳定调试方法或复盘结论 |
| `docs/audit/` | OCR/导入/安全审计报告 | 审计完成或修复后沉淀结论 |
| `docs/planning/` | 功能规划、任务计划、设计分析 | 新功能设计阶段 |
| `docs/achieve/` | 已完成阶段归档 | 阶段完成后归档 |
| `docs/development/` | 外部开发规范参考：编码、工作流、Git、Agent 体系 | 新增或调整通用开发/Agent 规则参考 |
| 根目录兼容入口 | 历史兼容入口，仅保留短入口，不重复维护正文 | 仅在仍被引用或用户要求时同步 |

> 2026-09-23 更新原因：补齐 9 月 13 日之后的 408 考试、题目 CSV、多空题型与公式图卷事实。历史阶段文档和审计报告不改写成当前承诺。
> 同日重写 `docs/project/ROADMAP.md` 与 `docs/project/MVP_SCOPE.md`：去掉「导入管线开发中」，并标明 `prompts/tasks/backlog/` 不是施工单。

---

## 3. 常用文档入口

### 项目与阶段

| 文档 | 作用 |
|------|------|
| `docs/project/PROJECT_RULES.md` | 长期项目规则与明确不做事项 |
| `docs/project/MVP_SCOPE.md` | 原 MVP 清单（已完成；现行范围见路线图） |
| `docs/project/ROADMAP.md` | 现行范围。不排新功能，也不要把 backlog 当待办 |
| `docs/project/CHANGELOG.md` | 项目变更记录 |
| `docs/project/BUGS.md` | Bug 完整记录 |
| `docs/project/BUGS_HISTORY.md` | Bug 历史归档 |
| `docs/project/DEPLOY_PLAN.md` | 部署方案与计划 |
| `docs/project/KNOWLEDGE_BASE_MIGRATION_2026-11-04.md` | 旧 Wiki 归档与 `docs/` 唯一知识源的迁移对照 |
| `docs/backend/REVIEW_SMOKE_CHECKLIST.md` | 复习模块冒烟测试清单 |
| `docs/project/FILE_CHANGE_MAP.json` | 文件变更映射 |
| `docs/achieve/README.md` | 历史阶段归档入口 |

### 后端

| 文档 | 作用 |
|------|------|
| `docs/backend/API_SPEC.md` | App API 规范 |
| `docs/api/GUEST_EXPERIENCE_API.md` | 游客公式浏览、5题试做、24小时签名批次及自主登录/隐私边界 |
| `docs/backend/DB_SCHEMA.md` | App 数据库 schema |
| `docs/backend/STORAGE_DESIGN.md` | 文件 / 图片 / 存储设计 |
| `docs/backend/SYNC_LOCAL_TO_CLOUD.md` | 本地到云端同步方案 |
| `docs/backend/API_SPEC.md` 复习章节 | 现行复习接口。`REVIEW_API_CONTRACT.md` 与 `SM2_MIGRATION_CHECKLIST.md` 已丢失，不要当作现行合约 |

### AI / OCR / 导入

| 文档 | 作用 |
|------|------|
| `docs/ai/AI_PIPELINE.md` | AI 管线 |
| `docs/ai/AI_DEBUG_RULES.md` | AI 调试规则 |
| `docs/ai/OCR_STRATEGY.md` | OCR 策略 |
| `docs/ai/STANDARDIZATION_FLOW.md` | AI 标准化流程 |
| `docs/architecture/OCR_FLOW.md` | OCR 导入架构流程 |
| `docs/architecture/OCR_USAGE.md` | OCR 导入使用说明 |
| `docs/architecture/DUAL_ENV_OCR.md` | 双环境 OCR 配置 |
| `docs/ocr/OPERATIONS.md` | OCR 运维手册 |
| `docs/ocr/TROUBLESHOOTING.md` | OCR 故障排查手册 |
| `docs/ocr/DEPLOY_CHECKLIST.md` | OCR 发布检查清单 |

### 前端

| 文档 | 作用 |
|------|------|
| `docs/frontend/UI_RULES.md` | 小程序 UI 规则 |
| `docs/frontend/COMPONENT_RULES.md` | 组件规范 |
| `docs/frontend/DESIGN_SYSTEM.md` | 设计系统 |
| `docs/frontend/render-invariant.md` | 题干渲染不变性架构 |
| `docs/frontend/LAUNCH_RESUME.md` | 默认冷启动还原刷题/今日复习/番茄钟、用户隔离与手工验收 |

### Admin 后台

| 文档 | 作用 |
|------|------|
| `docs/admin/README.md` | Admin 文档入口 |
| `docs/admin/ADMIN_ARCHITECTURE.md` | Admin 总体架构 |
| `docs/admin/PHASE_PLAN.md` | Admin 分阶段计划 |
| `docs/admin/ADMIN_API_SPEC.md` | Admin API 规范 |
| `docs/admin/DB_SCHEMA_ADMIN.md` | Admin 数据库设计 |
| `docs/admin/RBAC_RULES.md` | Admin RBAC 规则 |
| `docs/admin/AUDIT_LOG.md` | Admin 审计日志 |
| `docs/admin/REVIEW_FLOW.md` | 题目审核流程 |
| `docs/admin/DEEPSEEK_DEV_RULES.md` | DeepSeek 开发强制约束 |

### 当前实现补充

| 文档 / 入口 | 当前事实 |
|------|------|
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | 2026-09-02 总体架构与运行时状态 |
| `docs/architecture/AI_ANALYSIS_COMPATIBILITY.md` §18–19 | 错题AI共享健康门禁、真实模型探测、额度/鉴权禁用、管理员解锁与小程序提示 |
| `docs/project/PRODUCTION_AI_ANALYSIS_AVAILABILITY_DEPLOY_2026-11-01.md` | 错题AI可用性门禁后端生产部署、备份、健康检查与真实模型验收边界 |
| `docs/project/PRODUCTION_AI_MODEL_HEALTH_REVIEW_DEPLOY_2026-11-02.md` | 错题AI内聚/耦合复核、提交与三个后端角色再部署，含备份与限定验证 |
| `docs/admin/ADMIN_API_SPEC.md` | Admin API v2.9，包含 system/tasks/backup 端点与批量答案补录端点 |
| `docs/admin/RBAC_RULES.md` | JWT 隔离签名域与 `system:*` 权限 |
| `docs/project/ROLE_DEPLOYMENT.md` | `local_import` / `cloud_api` 角色拆分与生产约束 |
| `docs/frontend/render-invariant.md` | 小程序 CODE / LaTeX / 图片渲染路径 |

### 开发规范参考

| 文档 | 作用 |
|------|------|
| `docs/development/coding-style.md` | 通用编码规范与上线后阶段原则：模块边界、抽象、技术债、错误处理、输入验证 |
| `docs/development/development-workflow.md` | 特性实现流程、项目阶段技术决策标准与子 agent 分工参考 |
| `docs/development/git-workflow.md` | Git 提交消息与 PR 工作流参考 |
| `docs/development/agents-and-commands.md` | Codex Agent 体系与常用指令参考 |

### 调试 / 审计 / 规划

| 文档 | 作用 |
|------|------|
| `docs/debug/DEBUG_SYSTEM.md` | 调试体系 |
| `docs/debug/DEBUG_HISTORY.md` | 调试历史记录 |
| `docs/audit/AUDIT_INDEX.md` | 审计报告索引 |
| `docs/planning/TASK_PLAN.md` | 当前任务计划 |
| `docs/planning/image-import-analysis.md` | 图片导入分析 |
| `docs/planning/image-import-architecture.md` | 图片导入架构设计 |
| `docs/planning/image-import-risk-review.md` | 图片导入风险审查 |
| `docs/planning/image-import-roadmap.md` | 图片导入路线图 |

### 架构

| 文档 | 作用 |
|------|------|
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | 系统总体架构 |
| `docs/architecture/PRODUCTION_ARCH.md` | 生产环境架构 |
| `docs/architecture/REVIEW_SYSTEM_DESIGN.md` | 复习系统设计 |
| `docs/architecture/REVIEW_ALGORITHM.md` | SM-2 复习算法 |
| `docs/architecture/MEMORY_SYSTEM.md` | 记忆系统设计 |
| `docs/architecture/MATH_IMAGE_ARCHITECTURE.md` | 数学公式图片架构 |
| `docs/architecture/refresh_token_architecture.md` | Refresh Token 架构 |
| `docs/architecture/REDIS_USAGE.md` | Redis 使用情况、失败降级矩阵与稳定性修复记录 |
| `docs/project/DEPLOY_PLAN.md` | 生产部署、Redis 持久化/备份与 AOF 安全恢复流程 |
| `docs/architecture/POMODORO_NOTIFICATION.md` | 番茄钟通知设计 |

### 一级目录兼容入口

> 2026-06-28 目录整理：以下兼容入口由 `git mv` 搬移后保留为短入口 stub，权威正文在目标路径。

| 文档 | 权威正文 |
|------|----------|
| `docs/API_SPEC.md` | `docs/backend/API_SPEC.md` |
| `docs/DB_SCHEMA.md` | `docs/backend/DB_SCHEMA.md` |
| `docs/OCR_FLOW.md` | `docs/architecture/OCR_FLOW.md` |
| `docs/OCR_USAGE.md` | `docs/architecture/OCR_USAGE.md` |
| `docs/DUAL_ENV_OCR.md` | `docs/architecture/DUAL_ENV_OCR.md` |
| `docs/AI_PIPELINE.md` | `docs/ai/AI_PIPELINE.md` |
| `docs/AI_DEBUG_RULES.md` | `docs/ai/AI_DEBUG_RULES.md` |
| `docs/PROJECT_RULES.md` | `docs/project/PROJECT_RULES.md` |
| `docs/UI_RULES.md` | `docs/frontend/UI_RULES.md` |
| `docs/CHANGELOG.md` | 调试变更日志；项目级变更以 `docs/project/CHANGELOG.md` 为准 |
| `docs/BUGS.md` | `docs/project/BUGS.md` |
| `docs/BUGS_HISTORY.md` | `docs/project/BUGS_HISTORY.md` |
| `docs/DEPLOY_PLAN.md` | `docs/project/DEPLOY_PLAN.md` |
| `docs/FILE_CHANGE_MAP.json` | `docs/project/FILE_CHANGE_MAP.json` |
| `docs/DEBUG_HISTORY.md` | `docs/debug/DEBUG_HISTORY.md` |
| `docs/AUDIT_INDEX.md` | `docs/audit/AUDIT_INDEX.md` |
| `docs/TASK_PLAN.md` | `docs/planning/TASK_PLAN.md` |
| `docs/render-invariant.md` | `docs/frontend/render-invariant.md` |
| `docs/MEMORY_SYSTEM.md` | `docs/architecture/MEMORY_SYSTEM.md` |
| `docs/REVIEW_ALGORITHM.md` | `docs/architecture/REVIEW_ALGORITHM.md` |
| `docs/SYNC_LOCAL_TO_CLOUD.md` | `docs/backend/SYNC_LOCAL_TO_CLOUD.md` |

> 以下文件（曾出现在根目录）未纳入 git 追踪，Zone.Identifier 清理时意外丢失：`SMOKE_TEST_CHECKLIST.md`、`RC_RELEASE_CHECKLIST.md`、`REVIEW_API_CONTRACT.md`、`SM2_MIGRATION_CHECKLIST.md`、`TESTING_POLICY.md`。如需要需重新创建。

| 文档 | 权威正文 |
|------|----------|
| `docs/API_SPEC.md` | `docs/backend/API_SPEC.md` |
| `docs/DB_SCHEMA.md` | `docs/backend/DB_SCHEMA.md` |
| `docs/OCR_FLOW.md` | `docs/architecture/OCR_FLOW.md` |
| `docs/OCR_USAGE.md` | `docs/architecture/OCR_USAGE.md` |
| `docs/DUAL_ENV_OCR.md` | `docs/architecture/DUAL_ENV_OCR.md` |
| `docs/AI_PIPELINE.md` | `docs/ai/AI_PIPELINE.md` |
| `docs/PROJECT_RULES.md` | `docs/project/PROJECT_RULES.md` |
| `docs/UI_RULES.md` | `docs/frontend/UI_RULES.md` |
| `docs/CHANGELOG.md` | 调试变更日志；项目级变更以 `docs/project/CHANGELOG.md` 为准 |

以上一级目录文档仅作兼容入口或特定用途记录；除 `docs/INDEX.md` 自身外，不应在一级目录重复维护权威正文。

---

## 4. 变更类型 → 必查文档

| 变更类型 | 必查 / 必改 |
|----------|-------------|
| 新增或修改 App API | `docs/backend/API_SPEC.md`、`docs/project/CHANGELOG.md` |
| 新增或修改 Admin API | `docs/admin/ADMIN_API_SPEC.md`、`docs/admin/README.md`、`docs/project/CHANGELOG.md` |
| 数据库模型 / 字段 / 迁移变化 | `docs/backend/DB_SCHEMA.md` 或 `docs/admin/DB_SCHEMA_ADMIN.md`、相关流程文档 |
| OCR / PDF 导入流程变化 | `docs/architecture/OCR_FLOW.md`、`docs/ai/OCR_STRATEGY.md`、`docs/ai/STANDARDIZATION_FLOW.md` |
| AI 标准化 / Prompt 行为变化 | `docs/ai/AI_PIPELINE.md`、`docs/ai/STANDARDIZATION_FLOW.md`、必要时同步 `/prompts/` |
| 小程序页面 / 组件规则变化 | `docs/frontend/UI_RULES.md`、`docs/frontend/COMPONENT_RULES.md`、`docs/frontend/DESIGN_SYSTEM.md` |
| Admin RBAC / 权限变化 | `docs/admin/RBAC_RULES.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/AUDIT_LOG.md` |
| 审核流 / 题目版本变化 | `docs/admin/REVIEW_FLOW.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/AUDIT_LOG.md` |
| 阶段完成 | `docs/project/CHANGELOG.md`、`docs/achieve/README.md`、对应阶段归档 |
| 长期规则变化 | 根 `AGENTS.md`、`docs/project/PROJECT_RULES.md`、根 `CLAUDE.md` 如确有必要 |

---

## 5. docs-maintainer 执行清单

1. 先确认当前实现或用户已确认的变更范围。
2. 根据“变更类型 → 必查文档”定位文档。
3. 对照代码 / 已完成实现同步事实，不写未实现承诺。
4. 更新版本、日期、状态时保持全仓一致。
5. 如文档间存在冲突，以当前代码与 `CLAUDE.md` / `docs/project/PROJECT_RULES.md` 的长期约束为准。
6. 输出时说明：改了哪些文档、同步了哪些事实、是否发现文档冲突。

---

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/COMMIT_RULES.md|COMMIT_RULES]] — 提交规范
