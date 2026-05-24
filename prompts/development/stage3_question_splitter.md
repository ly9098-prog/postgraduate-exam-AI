# Stage 3: 题目切分器

## 阶段目标

从混乱文档文本中精准切分出单道题目，识别题号、选项标记（A./B./C./D.），输出结构化的原始题目片段。

## 当前阶段范围

### 能做

- 接收 stage2 输出的结构分析结果 + stage1 的 `normalized_blocks` 作为输入
- 按题号切分（支持多格式题号）
- 识别选项行（A. / B. / C. / D. 及其变体）
- 处理跨页题目（同一题在不同 page/block 间切分）
- OCR 容错（模糊匹配题号和选项标记）
- 输出 `raw_questions` 列表

### 禁止做

- 不做答案匹配（那是 stage4 的事）
- 不做题型判断
- 不做内容清洗或标准化
- 不调用 AI/LLM
- 不修改文本内容

## 输入输出结构

### 输入

```python
# 来自 stage2 + stage1
{
    "structure": {
        "mode": "INLINE",
        "question_pages": [1, 2, 3],
        "confidence": 0.85
    },
    "normalized_blocks": [
        {"page": 1, "raw_text": "...", "normalized_text": "...", "block_index": 0},
        ...
    ]
}
```

### 输出

```python
[
    {
        "number": 1,                    # 题号（int）
        "raw_question_text": "...",      # 原始文本（含题号、选项、答案等）
        "page_start": 1,                 # 起始页码
        "page_end": 1,                   # 结束页码
        "has_options": True,             # 是否检测到选项
        "option_lines": {                # 选项行原始文本
            "A": "...",
            "B": "...",
            "C": "...",
            "D": "..."
        },
        "confidence": 0.9               # 切分置信度
    }
]
```

### 核心函数

```python
def split_questions(normalized_blocks: list[dict], structure: dict) -> list[dict]:
    """从文档块中切分出单道题目。"""

def _detect_question_number(text: str) -> int | None:
    """检测文本开头的题号。"""

def _detect_option_line(text: str) -> tuple[str, str] | None:
    """检测选项行，返回 (key, text)。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/question_splitter.py`

### 实现方案

1. **题号检测**（规则优先，模糊匹配）：

```python
QUESTION_PATTERNS = [
    (r"^(\d+)[.、)）]", 1),         # "1." / "1、" / "1)" / "1）"
    (r"^\((\d+)\)", 1),             # "(1)"
    (r"^【(\d+)】", 1),             # "【1】"
    (r"^第\s*(\d+)\s*题", 1),       # "第1题"
]

# OCR 容错：常见 OCR 错误映射
OCR_DIGIT_MAP = {
    "O": "0", "o": "0", "l": "1", "I": "1", "S": "5"
}
```

2. **选项检测**：

```python
OPTION_PATTERNS = [
    r"^([A-Da-d])[.、:：)）]\s*(.+)",  # "A. xxx" / "A: xxx"
    r"^([A-Da-d])\s(.+)",               # "A xxx"（空格分隔，需过滤短内容）
]

# OCR 容错：常见选项 OCR 错误
OCR_OPTION_MAP = {
    "8": "B", "6": "B", "0": "D", "C": "C", "c": "C"
}
```

3. **切分算法**：
   - 按 `normalized_blocks` 顺序拼接全文（保留页码标记，使用 `normalized_text`）
   - 正则扫描所有题号位置
   - 以题号作为切分点，分割全文
   - 对每段文本再扫描选项标记
   - 跨页题目：同一题号跨 block 的合并

4. **模糊匹配**：
   - 题号 OCR 错误：先尝试精确匹配，失败后应用 OCR 映射表再试
   - 选项 OCR 错误：`8 → B`、`0 → D` 等映射
   - 连续多个切分失败时降低置信度

5. **未解析文本**：
   - 题号无法匹配的文本段收集到 `unparsed` 列表
   - 置信度过低的题目标记出来供 stage6（AI 修复）处理

### 关键设计

- 所有正则模式在模块顶层定义，不硬编码在函数内部
- 模糊匹配只在精确匹配失败后触发，不影响正常数据
- 跨页合并：用题号连续性判断

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/question_splitter.py` | 题目切分核心模块 |

### 不修改

- 不修改 `text_extractor.py` / `structure_analyzer.py`
- 不修改任何 model / service / API 路由
- 不修改 `requirements.txt`

## 测试要求

### 单元测试

`backend/tests/test_services/test_question_splitter.py`

| 测试用例 | 描述 |
|---------|------|
| 标准 INLINE 文档 | 典型题目+选项混合文档 |
| 单一题号格式 | 统一使用 "1." 格式 |
| 多题号格式混用 | "1." + "1、" + "(1)" 混用 |
| 跨页题目 | 同一题在两页之间 |
| OCR 错字题号 | "l" 代替 "1"，"O" 代替 "0" |
| OCR 错字选项 | "8" 代替 "B" |
| 无选项题目 | 填空题等无选项的题目 |
| 空文本 | 空字符串/空列表 |
| 单题文档 | 只有一个题目的边界情况 |

### 测试数据

`backend/tests/fixtures/` 下准备：
- `splitter_inline.txt` — 标准混合文本
- `splitter_ocr_noise.txt` — 含 OCR 错误的文本
- `splitter_cross_page.txt` — 跨页题目的文本
- `splitter_single.txt` — 单题文本

## 完成标准

- [ ] 支持 4 种以上题号格式（1. / 1、/ (1) / 【1】 / 第1题）
- [ ] 支持选项行识别（A. / A: / A、等变体）
- [ ] 跨页题目正确合并
- [ ] OCR 容错机制生效（常见数字/字母混淆）
- [ ] 所有单测通过
- [ ] 未解析的文本段收集到独立列表，不丢失

## docs 更新要求

- `/docs/ai/AI_PIPELINE.md`：新增 question_splitter 模块说明

## 下一阶段衔接

Stage 4 以本阶段输出的 `raw_questions` 作为输入进行答案匹配和关联。本阶段只关注切分，不关心答案内容。
