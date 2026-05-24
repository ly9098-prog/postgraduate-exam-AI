# Stage 4: 答案解析关联器

## 阶段目标

解决题目与答案/解析分离的问题，将切分后的题目与对应的答案、解析进行自动关联，支持跨页、跨区域匹配。

## 当前阶段范围

### 能做

- 接收 stage3 输出的 `raw_questions` + stage1 的 `normalized_blocks` + stage2 的结构分析结果
- 支持 `INLINE` 模式：从题目文本中直接提取答案/解析
- 支持 `SEPARATED` 模式：从答案区域按题号匹配答案
- 支持多种答案标记格式
- 支持多种解析标记格式
- 允许部分题目缺失答案或解析（不崩溃）

### 禁止做

- 不做内容清洗（那是 stage5 的事）
- 不做题型判断
- 不调用 AI/LLM（规则实现）
- 不修改题目原始文本
- 不改数据库模型

## 输入输出结构

### 输入

```python
{
    "raw_questions": [                      # stage3 输出
        {
            "number": 1,
            "raw_question_text": "...",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "...", "B": "..."},
            "confidence": 0.9
        }
    ],
    "normalized_blocks": [...],              # stage1 输出
    "structure": {                           # stage2 输出
        "mode": "INLINE" | "SEPARATED",
        "answer_pages": [4, 5],
        "explanation_pages": [5, 6]
    }
}
```

### 输出

```python
[
    {
        "question_number": 1,
        "answer": "A",                   # 提取到的答案（原始格式）
        "explanation": "解析内容...",     # 提取到的解析（可能为空）
        "answer_source": "inline",       # "inline" | "separated" | "missing"
        "explanation_source": "inline",  # "inline" | "separated" | "missing"
        "confidence": 0.95,              # 匹配置信度
        "raw_answer_text": "答案：A",     # 答案原始文本
        "raw_explanation_text": "解析："  # 解析原始文本
    }
]

# 未匹配的题目单独列出
"unmatched": [
    {
        "question_number": 5,
        "reason": "answer_not_found"
    }
]
```

### 核心函数

```python
def match_answers(
    raw_questions: list[dict],
    normalized_blocks: list[dict],
    structure: dict
) -> dict:
    """关联题目与答案、解析，返回匹配结果。"""

def _extract_inline_answer(text: str) -> dict | None:
    """从题目文本中提取内联答案。"""

def _extract_separated_answer(
    normalized_blocks: list[dict],
    answer_pages: list[int],
    question_number: int
) -> dict | None:
    """从答案区域提取分离式答案。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/answer_matcher.py`

### 实现方案

1. **答案格式识别**（模块顶层常量）：

```python
ANSWER_PATTERNS = [
    # 格式: 【答案】A / 答案：A / 正确答案：A
    (r"(?:【答案】|答案[：:]|参考答案[：:]|正确答案[：:])\s*([A-Da-d]+)", "inline"),
    # 格式: 1.A / 1、A（在答案区域）
    (r"(\d+)\s*[.、）)]\s*([A-Da-d])", "separated"),
    # 格式: KEY: A / Answer: A
    (r"(?:KEY|Answer|answer)[：:]\s*([A-Da-d]+)", "inline"),
    # 格式: 1. 答案: A（带题号前缀）
    (r"(\d+)[.、）)]\s*(?:答案[：:]|【答案】)\s*([A-Da-d]+)", "separated"),
]

ANSWER_CLEAN_PATTERNS = [
    r"^答案[：:]?\s*",
    r"^【答案】\s*",
    r"^参考答案[：:]?\s*",
    r"^正确答案[：:]?\s*",
]
```

2. **解析格式识别**：

```python
EXPLANATION_PATTERNS = [
    r"(?:【解析】|解析[：:]|解答[：:]|讲解[：:]|分析[：:]\s*)(.+)",
    r"(?:Explanation[：:]|explanation[：:])(.+)",
]

EXPLANATION_CLEAN_PATTERNS = [
    r"^解析[：:]?\s*",
    r"^【解析】\s*",
    r"^解答[：:]?\s*",
]
```

3. **匹配算法**：
   - **INLINE 模式**：对每题 `raw_question_text` 扫描答案格式和解析格式
   - **SEPARATED 模式**：
     - 从 `answer_pages` 中提取答案区域文本
     - 按题号匹配（`1.A`、`1、A`、`1 答案：A` 等）
     - 无法按题号匹配时，按题目顺序顺序关联
   - **置信度**：精确格式匹配 0.95，模糊匹配 0.7，缺失 0.0
   - **未匹配处理**：收集到 `unmatched` 列表，记录原因

### 关键设计

- 只做格式匹配和提取，不做内容理解
- 分离模式下的顺序关联需要 stage2 的结构分析支持
- 答案和解析独立匹配，一方缺失不影响另一方

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/answer_matcher.py` | 答案匹配核心模块 |

### 不修改

- 不修改 `text_extractor.py` / `structure_analyzer.py` / `question_splitter.py`
- 不修改任何 model / service / API 路由
- 不修改 `requirements.txt`

## 测试要求

### 单元测试

`backend/tests/test_services/test_answer_matcher.py`

| 测试用例 | 描述 |
|---------|------|
| INLINE 答案提取 | 答案在题目文本中的情况 |
| SEPARATED 答案提取 | 答案在独立区域的情况 |
| 多格式答案 | 【答案】/ 答案：/ 参考答案：/ KEY: |
| 多格式解析 | 【解析】/ 解析：/ 解答： |
| 跨页答案关联 | 题目在前，答案在 3 页后 |
| 缺失答案 | 某题无答案，标记为 missing |
| 缺失解析 | 某题无解析，标记为 missing |
| 题号顺序关联 | 答案区只有 "1.A 2.C 3.B" |
| OCR 错字答案 | "8" 代替 "B"、"0" 代替 "D" |
| 空输入 | 空题目列表，返回空结果 |

### 测试数据

`backend/tests/fixtures/` 下准备：
- `matcher_inline.txt` — 内联答案文本
- `matcher_separated.txt` — 分离答案文本
- `matcher_missing.txt` — 部分缺失的文本

## 完成标准

- [ ] INLINE 模式能正确提取答案和解析
- [ ] SEPARATED 模式能跨页关联答案
- [ ] 支持 5+ 种答案格式
- [ ] 答案缺失/解析缺失时不崩溃
- [ ] 所有单测通过

## docs 更新要求

- `/docs/ai/AI_PIPELINE.md`：新增 answer_matcher 模块说明
- `/docs/backend/API_SPEC.md`：新增答案解析关联模块说明（如有接口变更时同步更新）

## 下一阶段衔接

Stage 5 以本阶段的输出（匹配后的题目）作为输入，进行内容清洗、题型识别和标准化，最终生成统一 Question Schema。
