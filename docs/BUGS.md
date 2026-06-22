# 代码题目题干/选项部分缺失

##### 案例一（失败）

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

###### 导入后进入审核

~~~tex
#define MAXSIZE 100 typedef struct
```text
int data[MAXSIZE];
int top;
} Stack;
```
执行如下代码: C
```text
while (s.top != − 1) {
printf("%d", s.data[s.top]);
s.top −  − ;
```

选项缺失
~~~

###### OCR 原文 / 导入原始信息

~~~tex
#define MAXSIZE 100 typedef struct
```text
int data[MAXSIZE];
int top;
} Stack;
``` 执行如下代码: C
```text
while (s.top != -1) {
printf("%d", s.data[s.top]);
s.top--;
```
~~~

###### 解析数据

```json
{
  "parsed_content": {
    "text": "#define MAXSIZE 100 typedef struct\n```text\nint data[MAXSIZE];\nint top;\n} Stack;\n```\n执行如下代码: C\n```text\nwhile (s.top != -1) {\nprintf(\"%d\", s.data[s.top]);\ns.top--;\n```"
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
    "stem": "#define MAXSIZE 100 typedef struct\n```text\nint data[MAXSIZE];\nint top;\n} Stack;\n```\n执行如下代码: C\n```text\nwhile (s.top != -1) {\nprintf(\"%d\", s.data[s.top]);\ns.top--;\n```",
    "options": [],
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "#define MAXSIZE 100 typedef struct\n```text\nint data[MAXSIZE];\nint top;\n} Stack;\n``` 执行如下代码: C\n```text\nwhile (s.top != -1) {\nprintf(\"%d\", s.data[s.top]);\ns.top--;\n```",
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
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:watermark_noise_detected",
      "code_integrity:code_line_break_suspicious",
      "low_confidence"
    ],
    "stem_hash": "6495ad53",
    "confidence_score": 0.9,
    "risk_flags": [
      "fallback_low_confidence",
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ],
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned"
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
      "ocr_quality:code_line_break_suspicious",
      "ocr_quality:watermark_noise_detected",
      "code_integrity:code_line_break_suspicious",
      "low_confidence"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "6495ad53",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned"
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

##### 案例二（失败）

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

~~~tex
void countLeaf(BiTree T) {
if (T = = NULL) return;
if (T − >lchild = = NULL && T − >rchild = = NULL)
    count + +;
countLeaf(T − >lchild);
countLeaf(T − >rchild);
}

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

###### 解析数据

```json
{
  "parsed_content": {
    "text": "void countLeaf(BiTree T) {\nif (T == NULL) return;\nif (T->lchild == NULL && T->rchild == NULL)\n    count++;\ncountLeaf(T->lchild);\ncountLeaf(T->rchild);\n}"
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
    "stem": "void countLeaf(BiTree T) {\nif (T == NULL) return;\nif (T->lchild == NULL && T->rchild == NULL)\n    count++;\ncountLeaf(T->lchild);\ncountLeaf(T->rchild);\n}",
    "options": [],
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
    "confidence_score": 0.95,
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
        "reason": "code_format_fixed"
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
        "stem_repeated_fragment",
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
        "reason": "code_format_fixed"
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
      "code_line_break_suspicious",
      "code_block_incomplete",
      "low_confidence"
    ]
  }
}
```

##### 案例三（失败）

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
    "stem_hash": "9c93ab00",
    "confidence_score": 0.9,
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
        "reason": "stem_cleaned;type_detected"
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
    "stem_hash": "9c93ab00",
    "decision_trace": [
      {
        "stage": "ai_repair",
        "result": "repaired",
        "reason": "stem_cleaned;type_detected"
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

##### 案例四（成功）

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

##### 案例五（失败）

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

###### 导入后进入审核

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
    "schema_version": "v1",
    "subject": "",
    "question_type": "subjective",
    "stem": "B.在单链表中进行如下操作:\n```text\ntypedef struct LNode {\nint data;\nstruct LNode *next;\n} LNode, *LinkList;\n```已知 p 指向某节点，执行插入操作: d = ->s :->s = jxau->d '\nB. s->next = p->next; p->next = s\nC. p->next = s; s = p->next\nD. s = p; p->next = NULL",
    "options": [],
    "answer": "",
    "analysis": "",
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
    "vision_fallback_attempted": true,
    "vision_fallback_used": false,
    "vision_fallback_status": "unavailable",
    "vision_fallback_reason": [
      "code_line_break_suspicious",
      "code_block_incomplete"
    ],
    "pre_fallback_code_flags": [
      "code_line_break_suspicious",
      "code_block_incomplete"
    ],
    "post_fallback_code_flags": [
      "code_line_break_suspicious",
      "code_block_incomplete"
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
        "reason": "safety_rejected: options_dropped(4→0)"
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
        "reason": "safety_rejected: options_dropped(4→0)"
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
| 案例二（BiTree树递归） | `022_bugs_case2_treerecursion` | `backend/tests/ocr_regression/cases/022_bugs_case2_treerecursion/` | 代码块围栏包裹+选项提取 |
| 案例三（单链表while循环） | `023_bugs_case3_linkedlist` | `backend/tests/ocr_regression/cases/023_bugs_case3_linkedlist/` | 代码块围栏包裹+选项提取 |
| 案例四（for循环·成功） | `024_bugs_case4_forloop` | `backend/tests/ocr_regression/cases/024_bugs_case4_forloop/` | 管道正常通过基线 |
| 案例五（链表插入+typedef） | `025_bugs_case5_listinsert` | `backend/tests/ocr_regression/cases/025_bugs_case5_listinsert/` | 题号8→B OCR纠错覆盖，切出0题 |

运行方式：
```bash
cd backend && PYTHONPATH=. python3 -m pytest tests/ocr_regression/runner.py -v -k "bugs"
```
