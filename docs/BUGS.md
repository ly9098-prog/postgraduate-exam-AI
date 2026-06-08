# OCR 识别后多空选择题第一组空位选项组的 A 选项消失

## 现象

OCR 导入多空选择题后，审核页面展示的题目中，第一组空位（①）的选项组缺少 A 选项，只显示 B/C/D；第二组空位（②）的选项组完整（A/B/C/D）。

## 复现数据

**批次**：`REVIEW_20260607_224650_a1f5ad`，题目 ID `1163`

**原题**：

```
若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。

 ① A. n+1  B. n  C. n−1  D. 1
 ② A. n+1  B. n  C. n−1  D. 1
```

**导入识别后审核页面显示**：

```
若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。

 ① B. n  C. n−1  D. 1
 ② A. n+1  B. n  C. n−1  D. 1
```

## 前端数据

```json
{
  "blankOptionGroups": [
    { "id": "1", "optionKeys": ["B", "C", "D"] },
    { "id": "2", "optionKeys": ["A", "B", "C", "D"] }
  ],
  "parsedContentHasBlankOptionGroups": true,
  "rawDataHasBlankOptionGroups": false
}
```

- `rawDataHasBlankOptionGroups: false` — 原始 OCR 数据中未识别出多空选项组
- `parsedContentHasBlankOptionGroups: true` — AI 标准化后的 parsed_content 中识别出了多空选项组
- 第一组只有 3 个选项（B/C/D），第二组 4 个选项（A/B/C/D）

## 影响范围

- 题型：`multi_blank_choice`（多空选择题）
- 触发条件：OCR 识别后经 AI 标准化，原始 OCR 文本中多空选项组的第一个选项（A）可能被 OCR 识别为题干的一部分（如"① A. n+1"中的"A"被合并到上一行），导致第一组空位的 A 选项丢失

## 可能根因

OCR 文本布局解析或 AI 标准化过程中，第一组空位标记（①）与其后的 A 选项之间的边界处理不当，A 选项被误归入题干或前一组内容。
