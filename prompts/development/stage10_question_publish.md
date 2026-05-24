# Stage 10: 正式题库发布系统

## 1. 阶段目标

建立 `question_imports`（审核区）→ `questions`（正式题库）的完整发布流程，实现"审核通过 → 发布到正式题库"的状态管理，确保题目从暂存区到正式库的原子性、可追溯性和去重能力。

## 2. MVP 范围

### 能做

- QuestionImport 状态扩展：`pending → approved → published`
- 批量发布已 approved 的题目到 questions 表
- 基于 `stem_hash` 的去重检测（发布时过滤）
- 发布统计（总数/成功/重复/失败）
- 发布记录追溯（import_batch_id 关联）
- 现有 approved 数据的向后兼容（自动补齐 published 状态）

### 禁止做

- 不做多版本管理（versioning）
- 不做 embedding 相似度去重
- 不做 merge/upsert（仅跳过重复）
- 不做大规模事务（分批发布，每批最多 100 条）
- 不修改已存在的 Question 模型字段
- 不修改 QuestionImport 模型字段（仅扩展 status 枚举）
- 不涉及前端改动（当前阶段仅后端）

## 3. 非目标

- 不实现自动发布（全部需人工触发）
- 不做发布回滚（发布即不可逆）
- 不实现脏数据自动清理
- 不涉及错误题目自动重试（仅跳过）

## 4. 目录结构修改

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/question_publish_service.py` | 发布服务核心逻辑 |
| `backend/app/schemas/question_publish.py` | 发布相关 Pydantic 模型 |
| `backend/tests/test_services/test_question_publish_service.py` | 发布服务单元测试 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/api/v1/imports.py` | 新增 3 个发布相关端点 |
| `backend/app/features/question_pipeline.py` | `approve_question` 设置 `status=approved` 后不再创建 Question 记录（延迟到 publish 阶段） |
| `backend/app/features/review_service.py` | 确保 submit_to_review 创建的记录初始为 `pending`（已有，无需改动） |

### 不修改文件

- `app/models/question.py` — 字段已完备
- `app/models/question_import.py` — status 用 string，天然支持 published
- `app/schemas/question_import.py` — 无需修改
- `app/schemas/import_review.py` — 无需修改

## 5. 数据库变更

### 表结构不变

Question 和 QuestionImport 表结构均不改变。仅扩展 QuestionImport.status 的枚举值。

### QuestionImport.status 枚举扩展

```
现有: pending | approved | rejected
新增: published
```

### 状态机

```
pending
  ├──→ approved ──→ published  (正常路径)
  └──→ rejected               (拒绝路径)

禁止:
  pending → published          (必须经过 approved)
  rejected → approved/published
  approved → rejected/pending
  published → 任何其他状态
```

### 数据迁移

首次部署时，需要将现有 `status=approved` 且 `question_id IS NOT NULL` 的记录自动补齐 `published` 状态：

```sql
UPDATE question_imports
SET status = 'published'
WHERE status = 'approved' AND question_id IS NOT NULL;
```

迁移脚本路径：`backend/alembic/versions/XXXX_add_published_status.py`（若已使用 alembic），或在首次发布 API 调用时自动处理。

## 6. API 设计

### 6.1 发布审核通过的题目

```
POST /api/v1/import/review/publish
```

**Request Body:**
```json
{
    "question_ids": [1, 2, 3],
    "batch_id": "REVIEW_20250524_123456_abc123"
}
```

`question_ids` 和 `batch_id` 二选一，同时提供时以 `question_ids` 为准。

**Response:**
```json
{
    "total": 10,
    "published": 8,
    "duplicates": 1,
    "failed": 1,
    "details": [
        {"id": 1, "status": "published", "question_id": 101},
        {"id": 2, "status": "duplicate", "question_id": 99, "reason": "stem_hash collision"},
        {"id": 3, "status": "failed", "reason": "题目数据不完整"}
    ]
}
```

### 6.2 查询发布历史

```
GET /api/v1/import/review/publish-history
```

**Query Parameters:**
- `page` (int, default 1)
- `page_size` (int, default 20)
- `status` (str, optional: published/duplicate/failed)

**Response:**
```json
{
    "items": [
        {
            "batch_id": "REVIEW_20250524_abc",
            "published_at": "2025-05-24T10:00:00",
            "total": 10,
            "published": 8,
            "duplicates": 1,
            "failed": 1
        }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
}
```

### 6.3 批量审核并发布（快捷操作）

```
POST /api/v1/import/review/approve-and-publish
```

一次性完成 approve + publish 两步，适用于高置信度题目。

**Request Body:**
```json
{
    "question_ids": [1, 2, 3]
}
```

**Response:**
```json
{
    "total": 3,
    "approved": 3,
    "published": 2,
    "duplicates": 1,
    "failed": 0,
    "details": [...]
}
```

### 6.4 现有端点修改

`POST /api/v1/import/batches/{batch_id}/approve` — 行为不变，但 approve 后不再直接创建 Question 记录。Question 的创建延迟到 publish 阶段。

## 7. Service 设计

### 新增：`question_publish_service.py`

```python
# 核心函数

async def publish_questions(
    db: AsyncSession,
    question_ids: list[int] | None = None,
    batch_id: str | None = None,
) -> dict:
    """
    发布题目到正式题库。

    - 只处理 status=approved 的记录
    - 逐条去重（stem_hash）
    - 同一事务内写入 questions + 更新 question_imports
    - 返回发布统计
    """

async def publish_single_question(
    db: AsyncSession,
    qi: QuestionImport,
) -> dict:
    """
    发布单条记录到 questions 表。

    1. 校验 qi.status == 'approved'
    2. 通过 process_question_pipeline 标准化数据
    3. 检查 stem_hash 去重
    4. 创建 Question 记录
    5. 更新 qi.status = 'published', qi.question_id = q.id
    6. 返回发布结果
    """

async def detect_duplicate_question(
    db: AsyncSession,
    stem_hash: str,
    subject: str,
) -> Question | None:
    """
    基于 stem_hash 检测重复。
    复用现有 find_duplicate_question 逻辑（在 question_pipeline.py 中）。
    """

async def get_publish_history(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> dict:
    """
    查询发布历史（从 question_imports 中按 batch_id 聚合）。
    """

async def approve_and_publish(
    db: AsyncSession,
    question_ids: list[int],
) -> dict:
    """
    快捷操作：approve + publish 一步完成。
    适用于高置信度题目的快速入库。
    """
```

### 修改：`question_pipeline.py` — `approve_question`

**当前行为：**
- approve 时直接创建 Question 记录
- 设置 qi.status = 'approved'

**目标行为：**
- approve 时仅校验、设置 qi.status = 'approved'
- 不创建 Question 记录
- Question 记录在 publish 阶段创建

详细变更：

```
approve_question 修改：
  - 保留：状态校验（pending）、数据提取、标准化校验
  - 移除：Question 创建、duplicate 检测
  - 保留：qi.status = 'approved', qi.review_note
  - 新增：qi.question_id = None（显式置空）

原因：Question 创建 → publish 阶段负责，保持单一职责。
```

### 去重策略

基于 `stem_hash`（SHA256 前 8 位）去重，与 Stage 5 `QuestionNormalizer` 一致。

```python
# 在 questions 表中查找 stem_hash 匹配的记录
stmt = select(Question).where(
    Question.stem_hash == stem_hash,
    Question.subject == subject,
    Question.is_active == True,
)
```

**MVP 策略（不做）：**
- 不做模糊匹配
- 不做 embedding 相似度
- 不做字段级 merge
- 不做版本化

**重复处理：**
- 不创建新 Question 记录
- 不阻止 import 记录的状态流转
- 记录 duplicate 统计信息
- 返回已有 question_id 供追踪

## 8. Schema 设计

### 新增：`schemas/question_publish.py`

```python
class PublishRequest(BaseModel):
    """发布请求。question_ids 和 batch_id 二选一。"""
    question_ids: list[int] | None = None
    batch_id: str | None = None


class PublishDetailItem(BaseModel):
    """单条发布结果。"""
    id: int
    status: str  # published / duplicate / failed
    question_id: int | None = None
    reason: str | None = None


class PublishResponse(BaseModel):
    """发布响应。"""
    total: int
    published: int
    duplicates: int
    failed: int
    details: list[PublishDetailItem]


class PublishHistoryItem(BaseModel):
    """发布历史条目。"""
    batch_id: str
    published_at: datetime
    total: int
    published: int
    duplicates: int
    failed: int


class PublishHistoryResponse(BaseModel):
    """发布历史响应。"""
    items: list[PublishHistoryItem]
    total: int
    page: int
    page_size: int


class ApproveAndPublishRequest(BaseModel):
    """快捷审批+发布请求。"""
    question_ids: list[int]


class ApproveAndPublishResponse(BaseModel):
    """快捷审批+发布响应。"""
    total: int
    approved: int
    published: int
    duplicates: int
    failed: int
    details: list[PublishDetailItem]
```

## 9. 测试计划

### 新增测试文件

`backend/tests/test_services/test_question_publish_service.py`

### 测试用例

| 类别 | 测试用例 | 描述 |
|------|---------|------|
| **发布成功** | `test_publish_single_question` | 单条 approved 记录成功发布 |
| | `test_publish_by_ids` | 按 ID 列表批量发布 |
| | `test_publish_by_batch` | 按 batch_id 发布 |
| | `test_publish_all_approved` | 发布所有 approved 记录 |
| | `test_publish_preserves_fields` | 发布后 question 字段完整 |
| **重复检测** | `test_duplicate_skip` | stem_hash 匹配时跳过 |
| | `test_duplicate_stats` | 重复计数正确 |
| | `test_partial_duplicates` | 混合场景（部分重复） |
| **状态校验** | `test_publish_non_approved_skipped` | pending/rejected 记录跳过 |
| | `test_publish_already_published_skipped` | 已发布记录跳过 |
| | `test_publish_invalid_data` | 数据不完整时标记 failed |
| **事务** | `test_transaction_rollback` | 发布失败时事务回滚 |
| | `test_partial_failure_no_commit` | 部分失败时全部回滚 |
| **快捷操作** | `test_approve_and_publish` | 一步完成 approve + publish |
| | `test_approve_and_publish_duplicate` | 快捷操作中处理重复 |
| **边界** | `test_empty_id_list` | 空 ID 列表 |
| | `test_nonexistent_ids` | ID 不存在 |
| | `test_publish_empty_batch` | batch 中无 approved 记录 |
| **发布历史** | `test_publish_history` | 查询发布历史 |
| | `test_publish_history_pagination` | 分页查询 |
| | `test_publish_history_empty` | 无发布记录 |

### 测试策略

- **Style B**（pytest + mock AsyncSession）：纯逻辑测试
- **Style A**（真实 SQLite + SQLAlchemy）：事务完整性测试（1-2 个关键用例）
- Mock `process_question_pipeline` 避免依赖 Stage 5 标准化逻辑
- 测试用 `stem_hash` 可提前计算好固定值

## 10. UI 影响范围

本阶段不涉及前端改动。

后端 API 变更对前端透明，当前小程序的后台审核流程不变。后续 Stage 11（刷题系统）开始涉及前端。

## 11. 风险与兼容性

### 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| `approve_question` 行为变更 | 现有 approve 流程不再创建 Question | 确保现有前端不依赖 approve 后立即获取 question_id |
| 已 approve 数据未发布 | 存量 approved 记录无对应 question | 提供迁移工具/首次发布补齐 |
| 重复检测边界 | stem_hash 碰撞导致漏判 | 目前 SHA256 前 8 位碰撞概率极低，可接受 |
| 大事务性能 | 批量发布 100+ 条时锁表 | 限制单批最多 100 条，分批提交 |

### 向后兼容

| 场景 | 兼容策略 |
|------|---------|
| 存量 `status=approved` 且 `question_id IS NOT NULL` 的记录 | 视为已发布，自动补齐 published 状态 + 跳过 |
| 存量 `status=approved` 但 `question_id IS NULL` 的记录 | 正常进入发布流程，视为待发布 |
| 现有 `POST /api/v1/import/batches/{batch_id}/approve` | 行为微调（不再创建 Question），返回值不变 |
| 现有 `GET /api/v1/import/batches/{batch_id}` | 不变，字段兼容 |

## 12. 开发顺序

### Step 1: 分析现有代码

- 确认 `process_question_pipeline` 在 question_pipeline.py 中的完整逻辑
- 确认 `find_duplicate_question` 的查询逻辑和 return 类型
- 确认 `approve_question` 的完整数据流
- 识别所有调用 `approve_question` 的位置（API、测试等）

### Step 2: 修改 `question_pipeline.py` — `approve_question`

- 移除 Question 创建逻辑
- 改为仅设置 status='approved'
- 保留数据校验和标准化
- 更新 `batch_approve` 同步修改

### Step 3: 创建 `question_publish_service.py`

- 实现 `publish_single_question()` — 核心逻辑
- 实现 `detect_duplicate_question()` — 去重检测
- 实现 `publish_questions()` — 批量发布
- 实现 `get_publish_history()` — 历史查询
- 实现 `approve_and_publish()` — 快捷操作

### Step 4: 创建 `schemas/question_publish.py`

- 定义所有 Pydantic 模型

### Step 5: 修改 `imports.py` — 新增 API 端点

- `POST /api/v1/import/review/publish`
- `GET /api/v1/import/review/publish-history`
- `POST /api/v1/import/review/approve-and-publish`

### Step 6: 数据迁移

- 编写迁移脚本文档
- 处理存量 approved+question_id 记录

### Step 7: 测试

- 编写 `test_question_publish_service.py`
- 修改现有测试（`approve_question` 行为变更影响）
- 全量回归测试

### Step 8: 文档更新

- 更新 `/docs/database/` 相关文档
- 更新 `/docs/api/` 相关文档
- 更新 `/prompts/tasks/current-task.md`
- 更新 changelog

## 13. 验收标准

- [ ] `approve_question` 不再创建 Question 记录，仅设置 status=approved
- [ ] 存量 approved + question_id 记录可正常识别为已发布
- [ ] `POST /api/v1/import/review/publish` 能将 approved 题目发布到 questions 表
- [ ] stem_hash 重复检测正常工作，重复题跳过不创建
- [ ] 发布统计准确（total/published/duplicates/failed）
- [ ] 非 approved 状态的记录发布时被跳过
- [ ] 事务回滚：部分失败时全部回滚
- [ ] 发布历史查询支持分页
- [ ] `approve_and_publish` 快捷操作一次完成两步
- [ ] 新测试全部通过
- [ ] 全量测试零回归
- [ ] 所有 API 返回格式与现有前端兼容
- [ ] 相关文档已更新

---

## 下一阶段衔接

Stage 10 完成后，题目从导入 → 审核 → 发布的全流程闭环完成。下个阶段（Stage 11）开始构建"刷题系统"，面向终端用户提供做题体验。
