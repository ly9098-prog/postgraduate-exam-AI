# 当前任务：OCR 图片题目导入成功率提升

## 当前阶段

已从最初的“先审计、不要改代码”阶段，推进到 **OCR 导入链路 P0/P1 能力增强与回归验证阶段**。

当前重点不再是单纯提高 OCR 字符识别率，而是提高“题目图片导入成功率”：用户上传考研 408 题目截图后，系统尽可能自动恢复题号、题干、选项、答案、解析，并进入人工审核导入流程。

## 核心边界

- 不做纯 AI 自动入库。
- 所有导入结果必须进入 `question_imports` 人工确认流程。
- OCR 负责提取文本，规则解析负责结构恢复，AI 只作为辅助修复/标准化能力。
- 优先采用确定性规则和最小改动，不引入不必要的新依赖或大规模重构。

## 已完成任务

### 1. OCR 架构审计

已完成当前 OCR 导入链路审计，覆盖：

- OCR 引擎与启用条件。
- 图片预处理能力。
- OCR 文本标准化。
- 题目切分。
- 答案匹配。
- 导入审核边界。
- 错误分类与诊断输出。

### 2. 图片预处理增强

已完成多项图片 OCR 预处理增强：

- 自动旋转候选。
- 倾斜校正。
- 去噪。
- 锐化。
- 对比度增强。
- 灰度化。
- 图片放大。
- 文本区域裁剪。
- 双栏/多栏阅读顺序重排。

### 3. OCR 运行时诊断与失败分类

已完成 OCR 导入诊断增强：

- 区分空 OCR 文本。
- 区分切题失败。
- 区分缺少选项。
- 区分管线异常。
- 保留原始文本、清洗文本、切分结果等调试信息。
- 记录 OCR 阶段指标与导入诊断信息。

### 4. 结构分析器接入导入管线

已完成 `analyze_structure` 接入导入管线：

- 在 `normalize_text` 后新增结构分析阶段。
- 将结构分析结果传入 `split_questions(..., structure=structure)`。
- 将结构分析结果传入 `match_answers(..., structure=structure)`。
- 在 diagnostics 中输出结构分析结果。

### 5. INLINE / SEPARATED / UNKNOWN 结构识别增强

已完成规则型结构识别增强：

- 识别题目与答案交错的 `INLINE` 模式。
- 识别题目前置、答案后置的 `SEPARATED` 模式。
- 对无答案或结构不明文本返回 `UNKNOWN`。
- 输出题目页、答案页、解析页。
- 补充结构诊断字段：
  - `diagnostic_reason`
  - `question_density`
  - `answer_density`
  - `analysis_density`
  - `ocr_noise_signals`
  - `has_question_blocks`
  - `has_answer_blocks`
  - `has_explanation_blocks`

### 6. 分离答案页保护

已完成 `SEPARATED` 场景下的答案页保护：

- 答案页保留给答案匹配器使用。
- 切题阶段不再把纯答案页中的 `1.A / 2.B` 等内容误切成题目。
- `answer_pages` 已按真实页码 `page` 返回，而不是按 `block_index` 返回。

### 7. 回归测试

已补充并通过相关回归测试：

- `structure_analyzer` 结构识别测试。
- OCR 噪声诊断测试。
- 空输入诊断字段测试。
- `answer_pages` 使用真实页码的回归测试。
- `question_splitter` 结构感知切题测试。
- `answer_matcher` 分离答案匹配测试。
- `pipeline_orchestrator` 结构分析接入测试。

最近一次相关测试结果：

```bash
PYTHONPATH=backend python3 -m pytest \
  backend/tests/test_services/test_structure_analyzer.py \
  backend/tests/test_services/test_answer_matcher.py \
  backend/tests/test_services/test_question_splitter.py \
  backend/tests/test_services/test_pipeline_orchestrator.py -q
```

结果：`143 passed, 1 warning`。

### 8. 已提交记录

已完成并提交：

- `4031701 docs: record OCR import diagnostics`
- `a520b80 feat: wire OCR structure into import pipeline`
- `066b0dd fix: complete structure analyzer diagnostics`

### 9. AI OCR Correction Layer 设计与接入

已完成 AI OCR 纠错层实现并接入导入管线：

- 新增 `backend/app/features/ocr_correction.py`，位于 `normalize_text` 与 `analyze_structure` 之间。
- 自动检测 OCR 噪声信号（乱码字符、短行、缺失题号、选项碎片化）。
- 噪声超阈值时调用 DeepSeek AI 修复换行错乱、选项错位、题号缺失、OCR 错字。
- 使用独立 token budget，auto 模式下仅在检测到噪声时触发，不影响正常文本。
- AI 不可用时静默降级，不阻塞管线。
- 修复结果仍进入 `question_imports` 人工审核，不做自动入库。
- `pipeline_orchestrator` 已插入 `ocr_correction` 阶段并输出诊断信息。
- 新增 `backend/app/ai/prompts.py` 中 `ocr_correction` system prompt。
- 20 项回归测试通过。
- 提交：`e88a33b feat: add AI OCR Correction Layer to import pipeline`。

### 10. 真实题库相似匹配纠错

已完成基于已有题库的相似题匹配纠错层：

- 新增 `backend/app/features/similarity_matcher.py`，位于 repair 与 review 之间。
- 加载同科目已有正式题目，使用 difflib 计算相似度比率。
- 相似度 >= 0.85 时附加 `similarity_suggestion` 字段，为人工审核提供参考。
- 仅作为”建议修正”，不自动覆盖或纠正。
- `pipeline_orchestrator` 已插入 `similarity_match` 阶段并输出诊断信息。
- 19 项回归测试通过。
- 提交：`affa30e feat: add similarity matching correction layer to import pipeline`。

### 11. Answer continuation pages 多页答案区扩展

已完成 SEPARATED 模式下多页答案区自动扩展：

- 在首个答案页后，检测后续页是否包含 >= 3 个编号答案模式（如 `26.B\n27.C`）。
- 即使后续页无”参考答案”关键词，也会被纳入 `answer_pages`。
- 遇到非答案页时停止扩展，避免误判。
- 5 项回归测试通过。
- 提交：`0fdca6f feat: add answer continuation pages detection`。

### 12. AI 标准化结果校验

已完成 AI 修复结果的二次校验层：

- 新增 `backend/app/features/ai_validation.py`，位于 repair 与 similarity_match 之间。
- 检测重复题干拼接（difflib 前后半段对比）。
- 检测字段污染（答案/解析标签混入 stem，stem 内容泄漏到 answer）。
- 检测 JSON 结构异常（字段类型错误、选项格式异常、confidence 越界）。
- 检测异常长度（stem 相对原文膨胀或缩短）。
- 结果以 `ai_validation` 字段附加到题目，不阻塞管线。
- 29 项回归测试通过。
- 提交：`a7145ac feat: add AI standardization result validation stage`。

### 13. PaddleOCR 配置优化

已完成 PaddleOCR 参数调优：

- 降低 `det_db_thresh`（0.3→0.2）减少漏检文本行。
- 降低 `det_db_box_thresh`（0.6→0.4）保留更多检测框。
- 增大 `det_db_unclip_ratio`（1.5→1.8）改善整行文本捕获。
- 设置 `drop_score=0.3` 保留低置信但有效的识别结果。
- 提升最小图片宽度至 1500px 以改善密集文字识别。
- 所有参数可通过环境变量配置。
- 提交：`699eee2 feat: optimize PaddleOCR configuration for exam screenshots`。

## 未完成任务

### P0：继续基于真实失败样本定位问题

仍需用户继续提供 OCR 失败样本，针对真实图片逐例分析：

- OCR 是否漏识别。
- 图片质量是否导致识别失败。
- 多栏/非标准排版是否导致顺序错乱。
- 题号、选项、答案、解析是否在结构解析阶段丢失。
- AI 标准化是否产生重复拼接、字段污染或结构错误。

### P0：确认真实图片导入端到端效果

当前规则和测试样本已通过，但仍需用真实失败图片验证：

- 图片上传。
- OCR 识别。
- 文本标准化。
- 结构分析。
- 题目切分。
- 答案匹配。
- AI 标准化。
- `question_imports` 人工审核结果。

### P2：PaddleOCR 进一步优化

参数调优已完成，以下为进一步优化方向：

- 评估是否引入 PP-StructureV2 版面分析能力。
- 建立 OCR 失败样本集与自动评测指标。
- 评估是否需要引入更强 OCR 模型。

## 当前优先级排序

### P0（必须做）

1. 使用真实 OCR 失败样本做根因分析。
2. 验证当前结构分析与切题/匹配增强在真实图片上的端到端效果。
3. 保持所有导入结果进入 `question_imports` 人工审核。
4. 修复真实样本中仍会导致导入失败的结构解析问题。

### P2（后期优化）

1. 引入更强版面分析能力。
2. 建立 OCR 失败样本集与自动评测指标。

## 预计收益

| 优化项 | 状态 | 预计收益 |
| --- | --- | --- |
| 图片预处理增强 | 已完成 | 提升低清、倾斜、弱对比图片识别稳定性 |
| OCR 诊断与失败分类 | 已完成 | 提升问题定位效率，减少”导入失败但原因不明” |
| 结构分析接入管线 | 已完成 | 提升 `INLINE` / `SEPARATED` 文档恢复成功率 |
| 分离答案页保护 | 已完成 | 减少答案页被误切成题目的问题 |
| 空输入诊断补齐 | 已完成 | 提升诊断结构一致性 |
| AI OCR Correction Layer | 已完成 | 对换行错乱、选项错位、题号缺失有潜在较大收益 |
| 题库相似匹配纠错 | 已完成 | 对已有题库覆盖范围内的 OCR 错误有较高纠错参考价值 |
| Answer continuation pages | 已完成 | 解决多页答案区后续页丢失问题 |
| AI 标准化结果校验 | 已完成 | 防止 AI 修复引入重复题干、字段污染、结构异常 |
| PaddleOCR 配置优化 | 已完成 | 降低文本行漏检率，提升密集文字识别精度 |
| 真实失败样本端到端验证 | 进行中 | 预计显著提升实际导入成功率 |
| 版面分析能力 | 未完成 | 对复杂排版（多栏、表格等）有较大收益 |

## 下一步

请继续提供真实 OCR 失败样本。下一步应基于样本逐例输出：

1. OCR 原始识别结果。
2. 图片质量问题。
3. 结构解析失败点。
4. AI 修复/标准化风险。
5. 最小修复方案。
6. 对应回归测试。