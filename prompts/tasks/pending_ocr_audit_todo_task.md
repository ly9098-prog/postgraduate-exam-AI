# OCR 系统待做任务（来自成熟度审计）

> 来源：docs/audit/ocr-capability-maturity-audit.md
> 优先级按 ROI（收益/开发成本）排序

---

## P0（立即做）

### 1. 跨图片题目合并 & 连续性检测

**当前瓶颈：** 多图导入时每张图片独立产生审核批次，图片之间题号不连续，选项不跨图。

**预期收益：** 将图片视为连续文档，大幅降低人工审核成本。

**涉及文件：**
- `backend/app/features/batch_image_import_service.py`
- `backend/app/api/v1/admin_imports.py`
- `backend/app/features/batch_validation.py`

---

### 2. OCR 纠错指标追踪

**当前瓶颈：** 当前无任何定量评估纠错效果，无法判断纠错是在改善还是破坏。

**预期收益：** 建立基准线，用数据驱动调优。

**涉及文件：**
- `backend/app/features/ocr_fix/canonical_output.py`
- `backend/app/features/ocr_fix/qwen_adapter.py`
- `backend/app/features/ocr_fix/deepseek_adapter.py`
- `backend/app/features/pipeline_orchestrator.py`（第 1476-1479 行日志切片）

---

## P1（近期做）

### 3. 敏感内容过滤移植到新路由

**当前瓶颈：** 旧版 `ocr_correction.py` 有 `_filter_sensitive()`（电话/邮箱/广告过滤），但新 OCRFixRouter 路径未调用。

**预期收益：** 消除数据合规风险。

**涉及文件：**
- `backend/app/features/ocr_correction.py`（第 330-338 行，旧版 `_filter_sensitive()`）
- `backend/app/features/ocr_fix/router.py`
- `backend/app/features/pipeline_orchestrator.py`（第 1240-1526 行，新路由入口）

---

### 4. 表格结构化解析（基础版）

**当前瓶颈：** `\begin{tabular}` 等 LaTeX 表格被当作纯文本处理，无行列/单元格解析。

**预期收益：** 支持简单单元格提取和行列结构。

**涉及文件：**
- `backend/app/features/ocr_service.py`（第 45-47 行，现有 ocr_table() 存根）
- `backend/app/services/formula_normalizer.py`

---

## P0 Bug（来自真实案例回归审计）

> 来源：`docs/audit/ocr-real-case-regression-audit.md`
> 5 张真实 408 真题图片经 PaddleOCR → clean_ocr_text → TextNormalizer → QuestionSplitter → AnswerMatcher 全链路追踪，**0/5 成功导入**。

### 5. TextNormalizer._normalize_punctuation CJK 字符丢失

**当前瓶颈：** `text_normalizer.py:555` 第二遍 `_RE_CJK_PUNCT.sub` 的 lambda 只返回标点符号，丢弃 group(1) 的 CJK 字符，导致"单链表中"→"单链表"、"前驱结点"→"前驱结"、"表尾指针"→"表尾指"。

**预期收益：** 修复所有中文题干中紧跟标点的最后一个 CJK 字符被静默删除的问题。

**涉及文件：**
- `backend/app/features/text_normalizer.py`（第 554-560 行，`_normalize_punctuation` 两遍 sub 调用）

**修复方向：** 第二遍 sub 的 lambda 返回值应为 `m.group(1) + 中文标点`，而非仅返回标点。

---

### 6. PaddleOCR 对 C/代码 `->` 指针符号识别不稳定

**当前瓶颈：** 特定字体/排版下，`->` 被 PaddleOCR 识别为 `<-` + 随机字母序列（`xau`/`axau`/`xeu`），导致 408 数据结构真题选项完全不可读。3/5 测试图片（faulty_case_1/2/3）受此影响。

**预期收益：** 408 计算机考研真题是可导入题目的核心科目之一，修复后可显著提升该科目图片导入成功率。

**涉及文件：**
- `backend/app/services/ocr_service.py`（`clean_ocr_text` 清洗层，可增加 `->` 修复规则）
- `backend/app/features/text_normalizer.py`（`_fix_pointer_arrows` 第 432 行，当前仅处理 `− >`→`->` 全角箭头）

**修复方向：** 在 `clean_ocr_text` 或 `_fix_pointer_arrows` 中增加 OCR 常见 `->` 乱码模式修复（`xau<-`、`axau<-` 等模式匹配）。

---

### 7. PaddleOCR 两栏排版按列读取 → 选项错序

**当前瓶颈：** 两栏排版的选项被 OCR 按列读取（B→A→D→C），`_detect_column_split` 未检测到分栏（gap 不满足 `image_width * 0.04` 阈值）。1/5 测试图片（success_case.png）受此影响。

**预期收益：** 覆盖两栏排版场景，修复选项顺序。

**涉及文件：**
- `backend/app/services/ocr_service.py`（`_detect_column_split` 第 371-393 行，gap 阈值 `image_width * 0.04`）
- `backend/app/features/question_splitter.py`（`_split_merged_two_column_questions` 第 1074 行，文本级两栏修复，当前有代码但未经真实图片验证）

**修复方向：** 放宽 `_detect_column_split` 的 gap 阈值或增加回退逻辑；验证 `_split_merged_two_column_questions` 对真实图片两栏文本是否生效。

---

### 8. PaddleOCR 低置信度水印文本未过滤

**当前瓶颈：** 水印与正文重叠区域 OCR 置信度低至 0.51，但 `ocr_image` 仍将其作为正常文本行输出，与选项合并。1/5 测试图片（watermark_fail_case.png）受此影响。

**预期收益：** 过滤水印污染文本，避免其混入题目正文干扰后续切分和匹配。

**涉及文件：**
- `backend/app/services/ocr_service.py`（`_extract_ocr_lines` 第 347 行，可增加置信度阈值过滤）
- `backend/app/features/text_normalizer.py`（`_filter_watermark_text` 第 570 行，已有水印过滤但依赖关键词/规则匹配，对随机乱码水印无效）

**修复方向：** 在 OCR 文本行输出阶段增加置信度阈值（如 < 0.6 的行标记为 low_confidence）；增强 `_filter_watermark_text` 对无意义字符串的检测能力。

---

## P1（近期做）

### 9. OCR 回归集补充真实图片 case

**当前瓶颈：** `tests/ocr_regression/cases/` 现有 11 个 case 全部为合成文本（无真实 OCR 输入），覆盖率仅 21/100。新增 5 个真实图片 case（010-014）可覆盖两栏排版、C 代码 OCR 乱码、水印污染等当前零覆盖场景，将覆盖率提升至约 45/100。

**预期收益：** 建立真实 OCR 质量回归基线，防止管道修改引入 OCR 识别质量退化。

**涉及文件：**
- `tests/ocr_regression/cases/010_real_two_column/`（success_case.png）
- `tests/ocr_regression/cases/011_real_code_garbling/`（faulty_case_1.png）
- `tests/ocr_regression/cases/012_real_var_misread/`（faulty_case_2.png）
- `tests/ocr_regression/cases/013_real_pointer_garbling/`（faulty_case_3.png）
- `tests/ocr_regression/cases/014_real_watermark/`（watermark_fail_case.png）

**关键约束：** 每个 case 的 `expected.txt` 必须由人工标注 ground truth（正确题干 + 选项 + 答案），**不可用 `--baseline` 模式生成**，否则会重蹈现有体系 expected=管道输出 → 测试永远 PASS 的覆辙。

**目录结构参考：** `docs/audit/ocr-real-case-regression-audit.md` 第 5 节。
