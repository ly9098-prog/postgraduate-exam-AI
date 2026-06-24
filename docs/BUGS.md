# 代码题目题干/选项部分缺失（第四次修复）

###### |结果：仍然存在选项缺失的情况

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

##### 案例三（✅ 已修复 — 双源策略优先使用 PP-OCRv6）

> 修复提交：`62f4870` — VL_REBUILD 中先跑 PP-OCRv6，检测到选项时直接使用（跳过 VL）。
> 验证结果：PP-OCRv6 输出 122 chars，detect_options=True，提取到完整 4 选项。

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

###### 导入后进入审核

~~~tex
```text
LNode * p = L;
while (p != NULL && p − >next != NULL) {
p = p − >next;
```

选项缺失
~~~

###### OCR 原文 / 导入原始信息

~~~tex
C
```text
LNode *p = L;
while (p != NULL && p->next != NULL) {
p = p->next;
```
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "```text\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n```"
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
    "stem": "```text\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n```",
    "options": [],
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "C\n```text\nLNode *p = L;\nwhile (p != NULL && p->next != NULL) {\np = p->next;\n```",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_8.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:code_brace_unbalanced",
      "ocr_quality:watermark_noise_detected",
      "code_integrity:code_brace_unbalanced",
      "low_confidence"
    ],
    "stem_hash": "18031c04",
    "confidence_score": 0.3,
    "risk_flags": [
      "fallback_low_confidence",
      "code_brace_unbalanced",
      "code_block_incomplete",
      "low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "ai_repaired"
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
      "ocr_quality:watermark_noise_detected",
      "code_integrity:code_brace_unbalanced",
      "low_confidence"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "18031c04",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "ai_repaired"
      },
      {
        "stage": "review",
        "result": "pending",
        "reason": "written_to_review_queue"
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

##### 案例四（失败）

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

###### 导入后进入审核

~~~tex
执行如下代码:
```text
for (int i = 0; i < n; i + +) {
if (a[i] > 0) {
sum + = a[i];
```
该代码的功能是:

A. 计算所有元素和
B. 计算负数和
C. 计算正数元素之和
D. 查找最大值
~~~

###### OCR 原文 / 导入原始信息

~~~tex
17. 执行如下代码:
```text
for (int i = 0; i < n; i++) {
if (a[i] > 0) {
sum += a[i];
``` 该代码的功能是:
A.计算所有元素和
B. 计算负数和
C. 计算正数元素之和
D.查找最大值
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "执行如下代码:\n```text\nfor (int i = 0; i < n; i++) {\nif (a[i] > 0) {\nsum += a[i];\n```\n该代码的功能是:"
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
    "stem": "执行如下代码:\n```text\nfor (int i = 0; i < n; i++) {\nif (a[i] > 0) {\nsum += a[i];\n```\n该代码的功能是:",
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
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "17. 执行如下代码:\n```text\nfor (int i = 0; i < n; i++) {\nif (a[i] > 0) {\nsum += a[i];\n``` 该代码的功能是:\nA.计算所有元素和\nB. 计算负数和\nC. 计算正数元素之和\nD.查找最大值",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_7.png",
      "page": 1,
      "type": "txt"
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
    "stem_hash": "56d96d25",
    "confidence_score": 0.8,
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
    "stem_hash": "56d96d25",
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
| 案例三（单链表while循环） | `023_bugs_case3_linkedlist` | `backend/tests/ocr_regression/cases/023_bugs_case3_linkedlist/` | VL 输出质量→双源策略（`62f4870`） |
| 案例四（for循环·成功） | `024_bugs_case4_forloop` | `backend/tests/ocr_regression/cases/024_bugs_case4_forloop/` | 管道正常通过基线 |
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
