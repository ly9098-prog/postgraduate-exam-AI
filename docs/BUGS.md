# 代码题目题干结构异常

##### 案例一

###### 原题

```tex
1. 设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行F(5)，则函数内部发生递归调用的总次数（含初始调用）为：
    int F(int n) {
        if (n <= 1) return n;
        return F(n - 1) + F(n - 2);
    }

A. 15
B. 14
C. 9
D. 5

```

###### 导入后进入审核

~~~tex
设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
```text
int F(int n) {
if (n <=
1) return n;
return F(n − 1) + F(n − 2);
```
~~~

###### OCR 原文 / 导入原始信息

````
1. 设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
```text
int F(int n) {
if (n <= 1) return n;
return F(n - 1) + F(n - 2);
```
A. 15
B.14
C.9
D.5
答案:A
````

###### 解析数据

```json
{
  "parsed_content": {
    "text": "设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:\n```text\nint F(int n) {\nif (n <=\n1) return n;\nreturn F(n - 1) + F(n - 2);\n```"
  },
  "parsed_options": {
    "A": "15",
    "B": "14",
    "C": "9",
    "D": "5"
  },
  "parsed_answer": "A",
  "parsed_analysis": null
}
```

###### OCR / AI 原始数据

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:\n```text\nint F(int n) {\nif (n <=\n1) return n;\nreturn F(n - 1) + F(n - 2);\n```",
    "options": [
      {
        "key": "A",
        "text": "15"
      },
      {
        "key": "B",
        "text": "14"
      },
      {
        "key": "C",
        "text": "9"
      },
      {
        "key": "D",
        "text": "5"
      }
    ],
    "answer": "A",
    "analysis": "",
    "raw_text": "1. 设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:\n```text\nint F(int n) {\nif (n <= 1) return n;\nreturn F(n - 1) + F(n - 2);\n```\nA. 15\nB.14\nC.9\nD.5\n答案:A",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_1.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "stem_hash": "be66f26f",
    "confidence_score": 1,
    "validation_status": "passed",
    "failure_reason": [],
    "retry_recommended": false,
    "ocr_quality_flags": [
      "watermark_noise_detected"
    ],
    "repair_skipped": true,
    "repair_skipped_reason": "low_risk_high_confidence",
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "be66f26f",
    "risk_flags": null
  }
}
```

##### 案例二

###### 原题

```tex
2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：

typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;

A. ABDECF
B. ABDCEF
C. ABDFEC
D. ACBEDF
```

###### 导入后进入审核

~~~tex
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:
```text
typedef struct BiTNode {
char data;
``` (1typu * p1tysI * apo11ta aonu2s
~~~

###### OCR 原文 / 导入原始信息

~~~tex
2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:
```text
typedef struct BiTNode {
char data;
``` (1typu* p1tysI* apo11ta aonu2s
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
答案:A
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:\n```text\ntypedef struct BiTNode {\nchar data;\n``` (1typu* p1tysI* apo11ta aonu2s"
  },
  "parsed_options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "parsed_answer": "A",
  "parsed_analysis": null
}
```

###### OCR / AI 原始数据

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:\n```text\ntypedef struct BiTNode {\nchar data;\n``` (1typu* p1tysI* apo11ta aonu2s",
    "options": [
      {
        "key": "A",
        "text": "ABDECF"
      },
      {
        "key": "B",
        "text": "ABDCEF"
      },
      {
        "key": "C",
        "text": "ABDFEC"
      },
      {
        "key": "D",
        "text": "ACBEDF"
      }
    ],
    "answer": "A",
    "analysis": "",
    "raw_text": "2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:\n```text\ntypedef struct BiTNode {\nchar data;\n``` (1typu* p1tysI* apo11ta aonu2s\nA.ABDECF\nB.ABDCEF\nC.ABDFEC\nD. ACBEDF\n答案:A",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_2.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "stem_hash": "dfa3875d",
    "confidence_score": 1,
    "validation_status": "passed",
    "failure_reason": [],
    "retry_recommended": false,
    "ocr_quality_flags": [
      "watermark_noise_detected"
    ],
    "repair_skipped": true,
    "repair_skipped_reason": "low_risk_high_confidence",
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "dfa3875d",
    "risk_flags": null
  }
}
```

## 问题描述

### 问题一：代码题题干中的代码块被破坏，但系统误判为高置信通过

在代码类选择题导入过程中，题干中的 C/C++ 代码块出现结构性损坏，但导入流程仍将其判定为 `validation_status=passed`，并且由于 `confidence_score=1` 和 `repair_skipped_reason=low_risk_high_confidence`，直接跳过了 OCR 修复和 AI 修复流程。

案例一中，原始 OCR 文本里的代码行为：

```c
if (n <= 1) return n;
```

但进入审核后的题干被错误拆成：

```text
if (n <=
1) return n;
```

同时代码块缺失函数闭合大括号，最终审核页面只保留了不完整代码。虽然选项和答案解析字段被正常解析，但题干代码已经发生破坏，影响题目可读性和正确性。

案例二中问题更严重。原题中的结构体代码应为：

```c
typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;
```

但导入后只保留了：

~~~text
typedef struct BiTNode {
char data;
``` (1typu * p1tysI * apo11ta aonu2s
~~~

代码块不仅被提前截断，还混入明显乱码 `(1typu * p1tysI * apo11ta aonu2s`。这类内容已经不是正常 C 代码，但系统仍然将该题标记为有效，并跳过修复。

这说明当前 OCR 导入流程对代码题存在两个缺陷：

1. 代码块结构完整性没有被纳入质量门禁；
2. “低风险高置信跳过修复”策略没有识别代码场景中的结构损坏和乱码污染。

### 问题二：代码场景的风险识别不足，watermark_noise_detected 未能升级为人工复核或视觉回退

两个案例的 `ocr_quality_flags` 均只记录了 `watermark_noise_detected`，但没有产生更高优先级的代码结构风险，例如：

- `code_block_incomplete`
- `code_block_truncated`
- `code_garbled_text`
- `code_brace_unbalanced`
- `code_semantic_corruption`
- `code_line_break_suspicious`

这导致系统认为题目整体仍是低风险，并继续执行 `repair_skipped=true`。实际表现是：题干核心代码已损坏，但系统只关注选项、答案是否解析成功，没有判断代码块本身是否完整。

对于 408、C/C++、数据结构类题目，题干中的代码往往是题目核心内容。即使选项和答案都能解析成功，只要代码块被截断、括号不平衡、出现异常乱码或 fenced code block 未闭合，都不应该直接标记为高置信通过。

## 修复进度

| 任务 | 状态 | 说明 |
|------|------|------|
| 任务一：代码块完整性检测 | ✅ 已完成 | `code_integrity.py` 实现 7 维度检测，集成到 ocr_quality_gate 和 question_normalizer |
| 任务二：low_risk_high_confidence 跳过规则 | ✅ 已完成 | ai_repair.py `_is_low_risk_skip_candidate()` 增加代码完整性检测 |
| 任务三：PaddleOCR-VL 视觉回退 | ✅ 已完成 | `vision_fallback.py` 核心逻辑 + `normalize_question()` 集成，27 个单元/集成测试 |
| 任务四：raw_text vs parsed_content 差异检测 | ✅ 已完成 | `detect_code_regression()` 在 question_normalizer 中调用 |
| 任务五：代码块保护规则 | ✅ 已完成 | `_break_before_number_markers()` + `_clean_stem()` 均跳过 fenced code block 内部 |
| 任务六：回归测试样例 | ✅ 已完成 | 新增 `018_code_fibonacci_linebreak` 和 `019_code_struct_garbled_truncation` |
| 任务七：验收标准 | ✅ 已完成 | `test_code_integrity.py` 含 33 个测试，覆盖全部验收标准 |

## 修复任务

### 任务一：增加代码块完整性检测

在 OCR 质量门禁或 question normalizer 阶段增加代码块完整性检测，重点识别以下异常：

1. fenced code block 是否成对闭合；
2. `{` 与 `}` 是否基本平衡；
3. `(` 与 `)` 是否基本平衡；
4. C/C++ 结构体、函数、if、for、while 等代码片段是否存在明显截断；
5. 代码块中是否混入高比例乱码、异常字符或疑似 OCR 噪声；
6. 代码块是否被错误插入到题干普通文本中；
7. 代码块中是否出现异常断行，例如 `n <=` 与 `1)` 被拆成两行。

建议新增风险标记：

```text
code_block_incomplete
code_block_truncated
code_brace_unbalanced
code_garbled_text
code_line_break_suspicious
code_fence_unclosed
```

当检测到上述任一风险时，题目不得进入 `low_risk_high_confidence` 跳过路径。

### 任务二：修复 low_risk_high_confidence 跳过规则

当前系统只要题干、选项、答案解析结构完整，就可能将题目标记为低风险并跳过修复。但代码题不能只看题目结构字段是否完整，还必须检查代码块内容是否可信。

请调整跳过逻辑：

```text
如果题干包含代码块或疑似 C/C++ 代码：
    必须额外执行代码完整性检查；
    如果存在代码块未闭合、括号不平衡、乱码污染、异常断行、疑似截断：
        禁止 repair_skipped=true；
        禁止 validation_status=passed；
        添加 high/medium risk flag；
        进入 OCR correction / vision fallback / 人工审核流程。
```

建议判断条件：

```python
contains_code = has_code_fence or contains_c_keywords or contains_pointer_symbol or contains_struct_function_pattern

if contains_code and code_quality_report.has_error:
    repair_skipped = False
    validation_status = "needs_review"
    retry_recommended = True
```

### 任务三：代码题触发 PaddleOCR-VL 重识别或视觉回退

对于代码块损坏的题目，优先使用 PaddleOCR-VL 对原图区域进行重新识别，而不是仅依赖纯文本纠错。

触发条件建议包括：

```text
code_block_incomplete
code_garbled_text
code_brace_unbalanced
code_fence_unclosed
raw_text 与 parsed_content 中代码块差异过大
```

处理策略：

1. 如果有原图 bbox 或 source region，优先裁剪代码区域调用 PaddleOCR-VL；
2. 如果没有代码区域 bbox，则对整页或整题区域进行 PaddleOCR-VL fallback；
3. PaddleOCR-VL 返回后重新进入规则清洗和代码完整性检测；
4. 若仍无法修复，进入人工审核并标注“代码块疑似损坏”。

### 任务四：保留 raw_text 与 parsed_content 的差异检测

案例一中，`raw_text` 里的代码行基本正常：

```c
if (n <= 1) return n;
```

但 `parsed_content.text` 中变成：

```text
if (n <=
1) return n;
```

说明问题可能发生在 OCR 之后的结构化、清洗或代码块重排阶段，而不一定是 OCR 本身错误。

因此需要增加一个差异检测：

```text
raw_text_code_block 与 parsed_content_code_block 对比：
    如果 parsed_content 中代码块长度明显缩短；
    或关键行被拆断；
    或闭合括号/大括号丢失；
    或 raw_text 中存在但 parsed_content 中丢失；
则标记为 code_structure_regression。
```

新增风险标记：

```text
code_structure_regression
```

该风险应至少为 medium，严重时为 high。

### 任务五：代码块保护规则

在文本清洗、结构化、题干提取、AI 修复阶段，应对代码块进行保护：

1. fenced code block 内部不要随意换行；
2. 不要将 `<= 1` 拆成 `<=\n1`；
3. 不要将 `*lchild, *rchild` 识别或清洗成乱码后仍通过；
4. 不要因为选项和答案解析成功就忽略代码块损坏；
5. 对 C/C++ 代码中的符号进行保护，包括：
   - `*`
   - `->`
   - `<=`
   - `>=`
   - `==`
   - `!=`
   - `{`
   - `}`
   - `;`
   - `,`

### 任务六：增加回归测试样例

请将这两个案例加入 OCR 回归测试集，分别作为代码题结构异常样本。

建议新增 case：

```text
018_code_fibonacci_linebreak
019_code_struct_garbled_truncation
```

测试断言至少包括：

#### 案例一断言

1. `if (n <= 1) return n;` 不应被拆成 `if (n <=\n1) return n;`
2. 代码块中应保留 `return F(n - 1) + F(n - 2);`
3. 如果函数闭合大括号缺失，应标记 `code_block_incomplete`
4. 不允许 `repair_skipped_reason=low_risk_high_confidence`

#### 案例二断言

1. 代码块不得混入 `(1typu* p1tysI* apo11ta aonu2s` 这类乱码后仍通过；
2. 如果结构体定义被截断，应标记 `code_block_truncated` 或 `code_garbled_text`；
3. 不允许 `validation_status=passed`
4. 不允许 `confidence_score=1`
5. 不允许 `repair_skipped=true`
6. 应进入视觉重识别或人工审核流程。

### 任务七：验收标准

修复后应满足以下标准：

1. 代码块损坏的题目不能再被标记为 `low_risk_high_confidence`；
2. 代码块乱码、截断、括号不平衡时，必须进入修复或人工审核；
3. 案例一中 `if (n <= 1) return n;` 不应被错误拆行；
4. 案例二中结构体代码被截断和乱码污染时，系统必须识别为高风险；
5. `confidence_score` 不能在代码块明显损坏时仍为 1；
6. `validation_status` 不能在代码块明显损坏时仍为 `passed`；
7. `ocr_quality_flags` 应包含代码相关风险，而不只是 `watermark_noise_detected`；
8. 两个案例应加入回归测试，后续修改不能再次回退。

```tex
注：

这两个案例不是普通 OCR 字符识别小错误，而是“代码题核心内容损坏后仍被系统高置信通过”的质量门禁缺陷，修复重点不是简单纠正某一行文字，而是让代码块损坏能够被识别、阻断、回退和回归测试覆盖。
```

