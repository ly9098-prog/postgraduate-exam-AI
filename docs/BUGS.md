# 代码题目题干/选项部分缺失（第五次修复）

###### |结果：案例三/四已通过代码结构重建阶段修复

##### 案例一（✅ 已修复 — confidence gate override）

> 修复提交：`0fed945` — PaddleOCR-VL 的 `confidence=0.0` 不再被 gate 丢弃。
> 修复后 VL 结果进入 AI safety gate 正常评估，237 chars（含选项）不再丢失。

###### 原题

```tex
15. 已知顺序栈定义如下：

#define MAXSIZE 100
typedef struct {
    int data[MAXSIZE];
    int top;
} Stack;

执行如下代码：

while (S.top != -1) {
    printf("%d", S.data[S.top]);
    S.top--;
}

该代码实现的功能是：

A. 入栈操作  
B. 出栈并输出栈中元素  
C. 判断栈满  
D. 初始化栈
```

###### 来源

"/ocr_test/images/example/ocr_code_test_10.png"

###### 导入后进入审核（选项缺）

~~~tex
#>
#define MAXSIZE 100
typedef struct {
int data[MAXSIZE];
int top;
} Stack;
执行如下代码：
while (s.top != − 1) {
printf("%d", S.data[S.top]);
S.top −  − ;
}
~~~

###### OCR 原文 / 导入原始信息

~~~tex
#>
#define MAXSIZE 100
typedef struct {
int data[MAXSIZE];
int top;
} Stack;
执行如下代码：
while (s.top != -1) {
printf("%d", S.data[S.top]);
S.top--;
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "#>\n#define MAXSIZE 100\ntypedef struct {\nint data[MAXSIZE];\nint top;\n} Stack;\n执行如下代码：\nwhile (s.top != -1) {\nprintf(\"%d\", S.data[S.top]);\nS.top--;\n}"
  },
  "parsed_options": null,
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
    "question_type": "subjective",
    "stem": "#>\n#define MAXSIZE 100\ntypedef struct {\nint data[MAXSIZE];\nint top;\n} Stack;\n执行如下代码：\nwhile (s.top != -1) {\nprintf(\"%d\", S.data[S.top]);\nS.top--;\n}",
    "options": [],
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "#>\n#define MAXSIZE 100\ntypedef struct {\nint data[MAXSIZE];\nint top;\n} Stack;\n执行如下代码：\nwhile (s.top != -1) {\nprintf(\"%d\", S.data[S.top]);\nS.top--;",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_10.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "ocr_quality:code_line_break_suspicious",
      "code_integrity:code_brace_unbalanced",
      "code_integrity:code_line_break_suspicious",
      "low_confidence"
    ],
    "stem_hash": "ff630def",
    "confidence_score": 0.7,
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "ai_validation": {
      "is_valid": false,
      "issues": [
        "post_repair_code_integrity:code_line_break_suspicious"
      ],
      "severity": "error"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "ocr_quality:code_line_break_suspicious",
      "code_integrity:code_brace_unbalanced",
      "code_integrity:code_line_break_suspicious",
      "low_confidence"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "ff630def",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [],
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ]
  }
}
```

##### 案例二（✅ 已修复 — VL_REBUILD 图片支持）

> 修复提交：`be03159` — VL_REBUILD 不再要求 `source_type == "pdf"`。
> 验证结果：VL 返回 239 chars，`detect_options_from_text=True`，提取到 {A:统计所有节点, B:统计叶子节点数量, C:删除叶子节点, D:层序遍历}。

###### 原题

```tex
19. 下列代码用于统计叶子节点：

void countLeaf(BiTree T) {
    if (T == NULL) return;

    if (T->lchild == NULL && T->rchild == NULL)
        count++;

    countLeaf(T->lchild);
    countLeaf(T->rchild);
}

该代码功能是：

A. 统计所有节点  
B. 统计叶子节点数量  
C. 删除叶子节点  
D. 层序遍历
```

###### 来源

"/ocr_test/images/example/ocr_code_test_9.png"

###### 导入后进入审核

第一次修复结果：缩进、行间空格被破坏

~~~tex
```text
void countLeaf(BiTree T) {
if (T = = NULL) return;
if (T − >lchild = = NULL && T − >rchild = = NULL)
    count + +;
countLeaf(T − >lchild);
countLeaf(T − >rchild);
```

选项缺失
~~~

###### OCR 原文 / 导入原始信息

~~~tex
```text
void countLeaf(BiTree T) {
if (T == NULL) return;
if (T->lchild == NULL && T->rchild == NULL)
count++;
countLeaf(T->lchild);
countLeaf(T->rchild);
```
~~~

###### 解析数据（第一次修复结果）

```json
{
  "parsed_content": {
    "text": "```text\nvoid countLeaf(BiTree T) {\nif (T == NULL) return;\nif (T->lchild == NULL && T->rchild == NULL)\n    count++;\ncountLeaf(T->lchild);\ncountLeaf(T->rchild);\n```"
  },
  "parsed_options": null,
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
    "question_type": "subjective",
    "stem": "```text\nvoid countLeaf(BiTree T) {\nif (T == NULL) return;\nif (T->lchild == NULL && T->rchild == NULL)\n    count++;\ncountLeaf(T->lchild);\ncountLeaf(T->rchild);\n```",
    "options": [],
    "frozen_options_restored": false,
    "options_preserved": false,
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "```text\nvoid countLeaf(BiTree T) {\nif (T == NULL) return;\nif (T->lchild == NULL && T->rchild == NULL)\ncount++;\ncountLeaf(T->lchild);\ncountLeaf(T->rchild);\n```",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_9.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:code_block_incomplete",
      "ocr_quality:watermark_noise_detected",
      "code_integrity:code_brace_unbalanced",
      "code_integrity:code_line_break_suspicious",
      "code_integrity:code_block_incomplete",
      "low_confidence"
    ],
    "stem_hash": "e3bcd348",
    "confidence_score": 0.99,
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "ai_validation": {
      "is_valid": false,
      "issues": [
        "post_repair_code_integrity:code_brace_unbalanced",
        "post_repair_code_integrity:code_line_break_suspicious",
        "post_repair_code_integrity:code_block_incomplete"
      ],
      "severity": "error"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:code_block_incomplete",
      "ocr_quality:watermark_noise_detected",
      "code_integrity:code_brace_unbalanced",
      "code_integrity:code_line_break_suspicious",
      "code_integrity:code_block_incomplete",
      "low_confidence"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "e3bcd348",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "type_detected"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "trace": [],
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ]
  }
}
```

##### 案例三（✅ 已修复 — code structure reconstruction）

> 修复提交：`e91a020` — 新增代码结构重建管道阶段（code_structure_reconstruct）。
> LLM 专用 prompt 允许修复 `{}` 花括号闭合、断行拼接、OCR 符号错误（`= =`→`==`、`- >`→`->`），
> 在 AI repair 之前修复代码完整性，解决 AI repair prompt 规则 10 "不得修改 {}" 导致的 brace 无法修复问题。

###### 原题

```tex
18. 在单链表中执行：

LNode *p = L;
while (p != NULL && p->next != NULL) {
    p = p->next;
}

该代码的作用是：

A. 找到头结点  
B. 找到尾结点  
C. 删除所有节点  
D. 逆置链表
```

###### 来源

"/ocr_test/images/example/ocr_code_test_8.png"

###### 导入后进入审核（选项被识别入题干区域，且题干代码内容不完整）

~~~tex
18。在单链表中执行:
(>C
LNode * p = L;
while (p != NULL && p − >next != NULL) {
p = p − >next;
该代码的作用是：
A.找到头结点
B.找到尾结点
C.删除所有节点
D.逆置链表

A.找到头结点
B.找到尾结点
C.删除所有节点
D.逆置链表
~~~

###### OCR 原文 / 导入原始信息

~~~tex
18。在单链表中执行:
(>C
LNode *p = L;
while (p != NULL && p->next != NULL) {
p = p->next;
该代码的作用是：
A.找到头结点
B.找到尾结点
C.删除所有节点
D.逆置链表
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表"
  },
  "parsed_options": {
    "A": "找到头结点",
    "B": "找到尾结点",
    "C": "删除所有节点",
    "D": "逆置链表"
  },
  "parsed_answer": null,
  "parsed_analysis": null
}
```

###### OCR / AI 原始数据

```json
{
  "raw_data": {
    "stem": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
    "code_blocks": [],
    "options": [
      {
        "key": "A",
        "text": "找到头结点"
      },
      {
        "key": "B",
        "text": "找到尾结点"
      },
      {
        "key": "C",
        "text": "删除所有节点"
      },
      {
        "key": "D",
        "text": "逆置链表"
      }
    ],
    "answer": "",
    "analysis": "",
    "subject": "",
    "question_type": "single_choice",
    "raw_text": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_8.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": false,
    "errors": [
      "missing_answer"
    ],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "code_integrity:code_brace_unbalanced",
      "low_confidence",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "0cbddc8d",
    "confidence_score": 0.35,
    "validation_status": "failed",
    "failure_reason": [
      "missing_answer_for_objective_question",
      "code_brace_unbalanced"
    ],
    "retry_recommended": true,
    "ocr_quality_flags": [
      "code_brace_unbalanced"
    ],
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_block_incomplete",
      "low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.35 flags=['code_brace_unbalanced']"
      },
      {
        "stage": "code_gate",
        "result": "blocked",
        "reason": "code_brace_unbalanced;code_block_incomplete"
      },
      {
        "stage": "validation",
        "result": "failed",
        "reason": "missing_answer_for_objective_question;code_brace_unbalanced"
      },
      {
        "stage": "ai_safety",
        "result": "blocked",
        "reason": "safety_rejected: options_dropped(4→0)"
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
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "status": "observed",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "raw_text length=122"
      },
      {
        "stage": "ocr_quality_gate",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}",
        "status": "success",
        "duration_ms": 0.41,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表",
              "after": "{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}"
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
        "notes": "stem length=122"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "c_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'C' token at pos 14"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "a_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'A' token at pos 91"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "b_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'B' token at pos 99"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "c_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [
          "stem_extraction"
        ],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'C' token at pos 107"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "d_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'D' token at pos 116"
      },
      {
        "stage": "noise_filtering",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "stem_extraction",
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "status": "success",
        "duration_ms": 0.01,
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
        "options_found_in": "fallback_from_raw_text",
        "options_origin": "fallback_from_raw_text",
        "options_confidence": 0.8,
        "options_failure_reason": null,
        "note": "option_count=4"
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
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "True",
        "status": "success",
        "duration_ms": 0.04,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表",
              "after": "True"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "code_integrity_check",
        "strategy": "observation",
        "input_source": "stem",
        "parent_stage": "code_detection",
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
        "notes": "flags=['code_brace_unbalanced'] score=0.35"
      },
      {
        "stage": "code_integrity_check",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "code_brace_unbalanced",
        "origin_stage": "code_integrity_check",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Code integrity issue: code_brace_unbalanced"
      },
      {
        "stage": "code_regression_check",
        "strategy": "observation",
        "input_source": "intermediate",
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
        "notes": "has_regression=False flags=[]"
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
        "notes": "attempted=True status=unavailable"
      },
      {
        "stage": "output_normalization",
        "strategy": "pipeline",
        "input_source": "final",
        "parent_stage": "vision_fallback",
        "input_preview": "{'schema_version': 'v1', 'subject': '', 'question_type': 'single_choice', 'stem': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC....[+10147]",
        "output_preview": "{'stem': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'code_blocks': [], 'options': [{'key': 'A', 'text': '找到头...[+10166]",
        "status": "success",
        "duration_ms": 1.45,
        "delta": {
          "added_tokens": [
            "'code_blocks':",
            "[],",
            "'subject':",
            "'',",
            "'question_type':",
            "'single_choice',",
            "'decision_trace':",
            "[{'stage':",
            "'ocr_quality_gate',",
            "'result':",
            "'blocked',",
            "'reason':",
            "\"score=0.35",
            "flags=['code_brace_unbalanced']\"},",
            "{'stage':",
            "'code_gate',",
            "'code_brace_unbalanced;code_block_incomplete'},",
            "'validation',",
            "'failed',",
            "'missing_answer_for_objective_question;code_brace_unbalanced'}],",
            "'trace':",
            "'ocr_raw_input',",
            "'strategy':",
            "'passthrough',",
            "'input_source':",
            "'raw_ocr',",
            "'parent_stage':",
            "None,",
            "'input_preview':",
            "'18。在单链表中执行:\\n(>C\\nLNode",
            "*p",
            "=",
            "L;\\nwhile",
            "(p",
            "!=",
            "NULL",
            "&&",
            "p->next",
            "NULL)",
            "{\\np",
            "p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表',",
            "'output_preview':",
            "'status':",
            "'observed',",
            "'duration_ms':",
            "0,",
            "'delta':",
            "{'added_tokens':",
            "'removed_tokens':",
            "'modified_regions':",
            "'has_changed':",
            "False},",
            "'notes':",
            "'raw_text",
            "length=122'},",
            "'rule',",
            "\"{'passed':",
            "False,",
            "'ocr_quality_flags':",
            "['code_brace_unbalanced'],",
            "'ocr_contamination_score':",
            "0.35}\",",
            "'success',",
            "0.41,",
            "[{'before':",
            "'18。在单链表中执行:",
            "(>C",
            "LNode",
            "L;",
            "while",
            "{",
            "p",
            "p->next;",
            "该代码的作用是：",
            "A.找到头结点",
            "B.找到尾结点",
            "C.删除所有节点",
            "D.逆置链表',",
            "'after':",
            "0.35}\"}],",
            "True},",
            "''},",
            "'stem_extraction',",
            "'observation',",
            "'info',",
            "'stem",
            "'detection',",
            "'intermediate',",
            "'corruption',",
            "'corruption_type':",
            "'c_token_noise',",
            "'origin_stage':",
            "'propagation_path':",
            "'resolved_at':",
            "'resolved_by':",
            "\"Standalone",
            "'C'",
            "token",
            "at",
            "pos",
            "14\"},",
            "'a_token_noise',",
            "'A'",
            "91\"},",
            "'b_token_noise',",
            "'B'",
            "99\"},",
            "['stem_extraction'],",
            "107\"},",
            "'d_token_noise',",
            "'D'",
            "116\"},",
            "'noise_filtering',",
            "'stem',",
            "0.01,",
            "'options_extraction',",
            "'options_trace',",
            "'options_found_in':",
            "'fallback_from_raw_text',",
            "'options_origin':",
            "'options_confidence':",
            "0.8,",
            "'options_failure_reason':",
            "'note':",
            "'option_count=4'},",
            "'classifier_gate',",
            "1.0,",
            "'question_type_detection',",
            "'type=single_choice'},",
            "'consistency_check',",
            "'consistent=True'},",
            "'code_detection',",
            "'True',",
            "0.04,",
            "'True'}],",
            "'code_integrity_check',",
            "\"flags=['code_brace_unbalanced']",
            "score=0.35\"},",
            "'code_brace_unbalanced',",
            "'Code",
            "integrity",
            "issue:",
            "code_brace_unbalanced'},",
            "'code_regression_check',",
            "'has_regression=False",
            "flags=[]'},",
            "'vision_fallback',",
            "'fallback',",
            "'attempted=True",
            "status=unavailable'}],",
            "'is_frozen':",
            "'options_classified':",
            "True,",
            "'options_classify_reason':",
            "'structured_option_patterns_detected',"
          ],
          "removed_tokens": [
            "'is_frozen':",
            "False,",
            "'options_classified':",
            "True,",
            "'options_classify_reason':",
            "'structured_option_patterns_detected',"
          ],
          "modified_regions": [
            {
              "before": "{'schema_version': 'v1', 'subject': '', 'question_type': 'single_choice', 'stem':",
              "after": "{'stem':"
            },
            {
              "before": "'decision_trace': [{'stage': 'ocr_quality_gate', 'result': 'blocked', 'reason': \"score=0.35 flags=['code_brace_unbalanced']\"}, {'stage': 'code_gate', 'result': 'blocked', 'reason': 'code_brace_unbalanced;code_block_incomplete'}, {'stage': 'validation', 'result': 'failed', 'reason': 'missing_answer_for_objective_question;code_brace_unbalanced'}], 'trace': [{'stage': 'ocr_raw_input', 'strategy': 'passthrough', 'input_source': 'raw_ocr', 'parent_stage': None, 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'status': 'observed', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'raw_text length=122'}, {'stage': 'ocr_quality_gate', 'strategy': 'rule', 'input_source': 'raw_ocr', 'parent_stage': None, 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': \"{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}\", 'status': 'success', 'duration_ms': 0.41, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [{'before': '18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表', 'after': \"{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}\"}], 'has_changed': True}, 'notes': ''}, {'stage': 'stem_extraction', 'strategy': 'observation', 'input_source': 'raw_ocr', 'parent_stage': 'ocr_quality_gate', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'stem length=122'}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'c_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'C' token at pos 14\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'a_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'A' token at pos 91\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'b_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'B' token at pos 99\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'c_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': ['stem_extraction'], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'C' token at pos 107\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'd_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'D' token at pos 116\"}, {'stage': 'noise_filtering', 'strategy': 'rule', 'input_source': 'stem', 'parent_stage': 'stem_extraction', 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'status': 'success', 'duration_ms': 0.01, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': ''}, {'stage': 'options_extraction', 'strategy': 'options_trace', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'options_found_in': 'fallback_from_raw_text', 'options_origin': 'fallback_from_raw_text', 'options_confidence': 0.8, 'options_failure_reason': None, 'note': 'option_count=4'}, {'stage': 'options_extraction', 'strategy': 'options_trace', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'options_found_in': 'classifier_gate', 'options_origin': 'classifier_gate', 'options_confidence': 1.0, 'options_failure_reason': None, 'note': 'option_count=4'}, {'stage': 'question_type_detection', 'strategy': 'observation', 'input_source': 'intermediate', 'parent_stage': 'options_extraction', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'type=single_choice'}, {'stage': 'consistency_check', 'strategy': 'observation', 'input_source': 'intermediate', 'parent_stage': 'question_type_detection', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'consistent=True'}, {'stage': 'code_detection', 'strategy': 'rule', 'input_source': 'stem', 'parent_stage': 'noise_filtering', 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': 'True', 'status': 'success', 'duration_ms': 0.04, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [{'before': '18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表', 'after': 'True'}], 'has_changed': True}, 'notes': ''}, {'stage': 'code_integrity_check', 'strategy': 'observation', 'input_source': 'stem', 'parent_stage': 'code_detection', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': \"flags=['code_brace_unbalanced'] score=0.35\"}, {'stage': 'code_integrity_check', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'code_brace_unbalanced', 'origin_stage': 'code_integrity_check', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': 'Code integrity issue: code_brace_unbalanced'}, {'stage': 'code_regression_check', 'strategy': 'observation', 'input_source': 'intermediate', 'parent_stage': 'code_integrity_check', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'has_regression=False flags=[]'}, {'stage': 'vision_fallback', 'strategy': 'observation', 'input_source': 'fallback', 'parent_stage': 'code_integrity_check', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'attempted=True status=unavailable'}]}",
              "after": "'schema_version': 'v1'}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      }
    ],
    "is_frozen": false,
    "options_classified": true,
    "options_classify_reason": "structured_option_patterns_detected",
    "vision_fallback_attempted": true,
    "vision_fallback_used": false,
    "vision_fallback_status": "unavailable",
    "vision_fallback_reason": [
      "code_brace_unbalanced",
      "code_block_incomplete"
    ],
    "pre_fallback_code_flags": [
      "code_brace_unbalanced",
      "code_block_incomplete"
    ],
    "post_fallback_code_flags": [
      "code_brace_unbalanced",
      "code_block_incomplete"
    ],
    "schema_version": "v1",
    "ai_validation": {
      "is_valid": false,
      "issues": [
        "post_repair_code_integrity:code_brace_unbalanced"
      ],
      "severity": "error"
    }
  },
  "ai_metadata": {
    "is_valid": false,
    "errors": [
      "missing_answer"
    ],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "code_integrity:code_brace_unbalanced",
      "low_confidence",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "0cbddc8d",
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.35 flags=['code_brace_unbalanced']"
      },
      {
        "stage": "code_gate",
        "result": "blocked",
        "reason": "code_brace_unbalanced;code_block_incomplete"
      },
      {
        "stage": "validation",
        "result": "failed",
        "reason": "missing_answer_for_objective_question;code_brace_unbalanced"
      },
      {
        "stage": "ai_safety",
        "result": "blocked",
        "reason": "safety_rejected: options_dropped(4→0)"
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
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "status": "observed",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "notes": "raw_text length=122"
      },
      {
        "stage": "ocr_quality_gate",
        "strategy": "rule",
        "input_source": "raw_ocr",
        "parent_stage": null,
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}",
        "status": "success",
        "duration_ms": 0.41,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表",
              "after": "{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}"
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
        "notes": "stem length=122"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "c_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'C' token at pos 14"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "a_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'A' token at pos 91"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "b_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'B' token at pos 99"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "c_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [
          "stem_extraction"
        ],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'C' token at pos 107"
      },
      {
        "stage": "stem_extraction",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "d_token_noise",
        "origin_stage": "stem_extraction",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Standalone 'D' token at pos 116"
      },
      {
        "stage": "noise_filtering",
        "strategy": "rule",
        "input_source": "stem",
        "parent_stage": "stem_extraction",
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "status": "success",
        "duration_ms": 0.01,
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
        "options_found_in": "fallback_from_raw_text",
        "options_origin": "fallback_from_raw_text",
        "options_confidence": 0.8,
        "options_failure_reason": null,
        "note": "option_count=4"
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
        "input_preview": "18。在单链表中执行:\n(>C\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n该代码的作用是：\nA.找到头结点\nB.找到尾结点\nC.删除所有节点\nD.逆置链表",
        "output_preview": "True",
        "status": "success",
        "duration_ms": 0.04,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [
            {
              "before": "18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表",
              "after": "True"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      },
      {
        "stage": "code_integrity_check",
        "strategy": "observation",
        "input_source": "stem",
        "parent_stage": "code_detection",
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
        "notes": "flags=['code_brace_unbalanced'] score=0.35"
      },
      {
        "stage": "code_integrity_check",
        "strategy": "detection",
        "input_source": "intermediate",
        "parent_stage": null,
        "input_preview": "",
        "output_preview": "",
        "status": "corruption",
        "duration_ms": 0,
        "delta": {
          "added_tokens": [],
          "removed_tokens": [],
          "modified_regions": [],
          "has_changed": false
        },
        "corruption_type": "code_brace_unbalanced",
        "origin_stage": "code_integrity_check",
        "propagation_path": [],
        "resolved_at": null,
        "resolved_by": null,
        "notes": "Code integrity issue: code_brace_unbalanced"
      },
      {
        "stage": "code_regression_check",
        "strategy": "observation",
        "input_source": "intermediate",
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
        "notes": "has_regression=False flags=[]"
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
        "notes": "attempted=True status=unavailable"
      },
      {
        "stage": "output_normalization",
        "strategy": "pipeline",
        "input_source": "final",
        "parent_stage": "vision_fallback",
        "input_preview": "{'schema_version': 'v1', 'subject': '', 'question_type': 'single_choice', 'stem': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC....[+10147]",
        "output_preview": "{'stem': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'code_blocks': [], 'options': [{'key': 'A', 'text': '找到头...[+10166]",
        "status": "success",
        "duration_ms": 1.45,
        "delta": {
          "added_tokens": [
            "'code_blocks':",
            "[],",
            "'subject':",
            "'',",
            "'question_type':",
            "'single_choice',",
            "'decision_trace':",
            "[{'stage':",
            "'ocr_quality_gate',",
            "'result':",
            "'blocked',",
            "'reason':",
            "\"score=0.35",
            "flags=['code_brace_unbalanced']\"},",
            "{'stage':",
            "'code_gate',",
            "'code_brace_unbalanced;code_block_incomplete'},",
            "'validation',",
            "'failed',",
            "'missing_answer_for_objective_question;code_brace_unbalanced'}],",
            "'trace':",
            "'ocr_raw_input',",
            "'strategy':",
            "'passthrough',",
            "'input_source':",
            "'raw_ocr',",
            "'parent_stage':",
            "None,",
            "'input_preview':",
            "'18。在单链表中执行:\\n(>C\\nLNode",
            "*p",
            "=",
            "L;\\nwhile",
            "(p",
            "!=",
            "NULL",
            "&&",
            "p->next",
            "NULL)",
            "{\\np",
            "p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表',",
            "'output_preview':",
            "'status':",
            "'observed',",
            "'duration_ms':",
            "0,",
            "'delta':",
            "{'added_tokens':",
            "'removed_tokens':",
            "'modified_regions':",
            "'has_changed':",
            "False},",
            "'notes':",
            "'raw_text",
            "length=122'},",
            "'rule',",
            "\"{'passed':",
            "False,",
            "'ocr_quality_flags':",
            "['code_brace_unbalanced'],",
            "'ocr_contamination_score':",
            "0.35}\",",
            "'success',",
            "0.41,",
            "[{'before':",
            "'18。在单链表中执行:",
            "(>C",
            "LNode",
            "L;",
            "while",
            "{",
            "p",
            "p->next;",
            "该代码的作用是：",
            "A.找到头结点",
            "B.找到尾结点",
            "C.删除所有节点",
            "D.逆置链表',",
            "'after':",
            "0.35}\"}],",
            "True},",
            "''},",
            "'stem_extraction',",
            "'observation',",
            "'info',",
            "'stem",
            "'detection',",
            "'intermediate',",
            "'corruption',",
            "'corruption_type':",
            "'c_token_noise',",
            "'origin_stage':",
            "'propagation_path':",
            "'resolved_at':",
            "'resolved_by':",
            "\"Standalone",
            "'C'",
            "token",
            "at",
            "pos",
            "14\"},",
            "'a_token_noise',",
            "'A'",
            "91\"},",
            "'b_token_noise',",
            "'B'",
            "99\"},",
            "['stem_extraction'],",
            "107\"},",
            "'d_token_noise',",
            "'D'",
            "116\"},",
            "'noise_filtering',",
            "'stem',",
            "0.01,",
            "'options_extraction',",
            "'options_trace',",
            "'options_found_in':",
            "'fallback_from_raw_text',",
            "'options_origin':",
            "'options_confidence':",
            "0.8,",
            "'options_failure_reason':",
            "'note':",
            "'option_count=4'},",
            "'classifier_gate',",
            "1.0,",
            "'question_type_detection',",
            "'type=single_choice'},",
            "'consistency_check',",
            "'consistent=True'},",
            "'code_detection',",
            "'True',",
            "0.04,",
            "'True'}],",
            "'code_integrity_check',",
            "\"flags=['code_brace_unbalanced']",
            "score=0.35\"},",
            "'code_brace_unbalanced',",
            "'Code",
            "integrity",
            "issue:",
            "code_brace_unbalanced'},",
            "'code_regression_check',",
            "'has_regression=False",
            "flags=[]'},",
            "'vision_fallback',",
            "'fallback',",
            "'attempted=True",
            "status=unavailable'}],",
            "'is_frozen':",
            "'options_classified':",
            "True,",
            "'options_classify_reason':",
            "'structured_option_patterns_detected',"
          ],
          "removed_tokens": [
            "'is_frozen':",
            "False,",
            "'options_classified':",
            "True,",
            "'options_classify_reason':",
            "'structured_option_patterns_detected',"
          ],
          "modified_regions": [
            {
              "before": "{'schema_version': 'v1', 'subject': '', 'question_type': 'single_choice', 'stem':",
              "after": "{'stem':"
            },
            {
              "before": "'decision_trace': [{'stage': 'ocr_quality_gate', 'result': 'blocked', 'reason': \"score=0.35 flags=['code_brace_unbalanced']\"}, {'stage': 'code_gate', 'result': 'blocked', 'reason': 'code_brace_unbalanced;code_block_incomplete'}, {'stage': 'validation', 'result': 'failed', 'reason': 'missing_answer_for_objective_question;code_brace_unbalanced'}], 'trace': [{'stage': 'ocr_raw_input', 'strategy': 'passthrough', 'input_source': 'raw_ocr', 'parent_stage': None, 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'status': 'observed', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'raw_text length=122'}, {'stage': 'ocr_quality_gate', 'strategy': 'rule', 'input_source': 'raw_ocr', 'parent_stage': None, 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': \"{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}\", 'status': 'success', 'duration_ms': 0.41, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [{'before': '18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表', 'after': \"{'passed': False, 'ocr_quality_flags': ['code_brace_unbalanced'], 'ocr_contamination_score': 0.35}\"}], 'has_changed': True}, 'notes': ''}, {'stage': 'stem_extraction', 'strategy': 'observation', 'input_source': 'raw_ocr', 'parent_stage': 'ocr_quality_gate', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'stem length=122'}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'c_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'C' token at pos 14\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'a_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'A' token at pos 91\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'b_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'B' token at pos 99\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'c_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': ['stem_extraction'], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'C' token at pos 107\"}, {'stage': 'stem_extraction', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'd_token_noise', 'origin_stage': 'stem_extraction', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': \"Standalone 'D' token at pos 116\"}, {'stage': 'noise_filtering', 'strategy': 'rule', 'input_source': 'stem', 'parent_stage': 'stem_extraction', 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'status': 'success', 'duration_ms': 0.01, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': ''}, {'stage': 'options_extraction', 'strategy': 'options_trace', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'options_found_in': 'fallback_from_raw_text', 'options_origin': 'fallback_from_raw_text', 'options_confidence': 0.8, 'options_failure_reason': None, 'note': 'option_count=4'}, {'stage': 'options_extraction', 'strategy': 'options_trace', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'options_found_in': 'classifier_gate', 'options_origin': 'classifier_gate', 'options_confidence': 1.0, 'options_failure_reason': None, 'note': 'option_count=4'}, {'stage': 'question_type_detection', 'strategy': 'observation', 'input_source': 'intermediate', 'parent_stage': 'options_extraction', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'type=single_choice'}, {'stage': 'consistency_check', 'strategy': 'observation', 'input_source': 'intermediate', 'parent_stage': 'question_type_detection', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'consistent=True'}, {'stage': 'code_detection', 'strategy': 'rule', 'input_source': 'stem', 'parent_stage': 'noise_filtering', 'input_preview': '18。在单链表中执行:\\n(>C\\nLNode *p = L;\\nwhile (p != NULL && p->next != NULL) {\\np = p->next;\\n该代码的作用是：\\nA.找到头结点\\nB.找到尾结点\\nC.删除所有节点\\nD.逆置链表', 'output_preview': 'True', 'status': 'success', 'duration_ms': 0.04, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [{'before': '18。在单链表中执行: (>C LNode *p = L; while (p != NULL && p->next != NULL) { p = p->next; 该代码的作用是： A.找到头结点 B.找到尾结点 C.删除所有节点 D.逆置链表', 'after': 'True'}], 'has_changed': True}, 'notes': ''}, {'stage': 'code_integrity_check', 'strategy': 'observation', 'input_source': 'stem', 'parent_stage': 'code_detection', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': \"flags=['code_brace_unbalanced'] score=0.35\"}, {'stage': 'code_integrity_check', 'strategy': 'detection', 'input_source': 'intermediate', 'parent_stage': None, 'input_preview': '', 'output_preview': '', 'status': 'corruption', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'corruption_type': 'code_brace_unbalanced', 'origin_stage': 'code_integrity_check', 'propagation_path': [], 'resolved_at': None, 'resolved_by': None, 'notes': 'Code integrity issue: code_brace_unbalanced'}, {'stage': 'code_regression_check', 'strategy': 'observation', 'input_source': 'intermediate', 'parent_stage': 'code_integrity_check', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'has_regression=False flags=[]'}, {'stage': 'vision_fallback', 'strategy': 'observation', 'input_source': 'fallback', 'parent_stage': 'code_integrity_check', 'input_preview': '', 'output_preview': '', 'status': 'info', 'duration_ms': 0, 'delta': {'added_tokens': [], 'removed_tokens': [], 'modified_regions': [], 'has_changed': False}, 'notes': 'attempted=True status=unavailable'}]}",
              "after": "'schema_version': 'v1'}"
            }
          ],
          "has_changed": true
        },
        "notes": ""
      }
    ],
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_block_incomplete",
      "low_confidence"
    ]
  }
}
```

##### 案例四（✅ 已修复 — code structure reconstruction）

> 修复提交：`e91a020` — 与案例三同一修复。
> `code_structure_reconstruct` 阶段将 OCR 断裂的 `i++) {`、`sum += a[i];}` 等语句拼接闭合，
> 恢复 `}` 闭合和缩进，使题干代码结构完整可读。

###### 原题

```tex
17. 执行如下代码：

for (int i = 0; i < n; i++) {
    if (a[i] > 0) {
        sum += a[i];
    }
}

该代码的功能是：

A. 计算所有元素和
B. 计算负数和
C. 计算正数元素之和
D. 查找最大值
```

###### 来源

"/ocr_test/images/example/ocr_code_test_7.png"

###### 导入后进入审核（题干代码内容不完整）

~~~tex
执行如下代码：
(1>
（
for (int i = 0; i < n; i + +) {
if (a[i] >0) {
sum + = a[i];
该代码的功能是:

A. 计算所有元素和
B. 计算负数和
C. 计算正数元素之和
D. 查找最大值
~~~

###### OCR 原文 / 导入原始信息

~~~tex
17.执行如下代码：
(1>
（
for (int i = 0; i < n; i++) {
if (a[i] >0) {
sum += a[i];
该代码的功能是:
A.计算所有元素和
B.计算负数和
C.计算正数元素之和
D.查找最大值
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "执行如下代码：\n(1>\n（\nfor (int i = 0; i < n; i++) {\nif (a[i] >0) {\nsum += a[i];\n该代码的功能是:"
  },
  "parsed_options": {
    "A": "计算所有元素和",
    "B": "计算负数和",
    "C": "计算正数元素之和",
    "D": "查找最大值"
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
    "stem": "执行如下代码：\n(1>\n（\nfor (int i = 0; i < n; i++) {\nif (a[i] >0) {\nsum += a[i];\n该代码的功能是:",
    "options": [
      {
        "key": "A",
        "text": "计算所有元素和"
      },
      {
        "key": "B",
        "text": "计算负数和"
      },
      {
        "key": "C",
        "text": "计算正数元素之和"
      },
      {
        "key": "D",
        "text": "查找最大值"
      }
    ],
    "frozen_options_restored": false,
    "options_preserved": true,
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "17.执行如下代码：\n(1>\n（\nfor (int i = 0; i < n; i++) {\nif (a[i] >0) {\nsum += a[i];\n该代码的功能是:\nA.计算所有元素和\nB.计算负数和\nC.计算正数元素之和\nD.查找最大值",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_7.png",
      "page": 1,
      "type": "image"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "code_integrity:code_brace_unbalanced",
      "low_confidence",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "3cd01b8f",
    "confidence_score": 0.95,
    "risk_flags": [
      "code_brace_unbalanced",
      "code_block_incomplete",
      "low_confidence"
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
      "is_valid": false,
      "issues": [
        "post_repair_code_integrity:code_brace_unbalanced"
      ],
      "severity": "error"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "code_integrity:code_brace_unbalanced",
      "low_confidence",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "3cd01b8f",
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
      "code_brace_unbalanced",
      "code_block_incomplete",
      "low_confidence"
    ]
  }
}
```

##### 案例五（✅ 已修复 — 双源策略优先使用 PP-OCRv6）

> 修复提交：`62f4870` — PP-OCRv6 输出 229 chars 含 A/C/D 选项（B 行 OCR 损坏但 3 个唯一 key ≥ 2 阈值）。
> detect_options=True，结构稳定。

###### 原题

```tex
8. 在单链表中进行如下操作：

typedef struct LNode {
    int data;
    struct LNode *next;
} LNode, *LinkList;

已知 p 指向某节点，执行插入操作：

A. p->next = s->next; s->next = p
B. s->next = p->next; p->next = s
C. p->next = s; s = p->next
D. s = p; p->next = NULL
```

###### 来源

"/ocr_test/images/example/ocr_code_test_6.png"

###### 导入后进入审核（无选项）

~~~tex
B.在单链表中进行如下操作:
```text
typedef struct LNode {
int data;
struct LNode * next;
} LNode, * LinkList;
```已知 p 指向某节点，执行插入操作: d = − >s : − >s = jxau − >d '
B. s − >next = p − >next; p − >next = s
C. p − >next = s; s = p − >next
D. s = p; p − >next = NULL
~~~

###### OCR 原文 / 导入原始信息

~~~tex
B.在单链表中进行如下操作:
```text
typedef struct LNode {
int data;
struct LNode *next;
} LNode, *LinkList;
``` 已知 p 指向某节点，执行插入操作: d = ->s :->s = jxau->d '
B. s->next = p->next; p->next = s
C. p->next = s; s = p->next
D. s = p; p->next = NULL
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "B.在单链表中进行如下操作:\n```text\ntypedef struct LNode {\nint data;\nstruct LNode *next;\n} LNode, *LinkList;\n```已知 p 指向某节点，执行插入操作: d = ->s :->s = jxau->d '\nB. s->next = p->next; p->next = s\nC. p->next = s; s = p->next\nD. s = p; p->next = NULL"
  },
  "parsed_options": null,
  "parsed_answer": null,
  "parsed_analysis": null
}
```

###### OCR / AI 原始数据

```json
{
  "raw_data": {
    "stem": "B.在单链表中进行如下操作:\n```text\ntypedef struct LNode {\nint data;\nstruct LNode *next;\n} LNode, *LinkList;\n```已知 p 指向某节点，执行插入操作: d = ->s :->s = jxau->d '\nB. s->next = p->next; p->next = s\nC. p->next = s; s = p->next\nD. s = p; p->next = NULL",
    "code_blocks": [
      "typedef struct LNode {\nint data;\nstruct LNode *next;\n} LNode, *LinkList;"
    ],
    "options": [],
    "answer": "",
    "analysis": "",
    "subject": "",
    "question_type": "subjective",
    "raw_text": "B.在单链表中进行如下操作:\n```text\ntypedef struct LNode {\nint data;\nstruct LNode *next;\n} LNode, *LinkList;\n``` 已知 p 指向某节点，执行插入操作: d = ->s :->s = jxau->d '\nB. s->next = p->next; p->next = s\nC. p->next = s; s = p->next\nD. s = p; p->next = NULL",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_6.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": false,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_line_break_suspicious",
      "code_integrity:code_line_break_suspicious",
      "low_confidence"
    ],
    "stem_hash": "790a2d87",
    "confidence_score": 0.35,
    "validation_status": "failed",
    "failure_reason": [
      "code_line_break_suspicious"
    ],
    "retry_recommended": true,
    "ocr_quality_flags": [
      "code_line_break_suspicious"
    ],
    "risk_flags": [
      "fallback_low_confidence",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.30 flags=['code_line_break_suspicious']"
      },
      {
        "stage": "code_gate",
        "result": "blocked",
        "reason": "code_line_break_suspicious;code_block_incomplete"
      },
      {
        "stage": "validation",
        "result": "failed",
        "reason": "code_line_break_suspicious"
      },
      {
        "stage": "ai_safety",
        "result": "blocked",
        "reason": "safety_rejected: code_symbol_lost:->"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "vision_fallback_attempted": true,
    "vision_fallback_used": false,
    "schema_version": "v1",
    "ai_validation": {
      "is_valid": false,
      "issues": [
        "post_repair_code_integrity:code_line_break_suspicious"
      ],
      "severity": "error"
    }
  },
  "ai_metadata": {
    "is_valid": false,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_line_break_suspicious",
      "code_integrity:code_line_break_suspicious",
      "low_confidence"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "790a2d87",
    "decision_trace": [
      {
        "stage": "ocr_quality_gate",
        "result": "blocked",
        "reason": "score=0.30 flags=['code_line_break_suspicious']"
      },
      {
        "stage": "code_gate",
        "result": "blocked",
        "reason": "code_line_break_suspicious;code_block_incomplete"
      },
      {
        "stage": "validation",
        "result": "failed",
        "reason": "code_line_break_suspicious"
      },
      {
        "stage": "ai_safety",
        "result": "blocked",
        "reason": "safety_rejected: code_symbol_lost:->"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
      }
    ],
    "risk_flags": [
      "fallback_low_confidence",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ]
  }
}
```

##### 回归测试映射

| 案例 | 回归 Case ID | 路径 | 核心问题 |
|------|-------------|------|----------|
| 案例一（栈定义+while循环） | `021_bugs_case1_stack` | `backend/tests/ocr_regression/cases/021_bugs_case1_stack/` | `#define` 外无序触发代码完整性告警 |
| 案例二（BiTree树递归） | `022_bugs_case2_treerecursion` | `backend/tests/ocr_regression/cases/022_bugs_case2_treerecursion/` | VL_REBUILD PDF gate（Fix B `be03159`） |
| 案例三（单链表while循环） | `023_bugs_case3_linkedlist` | `backend/tests/ocr_regression/cases/023_bugs_case3_linkedlist/` | VL 输出质量→双源策略（`62f4870`）；brace 不闭合→代码结构重建（`e91a020`） |
| 案例四（for循环） | `024_bugs_case4_forloop` | `backend/tests/ocr_regression/cases/024_bugs_case4_forloop/` | 管道通过基线；`}` 断裂+brace 告警→代码结构重建（`e91a020`） |
| 案例五（链表插入+typedef） | `025_bugs_case5_listinsert` | `backend/tests/ocr_regression/cases/025_bugs_case5_listinsert/` | VL/PP-OCRv6 B行损坏但≥2 key（双源策略 `62f4870`） |

运行方式：
```bash
# 文本回归（normalize/split）
cd backend && PYTHONPATH=. python3 -m pytest tests/ocr_regression/runner.py -v -k "bugs"

# OCR 全链路（含 PP-OCRv6 + 选项检测，需 PaddleOCR-VL 配置）
cd backend && PYTHONPATH=. python3 -m pytest tests/ocr_regression/runner.py -v -k "bugs"
# → OCR 测试自动触发（pipeline_stages 含 full_ocr 时）
# → 不满足 OCR 条件时测试 fallback 为 xfail
```

> **OCR 测试说明**：case 021-025 新增 `full_ocr` 阶段，自动运行 PP-OCRv6 图片 OCR + `detect_options_from_text` 验证。
> OCR 检测为附加断言，不影响现有文本回归基线。需本地 DB 中配置 PaddleOCR-VL（用于 VL_REBUILD 路径，但双源策略优先使用 PP-OCRv6）。
