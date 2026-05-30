# Admin API 规范

> 版本：v2.4（题库 Level 1 去重字段同步版） | 状态：Phase 7 后端已完成 | 更新：2026-05-30
> 修订自审计报告 I8（统一 Stripe 风格）、I10（liveness/readiness）、C1（拆分 app-users 与 admin-users）
>
> - **变更原因**：2026-05-30 同步 Phase 7 新增 AI 解析设置与月度用量接口、权限要求和导入 enrich 前置拦截语义。
> - **变更原因**：2026-05-30 同步题库 Level 1 完全重复检测在导入批次详情 / 审核队列返回的重复字段，以及发布阶段拦截语义。

---

## 一、基础规范

### Base URL
```
开发：http://localhost:8000/api/admin/v1
生产：https://api.2240ai.com/api/admin/v1
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
关键写操作（如 batch-approve）支持：
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
POST   /v1/questions/{id}/approve
POST   /v1/questions/{id}/reject
POST   /v1/questions/batch-approve
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

### 3.3 小程序用户管理 `/app-users`（C1：与 admin-users 严格区分）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/app-users` | 列表 | app_user:read |
| GET | `/app-users/{id}` | 详情（含练题数 / 错题数 / 最近活跃） | app_user:read |
| PATCH | `/app-users/{id}` | 编辑运营备注/状态类字段（白名单待确认；默认不改微信来源资料） | app_user:write |
| POST | `/app-users/{id}/ban` | 封禁（Body: `{ reason }`） | app_user:ban |
| POST | `/app-users/{id}/unban` | 解封 | app_user:ban |

### 3.4 后台管理员管理 `/admin-users`（C1）

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/admin-users` | 管理员列表 | admin_user:read |
| GET | `/admin-users/{id}` | 详情 | admin_user:read |
| POST | `/admin-users` | 创建（roleId 不能为 super_admin） | admin_user:write |
| PATCH | `/admin-users/{id}` | 更新（不可改自己的 role） | admin_user:write |
| DELETE | `/admin-users/{id}` | 删除（禁删 super_admin / 自己） | admin_user:delete |
| POST | `/admin-users/{id}/force-logout` | 强制下线（更新 nbf） | admin_user:write |
| POST | `/admin-users/{id}/reset-password` | 重置密码 | admin_user:write |

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
| GET | `/questions` | 列表（多维过滤） | question:read |
| GET | `/questions/{id}` | 详情 | question:read |
| GET | `/questions/{id}/versions` | 历史版本列表 | question:read |
| GET | `/questions/{id}/versions/{version}` | 某版本详情 | question:read |
| PATCH | `/questions/{id}` | 编辑（编辑后视权限进入 re_pending） | question:write |
| DELETE | `/questions/{id}` | 删除 | question:delete |
| POST | `/questions/{id}/approve` | 审核通过 | question:review |
| POST | `/questions/{id}/reject` | 审核拒绝（Body: `{ reason }`） | question:review |
| POST | `/questions/batch-approve` | 批量通过（ids 上限 50） | question:batch_review |
| POST | `/questions/batch-reject` | 批量拒绝 | question:batch_review |
| PATCH | `/questions/{id}/toggle-active` | 上下架 | question:write |
| POST | `/questions/{id}/rollback` | 回滚到指定版本（预留 Phase 3.5+） | question:write + question:review |

### 3.8 导入管理 `/imports`

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/imports` | 导入批次列表 | import:read |
| GET | `/imports/{batchId}` | 批次详情（含题目分页） | import:read |
| POST | `/imports/{batchId}/enrich` | 创建 AI 辅助处理任务（创建前检查全局 AI 开关与月度额度） | import:write |
| GET | `/imports/{batchId}/status` | 读取该批次最新 AI 任务进度（Redis/cache） | import:read |

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
- `POST /imports/{batchId}/approve` / 批次内导入题审核通过时会先走 Level 1 完全重复检测；若 `subject + question_hash` 命中正式题库重复题，则返回重复信息并阻止发布。

**`/imports/{batchId}/enrich` 约束**：
- 当前实现仍通过后台任务状态承载 AI 辅助处理；不得直接调用小程序端 API。
- 不得直接调用小程序端 API；如需复用 AI/OCR 逻辑，必须先确认 service/worker 边界。
- AI/OCR 结果只能作为辅助任务状态或待确认字段，AI 失败只更新任务为 `failed`，不得影响 `question_imports` 人工确认流程。
- 不得绕过 `question_imports + 人工确认` 直接写入 `questions`。

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
    "message": "没有权限执行此操作（缺少 question:review）",
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

```
POST /v1/questions/batch-approve
权限：question:batch_review
Body: { "ids": [1, 2, 3, ...] }  // 上限 50

响应：
{
  "data": {
    "totalRequested": 50,
    "successCount": 47,
    "failedCount": 3,
    "successIds": [1, 2, 3, ...],
    "failedItems": [
      { "id": 12, "reason": "题目不存在" },
      { "id": 23, "reason": "状态不允许" }
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
