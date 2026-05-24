# Stage 5: 题目标准化器（核心）

## 阶段目标

将原始题目文本清洗、解析、标准化为统一的 Question Schema，包含题干/选项/答案/题型等全部结构化字段。

## 当前阶段范围

### 能做

- 接收 stage4 输出的匹配后题目作为输入
- 题干清洗（去噪、去题号前缀、去 OCR 乱码）
- 选项结构化（A. / A: → `[{"key": "A", "text": "..."}]`）
- 答案标准化（各种格式统一为标准值）
- 题型自动识别（单选题/多选题/判断题/填空题/主观题）
- 输出统一 Question Schema
- 计算 `confidence_score` 用于后续审核优先级
- 题型和学科别名自动映射为标准值

### 禁止做

- 不做 AI 修复（那交给 stage6）
- 不做数据库写入（那是 stage7 的事）
- 不修改 `question_imports` 或 `questions` 表
- 不改变 stage3/4 的输出格式

## 输入输出结构

### 输入

```python
# 来自 stage4
[
    {
        "question_number": 1,
        "answer": "A",
        "explanation": "解析内容...",
        "answer_source": "inline",
        "confidence": 0.95,
        "raw_answer_text": "答案：A",
        "raw_explanation_text": "解析：..."
    }
]
```

同时还依赖 `raw_questions`（来自 stage3）中的 `raw_question_text` 和 `option_lines`。

### 输出

```python
{
    "questions": [
        {
            "schema_version": "v1",
            "subject": "exam408",               # 学科（暂无则留空）
            "question_type": "single_choice",    # 题型标准值
            "stem": "TCP三次握手的作用是？",       # 清洗后的题干
            "options": [                         # 结构化选项
                {"key": "A", "text": "建立连接"},
                {"key": "B", "text": "断开连接"}
            ],
            "answer": "A",                       # 标准化的答案
            "analysis": "解析内容...",             # 清洗后的解析
            "raw_text": "原始OCR/导入文本...",      # 原始文本（仅传递，不修改）
            "knowledge_points": [],               # 知识点（可选）
            "difficulty": 3,                      # 难度（默认 3）
            "source": {                           # 来源
                "file": "filename.pdf",
                "page": 1,
                "type": "pdf"
            },
            "is_valid": True,                    # 字段完整性校验
            "errors": [],
            "warnings": [],
            "stem_hash": "a1b2c3",               # 去重用短 hash
            "confidence_score": 0.92             # 结构化置信度
        }
    ],
    "errors": [],                                 # 无法标准化的题目
    "warnings": []                                # 可修复但需关注的问题
}
```

### 核心函数

```python
def normalize_question(
    raw_question: dict,
    matched: dict,
    source_info: dict
) -> dict:
    """标准化单道题目，返回标准 Question Schema。"""

def _clean_stem(text: str) -> str:
    """清洗题干：去除题号、OCR噪声、多余空白。"""

def _normalize_options(raw_options: dict | str) -> list[dict]:
    """标准化选项为 [{"key": "A", "text": "..."}] 格式。"""

def _normalize_answer(answer: str, question_type: str) -> str:
    """标准化答案格式。"""

def _detect_question_type(
    stem: str,
    options: list | None,
    answer: str
) -> str:
    """自动识别题型。"""

def _compute_confidence(question: dict) -> float:
    """计算结构化置信度。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/question_normalizer.py`

### 实现方案

1. **题型检测算法**（规则优先）：

```python
def _detect_question_type(stem, options, answer):
    if answer in ("T", "F", "true", "false", "正确", "错误"):
        return "true_false"
    if options and len(options) >= 2:
        if "," in answer or len(answer) > 1:
            return "multiple_choice"
        return "single_choice"
    if "填空" in stem or "___" in stem:
        return "fill_blank"
    return "subjective"
```

2. **题干清洗规则**：

```python
CLEAN_RULES = [
    (r"^\s*\d+[.、)）]\s*", ""),            # 前导题号
    (r"（\s*）", "()"),                      # 括号清理
    (r"　", " "),                       # 全角空格→半角
    (r"[　\t]+", " "),                       # 各种空白→单空格
    (r"\n{3,}", "\n\n"),                     # 多余换行
    (r"^\s*\((?:单选题|多选题|判断题|填空题)\)", ""),  # 题型标签
]
```

3. **答案标准化**：

```python
ANSWER_NORMALIZE = {
    "单选": "single_choice",
    "多选": "multiple_choice",
    "判断": "true_false",
    "填空": "fill_blank"
}
```

4. **选项标准化**：处理 dict/list/string 三种输入格式，统一输出 `[{"key": ..., "text": ...}]`

5. **置信度计算**：基于字段完整度 + 选项格式匹配度 + 答案有效性

### 关键设计

- 规则解析优先，不依赖 LLM
- `confidence_score` 反映结构化质量，低分题目在 stage7 审核中优先显示
- 不修改原始文本，清洗结果只影响输出 schema
- `stem_hash` 为去重预留（SHA256 短 hash，去空白后计算）

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/question_normalizer.py` | 题目标准化核心模块 |

### 不修改

- 不修改 `text_extractor.py` / `structure_analyzer.py` / `question_splitter.py` / `answer_matcher.py`
- 不修改任何 model / service / API 路由
- 不修改 `requirements.txt`

## 测试要求

### 单元测试

`backend/tests/test_services/test_question_normalizer.py`

| 测试用例 | 描述 |
|---------|------|
| 单选题标准化 | 典型单选题，含 4 个选项 |
| 多选题标准化 | 答案含 "," 的多选题 |
| 判断题标准化 | 答案含 T/F 或 正确/错误的题目 |
| 填空题标准化 | 题干含 "___" 的题目 |
| 题干清洗 | 含题号/空格/OCR 噪声的题干 |
| 选项多格式 | dict/list/字符串三种输入 |
| 答案多格式 | "答案：A" / "A" / "正确答案是 A" |
| 不完整题目 | 缺失选项/缺失答案，标记 is_valid=False |
| 题型别名映射 | "单选"→"single_choice" 等 |
| 空输入 | 空文本，返回 errors |

## 完成标准

- [ ] 支持 5 种题型自动识别（单选/多选/判断/填空/主观）
- [ ] 题干清洗规则覆盖题号、空格、OCR 噪声
- [ ] 选项结构化支持 dict/list/string 三种输入
- [ ] 答案标准化支持多种格式
- [ ] `confidence_score` 准确反映结构化质量
- [ ] 所有单测通过

## docs 更新要求

- `/docs/ai/AI_PIPELINE.md`：新增 question_normalizer 模块说明
- `/docs/backend/API_SPEC.md`：更新导入流程说明（新增标准化模块）
- `/docs/ai/STANDARDIZATION_FLOW.md`：更新标准化规则（如有变更）
- `/docs/backend/DB_SCHEMA.md`：无变更（不改数据库）

## 下一阶段衔接

Stage 6（可选）以本阶段输出中 `confidence_score` 较低/`is_valid=False` 的题目作为输入，进行 AI 辅助修复。Stage 7 以本阶段所有输出作为输入进入审核队列。
