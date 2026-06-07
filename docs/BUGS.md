# 分析ocr识别后多空选择题第一组空位选项组的A选项消失的问题

#### 日志信息

后端日志信息见logs.txt,

前端日志信息：

```
{batchId: "REVIEW_20260607_224650_a1f5ad", questionId: 1163, questionType: "multi_blank_choice", stemPreview: "31．若系统有n个进程，则就绪队列中进程的个数最多有()个；阻塞队列中进程的个数最多有()个。", blankOptionGroupCount: 2, …}
batchId: "REVIEW_20260607_224650_a1f5ad"
blankOptionGroupCount: 2
blankOptionGroups: Array(2)
0:
id: "1"
optionKeys: (3) ["B", "C", "D"]
__proto__: Object
1:
id: "2"
optionKeys: (4) ["A", "B", "C", "D"]
__proto__: Object
length: 2
nv_length: (...)
__proto__: Array(0)
parsedContentHasBlankOptionGroups: true
questionId: 1163
questionType: "multi_blank_choice"
rawDataHasBlankOptionGroups: false
stemPreview: "31．若系统有n个进程，则就绪队列中进程的个数最多有()个；阻塞队列中进程的个数最多有()个。"
__proto__: Object
```

#### 原题

若系统有 n*n* 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。

 ① A. n+1  B. n  C. n−1  D. 1

 ② A. n+1  B. n  C. n−1  D. 1

#### 导入识别后审核页面显示的题目

若系统有 n*n* 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。

 ① B. n  C. n−1  D. 1

 ② A. n+1  B. n  C. n−1  D. 1
