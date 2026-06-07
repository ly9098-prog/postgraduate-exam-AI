# 王道 408 PDF 245-280 页 OCR 识别问题最小修复方案

> 日期：2026-06-06  
> 范围：`backend/tests/fixtures/wangdao_408.pdf` 第 245-280 页  
> 关联问题：`docs/BUGS.md` 中“书籍扫描类 pdf 识别错误”  
> 目标：减少教材正文被误识别为题目，同时恢复 TCP 选择题 `01-12`、`43-45` 的识别。  
> 审计更新：根据方案审计结果，前置最小回归样本和 P0 diagnostics，避免修复后无法验收或误杀真实题。
> 当前状态：P0 已完成（P0-0 synthetic/golden 回归、P0-1 OCR text fallback、P0-2 book/content 正文编号过滤、P0-3 最小 diagnostics）。聚焦测试 `PYTHONPATH=. pytest tests/test_services/test_question_splitter.py tests/test_services/test_pipeline_orchestrator.py` 已通过：`149 passed, 4 warnings`。
> 2026-06-07 追加：真实导入仍出现 `stage 'extract' failed: PDF 中未提取到文本内容（文本层为空且 OCR 未启用或失败）`，日志显示含框 OCR 和 text fallback 都可能触发 `could not execute a primitive`，需补 P0-4 单页 OCR runtime 失败保底。

## 1. 问题现象

### 1.1 教材正文被误识别为题目

`docs/BUGS.md` 中记录了以下正文型误识别样例：

- `2.快重传和快恢复`
- TCP 拥塞控制、序号、窗口、慢开始、快重传等解释性正文段落

这类文本具有教材章节编号或小节编号，容易匹配题号模式 `^\d+[.、)]`，从而被 `question_splitter` 当成题目边界。

### 1.2 真实题目漏识别

`docs/BUGS.md` 中记录以下真实 TCP 选择题未被正常识别：

- `01-12`：普通 TCP 选择题；
- `43-45`：统考真题选择题。

这些题目具有明确题号、题干和 A/B/C/D 选项，理论上应进入 `question_imports` 人工确认队列。

## 2. 初步根因

问题不是单一 splitter 规则导致，而是以下因素叠加：

1. **OCR 含框页级失败导致真题页丢块**
   - 第 245-280 页 OCR 过程中，多页曾出现 `OCR（含框）... failed: could not execute a primitive`。
   - 36 页最终只产出少量 block，说明部分页文本可能未进入后续 split 阶段。

2. **book 模式正文编号过滤不够稳**
   - `2.快重传和快恢复` 这类教材小节标题会命中题号模式。
   - 如果 page classifier / structure analyzer 没有稳定把页面标记为 content / knowledge，正文编号可能被当成题目起点。

3. **layout filter 对无标题连续题目区支持不足**
   - 当前 `filter_book_layout_blocks()` 更依赖“习题精选/练习题”等 marker，或双栏正文/题目布局。
   - 若页面直接出现 `01.`、`02.`、`43.` 等连续题号和选项，而没有明显习题区标题，可能无法准确裁出题目区域。

4. **缺少稳定验收样本**
   - live OCR 环境不稳定，不能直接作为常规 CI 必过项。
   - 若不先建立 synthetic/golden 样本，P0 修复后无法证明“真实题恢复”和“正文污染下降”同时成立。

## 3. 修复原则

- 优先保证 OCR 失败页不静默丢文本。
- book 模式要比 exam/image/text 更保守地处理教材正文编号。
- 不应单纯增强正文过滤，否则可能进一步漏掉真实选择题。
- 真实选择题的核心结构信号应是：连续题号 + 题问信号 + A/B/C/D 选项。
- 正文过滤必须使用组合条件，不能仅凭 TCP 领域词跳过。
- 不确定的候选应优先保留为低置信，交给 `question_imports` 人工确认。
- 所有跳过、降级、OCR fallback 行为必须写入 diagnostics。
- diagnostics 只记录页码、计数、短 preview，不写入大段 OCR 原文。
- 不把 diagnostics 或整页 OCR 原文混入 `question_imports.ai_metadata` 的题目结构字段。

## 4. P0：必须先做

### P0-0：建立最小 synthetic/golden 回归样本

**目标**：先建立可重复验收基线，避免修复后无法判断是否误杀真实题或仍有正文污染。

**位置**：

优先检查并补充：

- `backend/tests/test_services/test_question_splitter.py`
- `backend/tests/test_services/test_pipeline_orchestrator.py`
- 可选：`backend/tests/ocr_eval/eval_wangdao.py`

**建议样本**：

至少覆盖以下文本结构：

```text
2.快重传和快恢复
采用快重传算法可以让发送方尽早知道个别报文段的丢失...
```

```text
01. 下列关于 TCP 协议的说法，正确的是
A. ...
B. ...
C. ...
D. ...

02. TCP 拥塞控制中，下列说法正确的是
A. ...
B. ...
C. ...
D. ...
```

```text
43. 【2009 统考真题】下列关于 TCP 拥塞窗口的说法，正确的是
A. ...
B. ...
C. ...
D. ...

44. 【2010 统考真题】...
A. ...
B. ...
C. ...
D. ...

45. 【2011 统考真题】...
A. ...
B. ...
C. ...
D. ...
```

**期望**：

- `2.快重传和快恢复` 不应作为正常题目进入候选；
- `01`、`02`、`43`、`44`、`45` 应正常生成题目候选；
- 领域词如 `协议`、`窗口`、`拥塞`、`报文段` 不应单独导致过滤；
- 不依赖 live OCR 作为常规 CI 必过项。

### P0-1：OCR 含框失败时做页级纯文本兜底

**目标**：解决真实题目因 OCR 含框失败而整页丢失的问题。

**位置**：

- `backend/app/services/ocr_service.py`
- 或调用 OCR 的 `backend/app/features/pipeline_orchestrator.py::_ocr_scanned_pdf`

**建议规则**：

当某一页 `ocr_pages_with_boxes` 失败时，不直接丢弃该页，而是：

1. 对该页降级执行普通 OCR / 纯文本 OCR；
2. 保留该页 text block；
3. fallback block 必须带最小结构标记：
   - `page_index: <page_index>`
   - `source: "ocr_text_fallback"`
   - `has_boxes: false`
4. 标记 diagnostics：
   - `ocr_boxes_failed: true`
   - `ocr_text_fallback: true`
   - `ocr_boxes_failed_pages: [...]`
   - `ocr_text_fallback_pages: [...]`

**边界**：

- 只影响 OCR 含框失败页；
- 不改变正常含框 OCR 页；
- 没有 boxes 的 fallback 页不启用 layout filter，但仍可进入 splitter；
- 不影响 text PDF 原生提取路径；
- diagnostics 不记录整页原文；
- chunked / resume 场景按 page 去重合并，避免重复追加同页 block；
- block 合并后仍保持页码顺序；
- 不把 fallback 原文塞入 `question_imports.ai_metadata` 的 diagnostics 字段。

**回归测试**：

新增或补充 `backend/tests/test_services/test_pipeline_orchestrator.py`：

- mock 某些页 `ocr_pages_with_boxes` 抛错；
- 断言该页仍生成 text block；
- 断言 fallback block 包含 `page_index`、`source=ocr_text_fallback`、`has_boxes=false`；
- 断言 diagnostics 包含失败页；
- 断言 chunked/resume 下不会重复合并同一页；
- 断言单页含框失败不会导致整页题目消失。

### P0-4：单页 OCR runtime 失败保底

**目标**：解决真实导入中含框 OCR 与 text fallback 都可能触发 `could not execute a primitive`，最终 extract 阶段判定无文本的问题。

**新增现象**：

`logs.txt` 中同一批第 245-280 页导入出现以下组合信号：

- 多页 `OCR（含框）第 X 页失败：could not execute a primitive`；
- 第 247/249/250/251/252/253 页又出现 `OCR 第 X 页识别到 N 行文本`，说明纯文本 OCR 曾对部分页成功；
- 最后出现 `OCR fallback unavailable: could not execute a primitive`；
- pipeline 抛出 `stage 'extract' failed: PDF 中未提取到文本内容（文本层为空且 OCR 未启用或失败）`。

**根因判断**：

P0-1 只覆盖“含框 OCR 失败但纯文本 OCR 成功”的场景；当前真实失败还包含 OCR 引擎/图像预处理层面的 runtime primitive error，导致 fallback 批次自身也可能抛错或返回空，最终 `_run_extract()` 看到 `raw_blocks` 为空或文本不足而失败。

**位置**：

- `backend/app/features/pipeline_orchestrator.py::_ocr_scanned_pdf`
- `backend/app/features/pipeline_orchestrator.py::_run_extract`
- `backend/app/services/ocr_service.py::_prepare_ocr_image`
- `backend/app/services/ocr_service.py::_ocr_with_rotation_candidates`

**建议规则**：

1. 含框 OCR 单页失败后，text fallback 仍按页兜底；
2. text fallback 如果对某页或某批抛 `RuntimeError`，不能让整批 extract 直接归零；
3. 对 fallback unavailable 的页写入 diagnostics：
   - `ocr_text_fallback_unavailable_pages: [...]`
   - `ocr_runtime_failed_pages: [...]`
4. OCR 图像预处理或旋转候选触发 primitive error 时，降级尝试未裁剪、未旋转原图 OCR；
5. fallback 仍无文本时只标记失败页，不把空文本 block 写入题目结构；
6. 如果至少有其它页 OCR 成功，应继续进入 splitter，而不是因为单页 fallback runtime error 直接抛 extract 空文本错误。

**边界**：

- 不改变正常含框 OCR 页；
- 不把失败页原文或图片数据写入 diagnostics；
- 不把 diagnostics 混入 `question_imports.ai_metadata` 的题目结构字段；
- 不吞掉整份 PDF 都无文本的真实失败，整批无任何有效文本时仍允许 extract 报错；
- 只把 OCR runtime failure 从“整批打穿”降级为“页级不可用诊断”。

**回归测试**：

补充 `backend/tests/test_services/test_pipeline_orchestrator.py`：

- mock 含框 OCR 失败且 text fallback 对单页抛 `RuntimeError`，断言 pipeline 记录 unavailable 页；
- mock 部分页 fallback 成功、部分页 fallback 失败，断言成功页 block 保留且失败页不导致整批 extract 失败；
- 断言 diagnostics 不包含整页 OCR 原文。

### P0-2：收紧 book 模式正文编号误判

**目标**：避免 `2.快重传和快恢复` 等教材标题被当成正常题目，同时不误杀真实 TCP 选择题。

**位置**：

- `backend/app/features/question_splitter.py`

**建议规则**：

在 `import_mode == "book"` 时，遇到 `^\d+[.．、)]` 题号候选，只有同时满足以下组合条件，才允许跳过或降权：

1. **无 A/B/C/D 选项结构**；
2. **无明确题问信号**，例如：
   - `下列`
   - `以下`
   - `正确`
   - `错误`
   - `的是`
   - `求`
   - `问`
   - `？`
3. **存在明显教材正文/标题形态**，例如：
   - 小节标题短语；
   - 解释性长句；
   - 连续知识点说明；
   - 缺少题干与选项结构。

以下词只能作为弱信号，不能单独触发过滤：

- `算法`
- `协议`
- `机制`
- `定义`
- `定理`
- `原理`
- `过程`
- `拥塞`
- `报文段`
- `窗口`
- `慢开始`
- `快重传`
- `快恢复`

**处理方式**：

- 明显正文：跳过，写入 `split_diagnostics.prose_skipped`；
- 疑似正文但不确定：保留为低置信候选，打 `book_pdf_prose_like`；
- 有明确选项结构或题问信号：不得因为领域词命中而跳过。

**边界**：

- 仅 book 模式生效；
- 不影响 exam 整卷；
- 不影响 image 单题；
- 不影响 text PDF 原生导入；
- 不影响有明确选项结构的 `01.`、`02.`、`43.` 真题；
- 不直接丢弃不确定候选，优先进入人工确认。

**回归测试**：

在 `backend/tests/test_services/test_question_splitter.py` 增加：

- `2.快重传和快恢复 + 正文解释` 不应生成正常题；
- `01. 下列关于 TCP... A/B/C/D` 必须正常生成题；
- `43. 【2009 统考真题】... A/B/C/D` 必须正常生成题；
- `协议/窗口/拥塞/报文段` 出现在真实题干中时不得被误杀；
- exam 模式下正文编号规则不生效；
- image 单题导入不受 book 模式规则影响。

### P0-3：补充 P0 必需 diagnostics

**目标**：P0 修复本身必须可验收，不能等到 P2 才补观测字段。

**位置**：

- `backend/app/features/pipeline_orchestrator.py::_build_diagnostics`
- OCR 调用结果结构
- split diagnostics

**P0 最小字段**：

```python
diagnostics = {
    "ocr_boxes_failed_pages": [...],
    "ocr_text_fallback_pages": [...],
    "split": {
        "prose_skipped_count": 0,
        "prose_skipped_preview": [...],
    },
}
```

**边界**：

- preview 限制 80 字以内；
- 不写整页 OCR 原文；
- chunked / resume 下只聚合计数和页码；
- 不污染 `question_imports.ai_metadata` 的题目结构字段。

## 5. P1：建议做

### P1-1：增强 layout filter 对连续题号区域的识别

**目标**：页面没有“习题精选/练习题”等 marker 时，也能识别真实题目区域。

**位置**：

- `backend/app/features/visual_boundary_detector.py::filter_book_layout_blocks`

**当前不足**：

现有过滤逻辑主要依赖：

- 习题 marker + 后续题号；
- 双栏：一侧正文、一侧题目。

但 `wangdao_408.pdf` 相关页可能直接出现：

```text
01. 下列关于...
A. ...
B. ...
C. ...
D. ...

02. TCP 规定...
A. ...
B. ...
C. ...
D. ...
```

未必有明显习题区标题。

**建议新增信号**：

无 exercise marker 时，如果检测到以下高置信结构，才从题目区域附近开始保留：

- 连续至少 2 个题号，例如 `01.`、`02.`；
- 或连续真题题号，例如 `43.`、`44.`、`45.`；
- 且每题附近有至少 3 个 A/B/C/D 选项；
- 或局部区域内 A/B/C/D 选项密度高。

**裁剪策略**：

- 触发后不要机械地从第一个题号行精确裁剪；
- 裁剪起点应向前保留少量同页 block，避免裁掉共用题干、表格说明、真题年份说明；
- 宁可多留少量正文，也不要裁掉题干依赖文本；
- 无高置信信号时不裁剪，只记录 diagnostics。

**边界**：

- 只在 `book + pdf + boxes` 下启用；
- 必须满足“连续题号 + 选项密集”，避免正文编号误入；
- 无高置信信号时不破坏性裁剪；
- 不影响 exam/image/text；
- 对没有 boxes 的 OCR text fallback 页不启用 layout filter。

**回归测试**：

新增 synthetic block：

- 上半页为 TCP 知识点正文；
- 下半页从 `01.` 开始连续选择题；
- 题目区域前有一小段共用说明；
- 断言 layout filter 从说明或 `01.` 前少量 block 开始保留；
- 断言正文 `快重传和快恢复` 被过滤掉；
- 断言无高置信连续题号时不裁剪。

### P1-2：建立 245-280 页可选 OCR eval

**目标**：把本次 BUG 固化为真实 PDF 回归验证，但不把不稳定 live OCR 作为常规 CI 必过项。

**位置**：

优先检查并补充：

- `backend/tests/ocr_eval/eval_wangdao.py`

**建议期望**：

pages `245-280` 应包含题号：

```text
01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 43, 44, 45
```

不应包含正文污染：

```text
2.快重传和快恢复
采用快重传算法可以让发送方尽早知道
```

**测试策略**：

- synthetic/golden text 测试作为常规 CI 基线；
- 真实 PDF 页范围作为可选 OCR eval；
- live OCR 环境不稳定时不作为常规 CI 必过项。

## 6. P2：后续可观测性补强

### P2-1：扩展 OCR 与 split diagnostics

**目标**：在 P0 最小 diagnostics 基础上，进一步区分“OCR 丢页”“layout 裁剪”和“split 过滤”。

**位置**：

- `backend/app/features/pipeline_orchestrator.py::_build_diagnostics`
- OCR 调用结果结构
- split diagnostics

**建议字段**：

```python
diagnostics = {
    "ocr_failed_pages": [...],
    "ocr_boxes_failed_pages": [...],
    "ocr_text_fallback_pages": [...],
    "ocr_block_counts_by_page": {...},
    "split": {
        "prose_skipped_count": 0,
        "prose_skipped_preview": [...],
        "layout_filter": {
            "enabled": true,
            "trimmed": false,
            "kept_blocks": 0,
            "dropped_blocks": 0,
            "reason": "...",
        },
        "visual_boundary": {...},
    },
}
```

**边界**：

- preview 限制 80 字以内；
- 不写整页 OCR 原文；
- chunked / resume 下只聚合计数和页码；
- 不污染 `question_imports.ai_metadata` 的题目结构字段；
- diagnostics 字段只用于导入诊断，不改变题目 JSON 结构。

## 7. 推荐实施顺序

1. **P0-0：建立最小 synthetic/golden 回归样本**
   - 先固定验收基线，确保后续修复可证明。

2. **P0-1：OCR 含框失败页纯文本兜底**
   - 先解决真实题目根本拿不到文本的问题。

3. **P0-2：收紧 book 模式正文编号误判**
   - 使用组合条件解决 `2.快重传和快恢复` 这类正文误入，避免领域词误杀真题。

4. **P0-3：补 P0 必需 diagnostics**
   - 确保 OCR fallback 和 prose skip 可验收。

5. **P1-1：layout filter 增加连续题号 + 选项密集信号**
   - 提升混合页面中真实题目区域识别，裁剪边界保持保守。

6. **P1-2：加入 245-280 页可选 OCR eval**
   - 防止后续真实 PDF 场景再次回归。

7. **P2-1：扩展 diagnostics**
   - 用于后续真实 PDF OCR 问题定位。

## 8. 回归验证清单

必须验证：

- book 模式导入第 245-280 页时，真实题目 `01-12`、`43-45` 能进入候选；
- `2.快重传和快恢复` 不作为正常题目进入 `question_imports`；
- 有明确 A/B/C/D 选项的 `01.`、`43.` 不被正文过滤误杀；
- `协议`、`窗口`、`拥塞`、`报文段` 等领域词出现在真实题干中时不触发跳过；
- OCR 含框失败页能降级保留文本；
- fallback block 能标记 `page_index`、`source=ocr_text_fallback`、`has_boxes=false`；
- chunked / resume 场景不会重复合并同一页 fallback block；
- layout filter 在无高置信信号时不破坏性裁剪；
- layout filter 触发裁剪时保守保留题目前置说明；
- exam 模式不受 book 模式正文编号规则影响；
- image 单题导入不受 book 模式规则影响；
- text PDF 原生提取路径不受 OCR fallback 影响；
- diagnostics 能看出 OCR fallback 页码和 prose skip 计数；
- `question_imports.ai_metadata` 不写入整页 OCR 原文，不混入 diagnostics 大字段。

## 9. 最小验收标准

本轮最小修复完成后，至少满足：

- synthetic/golden 样本中 `01`、`02`、`43`、`44`、`45` 均能生成候选；
- synthetic/golden 样本中 `2.快重传和快恢复` 不生成正常题；
- book PDF 245-280 页候选包含 `01-12`、`43-45`；
- 含框 OCR 单页失败后仍产生该页 text block；
- exam/image/text 导入模式测试不变；
- diagnostics 可区分：
  - OCR boxes 失败；
  - text fallback；
  - prose skipped；
  - layout filter 裁剪；
- `question_imports.ai_metadata` 不写入整页 OCR 原文，不混入 diagnostics 大字段。

## 10. 不在本轮范围

- 引入新的 OCR / 版面模型；
- 大规模重构 `page_classifier.py` / `structure_analyzer.py`；
- 取消 `question_imports` 人工确认流程；
- 依赖 AI 判断正文或题目；
- 把 live OCR 不稳定测试设为常规 CI 必过项；
- 为不确定正文候选做自动删除或自动入库。
