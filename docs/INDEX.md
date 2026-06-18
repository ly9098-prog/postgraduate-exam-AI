# 文档总索引（docs-maintainer 使用）

> 本文件是 docs-maintainer agent 的文档维护入口，用于快速判断“改了什么后应该同步哪些文档”。
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
| `docs/project/` | 项目规则、路线图、MVP、变更日志 | 阶段完成、范围调整、规则变化 |
| `docs/backend/` | API、数据库、存储设计 | 后端接口、模型、迁移、存储链路变化 |
| `docs/frontend/` | UI 规则、组件规范、设计系统 | 小程序页面、组件、交互规则变化 |
| `docs/architecture/` | 系统架构、OCR（流程/策略/使用说明/双环境）、记忆系统、复习算法 | 跨模块流程、架构约束、核心算法变化 |
| `docs/ai/` | AI 管线、OCR 策略、标准化流程 | AI 标准化、Prompt、OCR/PDF 导入链路变化 |
| `docs/admin/` | 后台管理系统设计与实施文档 | Admin 后台 API、RBAC、审计日志、审核流变化 |
| `docs/debug/` | 调试体系与排查规则 | 形成稳定调试方法或复盘结论 |
| `docs/achieve/` | 已完成阶段归档 | 阶段完成后归档 |
| 根目录兼容入口 | 历史兼容入口，仅保留短入口，不重复维护正文 | 仅在仍被引用或用户要求时同步 |

> 2026-05-31 更新原因：一级目录旧版副本文档已精简为兼容入口；权威正文以各子目录文档为准。

---

## 3. 常用文档入口

### 项目与阶段

| 文档 | 作用 |
|------|------|
| `docs/project/PROJECT_RULES.md` | 长期项目规则与明确不做事项 |
| `docs/project/MVP_SCOPE.md` | MVP 范围 |
| `docs/project/ROADMAP.md` | 路线图 |
| `docs/project/CHANGELOG.md` | 项目变更记录 |
| `docs/achieve/README.md` | 历史阶段归档入口 |

### 后端

| 文档 | 作用 |
|------|------|
| `docs/backend/API_SPEC.md` | App API 规范 |
| `docs/backend/DB_SCHEMA.md` | App 数据库 schema |
| `docs/backend/STORAGE_DESIGN.md` | 文件 / 图片 / 存储设计 |

### AI / OCR / 导入

| 文档 | 作用 |
|------|------|
| `docs/ai/AI_PIPELINE.md` | AI 管线 |
| `docs/ai/OCR_STRATEGY.md` | OCR 策略 |
| `docs/ai/STANDARDIZATION_FLOW.md` | AI 标准化流程 |
| `docs/architecture/OCR_FLOW.md` | OCR 导入架构流程 |

### 前端

| 文档 | 作用 |
|------|------|
| `docs/frontend/UI_RULES.md` | 小程序 UI 规则 |
| `docs/frontend/COMPONENT_RULES.md` | 组件规范 |
| `docs/frontend/DESIGN_SYSTEM.md` | 设计系统 |

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

### 一级目录兼容入口

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
| 长期规则变化 | `docs/project/PROJECT_RULES.md`、根 `CLAUDE.md` 如确有必要 |

---

## 5. docs-maintainer 执行清单

1. 先确认当前实现或用户已确认的变更范围。
2. 根据“变更类型 → 必查文档”定位文档。
3. 对照代码 / 已完成实现同步事实，不写未实现承诺。
4. 更新版本、日期、状态时保持全仓一致。
5. 如文档间存在冲突，以当前代码与 `CLAUDE.md` / `docs/project/PROJECT_RULES.md` 的长期约束为准。
6. 输出时说明：改了哪些文档、同步了哪些事实、是否发现文档冲突。
