# Stage 7: 人工审核系统

## 阶段目标

构建标准化的审核队列，将标准化后的题目写入 `question_imports` 暂存区，提供审核状态管理和人工修复接口，打通从暂存区到正式题库的审批流程。

## 当前阶段范围

### 能做

- 接收 stage5（和可选的 stage6）输出，写入 `question_imports` 表
- 实现审核状态管理：`pending` → `approved` / `rejected`
- 提供单题审核 API（通过/拒绝/修改）
- 提供批量审批 API
- 实现人工修复接口（修改 stem / options / answer / analysis）
- 提供低置信度题目优先显示（排序功能）
- 复用现有的 `import_service.py` 中批量审批逻辑

### 禁止做

- 不做纯 AI 自动入库（所有题目必须经过人工审核）
- 不改动 Question 模型结构
- 不改动 QuestionImport 模型结构（复用现有字段）
- 不修改现有导入 API 的签名
- 不让审核逻辑阻塞导入流程

## 输入输出结构

### 输入

```python
# 来自 stage5（+ 可选的 stage6）
{
    "questions": [
        {
            "stem": "TCP三次握手的作用是？",
            "options": [{"key": "A", "text": "..."}],
            "answer": "A",
            "analysis": "...",
            "question_type": "single_choice",
            "confidence_score": 0.85,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "source": {
                "file": "test.pdf",
                "page": 1,
                "type": "pdf"
            }
        }
    ],
    "batch_meta": {
        "source_type": "pdf",
        "source_file": "test.pdf",
        "subject": "exam408"
    }
}
```

### 输出

```python
# 写入 question_imports 表后的响应
{
    "batch_id": "batch_20260524_abc123",
    "total": 10,
    "written": 10,
    "skipped": 0,
    "items": [
        {
            "id": 101,
            "status": "pending",
            "confidence_score": 0.85,
            "stem_preview": "TCP三次握手的作用是？",
            "has_issues": False
        }
    ]
}
```

### 新增/修改 API

```python
# 现有接口（复用）
PUT /api/v1/import/questions/{id}          # 单题审批/拒绝
POST /api/v1/import/batches/{id}/approve   # 批量审批

# 新增接口
GET  /api/v1/import/review-queue           # 审核队列（按置信度排序）
    # query: page, pageSize, status, minConfidence
PUT  /api/v1/import/questions/{id}/fix     # 人工修复题目字段
```

### 核心函数

```python
def submit_to_review(
    questions: list[dict],
    batch_meta: dict
) -> dict:
    """将标准化题目提交到审核队列（question_imports）。"""

def get_review_queue(
    status: str | None,
    min_confidence: float | None,
    page: int,
    page_size: int
) -> dict:
    """获取审核队列（低置信度优先）。"""

def fix_question(question_id: int, fixes: dict) -> dict:
    """人工修复题目字段。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/review_service.py`（审核逻辑）
修改 `backend/app/api/v1/imports.py`（新增接口）
修改 `backend/app/services/import_service.py`（增强现有逻辑）

### 实现方案

1. **写入暂存区**：
   - 将 stage5 的 schema 字段映射到 `question_imports` 表的字段：
     - `stem` → `parsed_content = {"text": stem}`
     - `options` → `parsed_options`
     - `answer` → `parsed_answer`
     - `analysis` → `parsed_analysis`
     - `confidence_score` → `ai_confidence`（暂存）
     - `source` → `source_type` + `source_file`

2. **审核队列**：
   - `GET /api/v1/import/review-queue`：
     - 支持按 `status` 过滤（pending / approved / rejected）
     - 支持按 `minConfidence` 过滤
     - 默认按 `ai_confidence ASC` 排序（低分优先）

3. **人工修复**：
   - `PUT /api/v1/import/questions/{id}/fix`：
     - 允许修改：stem, options, answer, analysis
     - 记录修改历史（可选，通过 `updated_at` 跟踪）

4. **复用现有逻辑**：
   - 批量审批逻辑复用 `import_service.batch_approve()`
   - 暂存区模型复用 `question_imports` 表（不改字段）

### 前端审核页面

在 `miniprogram/pages/` 下新增审核页面（或增强 `import-batch` 页面）：

- 审核列表：显示待审核题目，低置信度靠前
- 单题详情：显示完整题目、解析、置信度标签
- 操作按钮：通过 / 拒绝 / 编辑
- 批量操作：全选 → 批量通过

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/review_service.py` | 审核队列管理 |
| `miniprogram/pages/review/` | 前端审核页面（可选） |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/api/v1/imports.py` | 新增 review-queue / fix 接口 |
| `backend/app/services/import_service.py` | 增强批量审批（支持 confidence 排序） |

### 不修改

- 不修改 `question_normalizer.py` / `ai_repair.py`
- 不修改 `Question` 模型
- 不修改 `QuestionImport` 模型（复用现有字段）

## 测试要求

### 单元测试

`backend/tests/test_services/test_review_service.py`

| 测试用例 | 描述 |
|---------|------|
| 提交审核 | 标准化题目写入 question_imports |
| 获取审核队列 | 按置信度排序返回 |
| 过滤状态 | 只返回 pending 状态的题目 |
| 单题通过 | approved 状态更新 + question_id 关联 |
| 单题拒绝 | rejected 状态更新 |
| 批量审批 | 多题同时通过 |
| 人工修复 | 修改 stem/options/answer |
| 空队列 | 无待审核题目 |
| 无效审批 | 缺少必填字段时跳过 |

## 完成标准

- [ ] 标准化题目正确写入 `question_imports`（字段映射正确）
- [ ] 审核队列 API 支持按置信度排序和状态过滤
- [ ] 人工修复接口可修改 stem / options / answer / analysis
- [ ] 批量审批复用现有逻辑，兼容已有功能
- [ ] 所有单测通过
- [ ] 前端审核页面可用（可选）

## docs 更新要求

- `/docs/backend/API_SPEC.md`：新增 review-queue / fix 接口说明
- `/docs/frontend/UI_RULES.md`：新增审核页面交互规则（如有前端页面）
- `/docs/backend/DB_SCHEMA.md`：更新（如有字段变更，但预期无变更）

## 下一阶段衔接

Stage 8（Pipeline 集成）将 stage1-7 的所有模块整合为统一的导入流水线，提供单一入口、任务状态管理和失败重试。
