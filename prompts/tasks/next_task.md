# 任务：修复 ocr_code_test_2.png 中“答案丢失 + 题干异常 + 代码块乱码”的 OCR 导入问题

请使用 `logs_1.txt` 做一次日志回放式调试：不要只看最终 JSON，必须标出错误首次出现在哪个阶段，并用回归测试锁定该阶段。

## 一、问题背景

原图题目为数据结构二叉树遍历选择题，图片中包含：

1. 中文题干
2. C 语言结构体代码
3. A-D 四个选项
4. 显式答案：`答案：A`

当前系统识别结果为：

```text
2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:
```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
问题表现：

- `answer` 没有识别出来。
- 题干中代码块第三行被识别成乱码。
- C 结构体代码没有被正确修复为 `struct BiTNode *lchild, *rchild;`。
- PaddleOCR-VL 返回低置信结果后被接受，但后续 AI safety 已检测到 `options_dropped(4→0)`。
- 最终题目被错误降级为无选项/无答案状态。

## 二、必须复现的输入

新增日志回放测试，不依赖真实 OCR 图片，直接使用日志中的 OCR 文本作为输入：

```python
RAW_OCR = """
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

## 三、根因定位要求

请重点排查以下链路：

### 1. clean_ocr_text 阶段

当前系统把乱码代码包装成：

~~~text
```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
但仅仅加代码围栏不等于修复成功。

必须新增代码块质量检测：

```python
detect_garbled_code_block(code: str) -> CodeGarbledResult
~~~

返回：

```python
@dataclass
class CodeGarbledResult:
    is_garbled: bool
    score: float
    reasons: list[str]
    expected_language: str | None
```

检测规则：

- 出现 `typedef struct Xxx { ... } Xxx, *Ptr;`，应判定为 C 语言结构体。
- 结构体内部若出现大量非 C 声明片段，如 `(1typu* p1tysI* apo11ta aonu2s`，必须标记：
  - `ocr_garbled_code`
  - `c_struct_body_garbled`
  - `code_block_incomplete`
- 不能因为代码块被包进 ```text 就认为已修复。

### 2. ocr_correction 阶段

当前日志显示 PaddleOCR-VL 低置信结果仍被接受，随后 AI safety 检测到选项丢失：

```text
PaddleOCR-VL succeeded conf=0.00
OCR fix accepted ... low_confidence_source
VL confidence override: accepting VL result
AI safety REJECTED: options_dropped(4→0)
```

修复要求：

- 当 VL/AI 修复结果 `conf=0.00` 且导致 `options_dropped(4→0)` 时，必须拒绝该结果。
- 不允许用低置信 VL 结果覆盖原始 OCR 中已存在的 A-D 选项和 `答案：A`。
- 如果候选结果丢失选项或答案，应回退到 raw OCR + structure_freeze 结果。
- `confidence override` 不能绕过 `ai_safety`。

建议逻辑：

```python
if candidate.confidence <= 0.2 and safety_result.has("options_dropped"):
    reject_candidate()
    keep_raw_ocr_structure()
    mark_risk("vl_low_confidence_rejected")
```

### 3. structure_freeze / split 阶段

原始 OCR 中已经有：

```text
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
答案：A
```

必须冻结并保留：

```json
{
  "A": "ABDECF",
  "B": "ABDCEF",
  "C": "ABDFEC",
  "D": "ACBEDF"
}
```

修复要求：

- 选项冻结后，后续任何 VL/AI 修复都不得删除 frozen options。
- split 阶段必须从 stem 中剥离 A-D 选项文本，但不能把选项对象清空。
- 支持如下格式：

```text
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
A. ABDECF B. ABDCEF C. ABDFEC D. ACBEDF
A.ABDECF B.ABDCEF C.ABDFEC D.ACBEDF
```

新增函数：

```python
strip_frozen_options_from_stem(stem: str, frozen_options: dict[str, str]) -> str
```

验收：

```python
assert "A.ABDECF" not in stem
assert "B.ABDCEF" not in stem
assert "C.ABDFEC" not in stem
assert "D. ACBEDF" not in stem
assert options["A"] == "ABDECF"
assert options["D"] == "ACBEDF"
```

### 4. 显式答案提取阶段

必须新增或修复显式答案提取函数：

```python
extract_explicit_answer(raw_text: str) -> str | None
```

必须支持：

```text
答案：A
答案:A
参考答案：A
正确答案：A
Answer: A
```

要求：

- 显式答案应优先于 AI 推理答案。
- 即使代码乱码无法修复，只要原始 OCR 中存在 `答案：A`，也必须提取 `answer = "A"`。
- 不允许因为题干质量低而清空显式答案。
- 如果答案行被剥离出 stem，必须进入 answer 字段，而不是被丢弃。

验收：

```python
assert answer == "A"
assert "答案" not in stem
```

### 5. normalize_schema 阶段

当前最终结果错误地变成：

```text
选项: 无
答案: 空
risk_flags: code_garbled_text / ocr_garbled_code / low_confidence
```

修复要求：

- `normalize_schema` 不能把已冻结的 options 清空。
- 如果 upstream 有 frozen options，则 final_options 必须优先恢复。
- 如果 raw_text 有显式答案，则 final_answer 必须优先恢复。
- 若仍存在 `ocr_garbled_code`，题目可以进入人工审核，但不能丢失 answer/options。
- `subjective` 类型不能覆盖已识别到 A-D 选项的单选题。

建议规则：

```python
if frozen_options and len(frozen_options) >= 2:
    question_type = "single_choice"
    options = frozen_options

if explicit_answer:
    answer = explicit_answer
```

## 四、最终期望输出

修复后，该题最终结构化结果必须为：

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
  "confidence_score": 0.8
}
```

如果代码块无法可靠修复，最低合格输出为：

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
  "confidence_score": 0.6,
  "risk_flags": [
    "ocr_garbled_code",
    "c_struct_body_garbled"
  ]
}
```

## 五、回归测试要求

新增测试文件：

```text
tests/ocr_regression/test_ocr_code_test_2_binary_tree.py
```

### 测试 1：日志回放 raw OCR

```python
def test_log_replay_ocr_code_test_2_raw_text():
    result = import_from_raw_ocr(RAW_OCR)

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
    assert "答案" not in result.stem
```

### 测试 2：代码块乱码风险不丢失结构

```python
def test_garbled_code_does_not_drop_options_or_answer():
    result = import_from_raw_ocr(RAW_OCR)

    assert result.options
    assert len(result.options) == 4
    assert result.answer == "A"

    if "ocr_garbled_code" in result.risk_flags:
        assert result.quality_status == "needs_manual_review"
        assert result.confidence_score <= 0.6
    else:
        assert result.quality_status == "passed"
        assert result.confidence_score >= 0.8
```

### 测试 3：VL 低置信且丢选项必须拒绝

~~~python
def test_vl_low_confidence_options_dropped_rejected():
    raw = RAW_OCR

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
assert result.options["D"] == "ACBEDF"
assert result.answer == "A"
assert "vl_low_confidence_rejected" in result.risk_flags
### 测试 4：显式答案提取

```python
@pytest.mark.parametrize("answer_line", [
    "答案：A",
    "答案:A",
    "参考答案：A",
    "正确答案：A",
    "Answer: A",
])
def test_explicit_answer_extraction(answer_line):
    text = RAW_OCR.replace("答案：A", answer_line)
    result = import_from_raw_ocr(text)
    assert result.answer == "A"
```

## 六、禁止事项

1. 禁止硬编码 `ocr_code_test_2.png` 文件名。
2. 禁止硬编码完整题干。
3. 禁止把所有 `typedef struct` 都强行修复成 `BiTNode`。
4. 禁止为了通过测试关闭 OCR quality gate。
5. 禁止为了通过测试关闭 AI safety gate。
6. 禁止让低置信 VL 结果覆盖 raw OCR 中已存在的选项和答案。
7. 禁止最终输出 `answer=""` 且 `confidence_score=1.0`。
8. 禁止把有 A-D 选项的题目降级成 subjective。
9. 禁止只在前端显示层修复，必须修复后端结构化数据。
10. 禁止只改 BUGS.md，不加测试、不改代码。

## 七、调试输出要求

请在修复后输出一份阶段链路说明，至少包含：

```json
{
  "raw_ocr": {
    "has_options": true,
    "has_explicit_answer": true,
    "answer": "A"
  },
  "code_quality": {
    "has_code_block": true,
    "is_garbled": true,
    "risk_flags": ["ocr_garbled_code"]
  },
  "ocr_correction": {
    "vl_candidate_confidence": 0.0,
    "vl_candidate_dropped_options": true,
    "decision": "rejected_or_merged_without_dropping_options"
  },
  "structure_freeze": {
    "frozen_options": ["A", "B", "C", "D"],
    "answer_preserved": true
  },
  "normalize_schema": {
    "question_type": "single_choice",
    "options_count": 4,
    "answer": "A",
    "quality_status": "passed_or_needs_manual_review"
  }
}
```

## 八、验收命令

请确保以下测试通过：

```bash
pytest tests/ocr_regression/test_ocr_code_test_2_binary_tree.py -q
pytest tests/ocr_regression -q
pytest tests -q
```

最终验收重点不是“能入库”，而是：

- 选项不丢；
- 显式答案不丢；
- 乱码代码不伪装成高置信成功；
- 低置信 VL 不覆盖 raw OCR 的可靠结构；
- 题干、代码块、选项、答案、risk_flags 全字段一致。

