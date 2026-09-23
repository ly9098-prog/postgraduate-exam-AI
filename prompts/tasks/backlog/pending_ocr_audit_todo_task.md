> **不要按本文施工（2026-09-23）。** 这是收进 `backlog/` 的历史任务书，不代表当前工作。现行范围见 `docs/project/ROADMAP.md`。

# OCR 系统待做任务（来自成熟度审计）

> 来源：docs/audit/ocr-capability-maturity-audit.md
> 优先级按 ROI（收益/开发成本）排序
> 最后更新：2026-06-19 — 全部完成 ✅

---

## P0（已完成 ✅）

### ✅ 1. 跨图片题目合并 & 连续性检测

**当前瓶颈：** 多图导入时每张图片独立产生审核批次，图片之间题号不连续，选项不跨图。

**预期收益：** 将图片视为连续文档，大幅降低人工审核成本。

**涉及文件：**
- `backend/app/features/batch_image_import_service.py`
- `backend/app/api/v1/admin_imports.py`
- `backend/app/features/batch_validation.py`

**完成日期：** 2026-06-19

---

### ✅ 2. OCR 纠错指标追踪

**当前瓶颈：** 当前无任何定量评估纠错效果，无法判断纠错是在改善还是破坏。

**预期收益：** 建立基准线，用数据驱动调优。

**涉及文件：**
- `backend/app/features/ocr_fix/canonical_output.py`
- `backend/app/features/ocr_fix/qwen_adapter.py`
- `backend/app/features/ocr_fix/deepseek_adapter.py`
- `backend/app/features/pipeline_orchestrator.py`（第 1476-1479 行日志切片）

**完成日期：** 2026-06-19
**产出：** `backend/app/features/ocr_fix/metrics.py`

---

## P0 Bug（已修复 ✅）

> 来源：`docs/audit/ocr-real-case-regression-audit.md`
> 5 张真实 408 真题图片经全链路追踪，**0/5 → 4/5 成功导入**。

### ✅ 5. TextNormalizer._normalize_punctuation CJK 字符丢失

**当前瓶颈：** `text_normalizer.py:555` 第二遍 `_RE_CJK_PUNCT.sub` 的 lambda 只返回标点符号，丢弃 group(1) 的 CJK 字符，导致"单链表中"→"单链表"、"前驱结点"→"前驱结"、"表尾指针"→"表尾指"。

**修复：** 第二遍 sub 的 lambda 返回值改为 `m.group(1) + 中文标点`
**涉及文件：** `backend/app/features/text_normalizer.py:554-560`
**完成日期：** 2026-06-19

---

### ✅ 6. PaddleOCR 对 C/代码 `->` 指针符号识别不稳定

**当前瓶颈：** 特定字体/排版下，`->` 被 PaddleOCR 识别为 `<-` + 随机字母序列（`xau`/`axau`/`xeu`），导致 408 数据结构真题选项完全不可读。

**修复：** 在 `clean_ocr_text` 和 `_fix_pointer_arrows` 中增加 OCR 常见 `->` 乱码模式修复
**涉及文件：** `backend/app/services/ocr_service.py`，`backend/app/features/text_normalizer.py`
**完成日期：** 2026-06-19

---

### ✅ 7. PaddleOCR 两栏排版按列读取 → 选项错序

**当前瓶颈：** 两栏排版的选项被 OCR 按列读取（B→A→D→C），`_detect_column_split` 未检测到分栏。

**修复：** 放宽 `_detect_column_split` 的 gap 阈值并增加文本级两栏修复回退
**涉及文件：** `backend/app/services/ocr_service.py`，`backend/app/features/question_splitter.py`
**完成日期：** 2026-06-19

---

### ✅ 8. PaddleOCR 低置信度水印文本未过滤

**当前瓶颈：** 水印与正文重叠区域 OCR 置信度低至 0.51，但 `ocr_image` 仍将其作为正常文本行输出。

**修复：** 在 OCR 文本行输出阶段增加置信度阈值过滤 + 增强 `_filter_watermark_text`
**涉及文件：** `backend/app/services/ocr_service.py`，`backend/app/features/text_normalizer.py`
**完成日期：** 2026-06-19

---

## P1（已完成 ✅）

### ✅ 3. 敏感内容过滤移植到新路由

**当前瓶颈：** 旧版 `ocr_correction.py` 有 `_filter_sensitive()`（电话/邮箱/广告过滤），但新 OCRFixRouter 路径未调用。

**修复：** 在 `pipeline_orchestrator.py` 的 `_run_ocr_correction_router` 中调用 `_filter_sensitive`，同时从 opts 和 DB `admin_ai_configs` 读取 `ocr_filter_sensitive` 配置
**涉及文件：** `backend/app/features/pipeline_orchestrator.py`
**完成日期：** 2026-06-19

---

### ✅ 4. 表格结构化解析（基础版）

**当前瓶颈：** `\begin{tabular}` 等 LaTeX 表格被当作纯文本处理，无行列/单元格解析。

**修复：** 在 `formula_normalizer.py` 中添加 `parse_latex_table()` 和 `extract_tables_from_text()` 函数，支持行列结构解析、`\multicolumn` 展开、`\hline`/`\cline` 跳过
**涉及文件：** `backend/app/services/formula_normalizer.py`，`backend/app/features/ocr_service.py`
**完成日期：** 2026-06-19

---

### ✅ 9. OCR 回归集补充真实图片 case

**当前瓶颈：** `tests/ocr_regression/cases/` 原有 11 个 case 全部为合成文本（无真实 OCR 输入），覆盖率仅 21/100。

**产出：** 新增 5 个真实图片 case（010-014），覆盖两栏排版、C 代码 OCR 乱码、水印污染等场景
**回归结果：** 4/5 PASS，1/5 DEGRADED（014 水印），平均 CER 0.0220，质量分 97.8/100
**涉及目录：**
- `tests/ocr_regression/cases/010_real_two_column/`
- `tests/ocr_regression/cases/011_real_code_garbling/`
- `tests/ocr_regression/cases/012_real_var_misread/`
- `tests/ocr_regression/cases/013_real_pointer_garbling/`
- `tests/ocr_regression/cases/014_real_watermark/`
**完成日期：** 2026-06-19

---

## 回归测试结果总结

```
综合结果: 16 cases total, 15 PASS, 1 DEGRADED, 0 FAIL
通过率: 94%
平均 CER: 0.0220
平均质量分: 97.8/100
```
