# BUGS

#### 案例一

##### 原题

```tex
在双链表中向 p所指的结点之前插入一个结点q的操作为( )。
A. p − >prior = q; q − >next = p; p − >prior − >next = q; q − >prior = p − >prior;
B. q − >prior = p − >prior; p − >prior − >next = q; q − >next = p; p − >prior = q − >next;
C. q − >next = p; p − >next = q; q − >prior − >next = q; q − >next = p;
D. p − >prior = q;q − >next = p;q − >prior = p − >prior;p − >prior = q; 
```

##### 前端内容显示

```tex
在双链表中向 p所指的结点之前插入一个结点 α 的操作为( )。

A. p − >prior = q; q − >next = p; p − >prior − >next = q; q − >prior = p − >prior;
B. q − >prior = p − >prior; p − >prior − >next = q; q − >next = p; p − >prior = q − >next;
C. q − >next = p; p − >next = q; q − >prior − >next = q; q − >next = p;
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "在双链表中向 p所指的结点之前插入一个结点 $\\alpha$ 的操作为( )。"
  },
  "parsed_options": {
    "A": "p->prior=q; q->next=p; p->prior->next=q; q->prior=p->prior;",
    "B": "q->prior=p->prior; p->prior->next=q; q->next=p; p->prior=q->next;",
    "C": "q->next=p; p->next=q; q->prior->next=q; q->next=p;"
  },
  "parsed_answer": null,
  "parsed_analysis": null
}
```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "在双链表中向 p所指的结点之前插入一个结点 $\\alpha$ 的操作为( )。",
    "options": [
      {
        "key": "A",
        "text": "p->prior=q; q->next=p; p->prior->next=q; q->prior=p->prior;"
      },
      {
        "key": "B",
        "text": "q->prior=p->prior; p->prior->next=q; q->next=p; p->prior=q->next;"
      },
      {
        "key": "C",
        "text": "q->next=p; p->next=q; q->prior->next=q; q->next=p;"
      }
    ],
    "blank_option_groups": [],
    "answer": "",
    "analysis": "",
    "raw_text": "15.在双链表中向 p所指的结点之前插入一个结点\\alpha的操作为()。\nA. p->prior=q; q->next=p; p->prior->next=q; q->prior=p->prior;\nB. q->prior=p->prior; p->prior->next=q; q->next=p; p->prior=q->next;\nC. q->next=p; p->next=q; q->prior->next=q; q->next=p;\n:b=oxd<-d !xot\\pid<-d=xotxd<-b :d=xau<-b :b=xau<-\\pio\\pid<-d '\\alpha",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "3.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:symbol_substitution_detected",
      "ocr_quality:option_structure_corrupted",
      "incomplete_options: missing D",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "650603c0",
    "confidence_score": 0.2,
    "risk_flags": [],
    "ai_validation": {
      "is_valid": true,
      "issues": [
        "stem_too_short"
      ],
      "severity": "warning"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:symbol_substitution_detected",
      "ocr_quality:option_structure_corrupted",
      "incomplete_options: missing D",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "650603c0",
    "risk_flags": null
  }
}
```

##### 问题
- OCR 将变量 `q` 误识别为 `\alpha`，将原题中以下标形式出现在题干中的字母误转为 LaTeX 公式
- 选项 D 被 OCR 吞掉，导致选项不完整

##### 修复
- OCR 后处理：对 `\alpha` 等单字母 LaTeX 符号做上下文校验，判断应为普通变量而非数学公式
- 选项完整性校验：检测预期选项数与实际数不一致时告警/自动补偿

---

#### 案例二

##### 原题（单选题）

```tex
一个链表最常用的操作是在末尾插入结点和删除结，则选用( )最节省时间。

A.不带头结点的循环双链表		B. 双链表
C.单链表			 		 D.不带头结点且有尾指针的循环单链表
```

##### 前端内容显示（多空选择题）

```tex
一个链表最常用的操作是在末尾插入结点和删除结，则选用( )最节省时间。
B. 循环单链表
A.带头结点的循环双链表
D.单链表
C.带尾指针的循环单链表在第一个元素之前插入新元；在最后一个元素之后插入新元，则最好使用()
O
口
医
2027年数据结构考研复习指导
口
A. 只有尾结点指针没有头结点指针的循环单链表
B.只有尾结点指针没有头结点指针的非循环双链表
C.只有头结点指针没有尾结点指针的循环双链表
D.既有头结点指针又有尾结点指针的循环单链表
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "一个链表最常用的操作是在末尾插入结点和删除结，则选用( )最节省时间。\nB. 循环单链表\nA.带头结点的循环双链表\nD.单链表\nC.带尾指针的循环单链表在第一个元素之前插入新元；在最后一个元素之后插入新元，则最好使用()\nO\n口\n医\n2027年数据结构考研复习指导\n口\nA. 只有尾结点指针没有头结点指针的循环单链表\nB.只有尾结点指针没有头结点指针的非循环双链表\nC.只有头结点指针没有尾结点指针的循环双链表\nD.既有头结点指针又有尾结点指针的循环单链表",
    "blank_option_groups": [
      {
        "id": "1",
        "options": [
          {
            "key": "A",
            "text": "带头结点的循环双链表"
          },
          {
            "key": "B",
            "text": "循环单链表"
          },
          {
            "key": "C",
            "text": "带尾指针的循环单链表在第一个元素之前插入新元；在最后一个元素之后插入新元，则最好使用() O 口 医 2027年数据结构考研复习指导 口"
          },
          {
            "key": "D",
            "text": "单链表"
          }
        ]
      },
      {
        "id": "2",
        "options": [
          {
            "key": "A",
            "text": "只有尾结点指针没有头结点指针的循环单链表"
          },
          {
            "key": "B",
            "text": "只有尾结点指针没有头结点指针的非循环双链表"
          },
          {
            "key": "C",
            "text": "只有头结点指针没有尾结点指针的循环双链表"
          },
          {
            "key": "D",
            "text": "既有头结点指针又有尾结点指针的循环单链表"
          }
        ]
      }
    ]
  },
  "parsed_options": null,
  "parsed_answer": null,
  "parsed_analysis": null
}
```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "multi_blank_choice",
    "stem": "一个链表最常用的操作是在末尾插入结点和删除结，则选用( )最节省时间。\nB. 循环单链表\nA.带头结点的循环双链表\nD.单链表\nC.带尾指针的循环单链表在第一个元素之前插入新元；在最后一个元素之后插入新元，则最好使用()\nO\n口\n医\n2027年数据结构考研复习指导\n口\nA. 只有尾结点指针没有头结点指针的循环单链表\nB.只有尾结点指针没有头结点指针的非循环双链表\nC.只有头结点指针没有尾结点指针的循环双链表\nD.既有头结点指针又有尾结点指针的循环单链表",
    "options": [],
    "answer": "",
    "analysis": "",
    "raw_text": "23. 一个链表最常用的操作是在末尾插入结点和删除结，则选用( )最节省时间。\nB. 循环单链表\nA.带头结点的循环双链表\nD.单链表\nC.带尾指针的循环单链表在第一个元素之前插入新元；在最后一个元素之后插入新元，则最好使用()\nO\n口\n医\n2027年数据结构考研复习指导\n口\nA. 只有尾结点指针没有头结点指针的循环单链表\nB.只有尾结点指针没有头结点指针的非循环双链表\nC.只有头结点指针没有尾结点指针的循环双链表\nD.既有头结点指针又有尾结点指针的循环单链表",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "4.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "stem_hash": "892e09a9",
    "confidence_score": 0.7,
    "validation_status": "passed",
    "failure_reason": [],
    "retry_recommended": false,
    "ocr_quality_flags": [],
    "blank_option_groups": [
      {
        "id": "1",
        "options": [
          {
            "key": "A",
            "text": "带头结点的循环双链表"
          },
          {
            "key": "B",
            "text": "循环单链表"
          },
          {
            "key": "C",
            "text": "带尾指针的循环单链表在第一个元素之前插入新元；在最后一个元素之后插入新元，则最好使用() O 口 医 2027年数据结构考研复习指导 口"
          },
          {
            "key": "D",
            "text": "单链表"
          }
        ]
      },
      {
        "id": "2",
        "options": [
          {
            "key": "A",
            "text": "只有尾结点指针没有头结点指针的循环单链表"
          },
          {
            "key": "B",
            "text": "只有尾结点指针没有头结点指针的非循环双链表"
          },
          {
            "key": "C",
            "text": "只有头结点指针没有尾结点指针的循环双链表"
          },
          {
            "key": "D",
            "text": "既有头结点指针又有尾结点指针的循环单链表"
          }
        ]
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
    "warnings": [],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "892e09a9",
    "risk_flags": null
  }
}
```

##### 问题
- 相邻两道独立题目（一页两列排版）被 OCR 合并为一道多空选择题
- 第一题选项顺序被打乱（原 A↔B 互换），第二题题干碎片混入第一题选项 C
- 教材页脚/水印（"2027年数据结构考研复习指导""O 口 医"）作为乱码混入

##### 修复
- OCR 排版分析：检测一页两列/多区域排版，用垂直坐标/列分割判断题目边界
- 水印/页脚过滤：识别并剥离教材页脚、半透明水印等非题目内容

---

#### 案例三

##### 原题

```tex
通过含有 n(n>1) 个元素的数组 a，采用头插法建立单链表 L，则 L 中的元素次序( )。
A. 与数组a的元素次序相同
B. 与数组a的元素次序相反
C. 与数组a的元素次序无关
D. 以上都错误
```

##### 前端内容显示

```tex
通过含有 n(n>1) 个元素的数组 α，采用头插法建立单链表 L，则 L 中的元素次序( )。
A. 与数组a的元素次序相同
B. 与数组a的元素次序相反
C. 与数组a的元素次序无关
D. 以上都错误
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "通过含有 $n(n>1)$ 个元素的数组 $\\alpha$，采用头插法建立单链表 L，则 L 中的元素次序( )。"
  },
  "parsed_options": {
    "A": "与数组a的元素次序相同",
    "B": "与数组a的元素次序相反",
    "C": "与数组a的元素次序无关",
    "D": "以上都错误"
  },
  "parsed_answer": "B",
  "parsed_analysis": "头插法每次将新结点插入链表头部，因此元素顺序与原数组相反。"
}xxxxxxxxxx {  "parsed_content": {    "text": "通过含有 $n(n>1)$ 个元素的数组 $\\alpha$，采用头插法建立单链表 L，则 L 中的元素次序( )。"  },  "parsed_options": {    "A": "与数组a的元素次序相同",    "B": "与数组a的元素次序相反",    "C": "与数组a的元素次序无关",    "D": "以上都错误"  },  "parsed_answer": "B",  "parsed_analysis": "头插法每次将新结点插入链表头部，因此元素顺序与原数组相反。"}{  "parsed_content": {    "text": "在双链表中向 p所指的结点之前插入一个结点 $\\alpha$ 的操作为( )。"  },  "parsed_options": {    "A": "p->prior=q; q->next=p; p->prior->next=q; q->prior=p->prior;",    "B": "q->prior=p->prior; p->prior->next=q; q->next=p; p->prior=q->next;",    "C": "q->next=p; p->next=q; q->prior->next=q; q->next=p;"  },  "parsed_answer": null,  "parsed_analysis": null}
```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "通过含有 $n(n>1)$ 个元素的数组 $\\alpha$，采用头插法建立单链表 L，则 L 中的元素次序( )。",
    "options": [
      {
        "key": "A",
        "text": "与数组a的元素次序相同"
      },
      {
        "key": "B",
        "text": "与数组a的元素次序相反"
      },
      {
        "key": "C",
        "text": "与数组a的元素次序无关"
      },
      {
        "key": "D",
        "text": "以上都错误"
      }
    ],
    "blank_option_groups": [],
    "answer": "B",
    "analysis": "头插法每次将新结点插入链表头部，因此元素顺序与原数组相反。",
    "raw_text": "13. 通过含有 n(n>1)个元素的数组\\alpha,采用头插法建立单链表 L,则 L 中的元素次序( )。\nA.与数组a的元素次序相同\nB.与数组a的元素次序相反口\n第2章线性表口\nC.与数组a的元素次序无关\nD. 以上都错误",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "3.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "1225eae9",
    "confidence_score": 0.95,
    "risk_flags": [],
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
    "stem_hash": "1225eae9",
    "risk_flags": null
  }
}
```

##### 问题
- 与案例一同源：变量 `a`（"数组 a"）被 OCR 误识别为 `\alpha` 并转为 LaTeX 公式
- 选项和答案/解析保留完整，但题干显示被 `\alpha` 污染

##### 修复
- 与案例一同一修复路径：OCR 后处理过滤误识别的单字母 LaTeX 符号

---

#### 案例四

##### 原题(背景含水印)

背景半透明水印内容："后续关注公众号[研大]" "永久微信xxxx" 

```tex
在一个单链表，已知a所指结点是p所指结点的前驱结点，若在a和p之间插入结点s,则执行()。

A. s − >next = p − >next;p − >next = s;		B. p − >next = s − >next;s − >next = p;
C. q − >next = s;s − >next = p;				D. p − >next = s − >next;s − >next = q;
```

##### 前端内容显示

```tex
在一个单链表，已知a所指结点是p所指结点的前驱结，若在a和p之间插入结点s,则执行()。

A. s − >next = p − >next;p − >next = s;
B. p − >next = s − >next;s − >next = p;
C. q − >next = s;s − >next = p;				
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "在一个单链表，已知a所指结点是p所指结点的前驱结，若在a和p之间插入结点s,则执行()。"
  },
  "parsed_options": {
    "A": "s->next=p->next;p->next=s;",
    "B": "p->next=s->next;s->next=p;",
    "C": "q->next=s;s->next=p;"
  },
  "parsed_answer": "C",
  "parsed_analysis": "在单链表中，在已知前驱结点a后插入新结点s，应先将s的next指向p，再将a的next指向s。选项C中q即为a，顺序正确。"
}

```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "在一个单链表，已知a所指结点是p所指结点的前驱结，若在a和p之间插入结点s,则执行()。",
    "options": [
      {
        "key": "A",
        "text": "s->next=p->next;p->next=s;"
      },
      {
        "key": "B",
        "text": "p->next=s->next;s->next=p;"
      },
      {
        "key": "C",
        "text": "q->next=s;s->next=p;"
      }
    ],
    "blank_option_groups": [],
    "answer": "C",
    "analysis": "在单链表中，在已知前驱结点a后插入新结点s，应先将s的next指向p，再将a的next指向s。选项C中q即为a，顺序正确。",
    "raw_text": "06.在一个单链表，已知a所指结点是p所指结点的前驱结，若在\\alpha和p之间插入结点\ns,则执行()。\nA. s->next=p->next;p->next=s; B. p->next=s->next;s->next=p;\nC. q->next=s;s-next-p;3D.p-ext=ss-next=q;",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "2.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "ocr_contamination_detected",
      "ocr_quality:symbol_substitution_detected",
      "ocr_quality:option_structure_corrupted",
      "low_confidence",
      "incomplete_options: missing D",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "d34ad259",
    "confidence_score": 0.65,
    "risk_flags": [
      "low_confidence"
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
      "ocr_contamination_detected",
      "ocr_quality:symbol_substitution_detected",
      "ocr_quality:option_structure_corrupted",
      "low_confidence",
      "incomplete_options: missing D",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "d34ad259",
    "risk_flags": [
      "low_confidence"
    ]
  }
}
```

##### 问题
- 同案例一/四：变量 `a` 被 OCR 为 `\alpha`（题干 "在\\alpha和p之间"）
- 选项 D 丢失，题干末尾缺字（"前驱结" 少 "点"）
- 水印背景导致 raw_text 尾部追加了乱码（"3D.p-ext=ss-next=q;" 是选项 D 的 OCR 碎片）

##### 修复
- 与案例一同一修复路径：OCR 后处理（单字母 LaTeX + 选项完整性）
- OCR 碎片清理：raw_text 尾部异常字符截断/清洗

---

#### 案例五

##### 原题(背景含水印)

背景半透明水印内容："后续关注公众号[研大]" "永久微信xxxx" 

```tex
给定有 n 个元素的一维数组，建立一个有序单链表的最低时间复杂度是( )。

A. O(1)			B. O(n)			C. O(m)			D. O(n+m)
```

##### 前端内容显示

```tex
给定有 n 个元素的一维数组，建立一个有序单链表的最低时间复杂度是( )。

A. O(1)
B. O(n)
D. O(nlog2n)
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "给定有 n 个元素的一维数组，建立一个有序单链表的最低时间复杂度是( )。"
  },
  "parsed_options": {
    "A": "O(1)",
    "B": "O(n)",
    "D": "O(nlog2n)"
  },
  "parsed_answer": "B",
  "parsed_analysis": "当原数组有序时，依次插入即可建立有序链表，时间复杂度为O(n)；若原数组无序，则最低时间复杂度为O(n^2)或O(nlogn)，但题目问“最低”，故取最好情况。"
}
```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "给定有 n 个元素的一维数组，建立一个有序单链表的最低时间复杂度是( )。",
    "options": [
      {
        "key": "A",
        "text": "O(1)"
      },
      {
        "key": "B",
        "text": "O(n)"
      },
      {
        "key": "C",
        "text": ""
      },
      {
        "key": "D",
        "text": "O(nlog2n)"
      }
    ],
    "blank_option_groups": [],
    "answer": "B",
    "analysis": "当原数组有序时，依次插入即可建立有序链表，时间复杂度为O(n)；若原数组无序，则最低时间复杂度为O(n^2)或O(nlogn)，但题目问“最低”，故取最好情况。",
    "raw_text": "07. 给定有 n 个元素的一维数，建立一个有序单链表的最低时间复杂度是( )。\nA. 0(1) B. 0n)[95C @() 7888D. 0(nlog2n)",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "2.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "incomplete_options: missing C,D",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "7a1d359d",
    "confidence_score": 0.5,
    "risk_flags": [],
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
      "incomplete_options: missing C,D",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [
      "单链表",
      "时间复杂度",
      "有序链表建立"
    ],
    "difficulty": 3,
    "stem_hash": "7a1d359d",
    "risk_flags": null
  }
}
```


##### 问题
- 原题选项 C（O(m)）和 D（O(n+m)）被 OCR 完全破坏：C 为空，D 变为 O(nlog2n)
- raw_text 严重污染（"0(1)""0n)[95C @() 7888D"），OCR 基本不可读
- AI 标准化正确提取了答案和解析，说明 AI 可修正重度 OCR 污染

##### 修复
- OCR confidence < 0.6 时优先信赖 AI 标准化结果而非 OCR 原始字段
- 选项完整性校验：选项为空或格式异常时触发 AI 重新补全

---
