# 任务：系统性修复 OCR 导题链路中的结构污染、选项冻结误判、低置信 VL 覆盖与 false pass 问题

你需要基于当前项目 `app.zip` 中的 OCR 导题链路进行代码审计与修复。目标不是只修某一道题，而是修复 OCR 导题流水线中会导致“题干、代码块、选项、答案错位或丢失”的系统性问题。

本次修复重点包括：

1. 同页多题时 frozen options 串题污染；
2. 横排英文/代码类选项被误冻结成单个 A 选项；
3. `PaddleOCR-VL conf=0.00` 或低置信候选仍被 override 接受；
4. AI/VL 候选丢失选项或答案后仍可能污染最终结构；
5. 代码块乱码被包装为 code fence 后伪装成已修复；
6. 有 A-D 选项的客观题被错误降级为 subjective 并 `passed`；
7. 缺少覆盖上述问题的 OCR 回归测试。

---

## 一、修复目标

最终 OCR 导题链路必须满足：

- 原始 OCR 中已经存在 A-D 选项时，后续 AI/VL 修复不得无理由删除或覆盖；
- 原始 OCR 中已经存在显式答案，如 `答案：A`，最终 `answer` 不得为空；
- 同一页有多道题时，选项冻结必须绑定到具体题块，不能按 page 全局注入；
- 低置信 VL 候选不能通过 `confidence override` 覆盖可靠 raw OCR 结构；
- 代码乱码可以进入人工审核，但不能因此丢失选项和答案；
- 选项解析不完整时不能标记为 `quality_status=passed`；
- 有 A-D 选项的题不能被错误降级成 `subjective`；
- 必须新增回归测试，防止后续再次破坏。

---

## 二、重点排查文件

请优先排查以下模块，具体文件名以项目实际路径为准：

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/structure_freeze_stage.py
backend/app/features/ocr_fix/router.py
backend/app/features/ocr_safety.py
backend/app/features/code_detector.py
backend/app/features/text_normalizer.py
backend/app/features/question_splitter.py
backend/app/features/output_normalization.py
backend/app/features/import_pipeline/*
```

如果实际路径不同，请通过搜索以下关键词定位：

```text
frozen_option_registry
structure_freeze
options_dropped
answer_dropped
VL confidence override
confidence override
extract_explicit_answer
strip_frozen_options
normalize_schema
question_type_detection
code_garbled
ocr_garbled_code
```

------

# 三、P0 问题 1：同页多题 frozen options 串题污染

## 现象

当前 `_run_split` 或相关 split 阶段可能按 `page` 收集 `frozen_option_registry`，然后把同页所有 frozen options 注入到每一道题里。

这会导致：

```text
第 1 题：
1. 第一题题干？
A. 一
B. 二
C. 三
D. 四
答案：A

第 2 题：
2. 第二题题干？
A. 甲
B. 乙
C. 丙
D. 丁
答案：B
```

错误结果可能变成：

```json
{
  "q1_stem": "第一题题干？",
  "q1_options": {
    "A": "甲",
    "B": "乙",
    "C": "丙",
    "D": "丁"
  },
  "q1_answer": "A",
  "is_valid": true
}
```

即第一题题干 + 第二题选项 + 第一题答案，被错误判定为有效。

## 修复要求

### 1. frozen options 必须绑定到题目 block/span

不能只用 `page` 作为索引。

请将 frozen options 的绑定维度从：

```python
page -> options
```

改为至少：

```python
(page, block_id) -> options
```

或更严谨：

```python
(page, question_index, start_line, end_line) -> options
```

建议结构：

```python
@dataclass
class FrozenQuestionStructure:
    page: int
    block_id: str | None
    question_index: int | None
    line_start: int
    line_end: int
    stem_span: tuple[int, int] | None
    options: dict[str, str]
    answer: str | None
    source: str
    confidence: float
    risk_flags: list[str]
```

### 2. split 阶段只能注入当前题块对应的 frozen options

禁止逻辑：

```python
# 错误示例
page_options = frozen_option_registry[page]
for question in questions_on_page:
    question.options = page_options
```

正确逻辑：

```python
matched = find_frozen_structure_for_question(
    question_span=question.span,
    page=question.page,
    registry=frozen_option_registry,
)

if matched and span_overlap(question, matched) >= threshold:
    question.options = matched.options
```

### 3. 如果无法精确匹配，不得强制注入

如果当前题块无法与 frozen options 对齐：

```python
if not matched:
    do_not_inject_global_page_options()
    mark_risk("frozen_options_unmatched")
```

------

## 四、P0 问题 2：横排选项冻结器误把整行冻结成 A 选项

## 现象

当前 inline option 正则可能使用类似：

```regex
[^A-Da-d\n]+?
```

这会导致选项文本中一旦出现字母 A/B/C/D/a/b/c/d，就提前截断或无法切分。

例如：

```text
A. Algorithm B. Binary tree C. Data structure D. Code
```

错误结果：

```json
{
  "A": "Algorithm B. Binary tree C. Data structure D. Code"
}
```

最终可能被误判为：

```json
{
  "question_type": "subjective",
  "options": {
    "A": "Algorithm B. Binary tree C. Data structure D. Code"
  },
  "answer": "A",
  "quality_status": "passed"
}
```

这是严重 false pass。

## 修复要求

### 1. 重写横排选项 splitter

不能通过排除字符 `A-D` 来切分。

必须通过“合法选项标签边界”切分。

建议正则：

```python
OPTION_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Da-d])\s*[\.\．、:：]\s*"
)
```

但需要注意：

- `A.` 是选项标签；
- `A．` 是选项标签；
- `A、` 是选项标签；
- `A:` / `A：` 可作为兼容；
- 英文单词里的 `A` / `B` / `C` / `D` 不能被当成标签；
- `Data` 里的 `D` 不能被当成选项 D；
- 代码里的 `struct BiTNode` 不能被误拆。

建议实现：

```python
def parse_inline_options(text: str) -> dict[str, str]:
    matches = list(OPTION_LABEL_RE.finditer(text))
    options = {}

    for i, m in enumerate(matches):
        key = m.group(1).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[start:end].strip()

        if key in "ABCD" and value:
            options[key] = value

    return options
```

### 2. 验证选项完整性

新增：

```python
def validate_option_set(options: dict[str, str]) -> OptionValidationResult:
    ...
```

规则：

```python
@dataclass
class OptionValidationResult:
    is_complete: bool
    is_usable: bool
    count: int
    missing_keys: list[str]
    suspicious_reasons: list[str]
```

要求：

- 单选题常规应至少有 2 个选项；
- A-D 完整更优；
- 只有一个 A 选项时，不得作为 authoritative frozen options；
- 只有一个 A 选项且内容包含 `B.`、`C.`、`D.`，必须标记 `inline_option_split_failed`；
- 选项文本超长且包含多个选项标签，也必须标记风险。

示例：

```python
if len(options) == 1 and "A" in options:
    text = options["A"]
    if re.search(r"(?<![A-Za-z0-9_])[BCD]\s*[\.\．、:：]", text):
        return unusable("inline_option_split_failed")
```

------

# 五、P0 问题 3：选项不完整时不能 subjective passed

## 现象

当选项解析失败时，系统可能把题目降级为 `subjective`，同时 `quality_status=passed`。

这会掩盖严重结构错误。

## 修复要求

### 1. 有客观题信号时禁止降级 subjective

客观题信号包括：

```text
A.
B.
C.
D.
答案：A
正确答案：B
单选题
多选题
下列选项
```

新增函数：

```python
def has_objective_question_signals(raw_text: str, stem: str, answer: str | None) -> bool:
    ...
```

如果满足以下任一条件：

```python
has_A_D_labels = detect_option_labels(raw_text) >= 2
has_explicit_choice_answer = answer in {"A", "B", "C", "D", "AB", "AC", ...}
has_choice_keywords = "下列" in raw_text or "选项" in raw_text
```

则不得自动降级为 subjective。

### 2. 选项不完整时进入人工审核

正确结果：

```json
{
  "question_type": "single_choice",
  "options": {},
  "answer": "A",
  "quality_status": "needs_manual_review",
  "risk_flags": [
    "objective_signals_but_options_incomplete",
    "inline_option_split_failed"
  ],
  "is_valid": false
}
```

禁止结果：

```json
{
  "question_type": "subjective",
  "options": {
    "A": "Algorithm B. Binary tree C. Data structure D. Code"
  },
  "answer": "A",
  "quality_status": "passed",
  "is_valid": true
}
```

------

# 六、P1 问题 4：低置信 PaddleOCR-VL 候选不能 override raw OCR 结构

## 现象

日志中出现过类似链路：

```text
PaddleOCR-VL succeeded conf=0.00
OCR fix accepted ... low_confidence_source
VL confidence override: accepting VL result
AI safety REJECTED: options_dropped(4→0)
```

问题是：

- VL 候选置信度极低；
- 候选文本丢失 A-D 选项；
- 候选文本丢失答案；
- 仍被某个 override 逻辑接受；
- AI safety 的拒绝结果没有成为唯一权威决策。

## 修复要求

### 1. 删除或收紧 confidence override

搜索：

```text
VL confidence override
confidence override
accepting VL result
accepted_with_risk_flags
```

如果存在类似逻辑：

```python
if from_vl:
    accept_candidate_even_if_low_confidence()
```

必须删除或加严格条件。

### 2. AI safety 必须是最终权威门禁

新增或加强：

```python
def evaluate_candidate_structure_loss(raw_text: str, candidate_text: str) -> SafetyResult:
    ...
```

必须检测：

```text
options_dropped
answer_dropped
stem_shrink_too_much
code_block_dropped
choice_labels_dropped
```

建议规则：

```python
raw_options = extract_options(raw_text)
candidate_options = extract_options(candidate_text)

raw_answer = extract_explicit_answer(raw_text)
candidate_answer = extract_explicit_answer(candidate_text)

if len(raw_options) >= 2 and len(candidate_options) == 0:
    reject("options_dropped")

if raw_answer and not candidate_answer:
    reject("answer_dropped")

if len(candidate_text) < len(raw_text) * 0.45:
    reject("stem_shrink_too_much")
```

### 3. 低置信候选触发硬拒绝

```python
if candidate.confidence <= 0.2:
    if safety.has_any(["options_dropped", "answer_dropped", "stem_shrink_too_much"]):
        reject_candidate()
        fallback_to_raw_structure()
        mark_risk("vl_low_confidence_rejected")
```

### 4. fallback 必须保留 raw OCR 中可靠结构

当 VL/AI 候选被拒绝时：

```python
result.text = raw_text_or_rule_repaired_text
result.options = raw_frozen_options
result.answer = raw_explicit_answer
result.risk_flags.append("ai_candidate_rejected_structure_loss")
```

禁止：

```python
result.options = {}
result.answer = ""
```

------

# 七、P1 问题 5：显式答案必须全链路保留

## 修复要求

新增或强化函数：

```python
def extract_explicit_answer(raw_text: str) -> str | None:
    ...
```

必须支持：

```text
答案：A
答案:A
参考答案：A
正确答案：A
Answer: A
答案：AB
参考答案：ACD
```

建议正则：

```python
ANSWER_RE = re.compile(
    r"(?:参考答案|正确答案|答案|Answer)\s*[:：]\s*([A-Da-d]{1,4})",
    re.IGNORECASE
)
```

要求：

- 显式答案优先于 AI 推理答案；
- 显式答案从 stem 中剥离后必须写入 `answer` 字段；
- 代码乱码、选项不完整、低置信 OCR 都不能清空显式答案；
- 如果最终 answer 为空，但 raw_text 有显式答案，应视为 pipeline bug。

验收：

```python
assert extract_explicit_answer("答案：A") == "A"
assert extract_explicit_answer("答案:A") == "A"
assert extract_explicit_answer("参考答案：B") == "B"
assert extract_explicit_answer("正确答案：CD") == "CD"
assert extract_explicit_answer("Answer: A") == "A"
```

------

# 八、P1 问题 6：代码块乱码不能伪装成已修复

## 背景样例

原 OCR：

```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
```

正确代码应接近：

```c
typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;
```

当前问题：

- 系统把乱码代码包进 ```text；
- 但没有真正修复；
- 后续可能误以为 code block 已经稳定；
- 或因 code block 乱码影响整题结构。

## 修复要求

新增：

```python
def detect_garbled_code_block(code: str) -> CodeGarbledResult:
    ...
```

结构：

```python
@dataclass
class CodeGarbledResult:
    is_garbled: bool
    score: float
    reasons: list[str]
    expected_language: str | None
```

检测规则：

```python
if "typedef struct" in code and re.search(r"}\s*\w+\s*,\s*\*\w+\s*;", code):
    expected_language = "c"

if expected_language == "c":
    if contains_many_non_c_tokens(code):
        reasons.append("c_struct_body_garbled")

    if not re.search(r"struct\s+\w+\s*\*\s*\w+", code):
        reasons.append("c_struct_pointer_field_missing_or_garbled")

    if line_has_high_symbol_noise(code):
        reasons.append("ocr_garbled_code")
```

输出要求：

- 如果代码能可靠修复，可提升质量；
- 如果无法可靠修复，不得丢选项和答案；
- 应输出：

```json
{
  "quality_status": "needs_manual_review",
  "risk_flags": [
    "ocr_garbled_code",
    "c_struct_body_garbled"
  ]
}
```

------

# 九、针对当前二叉树题的验收样例

## 输入

```python
RAW_OCR_BINARY_TREE = """
2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA
则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
答案：A
"""
```

## 最低合格输出

```json
{
  "question_type": "single_choice",
  "stem": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：",
  "code_blocks": [
    "typedef struct BiTNode {\nchar data;\n(1typu*  p1tysI* apo11ta aonu2s\n} BiTNode, *BiTree;"
  ],
  "options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "answer": "A",
  "quality_status": "needs_manual_review",
  "risk_flags": [
    "ocr_garbled_code",
    "c_struct_body_garbled"
  ]
}
```

## 理想输出

```json
{
  "question_type": "single_choice",
  "stem": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：",
  "code_blocks": [
    "typedef struct BiTNode {\n    char data;\n    struct BiTNode *lchild, *rchild;\n} BiTNode, *BiTree;"
  ],
  "options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "answer": "A",
  "quality_status": "passed",
  "risk_flags": []
}
```

注意：如果没有足够证据可靠修复代码，不要强行把乱码修成 `lchild, rchild`，保留乱码代码并进入人工审核即可。重点是不能丢选项和答案。

------

# 十、必须新增回归测试

新增测试目录：

```text
backend/tests/ocr_regression/
```

或项目现有测试目录下：

```text
tests/ocr_regression/
```

新增测试文件：

```text
test_ocr_pipeline_structure_safety.py
test_ocr_binary_tree_code_case.py
test_ocr_inline_options.py
test_ocr_multi_question_page_isolation.py
test_ocr_vl_low_confidence_rejection.py
```

------

## 测试 1：当前二叉树题保留选项和答案

```python
def test_binary_tree_code_question_preserve_options_and_answer():
    result = import_from_raw_ocr(RAW_OCR_BINARY_TREE)

    assert result.question_type == "single_choice"
    assert "中序遍历序列为 DBEAFC" in result.stem
    assert "后序遍历序列为 DEBFCA" in result.stem
    assert "前序遍历序列" in result.stem

    assert result.options["A"] == "ABDECF"
    assert result.options["B"] == "ABDCEF"
    assert result.options["C"] == "ABDFEC"
    assert result.options["D"] == "ACBEDF"

    assert result.answer == "A"

    assert "A.ABDECF" not in result.stem
    assert "B.ABDCEF" not in result.stem
    assert "C.ABDFEC" not in result.stem
    assert "D. ACBEDF" not in result.stem
    assert "答案" not in result.stem
```

------

## 测试 2：乱码代码不能导致选项/答案丢失

```python
def test_garbled_code_does_not_drop_options_or_answer():
    result = import_from_raw_ocr(RAW_OCR_BINARY_TREE)

    assert len(result.options) == 4
    assert result.answer == "A"

    if "ocr_garbled_code" in result.risk_flags:
        assert result.quality_status == "needs_manual_review"
        assert result.is_valid is False or result.review_required is True
```

------

## 测试 3：低置信 VL 候选丢选项必须拒绝

~~~python
def test_vl_low_confidence_candidate_dropping_options_is_rejected():
    raw = RAW_OCR_BINARY_TREE

    vl_candidate = """
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:
```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
~~~

"""

```
result = run_ocr_fix_router(
    raw_text=raw,
    candidate_text=vl_candidate,
    candidate_confidence=0.0
)

assert result.options["A"] == "ABDECF"
assert result.options["B"] == "ABDCEF"
assert result.options["C"] == "ABDFEC"
assert result.options["D"] == "ACBEDF"
assert result.answer == "A"

assert "vl_low_confidence_rejected" in result.risk_flags
assert "options_dropped" in result.risk_flags or "ai_candidate_rejected_structure_loss" in result.risk_flags
---

## 测试 4：同页两题不能串选项

```python
RAW_OCR_TWO_QUESTIONS = """
1. 第一题题干？
A. 一
B. 二
C. 三
D. 四
答案：A

2. 第二题题干？
A. 甲
B. 乙
C. 丙
D. 丁
答案：B
"""

def test_two_questions_same_page_options_do_not_cross_contaminate():
    results = import_from_raw_ocr_multi(RAW_OCR_TWO_QUESTIONS)

    assert len(results) == 2

    q1, q2 = results[0], results[1]

    assert "第一题题干" in q1.stem
    assert q1.options["A"] == "一"
    assert q1.options["B"] == "二"
    assert q1.options["C"] == "三"
    assert q1.options["D"] == "四"
    assert q1.answer == "A"

    assert "第二题题干" in q2.stem
    assert q2.options["A"] == "甲"
    assert q2.options["B"] == "乙"
    assert q2.options["C"] == "丙"
    assert q2.options["D"] == "丁"
    assert q2.answer == "B"

    assert q1.options != q2.options
```

------

## 测试 5：横排英文选项正确切分

```python
RAW_OCR_INLINE_ENGLISH = """
1. Which term describes a tree traversal method?
A. Algorithm B. Binary tree C. Data structure D. Code
答案：B
"""

def test_inline_english_options_split_correctly():
    result = import_from_raw_ocr(RAW_OCR_INLINE_ENGLISH)

    assert result.question_type == "single_choice"
    assert result.options["A"] == "Algorithm"
    assert result.options["B"] == "Binary tree"
    assert result.options["C"] == "Data structure"
    assert result.options["D"] == "Code"
    assert result.answer == "B"
    assert result.quality_status != "passed" or len(result.options) == 4
```

------

## 测试 6：横排选项误冻结成单 A 时不得 passed

```python
def test_single_a_option_containing_bcd_labels_is_not_authoritative():
    bad_options = {
        "A": "Algorithm B. Binary tree C. Data structure D. Code"
    }

    validation = validate_option_set(bad_options)

    assert validation.is_usable is False
    assert "inline_option_split_failed" in validation.suspicious_reasons
```

------

## 测试 7：客观题信号存在时不得降级 subjective

```python
RAW_OCR_OBJECTIVE_BROKEN_OPTIONS = """
1. 下列说法正确的是？
A. Algorithm B. Binary tree C. Data structure D. Code
答案：B
"""

def test_objective_signals_prevent_subjective_false_pass():
    result = import_from_raw_ocr_with_broken_inline_parser(
        RAW_OCR_OBJECTIVE_BROKEN_OPTIONS
    )

    assert result.question_type in {"single_choice", "multiple_choice"}
    assert result.quality_status == "needs_manual_review"
    assert result.is_valid is False or result.review_required is True
    assert "objective_signals_but_options_incomplete" in result.risk_flags
```

------

# 十一、最终链路决策要求

修复后，每道题应输出调试 trace，至少包含：

```json
{
  "raw_ocr": {
    "has_option_labels": true,
    "option_label_count": 4,
    "has_explicit_answer": true,
    "explicit_answer": "A"
  },
  "structure_freeze": {
    "frozen_options_count": 4,
    "frozen_options_keys": ["A", "B", "C", "D"],
    "binding": {
      "page": 1,
      "block_id": "block_0",
      "line_start": 8,
      "line_end": 11
    },
    "is_authoritative": true
  },
  "ocr_correction": {
    "vl_candidate_confidence": 0.0,
    "candidate_dropped_options": true,
    "candidate_dropped_answer": true,
    "decision": "rejected"
  },
  "split": {
    "question_count": 1,
    "options_cross_contamination_guard": "passed"
  },
  "normalize_schema": {
    "question_type": "single_choice",
    "options_count": 4,
    "answer": "A",
    "quality_status": "needs_manual_review"
  },
  "risk_flags": [
    "ocr_garbled_code"
  ]
}
```

------

# 十二、禁止事项

1. 禁止硬编码 `ocr_code_test_2.png` 文件名；
2. 禁止硬编码二叉树题干；
3. 禁止把所有 `typedef struct` 都强行修复成 `BiTNode`；
4. 禁止关闭 OCR quality gate；
5. 禁止关闭 AI safety gate；
6. 禁止低置信 VL 候选覆盖 raw OCR 中已有的选项和答案；
7. 禁止把同页 frozen options 全局注入每一道题；
8. 禁止只有一个 A 选项时仍判定选择题通过；
9. 禁止有 A-D 选项信号时降级为 subjective passed；
10. 禁止最终输出 `answer=""` 且 `confidence_score=1.0`；
11. 禁止只在前端展示层修复，必须修复后端结构化数据；
12. 禁止只改 prompt，不加回归测试；
13. 禁止删除风险标记来让测试通过；
14. 禁止把 `needs_manual_review` 强行改为 `passed`。

------

# 十三、验收命令

请在后端项目根目录执行：

```bash
pytest tests/ocr_regression/test_ocr_pipeline_structure_safety.py -q
pytest tests/ocr_regression/test_ocr_binary_tree_code_case.py -q
pytest tests/ocr_regression/test_ocr_inline_options.py -q
pytest tests/ocr_regression/test_ocr_multi_question_page_isolation.py -q
pytest tests/ocr_regression/test_ocr_vl_low_confidence_rejection.py -q
pytest tests/ocr_regression -q
pytest tests -q
```

如果项目测试目录是：

```text
backend/tests/
```

则执行：

```bash
cd backend
pytest tests/ocr_regression -q
pytest tests -q
```

------

# 十四、最终交付内容

请交付：

1. 修改过的后端代码；
2. 新增/修改的 OCR 回归测试；
3. 一份修复说明，包含：
   - 根因；
   - 修改文件；
   - 新增函数；
   - 关键逻辑；
   - 风险控制；
   - 回归测试结果；
4. 一份本题回放结果 JSON；
5. 一份同页多题回放结果 JSON；
6. 一份横排英文选项回放结果 JSON。

最终验收标准：

```text
二叉树题：选项不丢，答案不丢，代码乱码进审核。
低置信 VL：丢选项/答案则拒绝。
同页多题：不串选项。
横排英文选项：正确切分 A-D。
选项解析失败：不得 subjective passed。
显式答案：全链路保留。

```
