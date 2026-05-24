# Stage 8: 导入流水线整合

## 阶段目标

将 stage1-7 的所有模块整合为统一的导入流水线，提供单一入口函数、任务状态管理、异步执行和失败重试机制。

## 当前阶段范围

### 能做

- 创建统一入口 `process_question_pipeline()` 串联所有阶段
- 实现任务状态跟踪（parsing → normalizing → analyzing → splitting → matching → repairing → review_required → completed → failed）
- 实现大文件异步处理（`BackgroundTasks`）
- 实现失败重试和错误隔离（单题失败不影响其他题）
- 对接现有 `import_service.py` 的上传流程
- 对接 stage7 的审核队列

### 禁止做

- 不引入消息队列/RabbitMQ/Redis Queue
- 不修改已有模块的内部逻辑（只编排，不重写）
- 不修改现有 API 路由的签名（向后兼容）
- 不引入新数据库
- 不新增第三方依赖

## 输入输出结构

### 输入

```python
# 统一入口
{
    "file_path": "/tmp/upload.pdf",
    "source_type": "pdf",          # "pdf" | "docx" | "txt"
    "source_file": "filename.pdf",
    "subject": "exam408",          # 可选，用户指定
    "options": {
        "enable_ai_repair": True,
        "confidence_threshold": 0.6,
        "ocr_fallback": False
    }
}
```

### 输出

```python
{
    "pipeline_id": "pl_20260524_abc123",
    "status": "review_required",
    "batch_id": "batch_20260524_abc123",
    "stats": {
        "total": 50,
        "extracted": 50,
        "normalized": 50,           # 文本标准化
        "analyzed": 50,
        "split": 48,                # 2 题未切分
        "matched": 45,              # 3 题未匹配到答案
        "schema_normalized": 45,
        "repaired": 5,              # AI 修复了 5 题
        "to_review": 45,            # 进入审核队列
        "failed": 0
    },
    "stages": {
        "extract": {"status": "completed", "duration_ms": 1200},
        "normalize": {"status": "completed", "duration_ms": 800},
        "analyze": {"status": "completed", "duration_ms": 300},
        "split": {"status": "completed", "duration_ms": 500, "warnings": ["2 questions unparsed"]},
        "match": {"status": "completed", "duration_ms": 200, "warnings": ["3 answers not found"]},
        "normalize_schema": {"status": "completed", "duration_ms": 400},
        "repair": {"status": "completed", "duration_ms": 3000},
        "review": {"status": "completed", "duration_ms": 100}
    },
    "errors": []                     # 严重错误
}
```

### 核心函数

```python
async def process_question_pipeline(
    file_path: str,
    source_type: str,
    source_file: str,
    subject: str | None = None,
    options: dict | None = None
) -> dict:
    """完整的导入流水线入口。"""

# 内部编排
def _run_extract(...) -> list[dict]:       # → stage1
def _run_analyze(...) -> dict:              # → stage2
def _run_split(...) -> list[dict]:          # → stage3
def _run_match(...) -> dict:                # → stage4
def _run_normalize(...) -> dict:            # → stage5
def _run_repair(...) -> dict:               # → stage6 (可选)
def _run_review(...) -> dict:               # → stage7
```

## 推荐实现方式

### 文件位置

**新增** `backend/app/features/question_pipeline.py` — 流水线编排核心

**修改** `backend/app/services/import_service.py` — 对接新流水线

### 实现方案

1. **Pipeline 编排**：

```python
class PipelineStage:
    """单个阶段的执行单元。"""
    def __init__(self, name: str, fn: callable):
        self.name = name
        self.fn = fn
        self.status = "pending"
        self.duration_ms = 0
        self.warnings = []
        self.error = None

    async def run(self, input_data):
        start = time.time()
        try:
            result = await self.fn(input_data)
            self.status = "completed"
            return result
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            raise

class ImportPipeline:
    """导入流水线，编排所有阶段。"""
    def __init__(self, options: dict):
        self.stages = []
        self._build_pipeline(options)

    def _build_pipeline(self, options):
        self.stages = [
            PipelineStage("extract", extract_text),
            PipelineStage("normalize", normalize_text),       # stage1: 文本标准化
            PipelineStage("analyze", analyze_structure),      # stage2: 结构分析
            PipelineStage("split", split_questions),          # stage3: 题目切分
            PipelineStage("match", match_answers),            # stage4: 答案匹配
            PipelineStage("normalize_schema", normalize_questions),  # stage5: 题目标准化
        ]
        if options.get("enable_ai_repair"):
            self.stages.append(PipelineStage("repair", repair_questions))
        self.stages.append(PipelineStage("review", submit_to_review))

    async def run(self, file_path, source_type, source_file):
        data = {"file_path": file_path, "source_type": source_type, "source_file": source_file}
        for stage in self.stages:
            data = await stage.run(data)
        return data
```

2. **异步执行**：

```python
# 在 API 路由中
from fastapi import BackgroundTasks

@router.post("/import/upload")
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: str = None
):
    # 1. 保存文件
    file_path = save_upload(file)
    # 2. 立即返回
    pipeline_id = generate_pipeline_id()
    # 3. 后台启动 pipeline
    background_tasks.add_task(
        run_pipeline_background,
        pipeline_id, file_path, source_type, subject
    )
    return {"pipeline_id": pipeline_id, "status": "parsing"}
```

3. **状态查询**：

```python
# 新增 API
GET /api/v1/import/pipelines/{pipeline_id}
→ 返回 pipeline 当前状态和各阶段详情
```

4. **错误隔离**：
   - 每个 stage 独立 try/except
   - 单题失败不阻塞整体流程
   - 严重错误（文件损坏、格式不兼容）终止 pipeline

### 关键设计

- **向后兼容**：现有 `POST /api/v1/import/upload` 仍可用，新 pipeline 作为可选升级
- **同步/异步双模**：小文件同步直接返回，大文件异步处理
- **状态持久化**：pipeline 状态存内存 dict（非生产环境）或 Redis（生产），不进 Postgres
- **不引入新依赖**：用 `BackgroundTasks` 实现异步，不引入 Celery/RQ

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/question_pipeline.py` | Pipeline 编排核心 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/api/v1/imports.py` | 新增异步上传接口 + 进度查询接口 |
| `backend/app/services/import_service.py` | 对接 pipeline（可选降级到旧逻辑） |

### 不修改

- 不修改已有的 stage1-7 各模块的内部逻辑
- 不修改 model 文件
- 不修改 `requirements.txt`

## 测试要求

### 单元测试

`backend/tests/test_services/test_question_pipeline.py`

| 测试用例 | 描述 |
|---------|------|
| 完整 pipeline | 从文件到审核队列的全流程 |
| AI 修复开启 | pipeline 包含 repair 阶段 |
| AI 修复关闭 | pipeline 不包含 repair 阶段 |
| 单 stage 失败 | 某阶段失败，pipeline 终止并返回错误 |
| 空文件 | 空文件导致 pipline 早期失败 |
| 异步执行 | background task 正确启动 |
| 状态查询 | pipeline 状态正确返回 |

## 完成标准

- [ ] `process_question_pipeline()` 串联 stage1-7
- [ ] 任务状态正确流转（parsing → analyzing → ... → completed/failed）
- [ ] AI 修复可通过配置开关
- [ ] 异步处理大文件不阻塞 HTTP 响应
- [ ] 单题失败不影响整体
- [ ] 所有单测通过

## docs 更新要求

- `/docs/ai/AI_PIPELINE.md`：更新完整的 pipeline 架构说明
- `/docs/backend/API_SPEC.md`：新增 pipeline 相关接口说明
- `/docs/project/PROJECT_RULES.md`：更新目录结构（新增 features/）

## 下一阶段衔接

Stage 9（OCR 增强）是可选的高级阶段，在 stage1 框架基础上对扫描版 PDF 进行图片文字识别，输出与 `normalized_blocks` 兼容的格式。
