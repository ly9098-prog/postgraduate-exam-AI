# Admin API 规范

> 版本：v2.9（批量答案补录端点同步） | 状态：核心 Admin API 已实施 | 更新：2026-10-23
> 修订自审计报告 I8（统一 Stripe 风格）、I10（liveness/readiness）、C1（拆分 app-users 与 admin-users）
>
> - **变更原因**：2026-05-30 同步 Phase 7 新增 AI 解析设置与月度用量接口、权限要求和导入 enrich 前置拦截语义。
> - **变更原因**：2026-05-30 同步题库 Level 1 完全重复检测在导入批次详情 / 审核队列返回的重复字段，以及发布阶段拦截语义。
> - **变更原因**：2026-06-10 同步 AI 解析设置页面配置接口（`/ai-models`、`/ai-configs`）。
> - **变更原因**：2026-08-10 同步题目图片上传/替换/删除、快捷添加选项、keyword 匹配知识点名与别名，以及公式卡 API 与 PUT 版本号推导（行锁 + max 版本）。
> - **变更原因**：2026-08-29 同步系统运维细粒度权限、备份响应脱敏、用户/Admin JWT 签名域隔离与生产健康端点收敛。
- **变更原因**：2026-09-23 同步 408 考试管理接口、题目 CSV 直导入，以及生产 Base URL（`xzshub.top` / `api.xzshub.top`，不再使用 `api.2240ai.com`）。
- **变更原因**：2026-10-23 补齐 §3.8 批量答案补录 4 个端点（answers/preview、answers/apply、answers/image/preview、answers/image/apply，2026-07-12 起实现），并明确 preview_token 两段式与审计动作。

---

## 一、基础规范

### Base URL
```
开发：http://localhost:8000/api/admin/v1
生产：https://xzshub.top/api/admin/v1（`www.xzshub.top`、`api.xzshub.top` 同一 Nginx `server_name`）
```

### 认证
所有接口（除 `/auth/login`、`/health/*`）必须携带：
```
Authorization: Bearer <access_token>
```

`type` 字段必须为 `"admin"`，否则 401。

### 协议版本
URL 携带 `/v1/`，后期升级为 `/v2/` 时保持向后兼容；不在 Header 中传版本号。

### Idempotency（O4，关键写操作支持）
关键写操作（如 `/imports/{batchId}/publish`、`/questions/batch-delete`）支持：
```
Idempotency-Key: <UUID>
```
服务端在 Redis 使用 `admin:idempotency:{userId}:{key}` 缓存请求结果 10 分钟，同一 key 重复请求返回相同结果。Redis 不可用时，关键批量写/关键幂等接口应拒绝 503；如某接口选择降级执行，必须在接口文档中明确“不提供幂等保证”，不得静默假装幂等。

### 二次验证（预留位）
敏感操作支持：
```
X-Confirm-Password: <bcrypt 验证用>
```
当前 Phase 不强制要求，未来引入时不破坏 API 兼容性。

### Request ID / Trace ID（全链路调试）

- Admin 对外统一使用 `requestId` 命名；`requestId` 即本系统的全链路 traceId，不额外暴露 `traceId` 字段。
- FastAPI middleware 负责生成或透传请求 ID，并在响应头写入 `X-Request-Id: <requestId>`。
- 业务 API 的成功/错误响应必须在 `meta.requestId` 返回同一值；前端错误提示与问题反馈只展示该 `requestId`。
- 健康检查可保持轻量：必须返回 `X-Request-Id`，响应体可不包 `meta.requestId`，且不写 audit_log。
- 日志与审计日志复用同一 `requestId`；审计日志暂写入 `audit_logs.detail.extra.requestId`，Phase 0/1 不新增 `audit_logs.trace_id` 列。

---

## 二、RESTful 命名规范

```
GET    /v1/{resource}           # 列表（分页）
GET    /v1/{resource}/{id}      # 单条详情
POST   /v1/{resource}           # 创建
PATCH  /v1/{resource}/{id}      # 部分更新
DELETE /v1/{resource}/{id}      # 删除

# 特殊操作用动词后缀
POST   /v1/imports/{batchId}/publish
POST   /v1/imports/questions/{importId}/approve
POST   /v1/app-users/{id}/ban
POST   /v1/app-users/{id}/unban
POST   /v1/auth/logout
POST   /v1/auth/refresh
```

**禁用模糊动词**：`/changeStatus`、`/update`、`/handle` 等。

---

## 三、完整 API 列表

### 3.1 认证 `/auth`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| POST | `/auth/login` | 用户名+密码登录 | 公开 |
| POST | `/auth/logout` | 登出（加入黑名单） | 已登录 |
| POST | `/auth/refresh` | 刷新 Access Token | 已登录（带 refresh cookie） |
| GET  | `/auth/me` | 获取当前用户信息 + 权限列表 | 已登录 |
| POST | `/auth/change-password` | 修改密码（触发 nbf） | 已登录 |

### 3.2 健康检查 `/health`（I10 修订）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/health/live` | 进程存活（不依赖 DB/Redis） | 公开 |
| GET | `/health/ready` | 可接收流量（DB 必须 OK） | 公开 |
| GET | `/health` | 综合状态详情 | 公开（仅返回基础信息） |

**响应示例**：
```json
// /health/live
{ "status": "ok" }

// /health/ready
{ "status": "ok", "db": "ok", "redis": "ok" }
// Redis 不可用但 DB 可用时仍返回 200
{ "status": "ok", "db": "ok", "redis": "degraded" }
// DB 失败或关键 migration 未完成时返回 503
{ "status": "fail", "db": "fail", "redis": "ok" }
```

### 3.2.1 系统运维 `/system` 与任务 `/tasks`

这些接口属于 Admin API，不能使用 `import:*` 权限替代：

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/system/health` | DB、Redis、AI 等系统健康聚合 | `system:read` |
| GET | `/tasks` | 查询任务及队列位置 | `system:read` |
| GET | `/tasks/{task_id}` | 查看任务详情 | `system:read` |
| GET | `/tasks/diagnostics` | 任务/Outbox/投影诊断；`redis.memory` 提供容量、上限、阈值及淘汰键读数（不可用时为 `null`） | `system:read` |
| GET | `/tasks/trace/{trace_id}` | 查询任务生命周期 | `system:read` |
| GET | `/tasks/queue-status` | 队列计数 | `system:read` |
| GET | `/tasks/scheduled` | 查看 scheduler 任务 | `system:read` |
| POST | `/tasks/{task_id}/retry` | 重试失败任务 | `system:write` |
| POST | `/tasks/{task_id}/cancel` | 取消任务 | `system:write` |
| POST | `/tasks/scheduled/{task_id}/run` | 手动执行维护任务 | `system:write` |
| GET | `/tasks/system/postgres-backup/history` | 查看 PostgreSQL 备份历史 | `system:backup` |

执行 `postgres_backup` 时除 `system:write` 外还必须具备 `system:backup`。备份响应只返回文件名、大小、时间、方法和数据库名，不返回服务器目录或绝对路径。

### 3.3 小程序用户管理 `/app-users`（C1：与 admin-users 严格区分）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/app-users` | 列表 | app-user:read |
| GET | `/app-users/{id}` | 详情（含练题数 / 错题数 / 最近活跃） | app-user:read |
| PATCH | `/app-users/{id}` | 编辑运营备注/状态类字段 | app-user:write |
| POST | `/app-users/{id}/ban` | 封禁（Body: `{ reason }`） | app-user:ban |
| POST | `/app-users/{id}/unban` | 解封 | app-user:ban |

### 3.4 后台管理员管理 `/admin-users`（C1）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/admin-users` | 管理员列表 | admin-user:read |
| GET | `/admin-users/{id}` | 详情 | admin-user:read |
| POST | `/admin-users` | 创建（roleId 不能为 super_admin） | admin-user:create |
| PATCH | `/admin-users/{id}` | 更新（不可改自己的 role） | admin-user:update |
| DELETE | `/admin-users/{id}` | 停用（禁停用 super_admin / 自己） | admin-user:delete |
| POST | `/admin-users/{id}/force-logout` | 强制下线（更新 nbf） | admin-user:force-logout |
| POST | `/admin-users/{id}/reset-password` | 重置密码 | admin-user:reset-password |

### 3.5 角色管理 `/roles`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/roles` | 角色列表 | role:read |
| GET | `/roles/{id}` | 角色详情（含权限） | role:read |
| POST | `/roles` | 创建角色（不可创建 super_admin） | role:write |
| PATCH | `/roles/{id}` | 更新角色信息（不含权限绑定） | role:write |
| PUT | `/roles/{id}/permissions` | 更新角色权限绑定 | role:write |
| DELETE | `/roles/{id}` | 删除角色（isSystem 不可删） | role:delete |

### 3.6 权限管理 `/permissions`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/permissions` | 权限列表（含 category 分组） | permission:read |
| GET | `/permissions/by-category` | 按 category 分组 | permission:read |

### 3.7 题目管理 `/questions`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/questions` | 列表（多维过滤；keyword 命中题干/解析/知识点名及别名） | question:read |
| GET | `/questions/{id}` | 详情 | question:read |
| GET | `/questions/{id}/versions` | 历史版本列表 | question:read |
| GET | `/questions/{id}/versions/{version}` | 某版本详情 | question:read |
| PATCH | `/questions/{id}` | 编辑（无实际字段变更不写版本/审计；知识点评关联表） | question:write |
| DELETE | `/questions/{id}` | 软删除（is_active=false） | question:delete |
| POST | `/questions/batch-delete` | 批量软删除（ids 上限 50） | question:delete |
| POST | `/questions/{id}/options` | 快捷添加选项（single_choice/multiple_choice） | question:write |
| POST | `/questions/{id}/images` | 上传/替换题干或选项图片（multipart） | question:write |
| DELETE | `/questions/{id}/images` | 删除题干或选项图片 | question:write |
| PATCH | `/questions/{id}/toggle-active` | 上下架（仅 approved 可激活；rejected 须走重审通过） | question:write |
| POST | `/questions/{id}/approve` | 已入库题目重审通过（仅 re_pending/rejected） | question:review |
| POST | `/questions/{id}/reject` | 已入库题目重审拒绝（仅 re_pending；reason 必填） | question:review |
| POST | `/questions/batch-approve` | 已入库题目批量重审通过（ids 上限 50；可选 reason） | question:batch_review |
| POST | `/questions/batch-reject` | 已入库题目批量重审拒绝（ids 上限 50；可选 reason，默认"批量重审拒绝"） | question:batch_review |
| POST | `/questions/{id}/rollback` | 回滚到指定版本并追加新版本 | question:write + question:review |
| POST | `/questions/embeddings/backfill` | 批量回填题目 embedding 向量 | question:write |
| GET | `/questions/embeddings/status` | 查看向量功能状态与 embedding 统计 | question:read |

> **首次导入审核不走 `/questions`**：pending import 审核全部在导入管理 `/imports`（§3.8，权限 `import:write`）。`/questions` 的 approve/reject/rollback 只处理已入库题目重审与版本回滚。

**`GET /questions` keyword 搜索（2026-08-09 同步）**：
- `keyword` 命中范围：`answer`、`analysis`、`raw_content` 模糊匹配，以及 `Question.id` 命中知识点的子查询。
- 知识点子查询：按 `question_knowledge_points` 关联 `knowledge_points`，命中 `knowledge_points.name ILIKE` 或 **`knowledge_points.aliases` JSON 数组逐元素匹配**（适配 `knowledge_points.aliases` 新增别名字段）。
- SQLite 用 `json_each`，PostgreSQL 用 `json_array_elements_text` 逐元素匹配，两端行为一致。

**`POST /questions/{id}/options`（2026-08-09 同步）**：
- Body：`{ "options": [{ "text": string, "key"?: string }, ...], "edit_reason"?: string }`，`options` 数量 1-26。
- 仅 `single_choice` / `multiple_choice` 题型支持。
- `key` 缺省时自动分配下一个空闲字母（A-Z）；显式 `key` 必为 `A-Z` 单字母。
- 选项合并大小写不敏感判重（历史小写 `key` 与自动大写字母视为同槽位），显式 key 冲突返回 422。
- 原有选项的富键（`semantic_role`、`is_question_image` 等）在合并时保留。

**`POST /questions/{id}/images`（上传/替换，2026-08-09 同步）**：
- multipart：`file`（图片，PNG/JPEG/WebP，最大 10MB，超出返回 413）、`target`、`replace_url`（可选，替换指定 URL）。
- `target` 取值：`stem` 或 `option:A`-`option:Z`（非法返回 400）。
- 图片流式写入临时文件 → 压缩（同 `compress_image`）→ 存入 question-assets 存储后端，`storage_key` 形如 `{question_id}/{uuid}.{png|webp|jpg}`，返回题目列表项。
- **先校验题目存在与权限，再上传**——非法请求不浪费对象存储往返。
- 题干图：在 `content.segments` 追加 `{type: "image", url, semantic_role: "content_image"}`（旧版 `{text,stem}` 内容自动升级为 segments）；`replace_url` 指定时替换匹配 segment。
- 选项图：将 `options[key]` 升级/追加 image segment（`semantic_role: "option_image"`），保留选项文本与既有富键。
- 写入 `question.update` 审计（severity=important）；替换后旧 URL 若不再被任何题目引用则由孤儿清理删除。

**`DELETE /questions/{id}/images`（删除，2026-08-09 同步）**：
- Body：`{ "target": string, "url": string, "edit_reason"?: string }`。
- 删除题干图：移除 `content.segments` 中匹配 URL 的 image segment。
- 删除选项图：移除 `options[key]` 中匹配的 URL 的 image segment；无剩余 image segment 且无其他富键时降级为平文本。

**图片孤儿清理**：删除/替换后调用 `AssetReferenceService` 扫描引用（含 `questions.content/image_url/options` 与 `question_imports`），`reference_count == 0` 才删文件。

### 3.8 导入管理 `/imports`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/imports` | 导入批次列表 | import:read |
| GET | `/imports/{batchId}` | 批次详情（含题目分页） | import:read |
| POST | `/imports/upload` | 上传文件创建导入管线（Excel/PDF/TXT/图片） | import:write |
| GET | `/imports/review-queue` | 审核队列 | import:read |
| GET | `/imports/subject-options` | 科目选项 | import:read |
| GET | `/imports/questions/{importId}` | 导入题详情 | import:read |
| PUT | `/imports/questions/{importId}` | 修改导入题字段（含 status / review_note / parsed_*） | import:write |
| POST | `/imports/questions/{importId}/complete` | 单题 AI 补全（辅助，不绕过人工确认） | import:write |
| POST | `/imports/questions/batch-complete` | 批量 AI 补全（ids 上限 50） | import:write |
| POST | `/imports/{batchId}/answers/preview` | 答案串补录预览（解析答案串，不写入） | import:write |
| POST | `/imports/{batchId}/answers/apply` | 确认答案串预览结果并写入答案 | import:write |
| POST | `/imports/{batchId}/answers/image/preview` | 答案/解析图片预览（多图上传，mode=answer_only/answer_analysis） | import:write |
| POST | `/imports/{batchId}/answers/image/apply` | 确认图片预览结果并写入答案/解析 | import:write |
| POST | `/imports/questions/{importId}/approve` | 单题审核通过（审核即发布） | import:write |
| POST | `/imports/questions/{importId}/reject` | 单题审核拒绝 | import:write |
| POST | `/imports/{batchId}/approve` | 批次审核通过（逐题 Level 1 重复检测后发布） | import:write |
| POST | `/imports/{batchId}/approve-low-risk` | 仅通过 low risk 题目 | import:write |
| POST | `/imports/{batchId}/reject` | 批次审核拒绝 | import:write |
| POST | `/imports/{batchId}/publish` | 批次发布（写入正式 questions） | import:write |
| POST | `/imports/{batchId}/enrich` | 创建 AI 辅助处理任务（创建前检查全局 AI 开关与月度额度） | import:write |
| GET | `/imports/{batchId}/status` | 读取该批次最新 AI 任务进度（Redis/cache） | import:read |
| DELETE | `/imports/questions/{importId}` | 删除导入题 | import:write |
| DELETE | `/imports/{batchId}` | 删除整个批次 | import:write |
| POST | `/imports/questions-csv` | 导入题目导出 CSV，直接写入 `questions`（非 AI/OCR，不经 `question_imports` 审核） | import:write |

**批量答案补录端点（2026-07-12 起实现，管理端审核页已消费）**：
- preview → apply 两段式：preview 生成 `preview_token`（15 分钟 TTL）与 `operation_id`（1 小时幂等），apply 凭 token 确认后写入。
- 审计动作：答案串补录写 `import.batch_answer_fill`，图片补录写 `import.batch_answer_image_fill`。
- 前端消费：`admin-frontend/src/app/(admin)/imports/review/hooks/use-review-batch-answer-mutations.ts`、`use-review-image-answer-mutations.ts`。

**查询参数（Phase 4 实现，2026-05-29）**：
- `GET /imports`：`page`（默认 1，≥1）、`page_size`（默认 20，1-100）、`status`、`source_type`、`keyword`。
- `GET /imports/{batchId}`：`page`（默认 1，≥1）、`page_size`（默认 20，1-100）、`status`。

**响应字段（摘要）**：
- 批次列表 item：`batch_id`、`source_type`、`source_file`、`total_count`、`pending_count`、`approved_count`、`rejected_count`、`published_count`、`ai_count`、`created_at`、`updated_at`。
- 批次详情 item：包含 `raw_data`、`parsed_content`、`parsed_options`、`parsed_answer`、`parsed_analysis`、`status`、`review_note`、`question_id`、`reject_reason`、`reviewed_by`、`reviewed_at`、`question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id`、`ai_generated`、`ai_source`、`ai_confidence`、`ai_metadata`、`ai_reviewed_at`、`ai_answer_flag` 等导入、重复检测与 AI 辅助字段。
- enrich 响应：`{ task_id, batch_id, status, created_at }`，其中 `status` 初始为 `pending`。
- status 响应：`{ task_id, batch_id, status, created_at, updated_at, total_count, processed_count, error_message }`。

**状态码与副作用**：
- `404`：批次不存在，或该批次没有可查询的 AI 任务状态。
- `422`：请求参数或业务规则不满足。
- `POST /imports/{batchId}/enrich` 写入 `admin:ai:task:{taskId}` 与 `admin:ai:batch:{batchId}:task`，TTL 当前为 86400 秒，并写入 `import.enrich` 审计日志；创建前受 AI 设置服务的全局开关与月度额度拦截。
- `POST /imports/{batchId}/approve` / `POST /imports/questions/{importId}/approve`（审核即发布）时逐题走 Level 1 完全重复检测；若 `subject_id + question_hash` 命中正式题库重复题，则将该导入题置为 `published` 并挂到已发布题目 `question_id`，不重复创建；发布失败回滚为 `pending` 留在审核队列。

**`/imports/{batchId}/enrich` 约束**：
- 当前实现仍通过后台任务状态承载 AI 辅助处理；不得直接调用小程序端 API。
- 不得直接调用小程序端 API；如需复用 AI/OCR 逻辑，必须先确认 service/worker 边界。
- AI/OCR 结果只能作为辅助任务状态或待确认字段，AI 失败只更新任务为 `failed`，不得影响 `question_imports` 人工确认流程。
- 不得绕过 `question_imports + 人工确认` 直接写入 `questions`。

**`POST /imports/questions-csv`（2026-09-13）**：

- 仅接受 `.csv`，否则 415。
- 权限 `import:write`。成功响应：`total_rows`、`inserted_count`、`skipped_count`、`first_question_id`、`last_question_id`。
- 文件过大：413，`error.code=QUESTION_CSV_TOO_LARGE`。行级校验失败：400，`error.code=QUESTION_CSV_VALIDATION_ERROR`，`detail` 为可展示的行/字段说明（该接口不走全局 detail 脱敏）。
- 这是题库导出 CSV 的回灌，不是把 AI/OCR 结果直接入库。

### 3.9 科目管理 `/subjects`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/subjects` | 科目树 | subject:read |
| GET | `/subjects/{id}` | 科目详情 | subject:read |
| POST | `/subjects` | 创建科目 | subject:write |
| PATCH | `/subjects/{id}` | 编辑科目 | subject:write |
| DELETE | `/subjects/{id}` | 删除（有子科目或有题目引用时返回 422） | subject:delete |

**查询参数与请求体（Phase 4 实现，2026-05-29）**：
- `GET /subjects`：`include_inactive`（默认 `false`），返回树形 `items`。
- `POST /subjects` Body：`{ code, name, parent_id?, sort_order=0, is_active=true }`。
- `PATCH /subjects/{id}` Body：`{ code?, name?, parent_id?, sort_order?, is_active? }`，至少提供一个字段。

**响应字段**：`id`、`parent_id`、`code`、`name`、`level`、`path`、`sort_order`、`is_active`、`created_at`、`updated_at`；树节点额外包含 `children`。

**状态码与副作用**：
- `404`：科目不存在。
- `409`：`code` 冲突。
- `422`：层级超过 3、移动到自身/子孙节点、删除存在子科目或已有题目引用的科目等业务规则失败。
- 创建/更新/删除会写入 `subject.create` / `subject.update` / `subject.delete` 审计日志；`path` 当前按科目 `code` 拼接并在移动/改 code 时同步子树。

### 3.10 审计日志 `/audit-logs`（Phase 5 实现，2026-05-29）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/audit-logs` | 列表（多维过滤） | audit:read |
| GET | `/audit-logs/{id}` | 详情（含 detail JSON） | audit:read |

**查询参数**：
- `page`（默认 1，≥1）
- `pageSize`（默认 20，1-100，查询别名 `pageSize`）
- `operatorId`
- `action`（支持 `*` 通配，内部转 `LIKE`）
- `resourceType`
- `resourceId`
- `severity`：`critical|important|normal|low`
- `status`：`success|failed`
- `from` / `to`（ISO datetime）

**响应字段**：
- 列表 item：`id`、`operator_id`、`operator_name`、`action`、`resource_type`、`resource_id`、`severity`、`status`、`ip`、`created_at`
- 详情 item：在列表字段基础上增加 `detail`、`user_agent`、`error_message`

**约束**：
- 默认仅查询近 183 天；未传 `from` 时从 `to`（默认当前时间）向前回溯 183 天
- 查询跨度超过 1 年返回 422
- `from > to` 返回 422

### 3.11 统计 `/dashboard`（Phase 5 实现，2026-05-29）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/dashboard/overview` | 总览统计 | dashboard:read |
| GET | `/dashboard/daily` | 每日图表数据 | dashboard:read |
| GET | `/dashboard/questions-stats` | 题库分布 | dashboard:read |

**`/dashboard/overview` 响应字段**：
- `users_total`
- `users_new_today`
- `questions_total`
- `questions_pending_review`
- `questions_approved`
- `imports_total`
- `imports_pending`
- `audit_critical_today`
- `cache`（当前缓存运行指标，来自 `app.core.cache.get_stats()`）

**`/dashboard/daily` 查询参数**：
- `from` / `to`（date）
- 默认近 7 天；跨度超过 1 年返回 422；`from > to` 返回 422

**`/dashboard/daily` 响应字段**：
- `date`
- `users_new`
- `questions_new`
- `imports_new`
- `audits_total`

**`/dashboard/questions-stats` 响应字段**：
- `by_subject`
- `by_review_status`
- `by_difficulty`
- 每个分组项结构为 `{ "name": string, "count": number }`

**实现备注**：
- `overview` 使用 `admin:dashboard:overview` 缓存键、`admin:dashboard:overview:lock` 防穿透锁，Redis 不可用时直接查 DB
- 当前实现为请求触发缓存 + 锁，不依赖 BullMQ 主动刷新

### 3.12 AI 解析设置 `/ai-settings`（Phase 7 实现，2026-05-30）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/ai-settings` | 查看全局 AI 解析设置 | ai_setting:read |
| PATCH | `/ai-settings` | 更新 AI 解析开关或月度调用额度 | ai_setting:write |
| GET | `/ai-settings/usage` | 查看当前或指定月份 AI 用量 | ai_setting:read |

**查询参数**：
- `GET /ai-settings/usage`：`yearMonth`（可选，格式 `YYYY-MM`；不传时返回当前月）。

**设置字段（摘要）**：
- `ai_parse_enabled`：全局 AI 解析开关。
- `monthly_call_limit`：月度全局 API 调用额度；`0` 表示不限。
- `current_usage`：当前月用量快照。
- `remaining_calls`：剩余调用次数；不限额度时为 `null`。
- `updated_at`、`updated_by`：最近更新时间与操作者。

**用量字段（摘要）**：
- `year_month`、`call_count`、`limit_snapshot`、`created_at`、`updated_at`。

**与导入 enrich 的关系**：
- `POST /imports/{batchId}/enrich` 创建任务前会执行 `ensure_ai_parse_allowed`。
- 全局关闭时所有管理员均被拦截；`super_admin` 不绕过全局关闭。
- 月度额度超限时普通管理员被拦截；`super_admin` 仅绕过额度限制。

### 3.13 AI 模型配置 `/ai-models`（2026-06-10 新增）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/ai-models` | 获取模型列表（不含 api_key，含 `api_configured: bool`） | ai_setting:read |
| PATCH | `/ai-models/{id}` | 更新模型字段（is_enabled / is_default / api_key / api_base_url） | ai_setting:write |

**GET `/ai-models` 响应字段（摘要）**：
- `id`、`name`、`display_name`、`provider`、`api_base_url`、`api_configured`（布尔，表示是否已配置 API key）、`is_enabled`、`is_default`、`sort_order`、`created_at`、`updated_at`。

**PATCH `/ai-models/{id}` 行为**：
- `api_key="****"` 时视为不修改（保留原值）。
- 传入非掩码 api_key 时使用 Fernet 加密存储（依赖环境变量 `AI_CONFIG_ENCRYPT_KEY`；未配置时以明文存储并记录警告）。
- 设为 `is_default=true` 时自动清除其他模型的 default 标志。
- 写入审计日志 `action=ai_model_config.update, severity=normal`。

**Seed 默认模型**：
| name | display_name | provider |
|------|-------------|----------|
| deepseek-v4-flash | DeepSeek V4 Flash | deepseek |
| gpt-4o | GPT-4o | openai |
| claude-3.5-sonnet | Claude 3.5 Sonnet | anthropic |

### 3.14 AI 配置键值对 `/ai-configs`（2026-06-10 新增）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/ai-configs` | 获取全部配置键值，返回扁平 JSON | ai_setting:read |
| PATCH | `/ai-configs` | 部分更新配置项 | ai_setting:write |

**GET `/ai-configs` 响应**：
```json
{
  "configs": {
    "ocr_correction_prompt": "你是 OCR 文本纠错助手...",
    "ocr_strategy_math_formula": true,
    "completion_prompt": "你是考研题目补全助手...",
    "completion_auto_stem": true
  }
}
```
值会自动转换为 bool / int / str 类型。

**PATCH `/ai-configs` 请求体**：
```json
{
  "configs": {
    "ocr_strategy_digit_letter": false,
    "ocr_correction_prompt": "新的 prompt 内容..."
  }
}
```

**约束**：
- 不存在的 config_key 静默忽略（仅更新 `_DEFAULT_CONFIGS` 中定义的 17 个 key）。
- `ocr_correction_prompt` 和 `completion_prompt` 字段 max_length=5000，超长返回 422。
- 写入审计日志 `action=ai_config.update, severity=normal`。

**Seed 默认 config_key 清单（17 个）**：
```
ocr_correction_prompt, ocr_strategy_math_formula, ocr_strategy_punctuation,
ocr_strategy_digit_letter, ocr_strategy_space_newline, ocr_structure_question_type,
ocr_structure_options, ocr_structure_answer, ocr_structure_analysis,
ocr_filter_max_chars, ocr_filter_max_tokens, ocr_filter_sensitive,
completion_prompt, completion_auto_stem, completion_auto_options,
completion_auto_answer_reasoning, completion_auto_knowledge_tags
```

### 3.15 公式卡 `/formulas`（2026-08-10 同步）

> 权限前缀使用连字符：`formula:read` / `formula:create` / `formula:update` / `formula:delete` / `formula:review` / `formula:import` / `formula-category:read` / `formula-category:write`。

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/formulas` | 公式卡列表（status / category_id / q / library_type 过滤，分页） | formula:read |
| GET | `/formulas/tags` | 公式标签列表（只读） | formula:read |
| GET | `/formulas/{card_id}` | 公式卡详情 | formula:read |
| POST | `/formulas` | 创建公式卡（status=draft，version=1，写 v1 快照） | formula:create |
| PUT | `/formulas/{card_id}` | 更新公式卡（内容变更重置 draft，写新版本快照） | formula:update |
| DELETE | `/formulas/{card_id}` | 软删除（published 需先下架；写删除快照） | formula:delete |
| POST | `/formulas/{card_id}/review` | 状态机操作（approve/reject/publish/offline/restore） | formula:review |
| POST | `/formulas/batch-review` | 批量状态机操作 | formula:review |
| GET | `/formulas/{card_id}/versions` | 版本历史列表 | formula:read |
| POST | `/formulas/{card_id}/check-duplicate` | 重复检测（同 category + 同 content_hash） | formula:read |
| POST | `/formulas/validate-latex` | 服务端 LaTeX 校验（危险命令 / 括号配平） | formula:read |
| GET | `/formulas/import-jobs` | 导入任务列表 | formula:import |
| GET | `/formulas/import-jobs/{job_id}` | 导入任务详情 | formula:import |
| GET | `/formulas/import-jobs/{job_id}/items` | 导入项分页（review_status 过滤） | formula:import |
| PUT | `/formulas/import-items/{item_id}/review` | 审核导入项 | formula:import |
| GET | `/formulas/{card_id}/graph-assets` | 图资产列表 + effective | formula:read |
| PUT | `/formulas/{card_id}/graph-assets/{asset_id}/metadata` | 更新图资产 alt_text / description | formula:update |
| POST | `/formulas/{card_id}/graph-assets/upload` | 上传/替换图资产（pure_formula 拒绝） | formula:update |
| DELETE | `/formulas/{card_id}/graph-assets/{source_type}` | 删除图资产（uploaded/template） | formula:update |
| POST | `/formulas/{card_id}/graph/preview` | 生成预览图（graph_status=draft） | formula:update |
| POST | `/formulas/{card_id}/graph/confirm` | 确认预览为正式资产（preview_token + card_version 乐观锁） | formula:update |
| POST | `/formulas/{card_id}/graph/regenerate` | 重新生成并替换正式资产 | formula:update |
| DELETE | `/formulas/{card_id}/graph/generated` | 仅删生成资产（保留手动上传） | formula:update |
| POST | `/formulas/graphs/generate-missing` | 批量补生成缺失图（返回 job_id 轮询） | formula:update |
| GET | `/formulas/graphs/generate-missing/{job_id}` | 批量补生成任务状态 | formula:read |
| GET | `/formulas/categories` | 分类树 | formula-category:read |
| POST | `/formulas/categories` | 创建分类 | formula-category:write |
| PUT | `/formulas/categories/{category_id}` | 更新分类 | formula-category:write |

**`PUT /formulas/{card_id}` 版本号与审计链（2026-08-09 同步，b0190943）**：
- 问题：`card.version` 可能滞后于审计链——publish 动作会在 `card.version + 1` 处写快照但**不递增列值**，导致按 `card.version + 1` 直接取号可能与 `uq_formula_card_versions_card_version` 唯一约束冲突。
- 修复：
  1. `SELECT ... FOR UPDATE` 行锁该卡片，串行化同一卡片的并发编辑，消除 select max→+1 的 TOCTOU 竞态。
  2. 从 `formula_card_versions` 取 `MAX(version)` 推导新版本号：`next_version = max(card.version, max_ver) + 1`。
  3. 写 `FormulaCardVersion`（action=update）与审计 `formula.update` 在同一事务内。
- 内容字段（formula_blocks）变更时重算 `content_hash`（SHA-256）。
- 状态为 `approved` / `rejected` 的卡片内容更新后重置为 `draft`。

### 3.16 408 考试 `/exams`（2026-09-23 同步）

前缀 `/api/admin/v1/exams`。试卷类型 `past_exam_choice` / `mock_choice`，状态 `draft` / `published` / `archived`。列表默认排除 `deleted_at` 非空的试卷。数字 `paper_id` 与 `public_id`（32 位 hex）各有一套等价路径。

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/exams/papers` | 列表。查询 `status`、`paper_type`、`year`（2000–2100） | question:read |
| POST | `/exams/papers` | 创建草稿 | question:write |
| GET | `/exams/papers/{paper_id}` | 详情 | question:read |
| GET | `/exams/papers/public/{public_id}` | 按 public_id 取详情 | question:read |
| GET | `/exams/past-exam-candidates` | 某年真题候选题。查询 `year` 必填 | question:read |
| PATCH | `/exams/papers/{paper_id}` | 更新元数据 | 角色 `admin` 或 `super_admin` |
| PATCH | `/exams/papers/public/{public_id}` | 按 public_id 更新元数据 | 角色 `admin` 或 `super_admin` |
| DELETE | `/exams/papers/{paper_id}` | 软删除 | 角色 `admin` 或 `super_admin` |
| DELETE | `/exams/papers/public/{public_id}` | 按 public_id 软删除 | 角色 `admin` 或 `super_admin` |
| PUT | `/exams/papers/{paper_id}/items` | 整卷替换题目 | question:write |
| PUT | `/exams/papers/public/{public_id}/items` | 按 public_id 替换题目 | question:write |
| POST | `/exams/papers/{paper_id}/items/quick-fill-past-exam` | 按年份候选快速组真题 | question:write |
| POST | `/exams/papers/public/{public_id}/items/quick-fill-past-exam` | 同上，public_id | question:write |
| POST | `/exams/papers/{paper_id}/items/refresh-past-exam` | 按当前题库刷新真题题目 | question:write |
| POST | `/exams/papers/public/{public_id}/items/refresh-past-exam` | 同上，public_id | question:write |
| DELETE | `/exams/papers/{paper_id}/items` | 清空题目 | question:write |
| DELETE | `/exams/papers/public/{public_id}/items` | 按 public_id 清空题目 | question:write |
| POST | `/exams/papers/{paper_id}/publish` | 发布 | question:write |
| POST | `/exams/papers/public/{public_id}/publish` | 按 public_id 发布 | question:write |
| POST | `/exams/papers/{paper_id}/restore` | 从归档恢复 | question:write |
| POST | `/exams/papers/public/{public_id}/restore` | 按 public_id 恢复 | question:write |
| POST | `/exams/papers/{paper_id}/archive` | 归档 | question:write |
| POST | `/exams/papers/public/{public_id}/archive` | 按 public_id 归档 | question:write |

规则：

- 软删除写 `deleted_at`，`is_active=false`，若当前不是 `archived` 则改为 `archived`。作答记录与审计保留。响应 `{status:"ok", public_id}`。审计动作 `exam.paper.delete`，严重级别 `critical`。
- 同一年未删除的真题：发布时不能已有另一份 `published`；从归档恢复时不能已有另一份 `draft` 或 `published`。
- 真题选择题必须正好 40 道 `single_choice`，每题 2 分。题号区间：数据结构 1–10、组成原理 11–22、操作系统 23–32、计算机网络 33–40。模拟卷最多 40 道，同样只允许 `single_choice`。
- 换题与状态动作的失败不走全局 detail 脱敏。换题校验失败时 `error.code` 为 `EXAM_PAPER_ITEMS_INVALID`（或 `EXAM_PAPER_NOT_FOUND` / `EXAM_PAPER_STATE_ERROR`）。状态动作失败时为 `EXAM_PAPER_ACTION_INVALID` 或上述 not-found / state 码。HTTP 仍是 404 / 409 / 422。

---

## 四、统一响应结构（I8 修订：Stripe 风格）

**核心原则**：
- HTTP 状态码精确表达 HTTP 错误（200/400/401/403/404/422/429/500）
- 业务异常使用 HTTP 状态码 + 错误对象表达
- **不再混用业务 code**

### 成功响应（HTTP 200）

```json
{
  "data": { ... },
  "meta": {
    "requestId": "req_a1b2c3",
    "timestamp": "2026-05-26T10:00:00.000Z"
  }
}
```

### 分页列表响应（HTTP 200）

```json
{
  "data": {
    "items": [ ... ],
    "pagination": {
      "page": 1,
      "pageSize": 20,
      "total": 150,
      "totalPages": 8,
      "hasNext": true,
      "hasPrev": false
    }
  },
  "meta": { ... }
}
```

### 错误响应（HTTP 4xx / 5xx）

```json
{
  "error": {
    "type": "permission_denied",
    "message": "没有权限执行此操作（缺少 import:write）",
    "hint": "请联系超级管理员授权",
    "field": "permission"
  },
  "meta": {
    "requestId": "req_a1b2c3",
    "timestamp": "2026-05-26T10:00:00.000Z"
  }
}
```

---

## 五、HTTP 状态码与 error.type 映射

| HTTP | error.type | 含义 |
|------|------------|------|
| 200 | — | 成功 |
| 400 | `invalid_request` | 参数格式错误 / 类型错误 |
| 400 | `validation_failed` | 业务参数校验失败（同时返回 field） |
| 401 | `unauthorized` | 未登录 / token 无效 |
| 401 | `token_expired` | token 已过期 |
| 401 | `token_revoked` | token 已吊销（黑名单 / nbf） |
| 403 | `permission_denied` | 无权限 / 角色不足 |
| 403 | `resource_protected` | 系统资源不可操作（如删除 super_admin） |
| 404 | `not_found` | 资源不存在 |
| 409 | `conflict` | 资源冲突（如用户名重复） |
| 422 | `business_rule_violation` | 业务规则不允许（如有题目的科目不可删） |
| 429 | `rate_limit_exceeded` | 请求频率超限 |
| 500 | `internal_error` | 服务器错误 |
| 503 | `service_unavailable` | 第三方/依赖服务不可用 |

**校验失败响应示例**（field 标注）：
```json
{
  "error": {
    "type": "validation_failed",
    "message": "pageSize 必须 ≤ 100",
    "field": "pageSize"
  }
}
```

---

## 六、分页规范

### 请求参数

```
GET /v1/questions?page=1&pageSize=20&subject=math&status=pending
                 &sortBy=createdAt&sortOrder=desc
```

| 参数 | 类型 | 默认值 | 限制 |
|------|------|--------|------|
| page | number | 1 | ≥ 1 |
| pageSize | number | 20 | 1 ≤ x ≤ 100 |
| sortBy | string | createdAt | 白名单字段 |
| sortOrder | asc \| desc | desc | — |

### 过滤参数（各资源自定义）

题目列表过滤：
```
subject=408_ds&status=pending&questionType=choice
&keyword=操作系统&year=2023&importBatchId=batch_001
```

**题目列表实际查询参数（2026-08-10 同步，与代码一致）**：
- `GET /questions`：`page`、`page_size`、`subject_id`、`review_status`、`is_active`、`question_type`、`keyword`、`year`、`import_batch_id`。
- `keyword` 命中题干（raw_content/answer/analysis）与知识点名及别名（见 3.7）。
- 排序固定为 `updated_at DESC, id DESC`。

小程序用户列表过滤：
```
keyword=张三&isBanned=false
&createdFrom=2026-01-01&createdTo=2026-05-26
```

审计日志过滤：
```
operatorId=1&action=question.*&severity=critical
&from=2026-05-01&to=2026-05-26&status=success
```

**时间过滤跨度上限**：
- 一般列表：1 年
- 审计日志：1 年（超过返回 422）

---

## 七、批量操作规范（I3 修订）

> 2026-10-24 同步：题目批量接口包括 `POST /questions/batch-delete`（question:delete）与 `POST /questions/batch-approve` / `batch-reject`（question:batch_review，仅已入库重审）。首次导入审核仍走 `/imports/{batchId}/approve|reject|publish`；`/imports/questions/batch-complete` 是 AI 补全，不是审核。

```
POST /v1/questions/batch-delete
权限：question:delete
Body: { "ids": [1, 2, 3, ...] }  // 上限 50

响应：
{
  "data": {
    "successIds": [1, 2, 3, ...],
    "failedItems": [
      { "id": 12, "error": "题目不存在" },
      { "id": 23, "error": "状态不允许" }
    ]
  }
}
```

**规则**：
- 每条独立事务处理（默认）
- 单条失败不影响其他
- 整体写一条 audit_log（severity: critical）
- 支持 `Idempotency-Key` Header；Redis key 为 `admin:idempotency:{userId}:{key}`，TTL 10min
- Redis 不可用时，关键批量写接口返回 503，避免重复提交导致不一致

---

## 八、API 版本演进规范

- 当前版本：v1
- 不兼容变更必须发布 v2
- v1 至少维护 6 个月并行（与 v2 并存）
- 删除字段 → v2 之前先标记 `deprecated`（响应中包含 `deprecation` warning header）
- **同一版本内**不允许破坏性变更（仅追加字段）

---

## 九、CORS 与安全 Header

```
Access-Control-Allow-Origin: <配置中的 allowlist>
Access-Control-Allow-Credentials: true
Strict-Transport-Security: max-age=31536000
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
```

**禁止**：
- 使用 `Access-Control-Allow-Origin: *`
- 在响应中泄露内部错误 stack trace（生产环境）
- 通过 GET 请求传敏感数据

---

## 十、不变式（Invariants）

1. 所有业务响应通过 FastAPI response helper 统一包装，**禁止**裸 JSON（health 探针例外）
2. 所有异常通过 FastAPI exception handler 统一处理，**禁止**手动 `return { error: ... }`
3. pageSize > 100 → 422
4. 批量操作 ids.length > 50 → 422
5. 任何 GET 接口不修改服务端状态
6. 任何 POST/PUT/PATCH/DELETE 必须对应 audit_log 记录（按 severity 分级）
7. JWT type ≠ "admin" → 401
