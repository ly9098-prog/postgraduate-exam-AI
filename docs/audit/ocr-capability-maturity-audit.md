# OCR 系统能力成熟度审计报告

> 审计日期：2026-06-19
> 审计范围：全量 OCR 代码 + 配置 + 接口 + 测试 + 数据流
> 审计方式：基于实际代码静态分析，不做任何修改

---

## 一、总体能力雷达图（文字版）

```
Qwen-VL 多模态纠错：    85%  ████████████████████▌
多图批量导题：           70%  ██████████████████
表格结构恢复：            5%  █▌
版面分析：              70%  ██████████████████
文本规则修复体系：       90%  ████████████████████▊
```

---

## 二、能力矩阵

### 1. Qwen-VL 多模态纠错

| 能力 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| Qwen-VL 接入 | 已实现 | 100% | QwenFixer 完整实现，支持图像压缩（2048px/2MB）、base64 编码、httpx 异步调用 dashscope |
| 图片+OCR文本联合纠错 | 已实现 | 100% | Qwen-VL 接收原始图片 + OCR 文本进行视觉验证，prompt 要求核验而非重新 OCR |
| 模型切换 | 已实现 | 100% | OCRFixRouter 支持 auto/manual 策略，DB 驱动模型配置 |
| 降级策略 | 已实现 | 100% | Qwen-VL → DeepSeek → RuleFixer 三级降级链，自动跳过无 API key 适配器 |
| 失败重试 | 部分实现 | 60% | 链式降级而非重试，无指数退避或重试计数 |
| 结构化输出 | 已实现 | 100% | canonicalize() 统一处理 JSON/Markdown/Plain/Codeblock 四种输出格式 |
| OCR纠错前后对比 | 未实现 | 0% | 仅在日志中截断到 160 字符，无指标追踪、无定量评估 |

### 2. 多图批量导题

| 能力 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| 多图片上传 | 已实现 | 100% | 管理端前端支持拖放/粘贴/多选文件上传，接受 list[UploadFile] |
| 批量OCR | 已实现 | 100% | 编排器逐图独立 OCR → 清洗 → 管线 |
| 并发处理 | 已实现 | 100% | asyncio.Semaphore 控制 1-4 并发，每张图片错误隔离 |
| 跨页合并 | 部分实现 | 30% | PDF 块有重叠去重和跨页选项恢复，但图片之间无跨页合并 |
| 题目连续性判断 | 部分实现 | 50% | 单 PDF 内题号连续性检测，但图片之间不连续 |
| 批量导入题库 | 已实现 | 100% | 每图片独立审核批次，管理端支持批量 approve/reject/publish |

### 3. 表格结构恢复

| 能力 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| 识别表格区域 | 未实现 | 5% | 仅有 ocr_table() 接口存根，抛出 NotImplementedError |
| 保留行列结构 | 未实现 | 0% | 无行列结构恢复代码 |
| 恢复单元格关系 | 未实现 | 0% | 无单元格关系处理 |
| 合并单元格 | 未实现 | 0% | 无 colspan/rowspan 检测 |
| 题目中的表格 | 部分实现 | 20% | LaTeX \begin{tabular} 等被当作普通文本处理，不做结构化解析 |

### 4. 版面分析

| 能力 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| 双栏试卷 | 已实现 | 100% | OCR 层列检测 + 阅读顺序排列 + 问答区域过滤 |
| 左右栏切分 | 已实现 | 100% | _detect_column_split() 通过 bbox 水平间隙检测分栏 |
| 跨栏题目 | 部分实现 | 50% | 散文丢弃隐含处理跨栏，但无显式跨栏合并 |
| 跨页题目 | 已实现 | 100% | 跨页选项恢复 + 分块重叠去重 |
| 页眉页脚过滤 | 已实现 | 100% | Wangdao 坐标感知 + 通用正则双层过滤 |
| 水印过滤 | 已实现 | 100% | 四层：Wangdao 关键词 + 正则 + DB 规则引擎 + 质量门控 |
| 章节标题过滤 | 已实现 | 100% | 章标题 + 大题节标记 + 知识页面分类过滤 |

### 5. 文本规则修复体系

| 能力 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| text_normalizer | 已实现 | 100% | ImportTextNormalizer 15+ 清洗策略，可配置开关 |
| OCR纠错规则 | 已实现 | 100% | 数字/字母混淆纠正（8→B, 0→D, l→1），上下文感知 |
| 公式修复 | 已实现 | 100% | unicode 上下标、希腊字母、9 条常见 OCR 公式修复规则 |
| 符号修复 | 已实现 | 100% | 全角/半角转换、中文标点归一化、弯引号统一 |
| 题号修复 | 已实现 | 100% | OCR 题号错乱修复 + 罗马数字序列检测 + 自动补全候选 |
| 选项修复 | 已实现 | 100% | 选项行校正 + 完整性跨层检查（分割器/归一化/质量门控/批量校验） |

---

## 三、管线总览

完整管线阶段顺序（`pipeline_orchestrator.py` 第 928-951 行）：

```
extract → wangdao_preprocess → normalize_text → ocr_correction
→ analyze_structure → classify_pages → split
→ match → normalize_schema → batch_validation → batch_dedup
→ repair → ai_validation → similarity_match → review
```

涉及 OCR 的关键阶段：

| 阶段 | 方法 | 文件:行号 | 功能 |
|------|------|-----------|------|
| extract | `_ocr_scanned_pdf()` | pipeline_orchestrator.py:1097-1133 | PaddleOCR 扫描页回退 |
| wangdao_preprocess | `_run_wangdao_preprocess()` | pipeline_orchestrator.py:1146 | 水印/页眉/页脚过滤 |
| normalize_text | `ImportTextNormalizer.normalize()` | text_normalizer.py:130 | 所有规则清洗 |
| ocr_correction | `_run_ocr_correction()` | pipeline_orchestrator.py:1240 | AI 纠错（Router 或 Legacy） |
| classify_pages | `_run_classify_pages()` | pipeline_orchestrator.py:1605 | 非题目页面过滤 |
| split | `_run_split()` | pipeline_orchestrator.py:1648 | 跨页合并 + 双栏分裂 |
| batch_validation | `_run_batch_validation()` | pipeline_orchestrator.py:2067 | 编号连续性验证 |

---

## 四、代码证据

### 1. Qwen-VL 多模态纠错

| 证据 | 文件 | 行号 |
|------|------|------|
| QwenFixer 类 | `backend/app/features/ocr_fix/qwen_adapter.py` | 143-310 |
| OCR 校验 Prompt（8 条规则+9 个检查重点） | 同上 | 27-53 |
| 图像压缩（2048px / 2MB） | 同上 | 113-140 |
| 题干保留保护 `_preserve_stem_from_original()` | 同上 | 64-110 |
| OCRFixRouter 自动降级链 | `backend/app/features/ocr_fix/router.py` | 20, 99-158 |
| 策略解析（auto/manual） | 同上 | 86-98 |
| 结构化输出 `canonicalize()` | `backend/app/features/ocr_fix/canonical_output.py` | 157-223 |
| DeepSeek 文本降级适配器 | `backend/app/features/ocr_fix/deepseek_adapter.py` | 15-127 |
| 长度越界保护 | 同上 | 86-92 |
| 题干丢失检测 | 同上 | 94-110 |
| 规则降级兜底 | `backend/app/features/ocr_fix/rule_adapter.py` | 13-41 |
| 噪声检测 `_detect_noise()` | `backend/app/features/ocr_correction.py` | 69-109 |
| 结构异常检测 `_detect_structure_abnormal()` | 同上 | 117-201 |
| 触发引擎 `_should_correct()` | 同上 | 204-239 |
| DB 驱动模型配置 `resolve_active_model()` | `backend/app/services/model_config_resolver.py` | 27-104 |
| 默认模型 qwen-vl-max（已禁用） | `backend/app/services/admin_ai_config_service.py` | 110-118 |
| 管线纠错阶段入口 | `backend/app/features/pipeline_orchestrator.py` | 1240-1526 |
| 日志切片仅 160 字符（无结构化比对） | 同上 | 1476-1479 |
| 敏感内容过滤（旧版路径未移植） | `backend/app/features/ocr_correction.py` | 330-338 |

### 2. 多图批量导题

| 证据 | 文件 | 行号 |
|------|------|------|
| 管理端前端批量上传页面 | `admin-frontend/src/app/(admin)/imports/batch-image/page.tsx` | 全文 |
| 拖放/粘贴/多选文件 | 同上 | 224 |
| 并发选择器 1-4 | 同上 | 43 |
| 前端轮询进度（2.5s） | 同上 | 53-58 |
| 后端批量上传 API | `backend/app/api/v1/admin_imports.py` | 457-565 |
| 逐文件轻量验证 | 同上 | 438-454 |
| 批量进度查询 API | 同上 | 568-580 |
| 重解析 API | 同上 | 583-596 |
| 批量编排器 `run_batch_job()` | `backend/app/features/batch_image_import_service.py` | 259-317 |
| 单图处理 `_process_source()` | 同上 | 190-256 |
| 并发限制 `clamp_concurrency()`（1-4） | 同上 | 56-60 |
| OCR 文本缓存 | 同上 | 155-158 |
| 异步 OCR `asyncio.to_thread(ocr_image)` | 同上 | 139 |
| BATCH_IMAGE_MAX_FILES=100 | `backend/app/core/config.py` | 61 |
| BATCH_IMAGE_DEFAULT_CONCURRENCY=2 | 同上 | 62 |
| 小程序仅单文件 `count: 1` | `miniprogram/pages/import/import.js` | 91, 119 |

### 3. 表格结构恢复

| 证据 | 文件 | 行号 |
|------|------|------|
| ocr_table() 接口存根 → NotImplementedError | `backend/app/features/ocr_service.py` | 45-47 |
| 对应测试确认存根 | `tests/test_services/test_ocr_service.py` | 801-804 |

### 4. 版面分析

| 证据 | 文件 | 行号 |
|------|------|------|
| 双栏检测 `_detect_column_split()` | `backend/app/services/ocr_service.py` | 371-393 |
| 双栏阅读顺序 `_order_ocr_lines_reading_order()` | 同上 | 396-419 |
| 视觉分栏散文过滤 `filter_book_layout_blocks()` | `backend/app/features/visual_boundary_detector.py` | 96-101 |
| 双栏合并题目分裂 `_split_merged_two_column_questions()` | `backend/app/features/question_splitter.py` | 1074-1173 |
| 跨页选项恢复 `_recover_cross_page_options()` | 同上 | 1240-1300 |
| 分块重叠去重 `_compute_overlap_hash()` | `backend/app/features/pipeline_orchestrator.py` | 621-646 |
| 分块边界截断警告 | 同上 | 1906-1934 |
| 页眉/页脚坐标过滤 `_classify_zone()` | `backend/app/features/wangdao_preprocessor.py` | 85 |
| 页面分类器（7 种页面类型） | `backend/app/features/page_classifier.py` | 229-315 |
| 水印正则 `_RE_WATERMARK` | `backend/app/features/text_normalizer.py` | 68-82 |
| 章标题过滤 `_RE_CHAPTER_HEADER` | 同上 | 84-96 |
| DB 驱动水印规则引擎 | `backend/app/services/watermark_service.py` | 全文 |
| 水印规则快照机制 | `pipeline_orchestrator.py` | 2845-2863, 3268-3308 |
| 大题节标记 `_SECTION_MARKER_PATTERNS` | `backend/app/features/structure_analyzer.py` | 44-48 |
| 软散文检测 `_looks_like_book_soft_prose()` | `backend/app/features/question_splitter.py` | 114-181 |

### 5. 文本规则修复体系

| 证据 | 文件 | 行号 |
|------|------|------|
| ImportTextNormalizer 类 | `backend/app/features/text_normalizer.py` | 108 |
| normalize() 主入口 | 同上 | 130 |
| `_clean_newlines()` 行合并 | 同上 | 172-255 |
| `_clean_garbled()` 乱码移除 | 同上 | 257-268 |
| `_correct_ocr_errors()` 数字/字母混淆 | 同上 | 285-430 |
| `_fix_option_line()` 选项行修复 | 同上 | 323 |
| `_fix_question_number_line()` 题号行修复 | 同上 | 336 |
| `_fix_roman_numeral_duplicates()` 罗马数字重复修复 | 同上 | 379 |
| `_fix_pointer_arrows()` C 指针箭头修复 | 同上 | 432 |
| `_fix_latex_substitutions()` 上下标转换 | 同上 | 489 |
| `_normalize_punctuation()` 符号归一化 | 同上 | 524-567 |
| `_filter_watermark_text()` 水印过滤 | 同上 | 570-634 |
| `fix_ocr_formula()` 公式修复 | `backend/app/services/formula_normalizer.py` | 109-126 |
| 9 条常见 OCR 公式修复规则 | 同上 | 89-105 |
| PDF 文本行合并 `merge_broken_lines()` | `backend/app/services/pdf_text_normalizer.py` | 65 |
| PDF 去重 `deduplicate_repeated_text()` | 同上 | 96 |
| 选项归一化 `_normalize_options()` | `backend/app/features/question_normalizer.py` | 117 |
| 选项完整性检查 | 同上 | 273 |
| OCR 题号模式 `_OCR_Q_PATTERN`（l/I→1） | `backend/app/features/question_splitter.py` | 35 |
| OCR 选项映射 `_OCR_OPTION_MAP` | 同上 | 57 |
| 批量编号连续性 `_check_number_continuity()` | `backend/app/features/batch_validation.py` | 31 |
| 罗马数字序列检测 `_check_roman_numeral_sequence()` | 同上 | 116 |
| 罗马数字 schema `classify_roman_issue()` | `backend/app/features/roman_schema.py` | 56 |
| OCR 污染检测 `detect_ocr_contamination()` | `backend/app/features/ocr_quality_gate.py` | 111 |
| 策略配置 `_load_ocr_strategies()` | `backend/app/features/text_normalizer.py` | 1191 |
| 管线编排 `ImportPipeline` | `backend/app/features/pipeline_orchestrator.py` | 897-951 |

---

## 五、优先级建议

按 ROI（收益 / 开发成本）排序。

### P0（立即做）

| # | 项目 | 当前瓶颈 | 预期收益 |
|---|------|----------|----------|
| 1 | **跨图片题目合并 & 连续性检测** | 多图导入时每张图片独立产生审核批次，图片之间题号不连续，选项不跨图 | 将图片视为连续文档，大幅降低人工审核成本 |
| 2 | **OCR 纠错指标追踪** | 当前无任何定量评估纠错效果，无法判断纠错是在改善还是破坏 | 建立基准线，用数据驱动调优 |

### P1（近期做）

| # | 项目 | 当前瓶颈 | 预期收益 |
|---|------|----------|----------|
| 3 | **敏感内容过滤移植到新路由** | 旧版 `ocr_correction.py` 有 `_filter_sensitive()`（电话/邮箱/广告过滤），但新 OCRFixRouter 路径未调用 | 消除数据合规风险 |
| 4 | **表格结构化解析（基础版）** | `\begin{tabular}` 等 LaTeX 表格被当作纯文本处理 | 支持简单单元格提取和行列结构 |

### P2（可延后）

| # | 项目 | 说明 |
|---|------|------|
| 5 | **纠错 A/B 测试框架** | 需要指标追踪（P0#2）作为前提，目前设计实验框架为时过早 |
| 6 | **完整表格恢复（合并单元格/复杂表格）** | 考研题目中表格占比低，ROI 低 |
| 7 | **Qwen-VL 显式重试 + 指数退避** | 当前降级链已能覆盖失败场景，边际收益有限 |
| 8 | **图片上传前可视化预览 & 排序** | 改善体验但非功能缺失 |

---

## 六、系统成熟度总结

**强项（80-100%）：文本规则修复体系、Qwen-VL 多模态纠错**
- 形成了"规则预处理 → AI 视觉验证 → AI 文本降级 → 规则兜底"的四层防线
- ImportTextNormalizer 15+ 策略可配置，覆盖数字/字母混淆、公式、符号、题号、选项等维度
- Qwen-VL 集成完整，含图像压缩、结构化输出、题干保留保护

**中项（60-80%）：版面分析、多图批量导题**
- 双栏检测（bbox 分析 + 阅读顺序排序）和跨页恢复机制成熟
- 水印过滤四层体系（关键词 + 正则 + DB 引擎 + 质量门控）
- 批量导入基础流程完整，但图片之间缺乏关联处理

**弱项（0-30%）：表格结构恢复**
- 仅有 `ocr_table()` 接口存根，抛出 `NotImplementedError`
- LaTeX 表格被当作普通文本，无行列/单元格解析
- 考研题目中表格占比虽低，但不支持影响用户体验

**最值得投入的两个方向**是所有维度的共识：
1. **跨图片处理能力**（将多张图片视为连续文档）
2. **纠错效果可观测性**（用数据指导优化而非凭感觉调参）

---

## 相关链接

- [[docs/audit/AUDIT_INDEX.md|AUDIT_INDEX]] — 审计索引
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
