# API Specification

> 2240AI 全量 API 接口规范。Base URL: `/api/v1`
>
> 2026-08-10 更新原因：题目/科目关系已从 `subject`（string code，如 "math2"）迁移为 `subject_id`（int，FK `subjects.id`），响应中展开 `subject_code` / `subject_name`；本规范相关参数表与 JSON 示例已同步更新。
>
> 2026-10-23 更新原因：复习与错题本接口按当前路由修正——`/review/schedule-submit`、`/review/batch-submit`、`/review/grade-submit`、`PUT /wrong-questions/{id}/quality` 均不存在（已移除），评分提交统一为 `POST /review/grade-batch`；补登记 `/review/today/next-batch`、`/review/{schedule_id}/master|unmaster`、`/review/history` 与错题诊断（`/wrong-questions/diagnosis/*`）端点。
>
> 2026-11-04 更新原因：通用响应与错误码章节按当前 `PaginatedResponse`、`http_error_contract.py` 与无 success 外壳的实际实现修订。

---

## 认证方式

所有接口（除 `/auth/login` 外）需要 Header：

```
Authorization: Bearer <jwt_token>
```

---

## 通用响应格式

2026-11-04 修订：App API 成功响应不再描述为 `{code, message, data}` 外壳。路由返回的资源对象或列表就是响应正文；分页直接使用 `PaginatedResponse` 形态：

```json
{
  "items": [],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "total_pages": 5
}
```

`total=0` 时 `total_pages=0`；其他情况下 `total_pages` 至少为 1。各端点可能按既有契约使用其他列表形态或额外字段，新增端点必须核对所属模块而不是假设全局别名。

---

## 错误码

错误响应使用统一 `error` 对象，不使用数字成功码。客户端必须容忍未显式登记的 `HTTP_<status>` 兜底码，不能假设错误码枚举封闭：

```json
{
  "error": {
    "code": "HTTP_404",
    "message": "请求的资源不存在",
    "retryable": false,
    "request_id": "req_example",
    "trace_id": "trace_example"
  }
}
```

- `error.code` 为大写下划线机器码；`detail` 未提供可公开的稳定业务码时回退为 `HTTP_<status>`。
- `error.retryable` 由后端按错误类型或 429/502/503/504 判定；`request_id` 与 `trace_id` 在上下文可用时返回。
- 健康端点有专用轻量结构，不应按本错误对象解析；业务端点契约仍以对应章节为准。

---

## 认证

### POST `/auth/login`

微信 code 登录（唯一登录入口）。

```json
// Request
{
  "code": "wx_login_code"     // wx.login() 返回的临时 code
}

// Response
{
  "access_token": "jwt_token_string",
  "user": {
    "id": 1,
    "nickname": "考研人",
    "avatar_url": "https://..."
  }
}
```

首次登录自动创建用户。

### GET `/users/me`

获取当前用户信息。

### PUT `/users/me`

```json
// Request
{
  "nickname": "新昵称",
  "avatar_url": "https://..."
}
```

---

## 题库

### GET `/questions`

题目列表（分页）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 筛选科目 |
| question_type | string? | 筛选题型 |
| page | int | 默认 1 |
| page_size | int | 默认 20，最大 100 |

### POST `/questions`

创建题目。

```json
{
  "subject_id": 2,
  "question_type": "choice",
  "content": {"text": "题干..."},
  "options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"},
  "answer": "A",
  "analysis": "解析内容",
  "knowledge_points": ["导数", "求导公式"],
  "difficulty": 3,
  "source": "来源",
  "year": 2024
}
```

### GET `/questions/random`

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 科目筛选 |
| question_type | string? | 题型筛选 |
| exclude_ids | string? | 排除的题目 ID，逗号分隔 |

### GET `/questions/{id}/detail`

题目详情（含答案和解析）。仅已答过该题的用户可访问，未答过返回 403。

```json
{
  "id": 1,
  "subject_id": 2,
  "subject_code": "math2",
  "subject_name": "数学二",
  "question_type": "choice",
  "content": {"text": "题干"},
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "answer": "A",
  "analysis": "解析内容",
  "knowledge_points": ["导数"]
}
```

---

## 练习

### GET `/practice/questions`

获取刷题列表（不含答案）。知识点由 `question_knowledge_points` 关联表按 `position` 排序加载。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| subject_id | int | **必填** | 科目 ID（支持父级科目聚合） |
| include_children | bool | true | 是否包含子科目（父级科目 + sequential 报 400） |
| count | int | 20 | 题目数量，1-50 |
| mode | string | random | random / sequential / smart / similar |
| knowledge_point | string? | - | 知识点筛选（normalized_name 精确匹配，逗号分隔 = AND），传 `knowledge_point` |
| exclude_answered | bool | false | 是否排除已做题 |
| no_repeat_days | int? | - | 最近 N 天不重复，1-365 |
| use_leitner | bool | true | 是否启用 Leitner 到期过滤；关闭后仍保留 `exclude_answered` / `no_repeat_days` 约束 |
| source_question_id | int? | - | similar 模式的相似源题 ID |
| smart_strategy | string | weakness_vector | smart 模式策略 |

`use_leitner` 对 `smart` / `similar` 模式同样生效：候选召回完成后，由发题签发层按 `next_review_at` 做到期过滤，并在数量不足时用随机到期候选补齐。

```json
// Response
{
  "questions": [
    {
      "id": 1,
      "subject_id": 2,
      "subject_code": "math2",
      "subject_name": "数学二",
      "question_type": "choice",
      "content": {"text": "题干"},
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "knowledge_points": ["导数"],
      "difficulty": 3,
      "image_url": null,
      "trace_id": "trace-xxx",
      "recommend_reason": null,
      "recommend_score": null,
      "strategy": null,
      "similarity": null
    }
  ],
  "total": 10,
  "mode": "random",
  "trace_id": "trace-xxx",
  "request_id": null
}
```

### GET `/practice/subjects`

刷题页可用科目树（动态，不硬编码）。

### GET `/practice/knowledge-states`

查询当前用户所有知识点掌握状态（跨科目汇总）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| status | string? | - | 过滤：weak / normal / good / mastered / observing / possible_weak / possible_mastered |
| limit | int | 50 | 返回条数，1-200 |

```json
// Response
{
  "items": [
    {
      "knowledge_point_id": 1,
      "knowledge_point": "导数",
      "mastery_score": 60.0,
      "confidence": 0.8,
      "label": "good",
      "answer_count": 10,
      "correct_count": 8,
      "wrong_count": 2,
      "recent_wrong_count": 1,
      "last_practiced_at": "2026-05-24T12:00:00"
    }
  ],
  "total": 1
}
```

### GET `/practice/weak-knowledge-points`

查询用户明确薄弱的知识点（mastery_score < 40 且 confidence >= 0.3），供 V4 智能推荐使用。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 20 | 返回条数，1-100 |

### POST `/practice/submit`

单题提交答案。

```json
// Request
{
  "question_id": 1,
  "user_answer": "A",
  "used_time": 30,
  "request_id": "optional-idempotency-key"   // 可选
}

// Response
{
  "question_id": 1,
  "is_correct": true,
  "correct_answer": "A",
  "analysis": "解析内容",
  "knowledge_points": ["导数"],
  "is_wrong_added": false
}
```

### POST `/practice/batch-submit`

批量提交答案。`session`（刷题会话元数据）可选：旧客户端不带 `session` 时仍正常答题且不创建 PracticeSession；携带 `session` 时 `request_id` 必填，用于 `(user_id, request_id)` 幂等去重，防止网络重试重复记录学习时长。

```json
// Request
{
  "answers": [
    {"question_id": 1, "user_answer": "A", "used_time": 30},
    {"question_id": 2, "user_answer": "C", "used_time": 45}
  ],
  "session": {
    "request_id": "uuid-v4",
    "subject_id": 2,
    "mode": "random",
    "started_at": "2026-08-09T10:00:00Z",
    "finished_at": "2026-08-09T10:15:00Z",
    "duration_sec": 900,
    "question_count": 10,
    "answered_count": 10,
    "status": "completed"
  }
}

// Response
{
  "results": [
    {"question_id": 1, "is_correct": true, "correct_answer": "A", "analysis": "...", "knowledge_points": [], "is_wrong_added": false},
    {"question_id": 2, "is_correct": false, "correct_answer": "C", "analysis": "...", "knowledge_points": [], "is_wrong_added": false}
  ],
  "total_correct": 1,
  "total_wrong": 1,
  "trace_id": "trace-xxx"
}
```

### GET `/practice/stats`

刷题统计。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| days | int | 7 | 统计天数，1-365 |

```json
{
  "total_answered": 150,
  "total_correct": 120,
  "accuracy": 0.8,
  "by_subject": [
    {"subject_id": 2, "subject_code": "math2", "subject_name": "数学二", "answered": 100, "correct": 85, "accuracy": 0.85}
  ],
  "daily_stats": [
    {"date": "2026-05-24", "answered": 20, "correct": 16}
  ],
  "current_streak": 3
}
```

### GET `/practice/records`

练习记录列表（分页，每道题一条记录）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 筛选科目 |
| page | int | 默认 1 |
| page_size | int | 默认 20，最大 100 |

```json
// Response
{
  "items": [
    {
      "id": 1,
      "question_id": 5,
      "subject_id": 2,
      "subject_code": "math2",
      "subject_name": "数学二",
      "question_type": "choice",
      "user_answer": "A",
      "is_correct": true,
      "used_time": 25,
      "answered_at": "2026-05-24T12:00:00"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20
}
```

---

## 错题本

### GET `/wrong-questions`

错题列表（分页）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 筛选科目 |
| error_type | string? | 筛选错误类型 |
| topic | string? | 筛选知识点主题 |
| date_from | date? | 加入错题本的开始日期，`YYYY-MM-DD`，北京时间，包含当天 |
| date_to | date? | 加入错题本的结束日期，`YYYY-MM-DD`，北京时间，包含当天 |
| page | int | 默认 1 |
| page_size | int | 默认 20（1-100） |

日期条件作用于 `WrongQuestion.created_at`，与学科、错因和知识点条件组合使用；查询总数与分页使用同一组条件。结束日期覆盖当天最后一刻（内部使用次日北京时间零点之前的 UTC 范围）。日期参数均可省略；无效日期或开始日期晚于结束日期返回 422。

### GET `/wrong-questions/task-flow`

错题任务流，按今日应复习、高频错题、最近新增、待巩固、已掌握分组。支持与列表一致的 `subject_id`、`error_type`、`topic`、`product_scope`、`date_from`、`date_to` 参数；`preview_size` 默认 3，范围 1-10。日期筛选同时作用于分组总数、预览条目和 `summary`；不是只过滤当前页或预览条目。无日期条件时保持原有完整错题本统计。

### GET `/wrong-questions/stats`

错题统计。

```json
{
  "total": 50,
  "unmastered": 30,
  "by_subject": [
    {"subject_id": 2, "subject_code": "math2", "subject_name": "数学二", "count": 20},
    {"subject_id": 3, "subject_code": "exam408", "subject_name": "计算机 408", "count": 18},
    {"subject_id": 4, "subject_code": "english", "subject_name": "英语", "count": 12}
  ],
  "by_error_type": {
    "concept": 15,
    "calculation": 20,
    "careless": 10,
    "other": 5
  }
}
```

### GET `/wrong-questions/{id}`

单条错题详情（含关联题目信息）。

### PUT `/wrong-questions/{id}`

更新错题（标记已掌握 / 修改错误类型）。

```json
{
  "mastered": true,
  "error_type": "calculation"
}
```

### GET `/wrong-questions/diagnosis/taxonomy`

错误分类字典（错因分类树）。

### GET `/wrong-questions/diagnosis/stats`

错因诊断统计。

### GET `/wrong-questions/{id}/diagnosis`

单条错题的诊断结果。

### PUT `/wrong-questions/{id}/diagnosis`

更新单条错题的诊断结果。

### POST `/wrong-questions/{id}/diagnosis/suggest`

AI 错因诊断建议（辅助，需人工确认）。

### POST `/wrong-questions/batch`

批量错题操作。

> 已移除：`PUT /wrong-questions/{id}/quality`（质量评分端点已不存在；SM-2 评分提交统一走 `POST /review/grade-batch`，见复习章节）。

---

## 复习

### GET `/review/today`

今日待复习列表（分页）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 筛选科目 |
| limit | int | 默认 20 |

```json
// Response
{
  "total_today": 10,
  "questions": [
    {
      "schedule_id": 1,
      "question_id": 100,
      "subject_id": 2,
      "subject_code": "math2",
      "subject_name": "数学二",
      "question_type": "choice",
      "stem": "题干...",
      "interval": 6,
      "repetitions": 1,
      "ease_factor": 2.6
    }
  ]
}
```

### GET `/review/today/overview`

今日复习任务流概览（批次 / 完成情况 / 预计时长）。

```json
// Response
{
  "date": "2026-08-10",
  "today_due_count": 12,
  "today_completed_count": 3,
  "today_remaining_count": 9,
  "today_overdue_count": 2,
  "today_new_due_count": 1,
  "estimated_minutes": 18,
  "batch_size": 10,
  "current_batch_no": 1,
  "total_batch_count": 2,
  "remaining_batch_count": 1,
  "has_due_review": true,
  "is_completed": false
}
```

### GET `/review/today/result`

今日复习完成结果汇总（正确/错误/掌握/明日待复习数）。

### POST `/review/today/next-batch`

获取下一批待复习题目（提交上一批后领取）。

### POST `/review/grade-batch`

批量自动批改 + 提交复习评分（上限 40 条）。服务端按作答对错映射 rating：正确 → 4，错误 → 1；不支持调用方自带 rating。

```json
// Request
{
  "reviews": [
    {
      "schedule_id": 1,
      "question_id": 100,
      "question_version_id": 555,
      "occurrence_seq": 0,
      "request_id": "client-generated-id-8+",
      "user_answer": "A"
    }
  ],
  "session": {
    "request_id": "session-request-id",
    "duration_sec": 180
  }
}

// Response（逐条结果；单条失败不中断整批）
{
  "results": [
    {
      "schedule_id": 1,
      "question_id": 100,
      "question_version_id": 555,
      "occurrence_seq": 1,
      "request_id": "client-generated-id-8+",
      "success": true,
      "is_correct": true,
      "correct_answer": "A"
    }
  ],
  "total": 1
}
```

> 已移除：`POST /review/schedule-submit`、`POST /review/batch-submit`（自评 rating 的单条/批量提交端点已不存在）。

### GET `/review/schedule-stats`

复习统计。

```json
{
  "total_scheduled": 50,
  "total_reviewed_today": 3,
  "remaining_today": 9,
  "overdue": 2,
  "accuracy_last_7d": 0.78,
  "by_subject": [
    {"subject_id": 2, "subject_code": "math2", "subject_name": "数学二", "scheduled": 20, "reviewed": 5, "remaining": 8}
  ]
}
```

### GET `/review/history`

复习历史（分页）。

### POST `/review/{schedule_id}/master`

标记已掌握。

### POST `/review/{schedule_id}/unmaster`

取消已掌握。

> 已移除：`POST /review/grade-submit`（单题自动批改端点已不存在，统一走 `POST /review/grade-batch`）。

---

## 答题行为

### POST `/behavior/record`

批量记录答题行为。

```json
{
  "subject_id": 2,
  "session_type": "random",
  "records": [
    {
      "question_id": 1,
      "time_spent_sec": 30,
      "is_final_correct": true,
      "view_answer_count": 0,
      "switch_count": 0,
      "is_abandoned": false,
      "user_answer": "A",
      "correct_answer": "A"
    }
  ]
}
```

### GET `/behavior/stats`

答题行为统计。

```json
{
  "total_answers": 100,
  "correct_count": 70,
  "accuracy": 0.7,
  "avg_time_sec": 45,
  "by_subject": [
    {"subject_id": 2, "subject_code": "math2", "subject_name": "数学二", "count": 40, "avg_time_sec": 50}
  ]
}
```

---

## AI

### POST `/ai/error-analysis`

AI 错题分析。

```json
// Request
{
  "wrong_question_id": 1
}

// Response
{
  "session_type": "error_analysis",
  "content": {
    "error_analysis": "错误原因分析...",
    "knowledge_points": ["导数", "求导公式"],
    "study_suggestion": "复习建议..."
  },
  "from_cache": false,
  "from_fallback": false,
  "tokens_used": 150,
  "model": "qwen-plus (示例，实际由 admin_ai_model_configs 决定)",
  "duration_ms": 2000,
  "availability": null
}
```

模型鉴权失败、限流或生成超时通过 HTTP 200 的业务响应表示：
`from_fallback=true`，并携带 `error_code`、`retryable`；这类响应表示本次生成已经失败，
客户端应结束加载并展示错误。强制重新生成失败且存在匹配的历史缓存时，
返回 `cache_preserved=true`、`force_regenerated=false`，保留历史内容和生成时间。
`model="generating"` 表示已有生成请求占用租约，客户端可继续轮询结果。

当错题 AI 被共享模型健康门禁禁用时，响应可携带 `availability`：

```json
{
  "error_code": "ai_service_unavailable",
  "retryable": false,
  "cache_preserved": true,
  "availability": {
    "status": "unavailable",
    "enabled": false,
    "reason": "configuration",
    "message": "AI 服务配置或权限异常，等待管理员处理",
    "retry_after_ms": 300000
  }
}
```

`status` 为 `checking | available | unavailable`。共享原因包括 `quota`、
`configuration`、`transient`、`unconfigured`、`status_unavailable`；个人额度原因
为 `user_quota`。该状态只阻止新的 AI 分析、重新生成和 AI 老师调用，不删除或隐藏
已有分析、对话和普通错题内容。

### GET `/ai/error-analysis/availability`

查询当前用户能否使用错题 AI 分析与 AI 老师。加载错题详情时调用；首次请求或缓存
过期时会触发后端模型探测。成功状态共享 30 秒，临时故障按
`30/60/120/300` 秒退避，额度、鉴权或模型配置错误冷却 5 分钟。探测仍在进行时返回
`status=checking`，客户端应按 `retry_after_ms`（当前为 2000 毫秒）短轮询；页面
传输超时只结束等待动画，不应将检查中误判为业务调用失败。

```json
{
  "status": "available",
  "enabled": true,
  "reason": "",
  "message": "",
  "retry_after_ms": 30000
}
```

管理员更新绑定的 LLM 模型配置后会立即强制重新探测。只有测试已保存且参数完全匹配
的模型配置，才会更新共享健康状态；未保存表单的测试不会解锁用户功能。

`GET /ai/error-analysis/status/{wrong_question_id}` 只查询已持久化的结果，
返回 `ready`、`content`、`generated_at`；`ready=false` 本身不能证明后台仍在生成。
`POST /ai/error-analysis/recover` 接受错题 ID、`force_regenerate` 及可选
`baseline_generated_at`，返回 `queued`。小程序仅在网络响应丢失或 HTTP 408/502/504
时启动恢复与轮询；明确的 HTTP 4xx、500、503 等失败直接结束加载。

### POST `/ai/408-teacher`

执行服务端冻结的 408 AI 老师动作。请求不接受自由 Prompt，只接受
`question_id`、固定 `action` 及可选版本/诊断/考试上下文。模型健康检查不通过时返回
HTTP 503：

```json
{
  "detail": {
    "code": "ai_service_unavailable",
    "status": "unavailable",
    "enabled": false,
    "reason": "configuration",
    "message": "AI 服务配置或权限异常，等待管理员处理",
    "retry_after_ms": 300000
  }
}
```

小程序保留并展示已有老师结果，但禁用新的老师动作；管理员修复模型配置并且探测
成功后自动恢复。页面在老师面板内直接展示 `message` 或结构化原因，避免把所有禁用
情况折叠成通用网络错误。

### POST `/ai/study-advice`

AI 学习建议。

```json
// Request
{
  "subject_id": 2
}

// Response
{
  "session_type": "study_advice",
  "content": {
    "weak_points": ["导数", "积分"],
    "recommended_focus": "建议重点复习...",
    "daily_plan": "今日学习计划..."
  },
  "from_cache": false,
  "from_fallback": false,
  "tokens_used": 200,
  "model": "qwen-plus (示例，实际由 admin_ai_model_configs 决定)",
  "duration_ms": 3000
}
```

### POST `/ai/explain`

AI 题目讲解。

```json
// Request
{
  "question_id": 1,
  "user_answer": "A",
  "is_correct": false,
  "focus": "solution"
}

// Response
{
  "question_id": 1,
  "explanation": "讲解内容...",
  "solution_steps": ["步骤1", "步骤2"],
  "key_knowledge_points": ["导数"],
  "common_mistakes": ["易错点"],
  "tokens_used": 300,
  "from_fallback": false
}
```

### POST `/ai/recommend`

相似题推荐。当前为规则推荐，不消耗 AI token。

```json
// Request
{
  "question_id": 1,
  "count": 5
}

// Response
{
  "source_question_id": 1,
  "recommendations": [
    {
      "question_id": 2,
      "subject_id": 2,
      "subject_code": "math2",
      "subject_name": "数学二",
      "question_type": "single_choice",
      "stem": "题干...",
      "knowledge_points": ["导数"],
      "match_reason": "知识点相同"
    }
  ],
  "strategy": "rule_based",
  "tokens_used": 0
}
```

### POST `/ai/report`

AI 学习报告。

```json
// Request
{
  "subject_id": 2,
  "days": 7
}

// Response
{
  "subject_id": 2,
  "subject_code": "math2",
  "subject_name": "数学二",
  "period_days": 7,
  "total_answered": 30,
  "accuracy": 0.73,
  "weak_points": [
    {"knowledge_point": "积分", "accuracy": 0.4, "suggestion": "加强基础题训练"}
  ],
  "strong_points": [
    {"knowledge_point": "极限", "accuracy": 0.9, "suggestion": "保持练习"}
  ],
  "learning_suggestions": ["优先复习积分"],
  "tokens_used": 500,
  "from_fallback": false
}
```

### POST `/ai/analyze-mistake`

AI 错因分析。

```json
// Request
{
  "question_id": 1,
  "user_answer": "B",
  "correct_answer": "A"
}

// Response
{
  "error_type": "concept",
  "error_type_label": "概念错误",
  "analysis": "错因分析...",
  "suggestion": "复习建议...",
  "tokens_used": 300,
  "from_fallback": false
}
```

> 2026-05-31 更新原因：同步当前 AI 学习引擎端点；`/ai/recommend` 为规则推荐，`tokens_used=0`。

---

## 统计看板

### GET `/stats/overview`

学习总览。

```json
{
  "total_practices": 50,
  "total_questions": 200,
  "total_correct": 140,
  "total_wrong": 60,
  "accuracy": 0.7,
  "total_duration_min": 300,
  "current_streak": 5,
  "today_practices": 2,
  "today_questions": 10,
  "today_correct": 7,
  "today_duration_min": 15
}
```

### GET `/stats/subjects`

学科维度统计（返回数组）。

| 参数 | 类型 | 说明 |
|------|------|------|
| days | int | 统计天数，默认不限 |

### GET `/stats/trends`

学习趋势。

| 参数 | 类型 | 说明 |
|------|------|------|
| days | int | 天数，默认 7，最大 90 |

### GET `/stats/behavior`

学习行为分析。

### GET `/stats/forgetting`

遗忘趋势分析。

### GET `/stats/dashboard`

一站式看板聚合（包含 overview + subjects + trends + behavior + forgetting）。

---

## 知识点

### GET `/knowledge-points`

知识点列表（按科目分组）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 筛选科目 |

### GET `/knowledge-points/tree`

知识点树形结构。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject_id | int? | 筛选科目 |

### POST `/knowledge-points`

创建知识点。

```json
{
  "name": "导数",
  "subject_id": 2,
  "parent_id": null
}
```

### DELETE `/knowledge-points/{id}`

删除知识点。

---

## 题库导入

### GET `/import/template`

下载 Excel 导入模板（返回 .xlsx 文件）。

### POST `/import/pipeline/upload`

统一导入入口（Excel / PDF / TXT / 图片），异步返回 `pipeline_id`，通过 `GET /import/pipelines/{pipeline_id}` 查询进度。

| 参数 | 类型 | 说明 |
|------|------|------|
| file | multipart | .xlsx / .xls / .pdf / .txt / 图片 |
| subject_id | int? | 科目 ID（与 `subject` 二选一） |
| subject | string? | 科目 code（如 `math2`，已废弃为别名，优先用 `subject_id`） |
| import_mode | string | `auto` / `book` / `exam`，默认 `auto` |
| enable_ai_repair | bool | 默认 true |
| confidence_threshold | float | 默认 0.6 |
| page_start / page_end | int? | PDF 页范围（可选） |

```json
// Response
{
  "pipeline_id": "pipeline_20260522_120000_abc123",
  "status": "queued",
  "source_type": "pdf",
  "page_range": {"start": 1, "end": 40}
}
```

### GET `/import/pipelines/{pipeline_id}`

查询导入管线状态。状态读取顺序：先查 legacy `get_pipeline_status`，再查 Redis `import:image:pipeline:{pipeline_id}`，最后回退到同进程内存 `_image_pipeline_store`；只有 legacy 与 image 状态都缺失时返回 404。

图片导入状态写入时先更新内存，再 best-effort 写入 Redis，TTL 为 86400 秒。配置 `REDIS_URL` 后可跨 worker 短期共享状态，并在 TTL 内支持重启恢复；未配置或 Redis 不可用时仅保证同进程内存回退，不保证跨 worker / 重启恢复。

`PipelineStatusResponse` 会附带 OCR 运行时、文本与切题诊断字段：`ocr_enabled`、`paddleocr_available`、原始/清洗后文本长度、行数、预览、长度/行数差值、OCR stats、`normalized_block_count`、`text_block_count`、`raw_question_count`、`raw_questions_preview`、`fallback_created`、`failure_reason`。

图片导入会在入队前校验 `OCR_ENABLED` 与 PaddleOCR 可用性。失败分类当前包括：`ocr_empty_text`（OCR 未识别到文本）、`text_present_but_split_failed`（有文本但切题失败）、`missing_options`（选择题选项缺失）、`pipeline_failed`（管线失败）；切题 fallback 原因包括 `text_present_but_no_question_boundary`、`no_text_blocks`。

| 字段 | 说明 |
|------|------|
| status | 图片导入终态为 `completed` / `failed`；非终态包括 `queued` / `ocr_running` / `parsing` |

前端轮询应仅在 `completed` 或 `failed` 时停止。

### GET `/import/batches`

导入批次列表。

### GET `/import/batches/{batch_id}`

批次详情（该批次所有待审核题目）。

导入题目 item 会返回 Level 1 重复检测字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| question_hash | string? | 标准化题干/选项/答案生成的 32 位 MD5 hash |
| duplicate_status | string | `normal` / `possible_duplicate` |
| duplicate_of_question_id | int? | 命中的正式题目 ID |
| duplicate_of_import_id | int? | 命中的暂存导入题 ID |

### 导入审核（管理端，不在此处）

> 2026-08-10 同步：导入题目的人工审核（通过/拒绝/批量审核/发布）是**管理端接口**（`/api/admin/v1/imports/...`，权限 `import:write`），不在小程序端 `/api/v1` 暴露。历史文档化的 `PUT /import/questions/{id}` 与 `POST /import/batches/{batch_id}/approve` 已迁出，权威说明见 `docs/admin/ADMIN_API_SPEC.md` §3.8。
>
> 小程序端仅保留：`GET /import/template`、`POST /import/pipeline/upload`、`GET /import/pipelines/{pipeline_id}`、`GET /import/batches`、`GET /import/batches/{batch_id}`。

---

## 代码 RAG

### GET `/rag/search`

检索最相关的前端+后端模块。

| 参数 | 类型 | 说明 |
|------|------|------|
| query | string | 检索关键词 |
| top_k | int | 返回条数，默认 3 |

### GET `/rag/context`

构建结构化上下文（前后端分离）。

| 参数 | 类型 | 说明 |
|------|------|------|
| query | string | 检索关键词 |

---

## 番茄钟

### POST `/pomodoro/start`

开始番茄会话。已有进行中的会话时返回 409。

```json
// Request
{
  "subject_id": 2,
  "allocation_mode": "single",
  "chapter_id": null,
  "preset": "standard",        // standard / long / custom / debug / free
  "work_duration": 25,
  "break_duration": 5,
  "notification_enabled": false
}
```

`allocation_mode` 可省略，默认 `single`。选择 408 父级进行综合计时时传
`equal_408_core_v1`；服务端校验四个有效核心叶子，并在同一事务写入四条
`2500` 基点分配。会话响应、活动会话和历史中的 `subject_allocations` 保存科目
快照。科目分布按实际专注秒数逐统计日拆分后再按权重分配；全局会话次数仍只计
一个番茄。科目汇总的 `participation_sessions` 表示参与专注次数，综合番茄会在
四科各参与一次，因此不能相加推导全局番茄数。旧会话仍按原 `subject_id` 单科
100% 统计。

### POST `/pomodoro/{session_id}/complete`

完成会话。`actual_duration` 由服务端权威计算（请求体可为空）。

### POST `/pomodoro/{session_id}/interrupt`

中断会话（status → interrupted）。

### POST `/pomodoro/{session_id}/pause`

暂停会话（幂等；记录 pause interval）。

### POST `/pomodoro/{session_id}/resume`

恢复会话（幂等；重算暂停总时长与倒计时终点）。

### GET `/pomodoro/active`

当前进行中的会话（running / paused），无则返回 null。

### GET `/pomodoro/settings` · PUT `/pomodoro/settings`

获取/更新番茄钟设置。

```json
// PUT Request
{ "day_start_minute": 0 }
```

### GET `/pomodoro/stats`

今日/本周番茄统计卡片（timer 页）。仅统计已结束的 `completed` / `interrupted`
会话；仍处于 `running` / `paused` 的会话通过 `/pomodoro/active` 查询，不计入统计。

```json
{
  "today_sessions": 2,
  "today_duration_sec": 1800,
  "week_sessions": 10,
  "week_duration_sec": 9000,
  "today_date": "2026-08-09",
  "week_start_date": "2026-08-04",
  "day_start_minute": 0,
  "day_start_time": "00:00"
}
```

### GET `/pomodoro/daily-summary`

指定学习日的每日小结（含科目分组）。统计只包含已结束的 `completed` /
`interrupted` 会话，运行中的计时不会提前计入。

| 参数 | 类型 | 说明 |
|------|------|------|
| date | string? | YYYY-MM-DD，默认当前学习日 |

```json
{
  "date": "2026-08-09",
  "timezone": "Asia/Shanghai",
  "day_start_minute": 0,
  "day_start_time": "00:00",
  "sessions": 5,
  "duration_sec": 3600,
  "subjects": [
    {"subject_id": 2, "subject_code": "math2", "subject_name": "数学二", "sessions": 3, "participation_sessions": 3, "duration_sec": 2400}
  ]
}
```

### GET `/pomodoro/statistics-overview`

统计页首屏聚合：`stats` + `trends` + `daily_summary` 一次返回（单次窗口加载 + 单次归因）。统计时长混入刷题会话（PracticeSession.duration_sec，排除番茄已计时区间避免 double count）。统计只包含已结束的 `completed` / `interrupted` 会话；`running` / `paused` 会话结束后才进入聚合。

| 参数 | 类型 | 说明 |
|------|------|------|
| date | string? | YYYY-MM-DD，默认当前学习日 |

```json
{
  "stats": { "today_sessions": 2, "today_duration_sec": 1800, ... },
  "trends": [
    {"date": "2026-08-03", "sessions": 1, "duration_sec": 1500}
  ],
  "daily_summary": { "date": "2026-08-09", "sessions": 5, "duration_sec": 3600, "subjects": [...] }
}
```

### GET `/pomodoro/history`

统计页统一学习记录（分页），番茄会话与刷题会话混排：PomodoroSession + PracticeSession 按 start_time UNION DESC 全局翻页。每条记录带跨来源唯一 `record_key`（`pomodoro:<id>` / `practice:<id>`）。

| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 默认 1 |
| page_size | int | 默认 20，最大 100 |
| date | string? | YYYY-MM-DD 按学习日过滤 |

```json
{
  "items": [
    {
      "record_key": "pomodoro:12",
      "record_type": "pomodoro",      // pomodoro / practice
      "id": 12,
      "user_id": 1,
      "subject_id": 2,
      "subject_code": "math2",
      "subject_name": "数学二",
      "start_time": "2026-08-09T10:00:00",
      "end_time": "2026-08-09T10:25:00",
      "actual_duration": 1500,
      "status": "completed",
      "preset": "standard"
    },
    {
      "record_key": "practice:7",
      "record_type": "practice",
      "id": 7,
      "user_id": 1,
      "subject_id": 2,
      "subject_code": "math2",
      "subject_name": "数学二",
      "start_time": "2026-08-09T09:30:00",
      "end_time": "2026-08-09T09:45:00",
      "actual_duration": 900,
      "status": "completed",
      "preset": null
    }
  ],
  "total": 30,
  "page": 1,
  "page_size": 20
}
```

> 2026-08-10 更新原因：同步 practice/pomodoro 接口（subject_id 化、session 可选、stats by_subject 结构、history 混排、statistics-overview、knowledge-states/weak-knowledge-points/subjects 新接口）

---

## 408 考试

用户 JWT。前缀 `/api/v1/exams`。只服务已发布且 `is_active` 的选择题卷。试卷类型 `past_exam_choice` / `mock_choice`。作答状态 `in_progress` / `submitted` / `expired` / `abandoned`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/exams/papers` | 已发布试卷摘要：题量、总分、最近一次非 abandoned 尝试、最好成绩 |
| GET | `/exams/papers/{paper_id}` | 试卷详情，含科目分布 |
| POST | `/exams/papers/{paper_id}/attempts` | 开始或幂等恢复。body：`request_id`（去空白后 8–128 字符）。同一用户同一试卷同时只能有一份 `in_progress` |
| GET | `/exams/attempts/{attempt_id}` | 作答视图：题目（不含答案）、已保存答案、剩余时间 |
| PATCH | `/exams/attempts/{attempt_id}/answers/{item_id}` | 保存一题。`selected_answer` / `marked_for_review` / `used_time` 至少一项；用时上限 6 小时 |
| POST | `/exams/attempts/{attempt_id}/abandon` | 放弃进行中的尝试，返回 `{id, status:"abandoned"}` |
| POST | `/exams/attempts/{attempt_id}/submit` | 交卷。`answers` 可空；非空时在同一事务写入尚未单独保存的答案再判分 |
| GET | `/exams/attempts/{attempt_id}/result` | 成绩、科目分解、逐题对错与解析 |
| GET | `/exams/history/overview` | 汇总 + 分页历史。`limit` 1–50 默认 20，`offset` ≥ 0 |
| GET | `/exams/history` | 历史列表。`limit` 1–100 默认 50 |

规则：

- 找不到试卷或尝试：404。状态不允许（已交卷再改答案、重复放弃等）：409。参数不合法：422。
- 超过试卷 `duration_sec` 后，读/写入口会把进行中的尝试收成 `expired`。没有时长的试卷不会按这个规则过期。
- `abandoned` 不作为「最近尝试」，也不出现在历史列表。小程序本地草稿离开作答页 60 分钟失效；这是客户端缓存，不是服务端定时任务。待提交快照在本地保留 7 天。
- 作答题目绑定 `question_version_id`。V1 试卷题只接受 `single_choice`。
- 软删除的试卷不会出现在已发布列表（删除时改为非 active，且状态变为 `archived`）。

---

## 公式与速记卡

用户端前缀 `/api/v1/formulas`。公式数据仍按数据库中的真实 subject 分类存储；查询层额外支持逻辑学科 `math`。

### 数学逻辑学科契约

| 展示名 | 查询 `subject_code` | 实际查询范围 |
|--------|---------------------|--------------|
| 数学 | `math` | `elementary_math` + `math2_high_math` |

- `math` 只用于查询聚合，不会创建或迁移公式分类数据。
- `elementary_math`、`math2_high_math` 的原有精确查询行为保持不变。
- 聚合范围在同一 SQL 查询中参与其他过滤、全局排序、分页和 `total` 统计；不是分别分页后在应用层拼接。

| 方法 | 路径 | `subject_code=math` 行为 |
|------|------|--------------------------|
| GET | `/formulas` | 在初等数学与高等数学联合结果集中执行搜索、标签/分类、卡片类型、收藏、排序和分页 |
| GET | `/formulas/favorites/list` | 返回当前用户在联合范围内的收藏公式 |
| GET | `/formulas/random/next` | 从联合范围内随机选择下一条，保留 `exclude_ids` 等过滤 |
| GET | `/formulas/catalog` | 返回单一逻辑 subject 节点 `{code: "math", name: "数学"}`，其章节同时覆盖两个真实 subject |

`GET /formulas/catalog` 新增可选查询参数 `subject_code`。不传该参数时保持原有完整目录响应；传 `math` 时只返回聚合后的“数学”根节点。该逻辑根节点使用保留的合成 `id=0`，子章节继续返回真实数据库 category id。按公式 ID 获取详情不依赖 `subject_code`，无需改变。

> 2026-09-29 更新原因：新增公式逻辑学科 `math`，统一聚合初等数学与高等数学查询范围。

---

## 健康检查

### GET `/health`

```json
{
  "status": "ok",
  "env": "production"
}
```
