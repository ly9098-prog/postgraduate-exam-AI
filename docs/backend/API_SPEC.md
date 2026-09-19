# API Specification

> 2240AI 全量 API 接口规范。Base URL: `/api/v1`
>
> 2026-08-10 更新原因：题目/科目关系已从 `subject`（string code，如 "math2"）迁移为 `subject_id`（int，FK `subjects.id`），响应中展开 `subject_code` / `subject_name`；本规范相关参数表与 JSON 示例已同步更新。

---

## 认证方式

所有接口（除 `/auth/login` 外）需要 Header：

```
Authorization: Bearer <jwt_token>
```

---

## 通用响应格式

```json
// FastAPI 默认响应（直接在路由中返回 dict/Pydantic model）
// 前端 api.js 中通过 handleResponse 统一包装
{
  "code": 0,
  "message": "success",
  "data": {}
}

// 分页响应
{
  "code": 0,
  "data": {
    "items": [],
    "total": 100,
    "page": 1,
    "pageSize": 20,
    "totalPages": 5
  }
}
```

---

## 错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 40001 | 参数错误 |
| 40101 | 未登录 / token 过期 |
| 40401 | 资源不存在 |
| 50001 | 服务器内部错误 |
| 50002 | AI 服务不可用 |

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
| use_leitner | bool | true | 是否启用 Leitner 过滤 |
| source_question_id | int? | - | similar 模式的相似源题 ID |
| smart_strategy | string | weakness_vector | smart 模式策略 |

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
| page | int | 默认 1 |
| page_size | int | 默认 20（1-100） |

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

### PUT `/wrong-questions/{id}/quality`

质量评分（触发 SM-2 更新）。

```json
{
  "quality": 4
}
```

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

### POST `/review/schedule-submit`

提交单条复习评分（SM-2 更新）。

```json
// Request
{
  "schedule_id": 1,
  "question_id": 100,
  "rating": 4
}

// Response
{
  "schedule_id": 1,
  "question_id": 100,
  "rating": 4,
  "interval_after": 6,
  "ease_factor_after": 2.6,
  "next_review_at": "2026-08-16T10:00:00+08:00",
  "is_correct": true
}
```

### POST `/review/batch-submit`

批量提交复习评分。

```json
// Request
{
  "reviews": [
    {"schedule_id": 1, "question_id": 100, "rating": 4},
    {"schedule_id": 2, "question_id": 101, "rating": 2}
  ]
}

// Response
{
  "results": [
    {"schedule_id": 1, "question_id": 100, "next_review_at": "2026-08-16T10:00:00+08:00", "is_correct": true},
    {"schedule_id": 2, "question_id": 101, "next_review_at": "2026-08-11T10:00:00+08:00", "is_correct": false}
  ],
  "total": 2
}
```

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

### POST `/review/grade-submit` / `POST /review/grade-batch`

提交对错判定（`grade-submit` 单题，`grade-batch` 批量），返回是否正确/标准答案/更新后的 SM-2 参数。

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
  "duration_ms": 2000
}
```

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
  "chapter_id": null,
  "preset": "standard",        // standard / long / custom / debug / free
  "work_duration": 25,
  "break_duration": 5,
  "notification_enabled": false
}
```

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
    {"subject_id": 2, "subject_code": "math2", "subject_name": "数学二", "sessions": 3, "duration_sec": 2400}
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

## 健康检查

### GET `/health`

```json
{
  "status": "ok",
  "env": "production"
}
```
