# API Specification

> 2240AI 全量 API 接口规范。Base URL: `/api/v1`

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
| subject | string? | 筛选科目 |
| question_type | string? | 筛选题型 |
| page | int | 默认 1 |
| page_size | int | 默认 20，最大 100 |

### POST `/questions`

创建题目。

```json
{
  "subject": "math2",
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
| subject | string? | 科目筛选 |
| question_type | string? | 题型筛选 |
| exclude_ids | string? | 排除的题目 ID，逗号分隔 |

### GET `/questions/{id}`

题目详情。

---

## 练习

### POST `/practice/check`

单题判题。

```json
// Request
{
  "question_id": 1,
  "answer": "A"
}

// Response
{
  "question_id": 1,
  "user_answer": "A",
  "correct_answer": "A",
  "is_correct": true,
  "analysis": "解析内容"
}
```

### POST `/practice/batch-questions`

批量预加载题目（不含答案，避免泄露）。

```json
// Request
{
  "subject": "math2",
  "count": 10,
  "exclude_ids": [1, 2, 3]
}

// Response
{
  "questions": [
    {
      "id": 1,
      "subject": "math2",
      "question_type": "choice",
      "content": {"text": "题干"},
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "difficulty": 3
    }
  ],
  "total": 10
}
```

### POST `/practice/submit`

提交练习答案。

```json
// Request
{
  "subject": "math2",
  "mode": "random",
  "duration_sec": 120,
  "answers": [
    {"question_id": 1, "answer": "A"},
    {"question_id": 2, "answer": "C"}
  ]
}

// Response
{
  "record_id": 1,
  "subject": "math2",
  "mode": "random",
  "correct_count": 1,
  "wrong_count": 1,
  "total": 2,
  "duration_sec": 120,
  "results": [
    {
      "question_id": 1,
      "user_answer": "A",
      "correct_answer": "A",
      "is_correct": true,
      "analysis": "解析"
    }
  ]
}
```

### GET `/practice/records`

练习记录列表（分页）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject | string? | 筛选科目 |
| page | int | 默认 1 |
| page_size | int | 默认 20 |

### GET `/practice/records/{id}`

练习详情（含逐题结果）。

---

## 错题本

### GET `/wrong-questions`

错题列表（分页）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject | string? | 筛选科目 |
| mastered | bool? | 筛选掌握状态 |
| error_type | string? | 筛选错误类型 |
| page | int | 默认 1 |
| page_size | int | 默认 20 |

### GET `/wrong-questions/stats`

错题统计。

```json
{
  "total": 50,
  "unmastered": 30,
  "by_subject": [
    {"subject": "math2", "count": 20, "unmastered": 12},
    {"subject": "exam408", "count": 18, "unmastered": 10},
    {"subject": "english", "count": 12, "unmastered": 8}
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

### GET `/review/due`

今日待复习列表（分页）。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject | string? | 筛选科目 |
| page | int | 默认 1 |
| page_size | int | 默认 20 |

### POST `/review/submit`

批量提交复习质量评分。

```json
// Request
{
  "items": [
    {"wrong_question_id": 1, "quality": 4},
    {"wrong_question_id": 2, "quality": 2}
  ]
}

// Response
{
  "results": [
    {
      "wrong_question_id": 1,
      "quality": 4,
      "efactor": 2.6,
      "interval": 6,
      "repetitions": 1,
      "next_review_date": "2026-05-28",
      "mastered": false
    }
  ],
  "processed": 2
}
```

### GET `/review/stats`

复习统计。

```json
{
  "total": 50,
  "due_count": 10,
  "reviewed_today": 3,
  "mastered_count": 20,
  "avg_efactor": 2.3,
  "by_subject": [
    {"subject": "math2", "total": 20, "due": 5, "mastered": 8}
  ]
}
```

---

## 答题行为

### POST `/behavior/record`

批量记录答题行为。

```json
{
  "subject": "math2",
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
    {"subject": "math2", "total": 40, "correct": 30, "accuracy": 0.75, "avg_time_sec": 50}
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
  "model": "deepseek-chat",
  "duration_ms": 2000
}
```

### POST `/ai/study-advice`

AI 学习建议。

```json
// Request
{
  "subject": "math2"
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
  "model": "deepseek-chat",
  "duration_ms": 3000
}
```

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
| subject | string? | 筛选科目 |

### GET `/knowledge-points/tree`

知识点树形结构。

| 参数 | 类型 | 说明 |
|------|------|------|
| subject | string? | 筛选科目 |

### POST `/knowledge-points`

创建知识点。

```json
{
  "name": "导数",
  "subject": "math2",
  "parent_id": null
}
```

### DELETE `/knowledge-points/{id}`

删除知识点。

---

## 题库导入

### GET `/import/template`

下载 Excel 导入模板（返回 .xlsx 文件）。

### POST `/import/upload`

上传文件（Excel / PDF）。

| 参数 | 类型 | 说明 |
|------|------|------|
| file | multipart | .xlsx / .xls / .pdf |

```json
// Response
{
  "batch_id": "BATCH_20260522_120000_abc123",
  "total": 15,
  "source_type": "excel",
  "source_file": "math_questions.xlsx"
}
```

### GET `/import/batches`

导入批次列表。

### GET `/import/batches/{batch_id}`

批次详情（该批次所有待审核题目）。

### PUT `/import/questions/{id}`

审核单题。

```json
{
  "status": "approved",
  "review_note": "可选备注",
  "subject": "math2",           // 可覆盖现有值
  "question_type": "choice",
  "parsed_content": {},
  "parsed_options": {},
  "parsed_answer": "A",
  "parsed_analysis": "解析"
}
```

### POST `/import/batches/{batch_id}/approve`

批量通过一个批次的所有待审核记录。缺少必填字段的题目自动跳过。

```json
// Response
{
  "approved_count": 12
}
```

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

## 健康检查

### GET `/health`

```json
{
  "status": "ok",
  "env": "production"
}
```
