# OCR识别异常

## ✅ 已修复汇总（2026-07-08）

本轮修复已全面处理以下 5 个案例 + 5 个系统性架构问题（P0-P1），
详见下方各案例标记和文末修复总结。

| 案例 | 状态 | 回归测试 | 涉及文件 |
|------|------|----------|----------|
| Case 1 (false_3): 栈题横排选项 | ✅ 已修复 | `test_bugs_stack_and_code_cases::TestCase1_*` | `question_splitter.py`, `question_normalizer.py` |
| Case 2 (false_4): 题干选项粘连 | ✅ 已修复 | `TestCase2_*` | `question_normalizer.py` (inline stripping) |
| Case 3 (false_5): 下标误改写 | ✅ 已修复 | `TestSubscriptSafetyGate::test_detect_subscript_change_*` | `ai_repair.py` (safety gate) |
| Case 4 (false_1): 代码误切选项 | ✅ 已修复 | `TestCase4_*` | `question_splitter.py` (code quarantine) |
| Case 5 (ocr_code_test_2): 结构体+遍历序列 | ✅ 已修复 | `TestLogReplayOcrCodeTest2::*`, `TestCase5_*` | `code_integrity.py`, `answer_matcher.py`, `question_splitter.py` |

### 系统性修复

| 问题 | 状态 | 回归测试 |
|------|------|----------|
| P0.1 显式答案提取 | ✅ 已修复 | `TestExplicitAnswerExtraction::*` |
| P0.2 Frozen option stem 剥离 | ✅ 已修复 | `TestFrozenOptionsStripping::*` |
| P0.3 质量状态单调性 | ✅ 已修复 | `TestQualityStatus::*` |
| P0.4 乱码代码检测增强 | ✅ 已修复 | `TestGarbledCodeDetection::*` |
| P0.5 Review 保留 risk_flags | ✅ 已修复 | — |
| P1.1 代码隔离 | ✅ 已修复 | `TestCase4_*::test_code_quarantine_*` |
| P1.2 横排选项 + inline stripping | ✅ 已修复 | `TestCase1_*`, `TestCase2_*` |
| P1.3 数学下标安全门禁 | ✅ 已修复 | `TestSubscriptSafetyGate::*` |

---


## 本轮根据原图补充的修复目标

- 补全各案例的“原题”空块，记录图片可见的正确题干、选项与答案。
- 明确四类 OCR/AI 修复异常：数学下标丢失、横排选项截断、题干与选项粘连、代码片段被误切成选项。
- 新增二叉树遍历题作为“结构体代码块 + 遍历字符串 + 答案区”混合场景回归样例。
- 后续验收时，客观题应同时校验 `stem/options/answer/analysis`，不能只判定 `is_valid=true`。


##### 案例一 ✅ 已修复

修复：横排选项切分增强（`question_splitter.py` inline pattern 支持中文逗号边界）+ inline option stem stripping（`question_normalizer.py`）

回归测试：`test_bugs_stack_and_code_cases::TestCase1_False3_StackHorizontalOptions`

###### 原题

```tex
22. 已知栈的入栈序列是 $1,2,3,4$，其出栈序列为 $P_1,P_2,P_3,P_4$，则 $P_2,P_4$ 不可能是（ ）。

A. $2,4$
B. $2,1$
C. $4,3$
D. $3,4$

答案：C
```

###### 图片核对后的期望解析数据

```json
{
  "parsed_content": {
    "text": "已知栈的入栈序列是 $1,2,3,4$，其出栈序列为 $P_1,P_2,P_3,P_4$，则 $P_2,P_4$ 不可能是（ ）。"
  },
  "parsed_options": {
    "A": "2,4",
    "B": "2,1",
    "C": "4,3",
    "D": "3,4"
  },
  "parsed_answer": "C",
  "parsed_analysis": "栈输入序列为 1,2,3,4。可行出栈序列中不存在 $P_2=4$ 且 $P_4=3$ 的情况，因此 $P_2,P_4$ 不可能是 4,3。"
}
```

###### 异常点 / 修复要求

- 题干首项 `1`、右括号和多个下标被漏识别，`P_1,P_2,P_3,P_4` 被压缩为 `P、P、P、P`。
- 选项 B、D 被截断，`2,1` 识别为 `2、`，`3,4` 识别为 `3,`。
- 单行横排选项需要在 `A./B./C./D.` 之间重新切分，并保留逗号后的数字。
- 客观题应补回图片答案/可判定答案 `C`，不能仅给 `missing_answer_for_objective_question`。

###### 来源

"\ocr_test\images\failure\false-cases\ "

###### 导入后进入审核

~~~tex
已知栈的入栈序列是(2,3,4,其出栈序列为P、P、P、P、则P、P不可

A. 2,4 B. 2、C. 4,3 D. 3,
~~~

###### OCR 原文 / 导入原始信息

~~~tex
已知栈的入栈序列是(2,3,4,其出栈序列为P、P、P、P、则P、P不可

A. 2,4 B. 2、C. 4,3 D. 3,
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "已知栈的入栈序列是(2,3,4)，其出栈序列为P、P、P、P、，则P、P不可"
  },
  "parsed_options": {
    "A": "2,4",
    "B": "2、",
    "C": "4,3",
    "D": "3,"
  },
  "parsed_answer": null,
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
    "stem": "已知栈的入栈序列是(2,3,4)，其出栈序列为P、P、P、P、，则P、P不可",
    "options": [
      {
        "key": "A",
        "text": "2,4"
      },
      {
        "key": "B",
        "text": "2、"
      },
      {
        "key": "C",
        "text": "4,3"
      },
      {
        "key": "D",
        "text": "3,"
      }
    ],
    "frozen_options_restored": false,
    "options_preserved": true,
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "已知栈的入栈序列是(2,3,4,其出栈序列为P、P、P、P、则P、P不可\n\nA. 2,4 B. 2、C. 4,3 D. 3,",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "false_3.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "4f6ce390",
    "confidence_score": 0.5,
    "risk_flags": [
      "fallback_low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;options_structured;type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "4f6ce390",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;options_structured;type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [],
    "risk_flags": [
      "fallback_low_confidence"
    ]
  }
}

```

##### 案例二 ✅ 已修复

修复：`question_normalizer.py` `_extract_stem()` 添加 inline option stripping + `ai_repair.py` 下标安全门禁 + 选项边界检测增强

回归测试：`test_bugs_stack_and_code_cases::TestCase2_False4_StemOptionAdhesion`

###### 原题

```tex
21. 若栈的输入序列是 $P_1,P_2,\cdots,P_n$，输出序列是 $1,2,3,\cdots,n$，若 $P_3=3$，则 $P_1$ 的值（ ）。

A. 可能是 2
B. 不可能是 1
C. 一定是 1
D. 一定是 2

答案：A
```

###### 图片核对后的期望解析数据

```json
{
  "parsed_content": {
    "text": "若栈的输入序列是 $P_1,P_2,\cdots,P_n$，输出序列是 $1,2,3,\cdots,n$，若 $P_3=3$，则 $P_1$ 的值（ ）。"
  },
  "parsed_options": {
    "A": "可能是 2",
    "B": "不可能是 1",
    "C": "一定是 1",
    "D": "一定是 2"
  },
  "parsed_answer": "A",
  "parsed_analysis": "当 $P_3=3$ 且输出为 $1,2,3,\cdots,n$ 时，$P_1$ 可以取 2，例如输入序列 $2,1,3,\cdots,n$ 可通过栈得到递增输出；因此选 A。"
}
```

###### 异常点 / 修复要求

- 图片中的条件是 `$P_3=3$`，不是 `$P_i=3$`。
- 题问 `$P_1$ 的值` 在 OCR/AI 修复中整体丢失，导致题干残缺。
- 选项 B 的 `1` 被误识别为 `(`，选项 D 的 `是2` 被截断。
- 题干与横排选项粘连时，应以 `A.` 作为选项起点回切题干，并继续抽取 B/C/D 的完整文本。

###### 来源

###### "\ocr_test\images\failure\false-cases\ "

###### 导入后进入审核

~~~tex
若栈的输入序列是 $ P_{1}, P_{2}, \cdots, P_{n} $，输出序列是 $ 1, 2, 3, \cdots, n $，若 $ P_{i}=3 $，则A. 可能是2 B. 不可能是( C. 一定是1 D. 一定
~~~

###### OCR 原文 / 导入原始信息

~~~tex
若栈的输入序列是 $ P_{1}, P_{2}, \cdots, P_{n} $，输出序列是 $ 1, 2, 3, \cdots, n $，若 $ P_{i}=3 $，则A. 可能是2 B. 不可能是( C. 一定是1 D. 一定
~~~

###### 解析数据（第一次修复结果）

```json
{
  "parsed_content": {
    "text": "若栈的输入序列是 $ P_{1}, P_{2}, \\cdots, P_{n} $，输出序列是 $ 1, 2, 3, \\cdots, n $，若 $ P_{i}=3 $，则"
  },
  "parsed_options": {
    "A": "可能是2",
    "B": "不可能是(",
    "C": "一定是1",
    "D": "一定"
  },
  "parsed_answer": null,
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
    "stem": "若栈的输入序列是 $ P_{1}, P_{2}, \\cdots, P_{n} $，输出序列是 $ 1, 2, 3, \\cdots, n $，若 $ P_{i}=3 $，则",
    "options": [
      {
        "key": "A",
        "text": "可能是2"
      },
      {
        "key": "B",
        "text": "不可能是("
      },
      {
        "key": "C",
        "text": "一定是1"
      },
      {
        "key": "D",
        "text": "一定"
      }
    ],
    "frozen_options_restored": false,
    "options_preserved": true,
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "若栈的输入序列是 $ P_{1}, P_{2}, \\cdots, P_{n} $，输出序列是 $ 1, 2, 3, \\cdots, n $，若 $ P_{i}=3 $，则A. 可能是2 B. 不可能是( C. 一定是1 D. 一定",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "false_4.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "94669c71",
    "confidence_score": 0.7,
    "risk_flags": [
      "fallback_low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;options_structured;type_detected;missing_answer"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "94669c71",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;options_structured;type_detected;missing_answer"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [],
    "risk_flags": [
      "fallback_low_confidence"
    ]
  }
}

```

##### 案例三 ✅ 已修复

修复：`ai_repair.py` 新增 `_detect_subscript_changes()` 安全门禁，拦截无证据的下标改写

回归测试：`test_bugs_stack_and_code_cases::TestCase3_False5_SubscriptSafety + TestSubscriptSafetyGate`

###### 原题

```tex
20. 若栈的输入序列是 $P_1,P_2,\cdots,P_n$，输出序列是 $1,2,3,\cdots,n$，若 $P_3=1$，则 $P_1$ 的值（ ）。

A. 可能是 2
B. 一定是 2
C. 不可能是 2
D. 不可能是 3

答案：C
```

###### 图片核对后的期望解析数据

```json
{
  "parsed_content": {
    "text": "若栈的输入序列是 $P_1,P_2,\cdots,P_n$，输出序列是 $1,2,3,\cdots,n$，若 $P_3=1$，则 $P_1$ 的值（ ）。"
  },
  "parsed_options": {
    "A": "可能是 2",
    "B": "一定是 2",
    "C": "不可能是 2",
    "D": "不可能是 3"
  },
  "parsed_answer": "C",
  "parsed_analysis": "若第三个入栈元素为 1，则 1 出栈后，栈顶必须能继续输出 2，因此前两个入栈元素中 $P_2$ 必须为 2，$P_1$ 不可能为 2。"
}
```

###### 异常点 / 修复要求

- OCR 将 `$P_1,P_2,\cdots,P_n$` 破坏为 `P,P^{2},",Pn`，将 `$P_3=1$` 误作 `Ps=1`。
- 当前修复已能重建大部分题干与选项，但仍缺少客观题答案。
- 该类栈题应保留下标数字，尤其是 `$P_1$、$P_2$、$P_3$` 的角色不能互换。

###### 来源

"\ocr_test\images\failure\false-cases\ "

###### 导入后进入审核（选项被识别入题干区域，且题干代码内容不完整）

~~~tex
20.若栈的输入序列是P,P^{2},",Pn,输出序列是1,2,3,"",n,若Ps=1,则 P的值()。
A.可能是 2
B.一定是 2
C.不可能是 2
D.不可能是 3
~~~

###### OCR 原文 / 导入原始信息

~~~tex
20.若栈的输入序列是P,P^{2},",Pn,输出序列是1,2,3,"",n,若Ps=1,则 P的值()。
A.可能是 2
B.一定是 2
C.不可能是 2
D.不可能是 3
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "若栈的输入序列是 $P_1, P_2, \\ldots, P_n$，输出序列是 $1,2,3,\\ldots,n$，若 $P_1=1$，则 $P_2$ 的值( )。"
  },
  "parsed_options": {
    "A": "可能是 2",
    "B": "一定是 2",
    "C": "不可能是 2",
    "D": "不可能是 3"
  },
  "parsed_answer": null,
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
    "stem": "若栈的输入序列是 $P_1, P_2, \\ldots, P_n$，输出序列是 $1,2,3,\\ldots,n$，若 $P_1=1$，则 $P_2$ 的值( )。",
    "options": [
      {
        "key": "A",
        "text": "可能是 2"
      },
      {
        "key": "B",
        "text": "一定是 2"
      },
      {
        "key": "C",
        "text": "不可能是 2"
      },
      {
        "key": "D",
        "text": "不可能是 3"
      }
    ],
    "frozen_options_restored": true,
    "options_preserved": false,
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "20.若栈的输入序列是P,P^{2},\",Pn,输出序列是1,2,3,\"\",n,若Ps=1,则 P的值()。\nA.可能是 2\nB.一定是 2\nC.不可能是 2\nD.不可能是 3",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "false_5.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "21ccfd8f",
    "confidence_score": 0.8,
    "risk_flags": [],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;options_structured;type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "21ccfd8f",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;options_structured;type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [],
    "risk_flags": null
  }
}

```

##### 案例四 ✅ 已修复

修复：`question_splitter.py` 新增 `_quarantine_code_regions()` 代码隔离 + `_reconstruct_code_lines()` 断裂代码行合并 + `_is_code_line()` 避免代码被当选项

回归测试：`test_bugs_stack_and_code_cases::TestCase4_False1_CodeNotOptions`

###### 原题

```tex
12. 经过以下栈的操作后，变量 $x$ 的值为（ ）。

InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);

A. a
B. b
C. NULL
D. false

答案：A
```

###### 图片核对后的期望解析数据

```json
{
  "parsed_content": {
    "text": "经过以下栈的操作后，变量 x 的值为（ ）。\nInitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);"
  },
  "parsed_options": {
    "A": "a",
    "B": "b",
    "C": "NULL",
    "D": "false"
  },
  "parsed_answer": "A",
  "parsed_analysis": "先入栈 a，再入栈 b；Pop(st, x) 后 x=b 且 b 出栈；GetTop(st, x) 读取当前栈顶 a 并赋给 x，所以最终 x=a。"
}
```

###### 异常点 / 修复要求

- 代码中的参数 `a`、`b` 被误切成选项，导致题干只剩 `InitStack(st); Push(st,`。
- OCR 原文中选项顺序为 `D/C/B/A`，需要按选项键恢复为 `A/B/C/D`，而不是按出现顺序污染题干。
- 对包含 `InitStack/Push/Pop/GetTop`、分号、括号的片段应触发代码完整性保护：从首个函数调用连续保留到最后一个分号。
- `GetTop(st, x)` 会覆盖 `Pop(st, x)` 后的 x 值，答案应为 `A`。

###### 来源

"\ocr_test\images\failure\false-cases\ "

###### 导入后进入审核（题干代码内容不完整）

~~~tex
12.经过以下栈的操作后，变量x的值为( )。
InitStack(st); Push(st,
a); Push(st,
b); Pop(st, x); GetTop(st, x) ;
D.false
C.NULL
B.b
A.a
~~~

###### OCR 原文 / 导入原始信息

~~~tex
12.经过以下栈的操作后，变量x的值为( )。
InitStack(st); Push(st,
a); Push(st,
b); Pop(st, x); GetTop(st, x) ;
D.false
C.NULL
B.b
A.a
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,"
  },
  "parsed_options": {
    "A": "; Push(st,",
    "B": "; Pop(st, x); GetTop(st, x) ;",
    "C": "NULL",
    "D": "false"
  },
  "parsed_answer": null,
  "parsed_analysis": null
}
```

###### OCR / AI 原始数据

```json
{
  "raw_data": {
    "stem": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
    "code_blocks": [],
    "options": [
      {
        "key": "A",
        "text": "; Push(st,"
      },
      {
        "key": "B",
        "text": "; Pop(st, x); GetTop(st, x) ;"
      },
      {
        "key": "C",
        "text": "NULL"
      },
      {
        "key": "D",
        "text": "false"
      }
    ],
    "answer": "",
    "analysis": "",
    "subject": "",
    "question_type": "single_choice",
    "raw_text": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "false_1.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": false,
    "errors": [
      "missing_answer"
    ],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:watermark_noise_detected",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "871d8b6e",
    "confidence_score": 0.7,
    "validation_status": "passed",
    "failure_reason": [
      "missing_answer_for_objective_question"
    ],
    "retry_recommended": false,
    "ocr_quality_flags": [
      "code_line_break_suspicious",
      "watermark_noise_detected"
    ],
    "risk_flags": [],
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.55 flags=['code_line_break_suspicious', 'watermark_noise_detected']"
      },
      {
        "stage": "validation",
        "result": "pass",
        "reason": "missing_answer_for_objective_question"
      },
      {
        "stage": "ai_repair",
        "result": "rejected",
        "reason": "options_modified_by_ai"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [
      {
        "stage": "ocr_raw_input",
        "strategy": "passthrough",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "status": "observed",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "raw_text length=115"
      },
      {
        "stage": "ocr_quality_gate",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}",
        "status": "success",
        "duration_ms": 0.65,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "12.经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x) ; D.false C.NULL B.b A.a",
              "after": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "stem_extraction",
        "strategy": "observation",
        "input_source": "raw_ocr",
        "parent_stage": "ocr_quality_gate",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "stem length=44"
      },
      {
        "stage": "noise_filtering",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "stem_extraction",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "status": "success",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": "stem_extraction",
        "input_preview": "{'A': '; Push(st,', 'B': '; Pop(st, x); GetTop(st, x) ;', 'D': 'false', 'C': 'NULL'}",
        "output_preview": "[{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]",
        "status": "success",
        "duration_ms": 0.07,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "{'A':",
              "after": "[{'key': 'A', 'text':"
            },
            {
              "before": "Push(st,', 'B':",
              "after": "Push(st,'}, {'key': 'B', 'text':"
            },
            {
              "before": ";', 'D': 'false', 'C': 'NULL'}",
              "after": ";'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "options_trace",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "options_found_in": "classifier_gate",
        "options_origin": "classifier_gate",
        "options_confidence": 1,
        "options_failure_reason": null,
        "note": "option_count=4"
      },
      {
        "stage": "question_type_detection",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "options_extraction",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "type=single_choice"
      },
      {
        "stage": "consistency_check",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "question_type_detection",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "consistent=True"
      },
      {
        "stage": "code_detection",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "noise_filtering",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "False",
        "status": "success",
        "duration_ms": 0.13,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st,",
              "after": "False"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "vision_fallback",
        "strategy": "observation",
        "input_source": "fallback",
        "parent_stage": "code_integrity_check",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "attempted=None status=None"
      },
      {
        "stage": "output_normalization",
        "strategy": "pipeline",
        "input_source": "final",
        "parent_stage": "vision_fallback",
        "input_preview": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'options': [{'key': 'A', 'text': '; Push(st,'}, {...[+6011]",
        "output_preview": "{'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'code_blocks': [], 'options': [{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text':...[+6010]",
        "status": "success",
        "duration_ms": 0.78,
        "delta": {
          "added_tokens": [
            "'code_blocks':",
            "[],",
            "'subject':",
            "'',",
            "'question_type':",
            "'single_choice',"
          ],
          "removed_tokens": [
            "'is_frozen':",
            "True,",
            "'options_classified':",
            "'options_classify_reason':",
            "'frozen_options_present',"
          ],
          "modified_regions": [
            {
              "before": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem':",
              "after": "{'stem':"
            },
            {
              "before": "status=None'}]}",
              "after": "status=None'}], 'is_frozen': True, 'options_classified': True, 'options_classify_reason': 'frozen_options_present', 'schema_version': 'v1'}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      }
    ],
    "is_frozen": true,
    "options_classified": true,
    "options_classify_reason": "frozen_options_present",
    "schema_version": "v1",
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": false,
    "errors": [
      "missing_answer"
    ],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:watermark_noise_detected",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "871d8b6e",
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.55 flags=['code_line_break_suspicious', 'watermark_noise_detected']"
      },
      {
        "stage": "validation",
        "result": "pass",
        "reason": "missing_answer_for_objective_question"
      },
      {
        "stage": "ai_repair",
        "result": "rejected",
        "reason": "options_modified_by_ai"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [
      {
        "stage": "ocr_raw_input",
        "strategy": "passthrough",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "status": "observed",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "raw_text length=115"
      },
      {
        "stage": "ocr_quality_gate",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}",
        "status": "success",
        "duration_ms": 0.65,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "12.经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x) ; D.false C.NULL B.b A.a",
              "after": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "stem_extraction",
        "strategy": "observation",
        "input_source": "raw_ocr",
        "parent_stage": "ocr_quality_gate",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "stem length=44"
      },
      {
        "stage": "noise_filtering",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "stem_extraction",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "status": "success",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": "stem_extraction",
        "input_preview": "{'A': '; Push(st,', 'B': '; Pop(st, x); GetTop(st, x) ;', 'D': 'false', 'C': 'NULL'}",
        "output_preview": "[{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]",
        "status": "success",
        "duration_ms": 0.07,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "{'A':",
              "after": "[{'key': 'A', 'text':"
            },
            {
              "before": "Push(st,', 'B':",
              "after": "Push(st,'}, {'key': 'B', 'text':"
            },
            {
              "before": ";', 'D': 'false', 'C': 'NULL'}",
              "after": ";'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "options_trace",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "options_found_in": "classifier_gate",
        "options_origin": "classifier_gate",
        "options_confidence": 1,
        "options_failure_reason": null,
        "note": "option_count=4"
      },
      {
        "stage": "question_type_detection",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "options_extraction",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "type=single_choice"
      },
      {
        "stage": "consistency_check",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "question_type_detection",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "consistent=True"
      },
      {
        "stage": "code_detection",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "noise_filtering",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "False",
        "status": "success",
        "duration_ms": 0.13,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st,",
              "after": "False"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "vision_fallback",
        "strategy": "observation",
        "input_source": "fallback",
        "parent_stage": "code_integrity_check",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "attempted=None status=None"
      },
      {
        "stage": "output_normalization",
        "strategy": "pipeline",
        "input_source": "final",
        "parent_stage": "vision_fallback",
        "input_preview": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'options': [{'key': 'A', 'text': '; Push(st,'}, {...[+6011]",
        "output_preview": "{'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'code_blocks': [], 'options': [{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text':...[+6010]",
        "status": "success",
        "duration_ms": 0.78,
        "delta": {
          "added_tokens": [
            "'code_blocks':",
            "[],",
            "'subject':",
            "'',",
            "'question_type':",
            "'single_choice',"
          ],
          "removed_tokens": [
            "'is_frozen':",
            "True,",
            "'options_classified':",
            "'options_classify_reason':",
            "'frozen_options_present',"
          ],
          "modified_regions": [
            {
              "before": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem':",
              "after": "{'stem':"
            },
            {
              "before": "status=None'}]}",
              "after": "status=None'}], 'is_frozen': True, 'options_classified': True, 'options_classify_reason': 'frozen_options_present', 'schema_version': 'v1'}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      }
    ],
    "risk_flags": null
  }
}

```

##### 案例五 ✅ 已修复

修复：`question_splitter.py` frozen option stem stripping + `answer_matcher.py` 显式答案提取 + `code_integrity.py` 乱码检测

回归测试：`test_bugs_stack_and_code_cases::TestCase5_CodeTest2_StructAndTraversal` + `test_logs_ocr_code_test_2.py`

###### 原题

```tex
12. 经过以下栈的操作后，变量 $x$ 的值为（ ）。

InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);

A. a
B. b
C. NULL
D. false

答案：A
```

###### 图片核对后的期望解析数据

```json
{
  "parsed_content": {
    "text": "经过以下栈的操作后，变量 x 的值为（ ）。\nInitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);"
  },
  "parsed_options": {
    "A": "a",
    "B": "b",
    "C": "NULL",
    "D": "false"
  },
  "parsed_answer": "A",
  "parsed_analysis": "本案例与案例四同图同题，可作为重复回归样例。最终执行 GetTop(st, x) 后，x 被更新为当前栈顶 a。"
}
```

###### 异常点 / 修复要求

- 本案例与案例四重复，均用于验证“代码行被拆断 + 选项倒序 + 参数被误判为选项”的修复是否稳定。
- 修复后不应出现选项 `A: ; Push(st,`、`B: ; Pop(st, x); GetTop(st, x);` 这类代码污染选项。

###### 来源

"\ocr_test\images\failure\false-cases\ "

###### 导入后进入审核

~~~tex
12.经过以下栈的操作后，变量x的值为( )。
InitStack(st); Push(st,
a); Push(st,
b); Pop(st, x); GetTop(st, x) ;
D.false
C.NULL
B.b
A.a
~~~

###### OCR 原文 / 导入原始信息

~~~tex
12.经过以下栈的操作后，变量x的值为( )。
InitStack(st); Push(st,
a); Push(st,
b); Pop(st, x); GetTop(st, x) ;
D.false
C.NULL
B.b
A.a
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,"
  },
  "parsed_options": {
    "A": "; Push(st,",
    "B": "; Pop(st, x); GetTop(st, x) ;",
    "C": "NULL",
    "D": "false"
  },
  "parsed_answer": null,
  "parsed_analysis": null
}
```

###### OCR / AI 原始数据

```json
{
  "raw_data": {
    "stem": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
    "code_blocks": [],
    "options": [
      {
        "key": "A",
        "text": "; Push(st,"
      },
      {
        "key": "B",
        "text": "; Pop(st, x); GetTop(st, x) ;"
      },
      {
        "key": "C",
        "text": "NULL"
      },
      {
        "key": "D",
        "text": "false"
      }
    ],
    "answer": "",
    "analysis": "",
    "subject": "",
    "question_type": "single_choice",
    "raw_text": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "false_1.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": false,
    "errors": [
      "missing_answer"
    ],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:watermark_noise_detected",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "871d8b6e",
    "confidence_score": 0.7,
    "validation_status": "passed",
    "failure_reason": [
      "missing_answer_for_objective_question"
    ],
    "retry_recommended": false,
    "ocr_quality_flags": [
      "code_line_break_suspicious",
      "watermark_noise_detected"
    ],
    "risk_flags": [],
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.55 flags=['code_line_break_suspicious', 'watermark_noise_detected']"
      },
      {
        "stage": "validation",
        "result": "pass",
        "reason": "missing_answer_for_objective_question"
      },
      {
        "stage": "ai_repair",
        "result": "rejected",
        "reason": "options_modified_by_ai"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [
      {
        "stage": "ocr_raw_input",
        "strategy": "passthrough",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "status": "observed",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "raw_text length=115"
      },
      {
        "stage": "ocr_quality_gate",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}",
        "status": "success",
        "duration_ms": 0.65,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "12.经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x) ; D.false C.NULL B.b A.a",
              "after": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "stem_extraction",
        "strategy": "observation",
        "input_source": "raw_ocr",
        "parent_stage": "ocr_quality_gate",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "stem length=44"
      },
      {
        "stage": "noise_filtering",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "stem_extraction",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "status": "success",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": "stem_extraction",
        "input_preview": "{'A': '; Push(st,', 'B': '; Pop(st, x); GetTop(st, x) ;', 'D': 'false', 'C': 'NULL'}",
        "output_preview": "[{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]",
        "status": "success",
        "duration_ms": 0.07,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "{'A':",
              "after": "[{'key': 'A', 'text':"
            },
            {
              "before": "Push(st,', 'B':",
              "after": "Push(st,'}, {'key': 'B', 'text':"
            },
            {
              "before": ";', 'D': 'false', 'C': 'NULL'}",
              "after": ";'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "options_trace",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "options_found_in": "classifier_gate",
        "options_origin": "classifier_gate",
        "options_confidence": 1,
        "options_failure_reason": null,
        "note": "option_count=4"
      },
      {
        "stage": "question_type_detection",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "options_extraction",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "type=single_choice"
      },
      {
        "stage": "consistency_check",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "question_type_detection",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "consistent=True"
      },
      {
        "stage": "code_detection",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "noise_filtering",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "False",
        "status": "success",
        "duration_ms": 0.13,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st,",
              "after": "False"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "vision_fallback",
        "strategy": "observation",
        "input_source": "fallback",
        "parent_stage": "code_integrity_check",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "attempted=None status=None"
      },
      {
        "stage": "output_normalization",
        "strategy": "pipeline",
        "input_source": "final",
        "parent_stage": "vision_fallback",
        "input_preview": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'options': [{'key': 'A', 'text': '; Push(st,'}, {...[+6011]",
        "output_preview": "{'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'code_blocks': [], 'options': [{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text':...[+6010]",
        "status": "success",
        "duration_ms": 0.78,
        "delta": {
          "added_tokens": [
            "'code_blocks':",
            "[],",
            "'subject':",
            "'',",
            "'question_type':",
            "'single_choice',"
          ],
          "removed_tokens": [
            "'is_frozen':",
            "True,",
            "'options_classified':",
            "'options_classify_reason':",
            "'frozen_options_present',"
          ],
          "modified_regions": [
            {
              "before": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem':",
              "after": "{'stem':"
            },
            {
              "before": "status=None'}]}",
              "after": "status=None'}], 'is_frozen': True, 'options_classified': True, 'options_classify_reason': 'frozen_options_present', 'schema_version': 'v1'}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      }
    ],
    "is_frozen": true,
    "options_classified": true,
    "options_classify_reason": "frozen_options_present",
    "schema_version": "v1",
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": false,
    "errors": [
      "missing_answer"
    ],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:watermark_noise_detected",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "871d8b6e",
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.55 flags=['code_line_break_suspicious', 'watermark_noise_detected']"
      },
      {
        "stage": "validation",
        "result": "pass",
        "reason": "missing_answer_for_objective_question"
      },
      {
        "stage": "ai_repair",
        "result": "rejected",
        "reason": "options_modified_by_ai"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [
      {
        "stage": "ocr_raw_input",
        "strategy": "passthrough",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "status": "observed",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "raw_text length=115"
      },
      {
        "stage": "ocr_quality_gate",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "12.经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,\na); Push(st,\nb); Pop(st, x); GetTop(st, x) ;\nD.false\nC.NULL\nB.b\nA.a",
        "output_preview": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}",
        "status": "success",
        "duration_ms": 0.65,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "12.经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x) ; D.false C.NULL B.b A.a",
              "after": "{'passed': False, 'ocr_quality_flags': ['code_line_break_suspicious', 'watermark_noise_detected'], 'ocr_contamination_score': 0.55}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "stem_extraction",
        "strategy": "observation",
        "input_source": "raw_ocr",
        "parent_stage": "ocr_quality_gate",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "stem length=44"
      },
      {
        "stage": "noise_filtering",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "stem_extraction",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "status": "success",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": "stem_extraction",
        "input_preview": "{'A': '; Push(st,', 'B': '; Pop(st, x); GetTop(st, x) ;', 'D': 'false', 'C': 'NULL'}",
        "output_preview": "[{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]",
        "status": "success",
        "duration_ms": 0.07,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "{'A':",
              "after": "[{'key': 'A', 'text':"
            },
            {
              "before": "Push(st,', 'B':",
              "after": "Push(st,'}, {'key': 'B', 'text':"
            },
            {
              "before": ";', 'D': 'false', 'C': 'NULL'}",
              "after": ";'}, {'key': 'C', 'text': 'NULL'}, {'key': 'D', 'text': 'false'}]"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "options_extraction",
        "strategy": "options_trace",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "options_found_in": "classifier_gate",
        "options_origin": "classifier_gate",
        "options_confidence": 1,
        "options_failure_reason": null,
        "note": "option_count=4"
      },
      {
        "stage": "question_type_detection",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "options_extraction",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "type=single_choice"
      },
      {
        "stage": "consistency_check",
        "strategy": "observation",
        "input_source": "intermediate",
        "parent_stage": "question_type_detection",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "consistent=True"
      },
      {
        "stage": "code_detection",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "noise_filtering",
        "input_preview": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
        "output_preview": "False",
        "status": "success",
        "duration_ms": 0.13,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "经过以下栈的操作后，变量x的值为( )。 InitStack(st); Push(st,",
              "after": "False"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "vision_fallback",
        "strategy": "observation",
        "input_source": "fallback",
        "parent_stage": "code_integrity_check",
        "input_preview": "",
        "output_preview": "",
        "status": "info",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "attempted=None status=None"
      },
      {
        "stage": "output_normalization",
        "strategy": "pipeline",
        "input_source": "final",
        "parent_stage": "vision_fallback",
        "input_preview": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'options': [{'key': 'A', 'text': '; Push(st,'}, {...[+6011]",
        "output_preview": "{'stem': '经过以下栈的操作后，变量x的值为( )。\\nInitStack(st); Push(st,', 'code_blocks': [], 'options': [{'key': 'A', 'text': '; Push(st,'}, {'key': 'B', 'text': '; Pop(st, x); GetTop(st, x) ;'}, {'key': 'C', 'text':...[+6010]",
        "status": "success",
        "duration_ms": 0.78,
        "delta": {
          "added_tokens": [
            "'code_blocks':",
            "[],",
            "'subject':",
            "'',",
            "'question_type':",
            "'single_choice',"
          ],
          "removed_tokens": [
            "'is_frozen':",
            "True,",
            "'options_classified':",
            "'options_classify_reason':",
            "'frozen_options_present',"
          ],
          "modified_regions": [
            {
              "before": "{'schema_version': 'v1', 'subject_id': None, 'subject': '', 'question_type': 'single_choice', 'stem':",
              "after": "{'stem':"
            },
            {
              "before": "status=None'}]}",
              "after": "status=None'}], 'is_frozen': True, 'options_classified': True, 'options_classify_reason': 'frozen_options_present', 'schema_version': 'v1'}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      }
    ],
    "risk_flags": null
  }
}

```



##### 案例六（新增：结构体代码块 + 二叉树遍历题）✅ 已修复

修复：`question_splitter.py` frozen option stem stripping + `code_integrity.py` 乱码检测 + `answer_matcher.py` 显式答案提取 + `question_normalizer.py` quality_status 单调性

回归测试：`test_logs_ocr_code_test_2.py`（10 个测试）+ `TestCase5_*`

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

答案：A
```

###### 来源

`ocr_code_test_2.png`

###### 图片核对后的期望解析数据

```json
{
  "parsed_content": {
    "text": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：",
    "code_blocks": [
      "typedef struct BiTNode {\n    char data;\n    struct BiTNode *lchild, *rchild;\n} BiTNode, *BiTree;"
    ]
  },
  "parsed_options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "parsed_answer": "A",
  "parsed_analysis": "后序遍历最后一个结点 A 为根；中序序列 DBEAFC 以 A 分为左子树 DBE、右子树 FC。左子树后序 DEB，根为 B，前序为 BDE；右子树后序 FC，根为 C，前序为 CF。所以整棵树前序为 ABDECF。"
}
```

###### 异常点 / 修复要求

- 题干中包含 C 语言结构体定义，应整体识别为代码块，不能将 `char data`、`lchild/rchild` 或 `BiTree` 拆入题干/选项。
- 遍历序列 `DBEAFC`、`DEBFCA`、选项 `ABDECF/ABDCEF/ABDFEC/ACBEDF` 都是连续大写字母，应按字符串保留，不应自动加空格或拆字。
- 图片底部已有 `答案：A`，应从答案区回填 `parsed_answer`。
- 该样例用于验证“代码块保护 + 非数学连续字母串保护 + 图片答案区提取”。

###### 建议验收用例

```json
{
  "must_keep_code_block": true,
  "must_preserve_sequences": ["DBEAFC", "DEBFCA", "ABDECF", "ABDCEF", "ABDFEC", "ACBEDF"],
  "expected_answer": "A",
  "expected_question_type": "single_choice"
}
```
