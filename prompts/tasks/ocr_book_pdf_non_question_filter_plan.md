# OCR/PDF 教材正文误识别为题目专项分析与修复方案

> 日期：2026-06-06  
> 范围：扫描版书籍 PDF / OCR 导入链路  
> 目标：减少教材正文、知识点讲解、例题解析等非题目长文本被误识别为题目、选项或答案解析。

## 1. 背景问题

扫描版教材或辅导书 PDF 导入时，页面中往往同时包含：

- 章节标题、知识点讲解、定义、定理、公式推导；
- 例题、例题解析、证明过程；
- 真实习题、选择题选项、答案区、解析区。

当前系统在 OCR 与结构化过程中，存在将教材正文编号、知识点段落、例题解析等长文本误识别为题目或答案解析的风险。虽然最终入库前仍经过 `question_imports` 与人工确认，但批量审核场景下，低质量候选题仍可能污染正式题库。

## 2. 当前链路概览

主要链路：

1. 导入 API 接收 PDF / 图片 / 文本；
2. pipeline orchestrator 执行文本提取或 OCR；
3. OCR service 进行图像预处理、PaddleOCR、文本框提取、阅读顺序排序；
4. exercise region detector 尝试识别习题区域；
5. structure analyzer / page classifier 分析章节、题目区、答案区、知识点页；
6. question splitter 根据题号、选项、答案等信号切分题目；
7. question normalizer 标准化字段；
8. ai repair / ai validation 修复低置信题目或标记风险；
9. review service 写入 `question_imports`，等待人工确认。

相关职责文件：

- `backend/app/api/v1/imports.py`：导入 API 入口。
- `backend/app/features/pipeline_orchestrator.py`：统一导入流水线，包含 OCR fallback、split、repair、review 提交流程。
- `backend/app/services/ocr_service.py`：OCR 图像处理、识别、boxes、阅读顺序。
- `backend/app/features/exercise_region_detector.py`：OCR 前习题区域轻量检测。
- `backend/app/features/page_classifier.py`：按页分类 QUESTION / ANSWER / KNOWLEDGE / CATALOG 等。
- `backend/app/features/structure_analyzer.py`：章节、习题区、答案区结构分析。
- `backend/app/features/question_splitter.py`：题号边界、正文过滤、选项抽取。
- `backend/app/features/question_normalizer.py`：题目标准化。
- `backend/app/features/ai_repair.py`：低置信、缺字段题目的 AI 修复。
- `backend/app/features/ai_validation.py`：AI 结果校验与风险标记。

## 3. 分析结论

### 3.1 OCR 层不承担语义区域判断

`ocr_service.py` 主要能力是：

- 图像预处理；
- PaddleOCR 文本识别；
- OCR boxes 保留；
- 双栏或多行阅读顺序排序；
- 基础文本清洗。

它不具备稳定判断“这一块是教材正文”或“这一块是真实题目区域”的语义能力。OCR 层本身不是污染的唯一根因，但它会把页面所有可识别文本交给后续阶段。

### 3.2 习题区域检测漏检后，全本 OCR 放大污染面

`exercise_region_detector.py` 是 OCR 前减少正文混入的关键防线。问题在于：当习题区域未命中时，`pipeline_orchestrator.py` 可能回退到全本 OCR。

这会导致教材正文、知识点讲解、例题解析等大段文本全部进入 page classification、structure analysis 和 question split 阶段。

### 3.3 页级分类难以处理混合页面

`page_classifier.py` / `structure_analyzer.py` 更适合处理整页倾向明显的页面，例如纯习题页、纯答案页、目录页、知识点页。

但教材常见页面结构是：

- 上半页知识点讲解，下半页习题；
- 左栏例题解析，右栏练习题；
- 同页包含标题、公式推导、例题、习题。

少量题号、A-D 字母、答案 / 解析关键词，可能提升页面被判定为 QUESTION 或 ANSWER 的概率，从而让正文进入题目切分范围。

### 3.4 question_splitter 已有正文过滤，但依赖上游质量

审计确认：`question_splitter.py` 并非完全没有正文过滤，它已有章节号、散文正文、`content_pages` 等过滤逻辑。

但这些规则依赖上游结构识别结果。如果正文页未被正确标记为 content / knowledge，教材中的编号段落仍可能被误判为题号边界，例如：

- `1.`
- `1、`
- `1)`
- `（1）`

尤其当段落附近出现“答案”“解析”“A/B/C/D”等文本时，误判概率会进一步升高。

### 3.5 AI repair 不应承担正文过滤职责

`question_normalizer.py`、`ai_repair.py`、`ai_validation.py` 主要用于修复或校验已被认为是题目的结构化结果。

风险在于：如果正文型文本已经被前序阶段创建为低置信候选题，AI repair 可能尝试补全字段，把非题目内容进一步“修成题目”。这会带来两类问题：

- 增加 DeepSeek token 成本；
- 把原本应丢弃的正文污染物转化为更像题目的候选项，增加人工误发布风险。

## 4. 根因归纳

根因不是单纯的 OCR 识别错误，而是导入流水线的容错策略过宽：

> 习题区域检测漏检后回退全本 OCR；结构分析未能稳定排除正文；无明确题目边界时仍可能创建低置信待审核题；AI repair 又可能继续修补污染内容。

关键问题是：系统目前更倾向于“尽量生成候选题供人工确认”，而扫描版教材导入场景需要更保守，应优先避免正文进入 review queue。

## 5. 影响范围

### 5.1 数据污染

非题目文本可能进入 `question_imports`。如果人工确认页批量发布或标识不明显，正式 `questions` 题库可能被污染。

### 5.2 答案错配

正文中的“答案”“解析”“例题解法”等词可能被识别为答案区，导致真实题目与错误解析匹配。

### 5.3 去重失效

hash / dedup 只能识别重复文本，不能判断文本是否为真实题目。正文型伪题如果内容不同，仍会作为新候选题出现。

### 5.4 chunk / resume 污染扩散

大 PDF 分块处理或恢复导入时，如果每个 chunk 都在无边界情况下创建低置信题，可能重复扩大 review queue 污染。

### 5.5 性能与成本

全本 OCR 会放大扫描版 PDF 耗时；正文进入 AI repair 会额外消耗 DeepSeek token。

## 6. 修复方案规划

### P0：必须先做

#### P0-1：收紧 book 模式 split fallback

位置：`backend/app/features/pipeline_orchestrator.py`

目标：在 `_run_split()` fallback 创建低置信 review item 前增加保护。

建议规则：

- 当 `import_mode == book`；
- 且没有明确题号边界、习题区域边界或视觉边界；
- 且文本更像正文长段落；
- 则不创建 `question_imports` 候选题；
- 只记录 diagnostics / warning，提示“未检测到明确题目边界，已跳过正文型文本”。

边界要求：

- 不影响 `exam` 整卷导入；
- 不影响 `image` 单题导入；
- 不影响 `txt` 或手动粘贴题目；
- chunked / resume 场景应只记录诊断，不重复创建污染项。

#### P0-2：AI repair 前增加非题目过滤

位置：`backend/app/features/ai_repair.py` 或调用 AI repair 的入口处。

建议跳过条件：

- stem 超长且缺少明确题问；
- 无选项、无答案信号、无题号信号；
- 包含明显正文词：`定义`、`定理`、`知识点`、`证明`、`解法`、`例题`、`如下`、`因此可得` 等；
- 连续解释性长句比例高；
- 缺少选择题结构特征。

处理方式：

- 不调用 AI repair；
- 标记为 skipped / non_question_like；
- 写入 diagnostics，便于后续样本分析。

### P1：建议做

#### P1-1：强化 question_splitter 正文负样本过滤

位置：`backend/app/features/question_splitter.py`

增强方向：

- 对章节标题、知识点标题、定义定理段落降权；
- 对只有教材编号但无题问、无选项、无答案信号的段落跳过；
- 对连续长解释句且缺少题目结构的块跳过；
- 对“例题解析”与“练习题”做更明确区分。

#### P1-2：book 模式习题区域漏检时更保守

位置：`backend/app/features/exercise_region_detector.py` 与 `pipeline_orchestrator.py`

增强方向：

- book 模式下，习题区域检测不到时，不默认全本 OCR 进入题目结构化；
- 可以返回低置信状态，提示用户选择页码范围；
- 或仅允许进入 diagnostics，不进入 review queue。

#### P1-3：人工确认页风险标识

位置：小程序 review / import confirmation 相关页面。

增强方向：

- 对 low_confidence、fallback、no_options、non_question_like 标记醒目展示；
- 批量确认前提示存在低置信项；
- 避免用户误将正文型候选题发布到正式题库。

### P2：后续优化

#### P2-1：利用 OCR boxes 做版面级过滤

位置：`backend/app/services/ocr_service.py`、`exercise_region_detector.py`、`structure_analyzer.py`

方向：

- 根据标题、习题区起点、答案区起点裁剪区域；
- 支持双栏教材局部区域判断；
- 对同页“知识点 + 习题”进行区域级而非页级分类。

#### P2-2：补充可观测性日志

建议日志字段：

- pipeline_id；
- page_index；
- page classification label；
- exercise region 命中 / 未命中原因；
- split boundary 类型；
- fallback reason；
- AI repair reason / skip reason；
- review item 创建原因。

#### P2-3：建立误判样本回归集

样本类型：

- 纯知识点页；
- 章节讲解页；
- 例题解析页；
- 同页知识点 + 习题；
- 纯习题页；
- 答案解析页；
- 图片单题；
- 整卷 exam PDF。

## 7. 暂不建议优先做

短期内不建议：

- 引入新的大型 OCR / 版面分析模型；
- 大规模重构 page classifier 或 structure analyzer；
- 把正文过滤完全交给 AI 判断；
- 取消人工确认流程。

原因：当前更安全的修复路径是先收紧 fallback 和 AI repair 入口，减少污染进入 review queue，再基于日志和样本评估是否需要更复杂的版面分析能力。

## 8. 回归验证清单

必须验证：

- book 模式导入纯知识点页：不生成正文型 `question_imports`；
- book 模式导入章节讲解页：只记录 diagnostics，不进入 review queue；
- book 模式导入真实习题页：仍能正常提取题目；
- 同页“知识点 + 习题”：尽量只提取习题区域；
- exam 模式整卷 OCR：不误阻断正常试题；
- image 单题导入：无题号但有题干 / 选项时仍可进入审核；
- chunked / resume：无题目边界的 chunk 不重复创建污染项；
- AI repair：正文样本文本不触发 token 消耗，真实缺字段题仍可修复。

## 9. 最终 punch list

### 必须先做

- 收紧 `pipeline_orchestrator.py` 中 book 模式 `_run_split()` fallback。
- 在 AI repair 前增加非题目过滤与 skip diagnostics。
- 为 chunked / resume 场景补充无边界跳过行为验证。

### 建议做

- 强化 `question_splitter.py` 正文负样本过滤。
- book 模式习题区域漏检时提示页码范围或低置信导入。
- 前端确认页突出 low confidence / fallback / non-question 风险。
- 增加 pipeline 诊断日志字段。

### 暂不建议做

- 立即引入新 OCR / 版面模型。
- 大规模重构分类器。
- 依赖 AI 完成正文过滤。

## 10. 修复原则

- 优先阻止正文进入 `question_imports`，而不是依赖人工确认兜底。
- book 模式应比 exam / image / text 模式更保守。
- AI repair 只修复“像题目的低质量题”，不修复“像正文的非题目”。
- 所有跳过行为必须写入 diagnostics，方便用户理解和后续调试。
