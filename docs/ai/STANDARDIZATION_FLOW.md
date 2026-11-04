# Question Normalization

## 架构（单 pipeline）

题目可能来自 OCR PDF、AI 解析、Word、Excel、手动导入。所有入口都走唯一管线
`backend/app/features/question_pipeline.py` 中的 `process_question_pipeline()`（P5-3 已将 AI 补全/丰富/草稿/导入操作拆至 4 个子模块，主文件保留 `QuestionNormalizer` + 向后兼容重导出），
统一标准化、校验、去重，再转换成现有 DB 兼容字段。

```text
Excel / PDF / OCR / AI / 手动编辑
  ↓
16 阶段管线（pipeline_orchestrator.py，P5-2 已拆分 9 个 stage 到 pipeline_stages/）
  ├─ extract → normalize → ocr_correction → analyze_structure → classify_pages
  ├─ split → match → normalize_schema（含 batch_validation + batch_dedup）
  ├─ repair（AI 修复，可选低置信度触发）→ ai_validation
  ├─ similarity_match → math_detect → table_detect → review
  └─ 各阶段支持 checkpoint + artifact resume + quality_report
  ↓
process_question_pipeline(raw, source_type, source)
  → QuestionNormalizer（同文件类，保留向后兼容）
  → question_pipeline 子模块：ai_complete / ai_enrich / draft_generator / import_writer（P5-3 拆出）
  ↓
question_imports 暂存区（含 quality_report、risk_flags、performance_profile）
  ↓ 人工审核（支持低风险批量通过、原图对照预览、公式截图展示）
questions 正式题库
```

原则：

- AI 生成的题目必须经过 question_imports，绝不直接进 questions。
- Level 1 去重已落库：标准化后生成 `question_hash`，导入阶段只标记疑似重复，发布/审核通过阶段再做最终完全重复拦截。
- 质量报告（`quality_report`）和失败归因（`ocr_failure_analyzer`）随 pipeline 结果返回，自动识别 16 种失败类型。

> 2026-05-30 更新原因：同步题库 Level 1 完全重复检测已实现字段与流程。

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
- 不会把圈号/清晰的选项结构行错误合并到题干里（`_extract_stem()` 仅在 `option_lines` 非空时剥离 `_OPTION_LINE_RE` 匹配行，避免无选项时误剥离 `① A. n + 1` 类行）；对 OCR 紧凑文本中的连续题号边界也会保守保留，避免 `Q31 ... Q32 ...` 这类内容被吞并

选项 options 支持：

- dict：`{"A": "..."}`
- list：`[{"key":"A","text":"..."}]` 或 `["选项1","选项2"]`
- 字符串：`A. ... B. ...`、多行 `A:...\nB:...`，以及 OCR 场景下的连写形式如 `① A. n + 1`、`②B. 2n`

输出统一为 `[{"key":"A","text":"..."}]`，缺 key 时按 A/B/C/D 自动补齐；对清晰的连续 inline 选项标记会保守插入换行，但不会破坏圈号/清晰结构行。

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

Level 1 去重为“标准化内容 + Hash 完全匹配”，不做语义相似度判断：

1. 对题干、选项、答案做规则标准化后生成 `question_hash`（MD5，32 位）。
2. 导入写入 `question_imports` 时记录：
   - `question_hash`
   - `duplicate_status`：`normal` / `possible_duplicate`
   - `duplicate_of_question_id`：命中的正式题目 ID
   - `duplicate_of_import_id`：命中的暂存导入题 ID
3. 导入阶段只标记不删除、不拒绝，避免 OCR / AI 解析误差导致误杀。
4. 审核通过 / 发布写入 `questions` 前按 `subject + question_hash` 查询正式题库；命中完全相同 hash 时阻止发布，并返回重复题 ID。
5. 正式题库 `questions.question_hash` 保存最终 hash，供后续导入和发布阶段复用。

日志格式统一使用 `[DuplicateCheck]`，记录题目/导入 ID、hash、检测结果和命中 ID。

暂不实现：Embedding、AI 语义相似度、SimHash、Elasticsearch、向量数据库。

## 数据库兼容

DB 兼容字段：

- `Question.content = {"text": stem}`
- `Question.options = {"A": "..."}`
- `Question.answer = "A"` 或 `"A,C"`
- `Question.question_hash = "<md5>"`（用于完全重复检测）
- `Question.question_type` 为 canonical 值

`question_imports` 仍使用 `parsed_content` / `parsed_options` / `parsed_answer`
/ `parsed_analysis`。pipeline 内部用标准 schema，写库时通过 `to_import_fields`
和 `to_question_fields` 适配。

## 与 OCR / AI 的关系

- OCR 与 PDF 解析（`pdf_classifier` + `ocr_service` + `pdf_text_normalizer`）只负责文本提取、分页、初步切题。
- AI Parser（OpenAI-compatible 网关，Qwen/GLM）输出题型、知识点、难度、答案建议，结果同样进入 pipeline。
- 图片 OCR 导入也必须先经过 `question_imports` 暂存与人工审核，不会因为诊断信息更完整而变成自动入库。
- AI 不可用时 pipeline 仍可正常工作，导入和刷题不依赖 AI。
- 所有 AI 编辑经过 `ai_safety.py` 安全门禁：变更前后 diff + 代码符号保护 + 中文比例检查 + 选项数保护 + 可审计 `AIEditTrace`。

> 2026-06-21 更新：同步 16 阶段管线、P5 拆分、质量报告和 AI Safety Gate。

## 质量报告与失败归因（P6 新增）

每个 pipeline 完成后自动生成 `quality_report`：

| 字段 | 含义 |
|------|------|
| `total_questions` | 总识别题数 |
| `low_risk` | 低风险题数（无 risk_flag） |
| `medium_risk` | 需检查题数（有 risk_flag 但不含高危） |
| `high_risk` | 高风险题数（含高危 risk_flag） |
| `ai_answer_count` | AI 辅助生成答案数 |
| `math_image_count` | 公式截图数 |
| `table_markdown_count` | 表格 Markdown 数 |
| `ocr_cache_hit_rate` | OCR 缓存命中率 |
| `performance_summary` | 各阶段耗时/AI 调用/缓存统计 |

失败归因（`ocr_failure_analyzer.py`）16 种分类，兼容 `risk_flags` 体系，自动识别 math_image_missing / answer_missing / options_anomaly / watermark_noise 等失败类型并给出修复建议。

---

## 相关链接

- [[docs/ai/AI_PIPELINE.md|AI_PIPELINE]] — AI 管线
- [[docs/ai/OCR_STRATEGY.md|OCR_STRATEGY]] — OCR 策略
- [[docs/ai/AI_DEBUG_RULES.md|AI_DEBUG_RULES]] — AI 调试规则
