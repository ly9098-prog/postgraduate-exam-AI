# 代码题目题干结构异常 — 已修复

> **修复状态**: 已修复 (commit `8427b1a`) — 2026-06-22
> **根因**: `code_detector._fence_code_blocks()` 要求连续 ≥2 行 score≥1 才包裹 ```围栏，单行 OCR 乱码行（score=0）夹在两行代码行之间时导致围栏提前关闭、后续结构代码泄漏。
> **修复**: 新增单行桥接规则 — 相邻两行均为代码行时，中间孤立低分行 score 提升为 1，维持围栏连续性。
> **验证**: 22 个 OCR 回归测试全部通过，含 `019_code_struct_garbled_truncation`；实际图片 OCR 端到端验证通过。

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

```json
{
  "total": 1,
  "extracted": 1,
  "normalized": 1,
  "analyzed": 1,
  "split": 1,
  "matched": 1,
  "schema_normalized": 1,
  "missing_options": 0,
  "repaired": 0,
  "to_review": 1,
  "failed": 0,
  "ocr": {
    "raw_text_length": 195,
    "cleaned_text_length": 186,
    "raw_line_count": 11,
    "cleaned_line_count": 10,
    "raw_text_preview": "2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA\n则其前序遍历序列为:\ntypedef struct BiTNode {\nchar data;\n(1typu*  p1tysI* apo11ta aonu2s\n} BiTNode, *BiTree;\nA.ABDECF\nB.ABDCEF\nC.ABDFEC\nD. ACBEDF\n答案：A",
    "cleaned_text_preview": "2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA 则其前序遍历序列为:\n```text\ntypedef struct BiTNode {\nchar data;\n``` (1typu* p1tysI* apo11ta aonu2s\nA.ABDECF\nB.ABDCEF\nC.ABDFEC\nD. ACBEDF\n答案:A",
    "text_length_delta": 9,
    "line_count_delta": 1
  }
}
```

