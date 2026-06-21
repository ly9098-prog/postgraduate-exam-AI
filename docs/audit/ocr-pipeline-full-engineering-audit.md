# OCR Pipeline 全量工程审计报告

> 审计范围：`/home/lmh/projects/postgraduate-ai/backend/`
> 审计时间：2026-06-20（初版） / 2026-06-21（复查更新） / 2026-06-21（P2 完成更新） / 2026-06-21（P4 完成更新） / 2026-06-21（PaddleOCR-VL Adapter）
> 审计方法：全量代码扫描 + 文档审查 + 测试用例分析 + 配置审查
> 状态：P0 修复已全部落地（commit b63df47），P1 公式截图+审核提效已完成（commit c82c464），P2 三项改造已完成（2026-06-21），**P4 真断点恢复+幂等入库已完成（2026-06-21）**。新增 pipeline_artifacts.py 提供文件级 artifact 存储，resume 从 artifact 跳过已完成 stage；hash-based 去重确保同一 pipeline resume 不重复入库；质量报告 `quality_report` 随 pipeline 结果返回。**PaddleOCR-VL Adapter（2026-06-21）**新增外部高精 OCR 引擎适配器，接入 OCRFixRouter 路由链（paddleocr-vl → qwen → deepseek → rule），admin ai-settings 可动态切换。✅ 标记表示已修复项。

---

## 目录

1. [系统架构审计 — 完整数据流](#1-系统架构审计--完整数据流)
2. [代码结构审计](#2-代码结构审计)
3. [LLM 使用审计（重点）](#3-llm-使用审计重点)
4. [失败案例分析](#4-失败案例分析)
5. [性能与成本审计](#5-性能与成本审计)
6. [最终结论](#6-最终结论)

---

## 1. 系统架构审计 — 完整数据流

### 1.1 Pipeline 分层结构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        输入层 (Input Layer)                          │
│  PDF (扫描/文本) │ 单张图片 │ 批量图片 │ TXT │ Excel                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                    入口路由层 (API Router)                            │
│  /api/v1/import/pipeline/upload   → ImportPipeline.run()            │
│  /api/v1/import/image/upload      → import_single_image()           │
│  /api/v1/import/excel/upload      → process_question_pipeline()      │
│  /api/v1/import/image/batch       → batch_image_import_service()     │
│                                                                     │
│  ⚠ 问题: 入口点过多, 相同逻辑有 3 条路径并行存在                      │
│  (旧版 import_service.py / 新版 pipeline / 直接图片导入)              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   OCR 识别层 (PaddleOCR)                              │
│                                                                     │
│  services/ocr_service.py (637行):                                    │
│    ├─ _get_ocr()          → PaddleOCR 单例 (GPU/CPU, 延迟加载)      │
│    ├─ ocr_pages_with_boxes()  → PDF 逐页 OCR + bounding boxes       │
│    ├─ ocr_image()         → 单图 OCR                                 │
│    ├─ ocr_pages()         → 纯文本 OCR (无 box)                     │
│    ├─ ocr_table()         → 表格 OCR                                 │
│    ├─ ocr_math_formula()  → 公式 OCR (LaTeX)                        │
│    │                                                                 │
│    ├─ 预处理层:                                                       │
│    │   _prepare_ocr_image()          → EXIF 转正 + 缩放 + 裁边       │
│    │   _crop_blank_margins()         → 空白边裁剪                     │
│    │   _enhance_image_quality()      → 自适应增强                     │
│    │   _ocr_with_rotation_candidates() → 0°/90°/180°/270° 旋转检测   │
│    │                                                                 │
│    ├─ 版面分析层:                                                     │
│    │   _order_ocr_lines_reading_order()  → 单栏/双栏阅读顺序          │
│    │   _detect_column_split()            → 双栏分割 (gap 阈值)       │
│    │                                                                 │
│    └─ 后处理层:                                                       │
│        clean_ocr_text() → 代码围栏 + 乱码移除 + 箭头修复             │
│                                                                     │
│  输入: PDF路径 / 图片 bytes / numpy image                             │
│  输出: OcrPageResult[] (text, bbox, conf)                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   AI 视觉回退层 (DeepSeek API)                        │
│                                                                     │
│  features/ocr_service.py (293行):                                    │
│    ├─ ocr_fallback()    → 将 PDF 渲染为图片, 调用 DeepSeek 多模态 API │
│    ├─ _call_ocr_api()   → 发送图片 bytes 到 DeepSeek-v4-flash        │
│    └─ _split_ocr_paragraphs() → AI 返回文本的段落分割                │
│                                                                     │
│  输入: PDF 路径 (渲染为图片)                                          │
│  输出: str (段落文本)                                                 │
│                                                                     │
│  ⚠ 问题: PaddleOCR 失败时才触发, 但 DeepSeek Vision API 实际不可用   │
│  (当前仅配置 DeepSeek, 未接 Qwen-VL 视觉入口)                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   规则清洗层 (Rule-based Normalization)               │
│                                                                     │
│  features/text_normalizer.py (707行) — ImportTextNormalizer          │
│    ├─ normalize()              → 统一入口                             │
│    ├─ _normalize_line_breaks() → 换行规范化                           │
│    ├─ _normalize_spaces()      → 空格压缩                             │
│    ├─ _normalize_punctuation() → 全角/半角标点                        │
│    ├─ _remove_garbled_chars()  → 乱码 Unicode 字符移除                │
│    ├─ _correct_ocr_errors()    → OCR 数字/字母混淆修正                │
│    │   (8→B, 0→O/D, l→1, rn→m, cl→d, etc.)                         │
│    ├─ _fix_repeated_roman()    → 罗马数字重复修复                     │
│    ├─ _fix_pointer_arrows()    → C 指针箭头修复 (->)                 │
│    ├─ _fix_answer_block()      → 答案块格式化                         │
│    ├─ _clean_latex()           → LaTeX 标签清理                       │
│    └─ _filter_watermarks()     → 水印/页码过滤                        │
│                                                                     │
│  输入: str (OCR 原始文本)                                             │
│  输出: str (清洗后文本)                                               │
│                                                                     │
│  ⚠ 问题: CJK 字符丢失 bug (已修复, 但历史数据仍受影响)                │
│  clean_ocr_text() 在 services/ocr_service.py 中重复了部分逻辑         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│              OCR 质量门禁层 (Quality Gate)                            │
│                                                                     │
│  features/ocr_quality_gate.py (283行)                                │
│    ├─ assess_quality()         → 统一入口, 返回 OCRQualityReport     │
│    ├─ _detect_symbol_substitution()     → 符号替换检测               │
│    ├─ _detect_garbled_text()            → 乱码序列检测               │
│    ├─ _detect_option_structure_corruption() → 选项结构损坏检测       │
│    ├─ _assess_context()        → 语境感知 (数学/编程/未知)          │
│    └─ score_quality()          → 综合质量分 [0, 1]                  │
│                                                                     │
│  输入: str (清洗后文本)                                               │
│  输出: OCRQualityReport (quality_score, risk_flags[], context)       │
│                                                                     │
│  这是纯规则层, 无 AI。职责清晰, 设计良好。                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│              AI OCR 纠错层 (Multi-Model Correction)                  │
│                                                                     │
│  ✅ 路径已统一 — ocr_correction.py 已精简为向后兼容包装层             │
│                                                                     │
│  唯一路径 — OCRFixRouter (ocr_fix/router.py):                        │
│  ocr_fix/router.py → OCRFixRouter                                    │
│    ├─ PaddleOCRVLAdapter (ocr_vl/, 新增) → 外部高精 OCR API         │
│    │  输入: 原图 bytes → 输出: 完整识别文本                          │
│    │  API: POST /api/v2/ocr/jobs → poll → JSONL 结果                │
│    │  保护: 重试 3 次 + 超时 120s + 全部失败降级到下一适配器          │
│    ├─ QwenFixer (qwen_adapter.py, 309行) → 视觉+文本                 │
│    │  输入: 原图 bytes + OCR 文本 → 输出: 纠正后文本                 │
│    │  保护: _preserve_stem_from_original()                           │
│    ├─ DeepSeekFixer (deepseek_adapter.py, 126行) → 纯文本纠错        │
│    │  输入: OCR 文本 → 输出: 纠正后文本                               │
│    │  保护: 长度越界检查 (0.5x~2x) + 题干丢失保护                     │
│    └─ RuleFixer (rule_adapter.py, 41行) → no-op fallback             │
│                                                                     │
│  AI Safety Gate (ai_safety.py, 284行) — 所有 AI 编辑必经:             │
│    ├─ evaluate_and_trace()  → 变更前后 diff + 安全检查               │
│    ├─ safe_accept_ai_result() → 代码符号/中文比例/选项数保护         │
│    └─ AIEditTrace → 可审计的编辑轨迹 (model, before, after, diff)    │
│                                                                     │
│  ocr_correction.py (171行) — 向后兼容包装:                            │
│    └─ correct_ocr_blocks() → 委托 OCRFixRouter + Safety Gate         │
│                                                                     │
│  视觉回退 (features/ocr_service.py):                                  │
│    OCR 的 AI 视觉 API, 仅用于扫描 PDF 回退                           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   结构分析 & 分割层 (Structure & Split)               │
│                                                                     │
│  structure_analyzer.py (466行)                                       │
│    ├─ analyze_structure()      → Q/A/Analysis 区域检测               │
│    ├─ _detect_section_markers() → 章节标记检测                        │
│    └─ 模式判定: SEPARATED / INLINE / UNKNOWN                         │
│                                                                     │
│  question_splitter.py (1301行)                                       │
│    ├─ split_questions()           → 题号+选项提取, 跨页恢复          │
│    ├─ _detect_question_numbers()  → 多格式题号检测                   │
│    ├─ _extract_options()          → 选项提取 (ABCD/成组/圈号)        │
│    └─ _restore_cross_page_option() → 跨页选项合并                    │
│                                                                     │
│  page_classifier.py → 页面分类 (QUESTION/ANSWER/ANALYSIS...)         │
│  visual_boundary_detector.py → 视觉边界检测回退                      │
│                                                                     │
│  这些模块是纯规则的, 设计合理。                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   答案匹配 & 标准化层 (Match & Normalize)             │
│                                                                     │
│  answer_matcher.py → 题号精确匹配 + 序列回退                         │
│  question_normalizer.py (685行) → normalize_question()               │
│    ├─ OCR 质量门控集成                                                │
│    ├─ 题干/选项/答案提取                                              │
│    ├─ 题型检测 + 置信度                                               │
│    ├─ 一致性交叉检查                                                   │
│    └─ 风险标记聚合                                                    │
│                                                                     │
│  batch_validation.py → 跨题结构完整性验证                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                    AI 修复层 (AI Repair)                              │
│                                                                     │
│  ai_repair.py (850行)                                                │
│    ├─ repair_questions() → 两阶段修复                                │
│    │   阶段1: 罗马数字约束 AI 修复 (从预选候选中选择)                 │
│    │   阶段2: 标准 AI 批量修复 → 单题回退                            │
│    ├─ _call_ai_for_repair()       → DeepSeek API                     │
│    └─ _call_ai_for_batch_repair() → 批量 LLM 调用                    │
│                                                                     │
│  llm_text_structurer.py (451行)                                      │
│    ├─ structure_text_block() → LLM 结构化 (规则不足时才调用)         │
│    └─ 反幻觉检查: 输出字段必须在原文中找到                            │
│                                                                     │
│  ai_repair 有独立的令牌预算管理 (共享 token_budget.py)                │
│  llm_text_structurer 有自己的进程级预算 (互相不知道)                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   去重 & 入库层 (Dedup & Persist)                    │
│                                                                     │
│  similarity_matcher.py → 哈希优先 + difflib 回退                    │
│  review_service.py → submit_to_review()                             │
│    └─ 写入 question_imports 暂存表 + 批量去重检查                    │
│                                                                     │
│  输出: question_imports 表记录 (status=pending, 等待人工确认)        │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 各层 Input/Output 总结

| 层 | Input | Output | 格式 |
|---|---|---|---|
| 输入层 | PDF/图片/TXT/Excel | bytes/filepath | 二进制 |
| OCR 识别层 | bytes/numpy | `OcrPageResult[]` | `{text, bbox[[4,2]], conf}` |
| AI 视觉回退层 | PDF/图片 bytes | str | 纯文本 |
| 规则清洗层 | str | str | 纯文本 |
| 质量门禁层 | str | `OCRQualityReport` | `{score, risk_flags, context}` |
| AI 纠错层 | str + 可选图片 bytes | str | 纯文本 |
| 结构分析层 | str[] | `PageStructure` | `{mode, q_count, a_count}` |
| 分割层 | str[] | `RawQuestion[]` | `{number, stem, options, answer}` |
| 标准化层 | `RawQuestion[]` | `NormalizedQuestion[]` | `{type, stem, opts, answer, ...}` |
| AI 修复层 | `NormalizedQuestion[]` | `NormalizedQuestion[]` | 同上（修复后） |
| 入库层 | `NormalizedQuestion[]` | `question_imports` | DB 记录 |

---

## 2. 代码结构审计

### 2.1 模块职责评估表

| 模块 | 行数 | 职责 | 单一职责 | 重复逻辑 | 耦合度 |
|---|---|---|---|---|---|
| `pipeline_orchestrator.py` | 3646 | 16 阶段编排 + 内联 OCR + 内联状态管理 | ❌ 职责过多 | 大量内联 | 🔴 极高 |
| `question_pipeline.py` | 2573 | 标准化 + 解析 + AI + DB 写入 | ❌ 3 个子系统 | 中等 | 🔴 极高 |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 | ✅ 较好 | ✅ `clean_ocr_text` 已归并到 text_normalizer | 🟡 中 |
| `features/ocr_service.py` | 293 | AI 视觉 OCR 回退 | ✅ 单一 | 与路由纠错重叠 | 🟢 低 |
| `text_normalizer.py` | 1101 | 规则清洗 + 统一 OCR 规范化入口 | ✅ 良好 | ✅ 字符映射已统一 | 🟢 低 |
| `ocr_quality_gate.py` | 283 | 质量检测 | ✅ 优秀 | 无重复 | 🟢 低 |
| `ocr_correction.py` | 171 | ✅ 向后兼容包装（委托 OCRFixRouter） | ✅ 清晰 | ✅ 已统一到 Router | 🟢 低 |
| `ocr_correction_common.py` | — | ✅ 共享检测/过滤函数（从旧 ocr_correction 提取） | ✅ 单一 | 无重复 | 🟢 低 |
| `ai_safety.py` | 284 | ✅ AI 编辑安全门禁（diff 记录+版本回退） | ✅ 优秀 | 无重复 | 🟢 低 |
| `question_splitter.py` | 1301 | 题号+选项提取 | ✅ 良好 | ✅ OCR 映射已统一到 normalizer | 🟢 低 |
| `ai_repair.py` | 899 | AI 修复 + 向后兼容别名 | ✅ 较好 | — | 🟡 中 |
| `llm_text_structurer.py` | 451 | LLM 结构化 | ✅ 清晰 | — | 🟡 中 |
| `ocr_fix/router.py` | 158 | 纠错路由（策略模式，唯一路径） | ✅ 清晰 | ✅ 旧版路径已移除 | 🟢 低 |
| `ocr_fix/qwen_adapter.py` | 309 | Qwen-VL 适配器 | ✅ 单一 | ✅ 旧版内联 VL 已移除 | 🟢 低 |
| `ocr_fix/deepseek_adapter.py` | 126 | DeepSeek 适配器 | ✅ 单一 | ✅ 旧版重复已移除 | 🟢 低 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | PaddleOCR-VL 适配器 | ✅ 单一 | 新增 | 🟢 低 |
| `ocr_vl/paddleocr_vl_client.py` | 345 | PaddleOCR-VL HTTP 客户端 | ✅ 单一 | 新增 | 🟢 低 |
| `token_budget.py` | 60 | 令牌预算 | ✅ 良好 | — | 🟢 低 |

### 2.2 关键结构问题

**问题 1：`pipeline_orchestrator.py` 3550 行 — 超级类**

该文件包含：
- 16 个阶段的编排逻辑
- `_ocr_scanned_pdf()`（内联 OCR 实现，约 120 行）
- `_render_page_images()`（图像渲染）
- `_build_router_config()`（模型路由配置）
- `_is_two_column_layout()`（双栏检测）
- 完整的 `ImportPipeline` 类（含状态管理、内存管理、恢复逻辑）
- 所有的 `_run_stage_N()` 方法
- 公共 API 函数（`create_pipeline`, `get_pipeline`, `run_pipeline`）
- Excel 后台管道

**建议**：拆分出 `pipeline_stages/` 目录（每阶段独立文件）+ `pipeline_state.py` + `pipeline_api.py`

**问题 2：`question_pipeline.py` 2548 行 — 多功能综合体**

包含：
- `QuestionNormalizer` 类（标准化核心）
- `process_question_pipeline()`（处理入口）
- `enrich_import()` / `complete_import()` / `generate_drafts()`（AI 功能）
- Excel 解析逻辑
- 批量审核逻辑
- DB 写入逻辑

**建议**：拆分出 `question_normalizer.py`（核心）/ `question_enricher.py`（AI）/ `import_writer.py`（DB）

**问题 3：✅ OCR 清洗逻辑已统一（FIXED）**

~~`clean_ocr_text()` 的逻辑在以下 3 个文件中以不同形式存在：~~
~~1. `services/ocr_service.py:clean_ocr_text()` — 含代码围栏保护~~
~~2. `pipeline_orchestrator.py/_run_stage_extract()` — 内联调用~~
~~3. `question_pipeline.py` — 各内联正则~~

所有 OCR 文本清洗现已统一到 `text_normalizer.py:normalize_ocr_text()`（13 步管线，1101 行）。
该函数是唯一的 OCR 规范化入口，`services/ocr_service.py` 和 `pipeline_orchestrator.py` 均通过调用此函数完成清洗。
字符替换映射（8→B, 0→D, etc.）统一在 `normalize_ocr_text()` Step 3 中维护。

**问题 4：✅ 旧版路径已清理（FIXED）**

~~`ocr_correction.py`（旧版）和 `ocr_fix/router.py`（新版）同时存在，由 `enable_ai_correction` vs `enable_ai_repair` 分别控制。~~

`ocr_correction.py` 已从 548 行精简为 171 行向后兼容包装层：
- 共享检测/过滤函数提取到 `ocr_correction_common.py`
- `correct_ocr_blocks()` 委托给 `OCRFixRouter` + `ai_safety.evaluate_and_trace()`
- 敏感内容过滤（`_filter_sensitive`）已移植到 `ocr_correction_common.py`，在 Router 链中可用
- 旧版内联 VL 分支（`is_vl` + dashscope 检测）已移除，统一使用 `qwen_adapter.py`
- Pipeline 主路径直接调用 `_run_ocr_correction_router()`，不再经过旧版包装

---

## 3. LLM 使用审计（重点）

### 3.1 所有 LLM 调用的全览

| 调用点 | 模型 | 触发条件 | 频率 | 视觉能力 |
|---|---|---|---|---|
| `ocr_vl/paddleocr_vl_adapter.py` | PaddleOCR-VL-1.6 | OCR 路由 `auto` 模式（链首） | 每批纠错块 | ✅ 有（原图，外部 API） |
| `ocr_fix/qwen_adapter.py` | Qwen-VL | PaddleOCR-VL 失败/不可用 | 同上（回退） | ✅ 有（原图） |
| `ocr_fix/deepseek_adapter.py` | DeepSeek-v4-flash | Qwen 失败/不可用 | 同上（回退） | ❌ 无 |
| `features/ocr_service.py:_call_ocr_api` | DeepSeek-v4-flash | PaddleOCR 全失败 | 罕见 | ⚠️ 发送图片文本 |
| `ai_repair.py:repair_questions` | DeepSeek-v4-flash | 规则修复后仍有题不达标 | 每批 | ❌ 无 |
| `ai_repair.py:roman_decision` | DeepSeek-v4-flash | 罗马数字约束修复 | 每批 | ❌ 无 |
| `llm_text_structurer.py` | DeepSeek-v4-flash | 规则结构分析不足 | 每批少量 | ❌ 无 |
| `question_pipeline.py:enrich` | DeepSeek-v4-flash | 人工触发丰富 | 按需 | ❌ 无 |
| `question_pipeline.py:complete` | DeepSeek-v4-flash | 自动补全 | 每批 | ❌ 无 |
| `question_pipeline.py:generate` | DeepSeek-v4-flash | 生成新题 | 按需 | ❌ 无 |

> ✅ 已移除：`ocr_correction.py:_call_ai_correction`（旧版纠错路径）—— 功能由 OCRFixRouter 统一接管，旧版内联 VL 分支已删除。

### 3.2 Qwen-VL 使用合理性分析

**结论：Qwen-VL 的使用是合理的，但仅限于 OCR 纠错场景。**

理由：
- Qwen-VL 接收**原图+OCR 文本**做多模态纠错，可以视觉验证 OCR 识别结果
- 这确实是视觉任务（看图纠正文字）
- `_preserve_stem_from_original()` 保护机制表明团队已意识到 Qwen 可能丢弃题干
- 当前模型名 `qwen3.5-ocr` 是专为 OCR 定制的

⚠️ **问题**：Qwen-VL 只在 `ocr_fix/router.py` 的路由链中使用，而 `ocr_correction.py`（旧版）和 `features/ocr_service.py`（回退路径）使用的是 DeepSeek 视觉，但这些路径没有真正的图片输入能力（只传文本），所谓视觉调用是假的（只是传了图片的 base64 到 DeepSeek，但 DeepSeek-v4-flash 的多模态能力不确定）。

### 3.3 DeepSeek 角色合理性分析

**结论：部分合理，部分过度使用。**

合理的使用：
- `ai_repair.py` 的批量修复 — 需要语义理解的复杂修复，规则无法完成
- `llm_text_structurer.py` 的结构化 — 仅在规则不足时触发
- `question_pipeline.py` 的丰富/补全/生成 — 这是主要的 AI 价值点

**不合理的使用：**

1. **双 LLM 纠错冗余**：Qwen-VL + DeepSeek 在 `ocr_fix` 中串联使用，其实大部分情况下规则清洗 + Qwen-VL 一次就够了。DeepSeek 作为回退的成本很低（只是偶尔调用），问题不大。~~需要警惕的是两条并行路径（新旧版本）都会触发 DeepSeek 调用~~ ✅ 旧版路径已移除，现在只有 OCRFixRouter 单一入口。

2. **`features/ocr_service.py` 的 DeepSeek 视觉**：这是 PaddleOCR 全盘失败后的回退。但 `_call_ocr_api` 发送的是**渲染后的 PDF 图片**，调用的却是 `deepseek-v4-flash` — 这个模型是否真的支持高精度 OCR 文字识别？如果不行，这就是一次无用的 LLM 调用 + 增加的幻觉风险。

3. ~~**`ocr_correction.py` 中的内联 VL 分支**~~ ✅ 已移除：旧版内联 VL 分支（`is_vl` + dashscope 检测）已在 P0 清理中删除，Qwen-VL 调用统一由 `qwen_adapter.py` 管理。

### 3.4 Prompt 冲突分析

| Prompt | 输出格式 | 是否冲突 |
|---|---|---|
| `ocr_correction` | 纯文本 | 与 `text_structure`（JSON）不冲突 |
| `text_structure` | JSON | 明确分开的场景 |
| `question_repair` | JSON | 与 `ocr_correction`（纯文本）不冲突 |
| `enrich_question` | JSON | 不同调用点，不冲突 |
| Qwen-VL system prompt | 纯文本 | 与 DeepSeek 的 `ocr_correction` prompt 不同 |

**结论：prompt 之间不直接冲突，因为它们用于完全不同的阶段。**

⚠️ **但有一个关键问题**：旧版路径（`ocr_correction.py:build_ocr_correction`）和新版路径（`ocr_fix/`）使用不同的 prompt。对于同一个 OCR 纠错任务，旧版 prompt 专注于「修复行序错乱/选项错位/题号缺失/字符混淆」，新版 prompt 由各 adapter 内部管理。两套 prompt 没有对齐，可能导致对同一批 OCR 文本输出不同的纠错结果。

### 3.5 Hallucination 放大问题

**存在的风险：**

1. **`ocr_correction` → `ai_repair` 串联**：OCR 纠错可能会「修正」某些文本，改变原文含义。然后 `ai_repair` 再基于修正后的文本做修复。如果 OCR 纠错阶段产生了幻觉（比如把正确文本改成了错误的），`ai_repair` 会把它当作事实继续修复，幻觉被放大。

2. **`question_pipeline.py` 的 `complete_import` → `enrich_import`**：先让 AI 补全缺失字段，再让 AI 丰富知识点。如果补全阶段产生幻觉（填了错误的答案），丰富阶段会基于幻觉答案分析知识点。

3. **代码场景的幻觉风险**：C 语言代码 OCR 识别率低 → 纠错可能改写代码逻辑 → 修复阶段进一步改变代码。影响原始语义。

**已有的保护措施：**
- `deepseek_adapter.py`: 长度越界检查（0.5x~2x），题干丢失保护 — ✅ 有效
- `qwen_adapter.py`: `_preserve_stem_from_original` — ✅ 有效
- `canonical_output.py`: 多格式输出规范化 — ✅ 有效
- `llm_text_structurer.py`: 反幻觉检查（字段必须在原文中找到） — ✅ 有效
- ✅ **`ai_safety.py:evaluate_and_trace()`** — AI 编辑安全门禁（新增）：变更前后 diff + 代码符号保护 + 中文比例检查 + 选项数保护 + `AIEditTrace` 可审计轨迹 — ✅ 有效

**缺失的保护：**
- ~~❌ `ocr_correction` 到 `ai_repair` 之间没有 diff 对比~~ ✅ 已修复：`evaluate_and_trace()` 在 OCR 纠错和 AI 修复阶段均记录 diff 轨迹
- ❌ `question_pipeline.py` 的 complete→enrich 串联没有版本回退机制
- ❌ 代码场景没有语义等价性检查（纠错后的代码逻辑是否与原文一致）

---

## 4. 失败案例分析

### 4.1 已知失败样本分类

基于 `ocr_test/images/failure/` 和回归测试套件的实际数据：

| 样本 | 回归 ID | 分类 | 根因 | 解决方式 |
|---|---|---|---|---|
| `faulty_case_1` | `011_real_code_garbling` | **OCR 错** | PaddleOCR `->` 识别为 `<-`+乱码 | ✅ 规则修复（`_fix_pointer_arrows`） |
| `faulty_case_2` | `012_real_var_misread` | **结构恢复错** | 双栏按行读取，选项顺序 B→A→D→C | ✅ 规则修复（栏阈值降低） |
| `faulty_case_3` | `013_real_pointer_garbling` | **OCR 错** | 字体问题导致字母数字混淆（0→O, 1→l） | ✅ 规则修复（字符映射） |
| `faulty_case_4` | `015_real_faulty_case_4` | **OCR 错** | 低置信度水印文本未被过滤 | ✅ 规则修复（置信度阈值） |
| `page_spread_case` | `016_real_page_spread` | **结构恢复错** | 跨页题号+答案不连接 | ⚠️ 部分修复（跨页恢复） |
| `watermark_fail_case` | `014_real_watermark` | **OCR+LLM 错** | 水印污染 → LLM 纠错保留水印文字 | ⚠️ 规则过滤+质量门禁 |
| `watermark_chart_case` | `017_real_watermark_chart` | **OCR 错** | 水印+图表干扰，OCR 输出含大量乱码 | ❌ 仍存在问题 |

> ✅ 上述 7 个真实失败样本（含 1 个两栏成功样本 `010_real_two_column`）已纳入回归基线 `tests/ocr_regression/cases/`，共计 **17 个回归 case**（9 个合成文本 + 8 个真实图片）。每个 case 有独立的 `meta.json`（含 `review_status`）、`input.txt` 和人工标注的 `expected.txt`（ground truth）。回归系统支持 `--baseline`、`--review` 和 CI 严格模式。

### 4.2 失败根因分类统计

| 根因 | 占比（估） | 典型场景 | 可规则解决 | LLM 必要 |
|---|---|---|---|---|
| PaddleOCR 识别错误 | 45% | 箭头→乱码, 数字字母混淆, 水印残留 | ⚠️ 部分可 | ✅ 需要 |
| 版面分析错误 | 25% | 双栏顺序错, 跨页断开, 选项位置误判 | ✅ 可 | ❌ 不需要 |
| 结构恢复错误 | 15% | 题号丢失, 选项归属错, 答案不匹配 | ✅ 可 | ❌ 不需要 |
| AI 纠错产生的幻觉 | 10% | LLM 改写原文, 补充不在原文的内容 | ❌ 不可 | ⚠️ 需防护 |
| 代码场景特殊失败 | 5% | C 符号/指针被改写, 格式被压缩 | ✅ 可（围栏） | ❌ 不需要 |

### 4.3 「错误被二次放大」的具体案例

案例：**`watermark_fail_case` 的水印污染**

```
PaddleOCR 输出: "1. 下列选项中... 【解析】... 版权所有 翻印必究"
     ↓
规则清洗(_filter_watermarks): "版权所有 翻印必究" 未被匹配到水印模式
     ↓
AI 纠错(Qwen/DeepSeek): 认为"版权所有 翻印必究"是正文的一部分, 不做删除
     ↓
质量门禁: 检测到选项结构异常(多了一段文字) → 标记 risk_flag=option_structure_corruption
     ↓
AI 修复: 看到 risk_flag 后尝试修复 → 可能把正确选项改错
     ↓
结果: 水印文字进入最终输出, 质量分降低, 或 AI 修复引入二次错误
```

**关键结论**：约 60% 的失败可以通过**规则修复**解决（箭头修复已 OK，字符映射已 OK，水印过滤需要加强）。约 25% 需要**版面分析改进**。仅 10-15% 需要 LLM 介入。

---

## 5. 性能与成本审计

### 5.1 LLM 调用成本估算

| 调用 | 每次 tokens（估） | 频率（每 100 页 PDF） | 总 tokens | 成本（估） |
|---|---|---|---|---|
| Qwen-VL 纠错 | 图片+2K 文本 | 40 个噪声块 | — | ¥0.02/次×40=¥0.8 |
| DeepSeek 纠错（回退） | 2K | 5 个（10% 回退） | 10K | ¥0.003 |
| DeepSeek 修复（批量） | 8K | 2 次（40 题/批） | 16K | ¥0.005 |
| DeepSeek 修复（单题） | 4K | 5 次（失败回退） | 20K | ¥0.006 |
| DeepSeek 补全 | 2K | 50 题 | 100K | ¥0.03 |
| DeepSeek 丰富 | 2K | 50 题 | 100K | ¥0.03 |
| **合计** | | | **~246K** | **~¥0.874/100 页** |

**结论**：单次 PDF 处理成本可控（不到 1 元/100 页）。但存在以下浪费：

### 5.2 不必要的 LLM 调用

1. ~~**旧版路径的 DeepSeek 纠错**~~ ✅ 已修复：`ocr_correction.py` 不再独立调用 LLM，纠错统一由 OCRFixRouter 处理。

2. **`ai_repair` 对所有题目都调用**：即使 `normalize_schema` 阶段已经给出了高置信度（>0.95），`ai_repair` 仍然被调用（只是不会触发 AI 修复，但有判断逻辑的成本）。简单跳过高置信度题可节省约 70% 的 repair 开销。

3. **`llm_text_structurer` 的进程级预算计数**：它有自己的预算跟踪，与 `token_budget.py` 管理的共享预算互相独立。两个预算池互不知道，可能导致实际超限。

4. **`features/ocr_service.py` 的 DeepSeek 视觉回退**：在 PaddleOCR 全失败时调用，发送的是渲染后的 PDF 页面图片。但这其实应该用 Qwen-VL 而不是 DeepSeek。当前配置可能造成无用的调用（DeepSeek-v4-flash 是否真的能高精度识别 PDF 文字是不确定的）。

### 5.3 减少一层 LLM 的可能性

**可以去掉的方案：**

**方案 A：✅ 已完成 — 移除旧版 `ocr_correction.py` 的内联 DeepSeek 路径**

- 旧版 `_call_ai_correction` 与新版 `ocr_fix/router.py` 功能重叠
- 旧版的 VL 内联路径在 `qwen_adapter.py` 中已有独立实现
- **实际成效**：`ocr_correction.py` 从 548 行降至 171 行（仅保留向后兼容包装），消除每批 0-1 次额外 LLM 调用

**方案 B：在 `ai_repair` 中添加置信度跳过逻辑**

- `normalize_schema` 阶段输出的置信度 >0.95 的题目可以直接跳过 repair
- **潜在节省**：约 70% 的 repair 调用（¥0.011 → ¥0.003/批）

**方案 C：合并两个 token budget**

- `llm_text_structurer` 使用共享 `token_budget` 替代自己的独立预算
- **潜在节省**：无成本节省，但避免预算失控

**方案 D：`features/ocr_service.py` 的视觉回退使用 Qwen-VL 而不是 DeepSeek**

- 如果 DeepSeek-v4-flash OCR 精度不够，当前调用完全是浪费
- 切换到 Qwen-VL 可能增加单次成本，但保证回退可用

**总体结论：不建议完全去掉一层 LLM，但可以优化调用频率和路径选择。**

### 5.4 缓存策略

**当前缓存状态：**

| 可缓存内容 | 是否已缓存 | 策略 |
|---|---|---|
| PaddleOCR 结果 | ❌ 未缓存 | 每次流程重跑 |
| Qwen-VL 纠错结果 | ❌ 未缓存 | 每次重跑 |
| DeepSeek 修复结果 | ❌ 未缓存 | 每次重跑 |
| AI 补全结果 | ❌ 未缓存 | 每次重跑 |

**缓存建议：**

1. **图片哈希 → OCR 结果**：对每张输入图片计算 SHA256，如果之前已 OCR 过且结果相同，直接复用。可以节省 70%+ 的重复 OCR 工作（同一 PDF 多次导入场景）。

2. **批量图片的相似性检测**：同一本书的相邻页 OCR 结果高度相似，可以复用上一页的校正结果。

3. **DB 级缓存**：`question_imports.ocr_raw_text` 字段已存在，但仅在入库时填入。如果 OCR 结果已被缓存到 DB，下次同一图片可以直接复用。

**⚠️ 注意**：缓存不适用于 LLM 纠错/修复（因为每次 AI 输出的随机性，缓存可能会导致陈旧结果无法更新）。

### 5.5 Latency Bottleneck

> 注：OCR 导入功能主要在本地 i7-12700 + RTX 3060 4G 环境下执行，生产服务器（2 核 2G）不运行 OCR 管线。以下分析基于本地 GPU 配置。

| 阶段 | 耗时（估/100 页） | 瓶颈类型 |
|---|---|---|
| PaddleOCR（GPU, RTX 3060） | 10-25s | ✅ 可接受 |
| PaddleOCR（CPU 回退） | 120-300s | ⚠️ 仅回退路径 |
| 规则清洗 | 1-3s | 几乎不计 |
| Qwen-VL 纠错 | 20-60s | 🚨 API 调用（串行, 信号量=3） |
| DeepSeek 修复（批量） | 10-30s | API 调用 |
| 结构分析+分割 | 2-5s | 几乎不计 |
| AI 补全+丰富 | 30-200s | 🚨 API 调用（50 题串行） |
| **总计（本地 GPU）** | **~2-5min** | 可接受 |

**关键瓶颈**：
1. **Qwen-VL 串行调用**：信号量=3，但 API 调用仍占用 20-60s。
2. **AI 补全串行**：50 题串行调用 DeepSeek，每次 ~2-4s，总计 100-200s。可以轻松并行化。
3. **PaddleOCR CPU 回退**：仅作为 GPU 初始化失败时的紧急路径，非主路径。

---

## 6. 最终结论

### 6.1 核心问题 Top 10（2026-06-21 状态更新）

| 优先级 | 问题 | 状态 | 修复 commit |
|---|---|---|---|
| **P0** | 生命周期 3 个内存缺陷：PDF bytes 全程驻留 + 双 OCR 重复扫描 + pipeline_store 大字段积累 | ✅ 已修复 | d7b2ae5, 04fd013 |
| **P0** | 旧版 `ocr_correction.py` 与新版 `ocr_fix/router.py` 并行运行，功能重叠 | ✅ 已修复 | edcfd0c |
| **P0** | OCR 清洗逻辑三处重复（`services/ocr_service.py`, `text_normalizer.py`, `question_splitter.py`），三者不同步 | ✅ 已修复 | cc419dd |
| **P0** | AI 纠错→修复之间无 diff 对比，幻觉放大路径无防护 | ✅ 已修复 | edcfd0c, 04fd013 |
| **P0** | 回归测试体系「同义反复」：11 个合成 case 全部 PASS 但 5 张真实图片全部 FAIL，无人工标注 ground truth | ✅ 已修复 | 058aea3, b63df47 |
| **P1** | `pipeline_orchestrator.py`（3646 行）和 `question_pipeline.py`（2573 行）超级类，职责混杂 | ⏳ 待处理 | — |
| **P1** | AI 补全串行 50 题（100-200s），可并行但未并行 | ⏳ 待处理 | — |
| **P1** | 断点恢复完全缺失：OCR 中途崩溃全丢进度 | ⏳ 待处理 | — |
| **P1** | `complete→enrich` 串联无版本回退；旧版敏感内容过滤未移植到新版路由 | ✅ 敏感内容过滤已移植；版本回退 ⏳ | edcfd0c |
| **P1** | 公式截图保留、表格保真、低风险批量通过、原图对照预览 四个高收益闭环未实现 | ✅ 已修复 | c82c464 |
| **P2** | OCR 结果无缓存 + 两栏选项错序未完全解决 + 代码场景语义等价性无检查 | ⏳ 待处理 | — |

### 6.2 是否需要重构 — **YES**

**理由：**

1. **旧版/新版并行不是一个可维护的状态**。`ocr_correction.py` 和 `ocr_fix/` 的存在意味着同一功能有两套实现，且由不同的配置开关控制（`enable_ai_correction` vs `enable_ai_repair`）。继续并行只会扩大差异。

2. **两个超级类已经达到临界规模**。`pipeline_orchestrator.py` 的 3550 行意味着任何修改都有信心风险。在单一文件中调试 16 个阶段的交互是不可持续的。

3. **LLM 链路上存在幻觉放大路径**。OCR 纠错 → AI 修复的串联路径没有版本对比机制，当前靠「信任 LLM」策略，需要引入保护性架构。

4. **存在阻塞级内存缺陷**。PDF bytes 全程驻留（100-400 MB）、exercise detection 双 OCR（工作量翻倍）、pipeline_store 大字段积累（0.25-1.5 GB），三者叠加导致 400 页以上 PDF 高概率内存崩溃。

5. **当前架构可以渐进式重构**，不需要推倒重来。核心的规则模块（`text_normalizer`, `question_splitter`, `ocr_quality_gate`）设计良好，只需要旧版清理 + 超级类拆分 + 内存治理 + 回归体系重建。

### 6.3 推荐的新 Pipeline（2026-06-21 更新：已完成项标记 ✅）

```
贯穿全局: 内存治理 ✅
    └─ ✅ PDF bytes extract 后立即落盘释放（file_content → tempfile）
    └─ ✅ exercise detection 与全量 OCR 共享一次推理结果
    └─ ✅ pipeline_store 按阶段弹出大字段（raw_blocks / normalized_blocks / corrections）
    └─ review 阶段 50 题一批 commit，防单事务撑爆

阶段 1: PaddleOCR 识别
    └─ 单图/逐页 OCR → OcrPageResult[]
    └─ 图片缓存（SHA256 哈希）

阶段 2: 纯规则清洗 (text_normalizer) [✅ 唯一路径]
    └─ ✅ normalize_ocr_text() 13 步管线，统一所有 OCR 文本清洗
    └─ ✅ 所有字符映射统一在 text_normalizer.py 中维护

阶段 3: 质量门禁 (ocr_quality_gate)
    └─ 纯规则检测, 不调用任何 AI
    └─ 输出质量分 + risk_flag

阶段 4: AI 纠错 (ocr_fix/router — ✅ 唯一路径)
    └─ ✅ 旧版 ocr_correction.py 已精简为向后兼容包装（171 行）
    └─ ✅ 路由链: PaddleOCR-VL → Qwen-VL → DeepSeek → Rule（新增链首）
    └─ ✅ PaddleOCR-VL 适配器（ocr_vl/paddleocr_vl_adapter.py）：
    │     外部高精 OCR API（POST /api/v2/ocr/jobs → poll → JSONL）
    │     async HTTP 客户端，重试 3 次，超时 120s，降级不崩溃
    └─ ✅ 敏感内容过滤已移植到 ocr_correction_common.py
    └─ ✅ 纠错前后的 diff 记录（ai_safety.evaluate_and_trace）
    └─ 纠错效果指标追踪（ocr_fix/metrics.py 已有基础设施）

阶段 5: 结构分析 + 分割（不改）
    └─ structure_analyzer + question_splitter

阶段 6: 答案匹配 + 标准化（不改）
    └─ answer_matcher + question_normalizer

阶段 7: AI 修复 (ai_repair, 可选)
    └─ 跳过置信度 > 0.95 的题目
    └─ ✅ 修复前后 diff + 版本回退能力（ai_safety.evaluate_and_trace）
    └─ 添加: complete→enrich 串联的版本回退
    └─ 添加: 语义等价性检查（代码场景）

阶段 8: 去重 + 入库（不改）
    └─ similarity_matcher → question_imports

阶段 9: (新增) 断点恢复
    └─ import_batches + import_regions 表
    └─ region 级 checkpoint，崩溃后从 region 边界恢复
```

**关键变更状态（P0 ✅ / P1-公式截图审核 ✅ / P1-P2 待处理）**：
1. ✅ **内存治理**：PDF bytes 落盘释放、消除双 OCR、pipeline_store 剥大字段（d7b2ae5, 04fd013）
2. ✅ **删除** `ocr_correction.py` 的旧版纠错路径（保留向后兼容包装 + 移植敏感内容过滤）（edcfd0c）
3. ⏳ **拆分** `pipeline_orchestrator.py` → `pipeline_stages/` 目录（P1，3-5 天）
4. ⏳ **拆分** `question_pipeline.py` → `normalizer` + `enricher` + `writer`（P1，2-3 天）
5. ✅ **合并** 3 处 OCR 清洗逻辑 → 统一到 `text_normalizer.py:normalize_ocr_text()`（cc419dd）
6. ⏳ **AI 补全并行化**（P1, 0.5 天）
7. ✅ **添加** AI 安全门禁 `ai_safety.py`（diff 记录 + 版本回退机制）（edcfd0c, 04fd013）
8. ⏳ **添加** OCR 结果缓存（P2, 1 天）
9. ✅ **添加** 回归基线：8 张真实图片 + 9 个合成文本 = 17 个回归 case，含人工标注 ground truth + `meta.json.review_status` + CI 严格模式（058aea3）
10. ⏳ **添加** 断点恢复（P1, 2-3 天）
11. ✅ **添加** `math_import_profile.py`：规则数学候选检测引擎 + 408/code 排除（c82c464）
12. ✅ **添加** `table_region_detector.py`：多列 Token 分析 + Markdown 表格保真（c82c464）
13. ✅ **新增 pipeline stages 6.8-6.9**：公式区域检测 + 表格检测，注册到 `_build_pipeline()`（c82c464）
14. ✅ **审核页 segments 渲染**：math_image / table_markdown / 原图对照三种 segment（c82c464）
15. ✅ **低风险批量通过**：`approve_low_risk_questions` 接口 + 前端按钮（c82c464）
16. ✅ **segments 透传发布**：review_service + publish_service 保留 render_mode/segments（c82c464）
17. ✅ **11 个新 risk_flags** 映射到 high/medium + 中文 risk_reasons（c82c464）

### 6.4 改造优先级（修订版）

> 上下文：OCR 导入功能在本地 i7-12700 + RTX 3060 4G 环境下运行，GPU 可用。以下优先级基于此配置。
>
> 修订说明：本版基于优先级评审（`ocr-priority-review.md`）更新，补充了生命周期审计、真实案例回归审计和成熟度审计中遗漏的关键任务。原有 10 项任务保留，新增约 12 项。

#### P0 — ✅ 已全部完成（commit: b63df47）

| 任务 | 状态 | 实际 commit | 收益 |
|---|---|---|---|
| **PDF bytes 落盘释放**：extract 后 `file_content` 从 bytes 切换为 tempfile，释放 100-400 MB 内存 | ✅ | d7b2ae5 | 解决 400+ 页 PDF 内存崩溃根因 |
| **消除 EXERCISE_DETECTION 双 OCR**：lightweight 与全量 OCR 共享一次推理结果 | ✅ | d7b2ae5 | OCR 工作量减半，WSL OOM 风险降低 |
| **`_pipeline_store` 剥大字段**：diagnostics 中 raw_questions_preview + corrections 分离到独立 KV 存储，设置合理 TTL 上限 | ✅ | 04fd013 | 500 条任务 store 体积从 0.25-1.5 GB 降至 < 50 MB |
| **旧版 `ocr_correction.py` 纠错路径清理**：统一到 `ocr_fix/router`，移植 `_filter_sensitive_content()` 逻辑到新版路由 | ✅ | edcfd0c | 消除并行路径，避免重复 LLM 调用，消除合规风险 |
| **`clean_ocr_text` 和字符映射逻辑归并**：三处重复统一到 `text_normalizer.py:normalize_ocr_text()` | ✅ | cc419dd | 消除 3 处不同步，修复一处所有场景受益 |
| **添加 AI 安全门禁（diff 记录 + 版本回退）**：`ai_safety.py` 在 OCR 纠错和 AI 修复阶段记录 diff 轨迹 | ✅ | edcfd0c, 04fd013 | 解决幻觉放大风险，LLM 链路可追溯 |
| **建立真实图片回归基线**：8 张真实图片 + 9 个合成文本 = 17 个回归 case，含人工标注 ground truth + `meta.json.review_status` + CI 严格模式 | ✅ | 058aea3, b63df47 | 打破「同义反复」，改造效果可衡量 |

#### P1-公式截图审核流程 — ✅ 已完成（commit: c82c464）

| 任务 | 状态 | 实际 commit | 收益 |
|---|---|---|---|
| **公式区域检测接入新版 pipeline**：`math_import_profile.py` 规则引擎，含 408/code 排除 | ✅ | c82c464 | 高数题产生 math_regions，非数学题不触发 |
| **公式截图裁剪与 math_image segment**：pipeline stage 6.8 math_detect，裁剪截图写入 segments | ✅ | c82c464 | 复杂公式/低置信度公式保留截图供审核对照 |
| **管理端审核页展示 math_image segment**：分段渲染，置信度/需核对/上传失败三种状态 | ✅ | c82c464 | 审核员直接看到公式原图 |
| **审核透传 segments 到正式题库**：review_service 保留 segments，publish_service 保留 render_mode | ✅ | c82c464 | 发布后公式截图不丢失 |
| **低风险题批量通过**：后端 approve_low_risk + 前端批量按钮 + 条件检查 | ✅ | c82c464 | 减少人工逐题点击 |
| **原图/题目区域对照预览**：source_region_image 折叠展示，支持 image_url/page_image_url/bbox fallback | ✅ | c82c464 | 审核员对照原图快速修题 |
| **表格题初步检测与 Markdown 保真**：`table_region_detector.py` 多列 token 分析 + Markdown 转换 | ✅ | c82c464 | 408 调度表/Cache 表保留行列结构 |
| **风险等级与新增 risk_flags 联动**：11 个新 flag 映射到 high/medium，中文 risk_reasons | ✅ | c82c464 | 公式/原图/表格风险进入 P0 体系 |

#### P1 — 重要（功能/质量提升）

| 任务 | 来源 | 前置条件 | 预估工作量 | 收益 |
|---|---|---|---|---|
| `pipeline_orchestrator.py` 拆分为 `pipeline_stages/` 目录（预留流式接口） | 原始审计 + 生命周期审计 | P0-1：旧版清理完成 | 3-5 天 | 可维护性大幅提升，独立测试 |
| `question_pipeline.py` 拆分为 `normalizer` + `enricher` + `writer` | 原始审计 | P0-2：字符映射归并完成 | 2-3 天 | 职责分离，独立测试 |
| AI 补全并行化（`asyncio.gather` + 信号量控制） | 原始审计 | 无 | 0.5 天 | 5x 加速（100-200s → 20-40s） |
| `complete→enrich` 串联版本回退机制 | 原始审计 3.5 节（补充） | diff 记录机制就绪 | 1-2 天 | 防止补全幻觉污染丰富阶段 |
| OCR 纠错效果指标追踪 | 成熟度审计 | diff 记录完成（提供数据源） | 1 天 | 定量评估纠错效果，发现：改善还是破坏 |
| 断点恢复（最小子集）：region 级 checkpoint + `import_batches`/`import_regions` 表 | 生命周期审计 | 结构拆分完成 | 2-3 天 | 400 页崩溃后从 region 边界恢复 |
| 各阶段间 data 大字段弹出（`raw_blocks` / `normalized_blocks` / `raw_questions` / `matched` 用完即弃） | 生命周期审计 | 伴随结构拆分执行 | 1 天 | 峰值内存进一步降低 50%+ |
| review 阶段分批 commit：50 题一批，避免全 batch 单事务 | 生命周期审计 | 无 | 1 天 | 失败粒度变小，不改则 500+ INSERT 全回滚 |
| 回归基准 CI：改造前后自动对比，检测回归 | 真实案例审计 | 真实基线就绪 | 0.5 天 | 防止改造引入新 bug |

#### P2 — 值得做（成本/体验优化）

| 任务 | 来源 | 前置条件 | 预估工作量 | 收益 |
|---|---|---|---|---|
| ~~PaddleOCR 结果缓存（图片 SHA256 → OCR 文本）~~ | 原始审计 | 确认流式架构方向 | 1 天 | ✅ 已完成（`ocr_cache_service.py` 文件缓存） |
| `features/ocr_service.py` 回退路径改为 Qwen-VL | 原始审计 | 无 | 0.5 天 | 确保回退路径真正可用 |
| 合并两个 token budget（`llm_text_structurer` 独立预算并入共享 `token_budget.py`） | 原始审计 | 无 | 0.5 天 | 统一预算管理 |
| ~~高置信度题跳过 AI 修复（置信度 > 0.95 跳过 `ai_repair`）~~ | 原始审计 | 旧版清理完成 | 0.5 天 | ✅ 已完成（`_is_low_risk_skip_candidate`） |
| 代码场景语义等价性检查 | 原始审计 3.5 节（补充） | diff 记录完成 | 1-2 天 | 防止 C 代码被 LLM 改写逻辑 |
| `raw_data` 字段瘦身：剥离 `raw_text` / `warnings` / `similarity_suggestion` | 生命周期审计 | 无 | 0.5 天 | DB 单行体积下降 50%+ |

### 6.5 推荐执行路线（2026-06-21 更新）

#### 当前状态：阶段一（P0）✅ 已完成，阶段一B（P1-公式截图）✅ 已完成，**阶段二B（P2-三项改造）✅ 已完成**，阶段二（P1-结构优化）待启动

```
✅ 阶段一: 基础清理 + 回归基线 (已完成 — b63df47)
┌─────────────────────────────────────────────────────────────────────┐
│ ✅ P0-1: 旧版路径清理 (edcfd0c)                                      │
│ ✅ P0-2: 字符映射归并 (cc419dd)                                      │
│ ✅ P0-3: PDF bytes 释放 (d7b2ae5)                                    │
│ ✅ P0-4: 消除双 OCR (d7b2ae5)                                        │
│ ✅ P0-5: store 瘦身 (04fd013)                                        │
│ ✅ P0-6: AI diff 记录 + 安全门禁 (edcfd0c, 04fd013)                   │
│ ✅ P0-7: 真实回归基线 (058aea3, b63df47)                             │
└─────────────────────────────────────────────────────────────────────┘
                                     │
                                     v
✅ 阶段一B: 公式截图 + 审核提效 + 原图对照 (已完成 — c82c464)
┌─────────────────────────────────────────────────────────────────────┐
│ ✅ P1-2: 公式区域检测 (math_import_profile.py)                       │
│ ✅ P1-3: 公式截图裁剪 (math_detect stage 6.8)                       │
│ ✅ P1-4: 审核页 math_image 展示                                     │
│ ✅ P1-5: segments 透传发布                                          │
│ ✅ P1-6: 低风险批量通过                                             │
│ ✅ P1-7: 原图对照预览                                               │
│ ✅ P1-8: 表格检测保真 (table_region_detector.py)                    │
│ ✅ P1-9: risk_flags 联动                                             │
└─────────────────────────────────────────────────────────────────────┘
                                     │
                                     v
✅ 阶段二B: P2 三项改造 (已完成 — 2026-06-21)
┌─────────────────────────────────────────────────────────────────────┐
│ ✅ P2-1: page image 轻量引用贯穿 (`_render_page_image_refs`)         │
│ ✅ P2-2: 真实公式截图裁剪上传 (`crop_from_page_ref` + async upload) │
│ ✅ P2-3: 低风险跳过 AI repair (`_is_low_risk_skip_candidate`)       │
│ ✅ P2-4: AI repair 统计 (repair_stats → diagnostics)                │
│ ✅ P2-5: PaddleOCR 缓存 (`ocr_cache_service.py`, SHA256+config)     │
│ ✅ P2-6: 回归样本扩展 (5 个真实高数题 case + 25 tests)               │
└─────────────────────────────────────────────────────────────────────┘
                                     │
                                     v
⏳ 阶段二: 结构优化 + 幻觉防护 (未开始)
┌─────────────────────────────────────────────────────────────────────┐
│ P1-1: pipeline 结构拆分 ───────→ P1-6: 断点恢复 (结构明确后)         │
│ P1-2: q_pipeline 拆分           │                                   │
│ P1-5: stage data 清理 (伴随拆分) │                                   │
│ P1-7: review 分批 commit (独立)  │                                   │
│ P1-4: complete→enrich 版本回退   │                                   │
│ P1-3: AI 补全并行化 (独立)       │                                   │
└─────────────────────────────────────────────────────────────────────┘
                                     │
                                     v
⏳ 阶段三: 性能优化 + 能力补充 (部分完成)
┌─────────────────────────────────────────────────────────────────────┐
│ ✅ P2-1: OCR 缓存 — 已完成 (`ocr_cache_service.py`)                  │
│ ✅ P2-4: 跳过修复 — 已完成 (`_is_low_risk_skip_candidate`)           │
│ ⏳ P2-2: Qwen回退 (未开始)                                           │
│ ⏳ P2-3: 合并 token budget (未开始)                                  │
│ ⏳ P2-5: 代码语义等价性检查 (未开始)                                  │
│ ⏳ P2-6: raw_data 瘦身 (未开始)                                      │
│ 以及 P1 收尾: 纠错指标追踪、断点恢复收尾                              │
└─────────────────────────────────────────────────────────────────────┘
```

#### P0 交付成果

- **测试结果**：1474 passed, 24 failed（24 个失败均为预存问题，非 P0 引入）
- **回归基线**：17 个 case（9 合成 + 8 真实），含人工标注 ground truth
- **CI 就绪**：`pytest.ini` 已修复（移除阻塞测试发现的空 `python_classes`），`runner.py --review` 支持 CI 严格模式
- **向后兼容**：`ocr_correction.correct_ocr_blocks()` 保留为包装函数，测试全部通过

#### 回归检查清单（阶段一交付状态）

| 检查项 | 状态 |
|---|---|
| 8 张真实图片纳入回归基线（允许 known_failure_types） | ✅ 通过 |
| 现有 9 个合成 case 不受影响 | ✅ 通过 |
| PDF（文本型）导入正常 | ✅ 通过 |
| PDF（扫描型）导入正常 | ✅ 通过 |
| Excel 导入不受影响 | ✅ 通过 |
| 300 题以上请求时内存不崩溃 | ✅ 通过（PDF bytes 落盘释放） |
| 旧版路径彻底不可调用 | ✅ 通过（ocr_correction.py 为包装层，不独立调用 LLM） |
| 纠错前后存在 diff 记录 | ✅ 通过（ai_safety.evaluate_and_trace） |

---

## 附录 A：审计涉及的文件清单

### 核心 OCR/导入管线

| 文件 | 行数 | 用途 |
|---|---|---|
| `features/pipeline_orchestrator.py` | 3646 | 主编排器（16 阶段） |
| `features/question_pipeline.py` | 2573 | 问题标准化管道 |
| `features/ocr_service.py` | 293 | AI 视觉 OCR 回退 |
| `features/ocr_correction.py` | 171 | ✅ 向后兼容包装（委托 OCRFixRouter） |
| `features/ocr_correction_common.py` | — | ✅ 共享检测/过滤函数（从旧 ocr_correction 提取） |
| `features/ai_safety.py` | 284 | ✅ AI 编辑安全门禁（diff 记录 + 版本回退） |
| `features/ocr_quality_gate.py` | 283 | 纯规则 OCR 污染检测 |
| `features/text_normalizer.py` | 1101 | ✅ 统一 OCR 文本规范化入口（normalize_ocr_text, 13 步） |
| `features/question_normalizer.py` | 685 | 规则题目标准化 |
| `features/question_splitter.py` | 1301 | 纯规则题目分割 |
| `features/structure_analyzer.py` | 466 | 结构分析 |
| `features/page_classifier.py` | — | 页面分类 |
| `features/visual_boundary_detector.py` | 223 | 视觉题目边界检测 |
| `features/ai_repair.py` | 899 | AI 修复模块 |
| `features/llm_text_structurer.py` | 451 | LLM 文本结构化 |
| `features/token_budget.py` | 60 | 共享令牌预算跟踪器 |
| `features/answer_matcher.py` | — | 答案匹配 |
| `features/similarity_matcher.py` | — | 相似度匹配 |
| `features/code_detector.py` | — | 代码围栏检测器 |
| `features/batch_validation.py` | — | 跨题结构验证 |

### `ocr_fix/` — 多模型 OCR 纠错路由器（✅ 现在为唯一路径）

| 文件 | 行数 | 用途 |
|---|---|---|
| `ocr_fix/interfaces.py` | 41 | OCRFixResult + OCRFixerProtocol 接口 |
| `ocr_fix/router.py` | 158 | 带降级链的策略路由（唯一纠错入口） |
| `ocr_fix/deepseek_adapter.py` | 126 | DeepSeek 纯文本 OCR 纠错 |
| `ocr_fix/qwen_adapter.py` | 309 | Qwen-VL 多模态 OCR 纠错 |
| `ocr_fix/rule_adapter.py` | 41 | no-op 规则回退 |
| `ocr_fix/canonical_output.py` | 223 | 模型输出规范化 |
| `ocr_fix/metrics.py` | 158 | 按模型指标收集 |

### `ocr_vl/` — PaddleOCR-VL 外部高精 OCR 适配器（2026-06-21 新增）

| 文件 | 行数 | 用途 |
|---|---|---|
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器，封装客户端，接入路由链 |
| `ocr_vl/paddleocr_vl_client.py` | 345 | async HTTP 客户端，作业提交+轮询+JSONL 解析 |

### AI/基础设施层

| 文件 | 行数 | 用途 |
|---|---|---|
| `ai/client.py` | 103 | DeepSeek HTTP 客户端 |
| `ai/prompts.py` | 590 | 所有场景的 Prompt 模板 |
| `ai/fallback.py` | 94 | AI 不可用时回退值 |
| `features/ai_safety.py` | 284 | ✅ AI 编辑安全门禁（evaluate_and_trace, safe_accept_ai_result, AIEditTrace） |
| `core/ocr_profile.py` | 58 | OCR 配置文件 |

### Service 层

| 文件 | 行数 | 用途 |
|---|---|---|
| `services/ocr_service.py` | 637 | PaddleOCR 封装 |
| `services/pdf_text_normalizer.py` | — | 文本去重 |
| `services/import_service.py` | — | 旧版导入服务 |
| `services/admin_import_service.py` | — | 管理导入服务 |
| `services/model_config_resolver.py` | — | 模型凭据解析 |

### API 路由

| 文件 | 行数 | 用途 |
|---|---|---|
| `api/v1/imports.py` | 1166 | 公共导入 API |
| `api/v1/admin_imports.py` | — | 管理导入 API |

### DB Model

| 文件 | 用途 |
|---|---|
| `models/question_import.py` | question_imports 表模型 |
| `models/import_batch_job.py` | import_batch_jobs + import_batch_job_items 表模型 |

### 测试文件

| 文件 | 用途 |
|---|---|
| `tests/test_features/test_pipeline_e2e.py` | 管道端到端测试 |
| `tests/test_features/test_pipeline_chunk_runner.py` | 分块运行测试 |
| `tests/test_features/test_pipeline_checkpoint.py` | 检查点测试 |
| `tests/test_features/test_pipeline_resume.py` | 恢复测试 |
| `tests/test_features/test_pipeline_status_chunk_progress.py` | 分块进度测试 |
| `tests/test_features/test_ocr_quality_gate.py` | OCR 质量门控测试 |
| `tests/test_features/test_llm_text_structurer.py` | LLM 结构化测试 |
| `tests/test_services/test_ocr_service.py` | OCR 服务测试 |
| `tests/test_services/test_ocr_correction.py` | OCR 纠错测试（已适配新包装层） |
| `tests/test_services/test_text_normalizer.py` | 文本规范化器测试（已适配 normalize_ocr_text） |
| `tests/test_services/test_question_normalizer.py` | 问题规范化器测试 |
| `tests/test_services/test_question_splitter.py` | 问题分割器测试 |
| `tests/test_services/test_pipeline_orchestrator.py` | 编排器测试 |
| `tests/test_ocr_fix/test_canonical_output.py` | 规范输出测试 |
| `tests/ocr_regression/runner.py` | ✅ OCR 回归运行器（1045 行，--baseline/--review/CI 严格模式） |
| `tests/ocr_regression/cases/` | ✅ 17 个回归 case（9 合成 + 8 真实，含 meta.json + expected.txt） |
| `tests/ocr_regression/metrics.py` | OCR 回归指标 |
| `tests/ocr_regression/classifier.py` | OCR 回归分类器 |
| `tests/ocr_eval/eval_ocr.py` | OCR 评估脚本 |
| `tests/ocr_eval/eval_wangdao.py` | 王道 OCR 评估 |
| `tests/test_pdf_normalizer.py` | PDF 规范化测试 |
| `tests/test_code_detector.py` | 代码检测器测试 |
| `tests/test_question_pipeline.py` | 问题管道测试 |

### 文档

| 文件 | 内容 |
|---|---|
| `docs/architecture/OCR_FLOW.md` | OCR & 导入流程架构 |
| `docs/architecture/OCR_USAGE.md` | 管理端 OCR 使用指南 |
| `docs/architecture/DUAL_ENV_OCR.md` | 双环境 OCR 配置文件 |
| `docs/ai/OCR_STRATEGY.md` | OCR 战略决策 |
| `docs/ai/AI_PIPELINE.md` | AI Pipeline 架构 |
| `docs/ai/STANDARDIZATION_FLOW.md` | 题目标准化架构 |
| `docs/ai/ocr_phase1_assessment.md` | OCR 可行性评估报告 |
| `docs/audit/ocr-pipeline-lifecycle-audit.md` | 数据生命周期 + 流式架构审计 |
| `docs/audit/ocr-real-case-regression-audit.md` | 真实案例回归审计 |
| `docs/audit/ocr-capability-maturity-audit.md` | OCR 能力成熟度审计 |
| `docs/audit/image-import-audit.md` | 图片导入架构审计 |

---

## 附录 B：P0 修复复查记录（2026-06-21）

### 修复范围

7 个 P0 任务全部完成，涉及 6 个 commit：

| Commit | 内容 |
|---|---|
| `edcfd0c` | P0 管线审计：移除旧版 OCR 纠错，归并字符映射，修复内存泄漏，添加回归 case 和 stage diff |
| `cc419dd` | 统一 OCR 文本清洗到单一 `normalize_ocr_text()` 入口 |
| `04fd013` | AI 安全门禁 + `_pipeline_store` 瘦身（Task 3 + Task 6） |
| `d7b2ae5` | PDF/图片/Excel bytes 落盘释放 + 废弃双 OCR 入口（Task 1 + Task 2） |
| `058aea3` | 回归基线安全：审核驱动的 ground truth 管理 + CI 支持（Task 7） |
| `b63df47` | P0 回归修复：测试兼容、Unicode 白名单、pytest.ini 测试发现 |

### 测试结果变化

| 指标 | 修复前 | 修复后 |
|---|---|---|
| Passed | 1402 | 1474 |
| Failed | 34 | 24 |
| Errors (collection) | 2 | 0 |

24 个遗留 failure 均为预存问题（publish service async mock、LaTeX mangling 等），非 P0 引入。

### 代码行数变化

| 文件 | 修复前 | 修复后 | 变化 |
|---|---|---|---|
| `ocr_correction.py` | 548 | 171 | -377（精简为向后兼容包装） |
| `text_normalizer.py` | 707 | 1101 | +394（统一 normalize_ocr_text 入口） |
| `ai_safety.py` | — | 284 | 新增（AI 安全门禁） |
| `ocr_correction_common.py` | — | — | 新增（共享检测/过滤函数） |
| `pipeline_orchestrator.py` | 3550 | 3646 | +96（安全门禁集成 + watermark 序列化修复） |
| `ai_repair.py` | 850 | 899 | +49（向后兼容别名） |
| `tests/ocr_regression/runner.py` | ~500 | 1045 | +545（--baseline/--review/CI 模式） |

### 关键遗留项（P1/P2）

| 优先级 | 任务 | 预估工作量 |
|---|---|---|
| P1 | `pipeline_orchestrator.py` 拆分为 `pipeline_stages/` | 3-5 天 |
| P1 | `question_pipeline.py` 拆分为 normalizer/enricher/writer | 2-3 天 |
| P1 | AI 补全并行化 | 0.5 天 |
| P1 | `complete→enrich` 串联版本回退 | 1-2 天 |
| P1 | 断点恢复（最小子集） | 2-3 天 |
| P2 | ~~PaddleOCR 结果缓存~~ | ✅ 已完成（`ocr_cache_service.py`） |
| P2 | Qwen-VL 回退路径修复 | 0.5 天 |
| P2 | 合并两个 token budget | 0.5 天 |
| P2 | ~~高置信度跳过 AI 修复~~ | ✅ 已完成（`_is_low_risk_skip_candidate`） |
| P2 | 代码语义等价性检查 | 1-2 天 |

---

*报告结束。初版审计：2026-06-20，复查更新：2026-06-21。审计范围：全量代码扫描 + 文档审查 + 测试用例分析 + 配置审查。*
