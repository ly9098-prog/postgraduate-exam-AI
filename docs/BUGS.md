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

