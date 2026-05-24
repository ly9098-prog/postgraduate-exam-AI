# Question Normalization

## 架构（单 pipeline）

题目可能来自 OCR PDF、AI 解析、Word、Excel、手动导入。所有入口都走唯一管线
`backend/app/features/question_pipeline.py` 中的 `process_question_pipeline()`，
统一标准化、校验、去重，再转换成现有 DB 兼容字段。

```text
Excel / PDF / OCR / AI / 手动编辑
  ↓  process_question_pipeline(raw, source_type, source)
QuestionNormalizer（同文件类）
  ↓
question_imports 暂存区
  ↓ 人工审核
questions 正式题库
```

原则：

- 单文件聚合，不再拆 service / helper / utils。
- 不改数据库结构，不引入新 migration。
- AI 生成的题目必须经过 question_imports，绝不直接进 questions。

## 标准 Question Schema

```json
{
  "schema_version": "v1",
  "subject": "math2",
  "question_type": "single_choice",
  "stem": "题干文本",
  "options": [
    {"key": "A", "text": "选项 A"},
    {"key": "B", "text": "选项 B"}
  ],
  "answer": "A",
  "analysis": "解析文本",
  "raw_text": "原始 OCR/导入文本",
  "knowledge_points": ["导数"],
  "difficulty": 3,
  "source": {"file": "source.pdf", "page": 1},
  "is_valid": true,
  "errors": [],
  "warnings": [],
  "stem_hash": "短 hash"
}
```

注意：`schema_version` 必须保留（如 `"v1"`），`raw_text` 始终保留原始导入文本用于追溯。

`process_question_pipeline()` 的返回值在标准 schema 之外还包含 `import_fields`
（写入 `question_imports` 用）和 `question_fields`（写入 `questions` 用）。

## 题型与学科取值

题型标准值：

- `single_choice` / `multiple_choice` / `true_false` / `fill_blank` / `subjective`

兼容别名（自动映射）：

- `choice` / `单选` / `单项选择` → `single_choice`
- `multiple` / `多选` / `多项选择` → `multiple_choice`
- `fill` / `填空` → `fill_blank`
- `判断题` → `true_false`
- `主观题` / `简答` / `论述` / `计算` → `subjective`

学科：`math2` / `exam408` / `english`，支持 `数学二`、`408`、`英语` 等中文别名。

## 清洗规则

题干 stem：

- 全角空格、不可见字符、连续空格
- OCR 错误换行
- 页码、分隔线等噪声行
- 前导题号 `1.` / `1、` / `1)`
- 完全重复行

选项 options 支持：

- dict：`{"A": "..."}`
- list：`[{"key":"A","text":"..."}]` 或 `["选项1","选项2"]`
- 字符串：`A. ... B. ...` 或多行 `A:...\nB:...`

输出统一为 `[{"key":"A","text":"..."}]`，缺 key 时按 A/B/C/D 自动补齐。

答案 answer：

- 单选：`正确答案：C` / `答案是C` / `C` 统一为 `"C"`
- 多选：`A,C` / `["A","C"]` 统一为 `["A","C"]`，落库转字符串 `"A,C"` 兼容现有判分

解析 analysis：去掉 `解析：` / `答案解析：` / `解答：` 等前缀和 OCR 噪声。

## 缺失字段与 invalid

校验后会标记：

- `stem` 为空 → `stem_empty`
- `answer` 为空 → `answer_empty`
- 选择题 `options` 为空 → `options_empty`

invalid 题目在 `import_excel` / `import_pdf` 阶段会跳过 question_imports 写入，
在审核阶段会被批量审批跳过或单条审批抛错。

日志：

```text
Invalid question skipped: source_type=excel file=xxx.xlsx errors=['answer_empty'] stem_hash=xxxx
```

## 去重策略

去重在 service 层完成，不改数据库：

1. 清洗后的 stem 去空白计算 SHA256 短 hash。
2. 审批入库前查询同 subject 现有题目。
3. 比较 stem hash；hash 不同时再用 `difflib.SequenceMatcher` 检测相似题。
4. 重复跳过并写日志：

```text
Duplicate question skipped: source=xxx.xlsx stem_hash=xxxx existing_id=12
```

## 数据库兼容

DB 字段保持不变：

- `Question.content = {"text": stem}`
- `Question.options = {"A": "..."}`
- `Question.answer = "A"` 或 `"A,C"`
- `Question.question_type` 为 canonical 值

`question_imports` 仍使用 `parsed_content` / `parsed_options` / `parsed_answer`
/ `parsed_analysis`。pipeline 内部用标准 schema，写库时通过 `to_import_fields`
和 `to_question_fields` 适配。

## 与 OCR / AI 的关系

- OCR 与 PDF 解析（`pdf_classifier` + `ocr_service` + `pdf_text_normalizer`）只
  负责文本提取、分页、初步切题。
- AI Parser（DeepSeek）输出题型、知识点、难度、答案建议，结果同样进入 pipeline。
- AI 不可用时 pipeline 仍可正常工作，导入和刷题不依赖 AI。
