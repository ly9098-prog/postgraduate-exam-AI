# 项目知识库迁移对照（2026-11-04）

> 状态：已完成归并与检索收敛。仓库 `docs/` 是项目知识的唯一权威正文来源，项目知识检索直接使用普通文件工具，不使用 `knowledge_wiki` MCP。
> Windows 侧 `C:\Users\Devil\wikis\postgraduate-ai-wiki` 保留为只读历史归档。本文只记录处置结论和来源，不复制旧 Wiki 正文，也不作为第二套项目规范。

## 事实源与切换

- 旧 Wiki 位于本仓库之外，含 Obsidian 配置、`.git`、`raw/`、正式页和待审摘要；本次未修改、删除或重命名其中任何文件。
- 新检索路径是本仓库 `docs/`，入口为 [INDEX](../INDEX.md)。旧 Wiki 不再作为现行项目规则、API、架构或运维事实来源；引用其中内容前必须与代码、运行时配置和 `docs/` 核对。
- 当日曾先将 `knowledge_wiki` MCP 根目录从 `/mnt/c/Users/Devil/wikis/postgraduate-ai-wiki` 切换到 `/home/lmh/projects/postgraduate-ai/docs`；因 `docs/` 已在项目工作区内，继续保留该 MCP 会形成多余检索层。经用户确认，MCP 检索要求撤销，Codex 中的 `knowledge_wiki` server 停用。
- 已连接的旧 MCP 会话不会自动刷新配置；普通文件工具不依赖 MCP 重连。

## 正式页处置

| 旧 Wiki 页面 | 处置 | 依据 / 归并去向 |
|---|---|---|
| `wiki/architecture/overview.md` | 已由 `docs/` 覆盖 | [docs/INDEX.md](../INDEX.md) 是文档分区与维护入口；不复制 Wiki 索引结构。 |
| `wiki/architecture/system-architecture.md` | 已由 `docs/` 覆盖 | [SYSTEM_ARCHITECTURE.md](../architecture/SYSTEM_ARCHITECTURE.md) 是权威系统架构； Wiki 页本身也是该文档的整理快照。 |
| `wiki/architecture/ocr-pipeline-overview.md` | 已由 `docs/` 覆盖 | OCR 定位、规则优先、人工确认、错误码、状态机与 DB 模型分布在 [OCR_FLOW](../architecture/OCR_FLOW.md)、[OCR_USAGE](../architecture/OCR_USAGE.md)、[OCR_STRATEGY](../ai/OCR_STRATEGY.md)、[AI_PIPELINE](../ai/AI_PIPELINE.md)、[ADMIN_IMPORT_COMPATIBILITY](../architecture/ADMIN_IMPORT_COMPATIBILITY.md) 与 `docs/admin/DB_SCHEMA_ADMIN.md`。 |
| `wiki/architecture/render-invariant.md` | 已由 `docs/` 覆盖 | [render-invariant.md](../frontend/render-invariant.md) 是权威题干渲染约束；相关回归入口见 [COMPONENT_RULES.md](../frontend/COMPONENT_RULES.md)。 |
| `wiki/architecture/review-system-design.md` | 已由 `docs/` 覆盖 | [REVIEW_SYSTEM_DESIGN.md](../architecture/REVIEW_SYSTEM_DESIGN.md) 已记录三层数据职责、单向同步、`grade-batch` 唯一入口与 Asia/Shanghai 日历日；评分上限 40 条和 `request_id` 8–128 字符见 [API_SPEC](../backend/API_SPEC.md) 复习章节。 |
| `wiki/architecture/rbac-rules.md` | 已由 `docs/` 覆盖 | [RBAC_RULES.md](../admin/RBAC_RULES.md)、[ADMIN_ARCHITECTURE.md](../admin/ADMIN_ARCHITECTURE.md) 与 [AUDIT_LOG.md](../admin/AUDIT_LOG.md) 记录身份域隔离、`role_permissions`、JWT/refresh、role-version 缓存和审计边界。 |
| `wiki/api/api-conventions.md` | 差异已补入 `docs/` | 前缀、凭证、错误体、分页和路由结构由 [API_SPEC](../backend/API_SPEC.md)、[ADMIN_API_SPEC](../admin/ADMIN_API_SPEC.md) 与 [API_ROUTER_STRUCTURE](../architecture/API_ROUTER_STRUCTURE.md) 承载。本次将 App API 通用响应/错误码章节从旧的 success 外壳和 camelCase 分页修订为现行无外壳、`error` 对象和 `page_size/total_pages` 形态。 |
| `wiki/guides/project-rules.md` | 已由 `docs/` 覆盖 | [PROJECT_RULES.md](PROJECT_RULES.md) 与 [COMMIT_RULES.md](../COMMIT_RULES.md) 是权威规范；2026-11-02 已同步稳定性治理口径、Prompt 位置、行数预算、Git type 与 AI 凭据边界。 |
| `wiki/guides/lessons-learned.md` | 不晋升为独立长期页 | 五个模式的原始事件、根因、处理与验证保留在 [BUGS_HISTORY](BUGS_HISTORY.md)；调试链路保留在 `docs/debug/DEBUG_SYSTEM.md`。派生摘要不建立第二份需要维护的正文。 |
| `wiki/guides/ui-design-system.md` | 差异已补入 `docs/` | 分包、组件和主题事实由 [UI_RULES](../frontend/UI_RULES.md)、[DESIGN_SYSTEM](../frontend/DESIGN_SYSTEM.md)、[COMPONENT_RULES](../frontend/COMPONENT_RULES.md) 承载。本次按 `miniprogram/styles/tokens.wxss`、`components.wxss` 与 `app.json` 修订基础 Token/组件/布局和 `premium-review` 色值描述。 |
| `wiki/guides/deployment-env.md` | 已由 `docs/` 覆盖 | 生产组件、入口、Redis 备份目录、备份/回滚与部署风险由 [DEPLOY_PLAN](DEPLOY_PLAN.md)、[PRODUCTION_ARCH](../architecture/PRODUCTION_ARCH.md) 和 [REDIS_USAGE](../architecture/REDIS_USAGE.md) 记录。 |
| `wiki/concepts/concepts-overview.md` | 无正文，不迁移 | 该页只是空概念索引；后续解释性内容按主题放入对应 `docs/` 文档。 |

## 待审摘要处置

| 旧 Wiki 摘要 | 处置 | 说明 |
|---|---|---|
| `wiki/memory/docs-sync-2026-10-23.md` | 已由 `docs/` 覆盖 | `grade-batch` 上限与请求键、Asia/Shanghai 口径、批量答案补录、审计 action、番茄钟推送链路删除、依赖规模、Redis 备份目录、preloadRule 均已在 API、复习、Admin、Pomodoro、CHANGELOG、DEPLOY_PLAN、REDIS_USAGE 或 UI 文档记录。 |
| `wiki/memory/repo-sync-2026-11-03.md` | 已由 `docs/` 覆盖；新事实仅保留可复用部署约束 | 规范口径由 [PROJECT_RULES](PROJECT_RULES.md) 和 `AGENTS.md` 记录；AI 可用性门禁由 [AI_ANALYSIS_COMPATIBILITY](../architecture/AI_ANALYSIS_COMPATIBILITY.md) 与部署记录承载；安全加固/SSRF/依赖锁见 [DEPLOY_PLAN](DEPLOY_PLAN.md) 和 OCR 审计文档；生产事件见 2026-11-01/02 部署记录；KaTeX vendor 与有限账本见前端文档和重构清单。本次把“内部 readiness 必须带生产域名 Host 头，失败时先用同探针核验旧镜像”补入 [DEPLOY_PLAN](DEPLOY_PLAN.md)。 |
| `wiki/memory/builtin-mirror.md`、`journal.md` | 不迁移 | 属于工具日志或自动记忆镜像，不是项目规范。 |
| `raw/`、`.obsidian/`、`.claude/`、`wiki/SCHEMA.md`、`wiki/log.md`、`wiki/index.md` | 保留在只读归档 | 分别是原始材料、Obsidian 配置、工具配置、写作契约和旧索引日志；不构成现行项目事实来源。 |

## 归并结果

- 唯一需要新增正文的是本对照记录；其余未记录事实只补入已有 `docs/` 文档，未另建正式 Wiki 页。
- 旧 Wiki 的历史摘要和派生页保留原样，用于追溯；不要将其中行号、计数或快照日期直接用于当前实现判断。
- 后续项目文档新增或修订只发生在本仓库 `docs/`；旧 Wiki 不再追加日志或正式页。

---

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
