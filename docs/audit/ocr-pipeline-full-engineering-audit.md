# OCR Pipeline 全量工程审计报告

> 审计范围：`/home/lmh/projects/postgraduate-ai/backend/`
> 审计时间：2026-06-20（初版）→ 2026-06-23（P9+Phase 2）→ 2026-06-23（PaddleOCR-VL 客户端修复 + ocr_mode=api 路由）→ **2026-06-23（4 层 SSOT 架构重构）**→ **2026-06-24（VL confidence gate + VL_REBUILD 图片支持 + 双源 OCR 策略）**→ **2026-06-24（代码结构重建阶段 + 审核池泄漏修复）**→ **2026-06-24（噪声治理 v2 + 案例三修复补完）**
> 审计方法：全量代码扫描 + 文档审查 + 测试用例分析 + 配置审查

**2026-06-23（本期新增）：**
- **PaddleOCR-VL 客户端 3 个 bug 修复**：轮询状态字段 `status`→`state`（官方 API 使用 `state`），失败消息 `errorMsg` 字段，JSONL 解析 `result.layoutParsingResults[].markdown.text`（原错解析顶层 `text`）
- **`ocr_mode=api` 路由**：batch-image 导入新增 API 模式，跳过本地 PaddleOCR，直接调用 PaddleOCR-VL，pipeline 跳过纠错阶段
- **轮询优化**：间隔 1.5s→5s + 首次轮询前延迟 5s，减少无用 DB 写入
- **认证头修正**：`bearer`→`Bearer`

**2026-06-23（后续-本期新增）：**
- **4 层 SSOT 架构重构**：新建 `question_type_classifier.py` 作为 Layer 1 严格 has_options 门控，`normalize_question()` 集成分类器，新增 `classify_questions` 管道阶段做 enforcement 门控
- **Layer 0（Input Clean）**：`question_normalizer.py` 仅做字符级清洗，不重排 A/B/C/D，不填充缺失选项
- **Layer 3（Option Engine）**：条件执行，仅当 `has_options=True` 时标准化选项
- **Layer 4（AI Repair 不可变）**：`ai_repair.py` 扩展选项不可变约束至全部题型（3 规则：已存在+修改→拒绝，已存在+删除→拒绝，空+非冻结→允许恢复）
- **冻结选项 SSOT**：AI 修复后始终从 `frozen_option_registry` 恢复冻结选项
- **代码审查修复**：收紧 `_CHOICE_KEYWORDS`（移除 `"下列"`、`"以下"` 单字），修复 `in "ABCD"` 子串匹配，移除 `normalize_option_order` 死代码

**2026-06-24（本次新增）：**
- **Fix A — VL confidence gate override**：PaddleOCR-VL 返回 `confidence=0.0`（API 不提供置信度）时不再被 gate 丢弃，VL 结果进入 AI safety gate 正常评估
- **Fix B — VL_REBUILD 图片支持**：移除 `source_type == "pdf"` 限制，`_run_vl_rebuild_blocks()` 支持图片文件（直接读 bytes，跳过 PyMuPDF）
- **双源 OCR 策略**：VL_REBUILD 中 PP-OCRv6 = 结构主源，PaddleOCR-VL = 语义回退。PP-OCRv6 检测到选项时直接使用（跳过 VL API 调用），VL 输出通过 `repair_option_structure()` 修复选项结构
- **repair_option_structure()**：6 步修复管线 — HTML 清理、LaTeX 修复、裸选项恢复（无前缀行自动标记 A/B/C/D）、种子文本匹配
- **全链路 TRACE 日志**：raw_input → text_detection → classifier_result → options_branch → final_options
- **force_options_probe()**：debug 诊断函数，暴力扫描全部 7 种 option pattern 并报告

**2026-06-24（后续-本期新增）：**
- **代码结构重建阶段（code_structure_reconstruct）**：新增独立 pipeline 阶段，位于 `normalize_schema` → `classify_questions` 之间
  - 仅处理含 `code_brace_unbalanced` / `code_block_incomplete` / `code_fence_unclosed` 标记的题目
  - 专用 LLM prompt 允许修复 `{}` 闭合、`= =`→`==`、`- >`→`->`、缩进和断行（AI repair prompt 规则 10 禁止修改 `{}`）
  - AI safety gate 验证修复结果，仅接受高置信度变更
  - 修复 BUGS 案例三（while 循环缺 `}`）和案例四（for 循环断裂 `}`）
- **审核池泄漏修复**：pipeline 前序阶段失败时（如 code_structure_reconstruct 异常），自动跳过 `review` 阶段，防止部分数据写入 `question_imports`

**2026-06-24（第二次更新-本期新增）：**
- **噪声治理 v2**：新增 `NoiseMetrics` 数据类 + `NoiseMetricsCollector` 逐题指标收集 + 批量聚合 `NoiseMetricsSummary`。`clean_code_language_noise()` 通过 `_collector` 参数集成指标采集。下游新增 `noise_drift_detector.py`（KL 散度 drift 检测 + 拉普拉斯平滑，阈值 0.15）和 `noise_rule_governor.py`（基于 FP-rate 的 `safe_mode` 自适应切换，带迟滞）。stage 输出新增 `noise_metrics_summary` / `noise_drift` / `noise_governor` 三个观测字段。新增 49 个单元测试覆盖所有模块。清理死代码：移除 `confidence_threshold` 字段（实际控制由 `safe_mode` boolean 承担）、统一 key 命名 `fix_actions`→`code_language_noise_fix_actions`。
- **案例三修复补完（`ad33620`）**：案例三经双源 OCR 策略 + 代码结构重建修复后，仍有三个残留问题：
  1. **Transition 模式扩展**：`code_language_noise_layer._TRANSITION_PATTERNS` 新增 `r"在\w+中执行[：：]"` 模式，使"在单链表中执行:"能触发过渡区检测，将 `(>C` 噪声纳入清洗范围
  2. **题干选项重剥离**：`question_normalizer.py` 新增 stem re-strip 守卫 —— 当 splitter 返回空 `option_lines`（VL_REBUILD 路径）但 `normalize_schema` 独立检测到 ≥2 个选项时，回调 `_extract_stem` 从题干剥离选项文本
  3. **VL_REBUILD 冻结注册表清理**：`pipeline_orchestrator.py` 在 VL_REBUILD 替换 blocks 后将 `frozen_option_registry = None`，防止冻结门控阻止基于正则的选项提取

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
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   OCR 识别层 (PaddleOCR / PaddleOCR-VL)              │
│                                                                     │
│  local 模式:                                                        │
│    services/ocr_service.py (637行):                                  │
│      ├─ _get_ocr()          → PaddleOCR 单例 (GPU/CPU, 延迟加载)    │
│      ├─ ocr_pages_with_boxes()  → PDF 逐页 OCR + bounding boxes    │
│      ├─ ocr_image()         → 单图 OCR                              │
│      ├─ ocr_pages()         → 纯文本 OCR (无 box)                   │
│      ├─ 预处理: EXIF 转正 + 缩放 + 裁边 + 自适应增强 + 旋转检测      │
│      └─ 后处理: clean_ocr_text() → 代码围栏 + 乱码移除 + 箭头修复   │
│                                                                     │
│  api 模式 (ocr_mode=api, 2026-06-23 新增):                          │
│    batch_image_import_service._run_vl_ocr()                         │
│      → resolve_active_model(feature="ocr") DB 解析                   │
│      → PaddleOCRVLClient.ocr_image() (异步提交+轮询)                │
│      → 跳过本地 OCR + pipeline 纠错阶段                             │
│                                                                     │
│  ✅ PaddleOCR-VL 客户端修复 (2026-06-23):                            │
│     ├─ state 字段 (原 status) — 官方 API 使用 data.state             │
│     ├─ errorMsg 字段 (原 error/message)                              │
│     ├─ JSONL 解析 result.layoutParsingResults[].markdown.text        │
│     ├─ 轮询间隔 5s + 首次 5s 延迟 (原 1.5s 立即轮询)                │
│     └─ 认证头 Bearer (原 bearer)                                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   规则清洗层 (Rule-based Normalization)               │
│  features/text_normalizer.py (1115行) — ImportTextNormalizer         │
│    ├─ normalize() → 13 步管线: 换行/空格/标点/乱码/OCR 修正/         │
│    │  罗马数字/指针箭头/答案块/LaTeX/水印过滤 (P6-4 扩充品牌关键词)  │
│    └─ 所有字符映射统一维护 (8→B, 0→O/D, l→1, rn→m, cl→d)           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│              AI OCR 纠错层 (Multi-Model Correction)                  │
│  唯一路径 — OCRFixRouter (ocr_fix/router.py):                       │
│    ├─ PP-OCRv6 (local) → 结构主源 (VL_REBUILD 中优先)              │
│    │  策略: detect_options=True → 直接使用，跳过 VL API             │
│    ├─ PaddleOCRVLAdapter (ocr_vl/) → 外部高精 OCR API (链首/回退)  │
│    │  API: POST /api/v2/ocr/jobs → poll data.state → JSONL          │
│    │  保护: 重试 3 次 + 超时 120s + 降级到下一适配器                │
│    ├─ repair_option_structure() → VL 输出结构修复 (LaTeX/列表/缺前缀)│
│    ├─ DeepSeekFixer (deepseek_adapter.py, 126行) → 纯文本纠错       │
│    └─ RuleFixer (rule_adapter.py, 41行) → no-op fallback            │
│                                                                     │
│  AI Safety Gate (ai_safety.py, 284行):                              │
│    ├─ evaluate_and_trace() → 变更前后 diff + 安全检查               │
│    ├─ safe_accept_ai_result() → 代码符号/中文比例/选项数保护         │
│    └─ AIEditTrace → 可审计的编辑轨迹                                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   结构分析 & 分割层 (Structure & Split)               │
│  structure_analyzer.py (466行) — Q/A/Analysis 区域检测               │
│  question_splitter.py (1301行) — 题号+选项提取 + 跨页恢复           │
│  page_classifier.py → 页面分类 / visual_boundary_detector.py → 边界  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   结构冻结层 (Structure Freeze)                       │
│  pipeline_stages/structure_freeze_stage.py (230行) — 选项结构冻结    │
│    ├─ 纯正则检测 (无 AI，无启发式)                                    │
│    ├─ 支持 A./B./C./D. / ①.②.③.④. / (A)(B) 及 inline 格式         │
│    ├─ 输出 frozen_option_registry → split/normalize/repair 只读     │
│    └─ 确保全 pipeline 选项只提取一次，消除 split 与下游的选项偏移     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   分割层 & 答案匹配 (Split & Match)                    │
│  question_splitter.py (1301行) — 题号+选项提取 + 跨页恢复           │
│    读取 frozen_option_registry，优先使用冻结选项而非重新提取          │
│  answer_matcher.py → 题号精确匹配 + 序列回退                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   标准化层 (Normalize)                                │
│  answer_matcher.py → 题号精确匹配 + 序列回退                         │
│  question_normalizer.py (1165行) → Layer 0/1/3: 题干清洗 + 分类器门控 + 选项标准化  │
│  batch_validation.py → 跨题结构完整性验证 (保序/连续性/全局检查)     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│               代码结构重建层 (Code Structure Reconstruct)              │
│  pipeline_stages/code_structure_stage.py (312行)                    │
│  ├─ 检测: code_brace_unbalanced / code_block_incomplete /            │
│  │        code_fence_unclosed                                       │
│  ├─ 修复: LLM 专用 prompt 闭合 {}、修复 `= =`→`==`、`- >`→`->`、    │
│  │        拼接断裂语句、恢复缩进                                     │
│  └─ 保护: AI safety gate 验证变更，拒绝高风险修改                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                    AI 修复层 (AI Repair)                              │
│  ai_repair.py (1116行) → Layer 4 两阶段修复: 罗马数字 + 标准批量（选项不可变门控）         │
│  llm_text_structurer.py (451行) → LLM 结构化 (规则不足时触发)        │
│  保护: 反幻觉检查 + token_budget 共享管理                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   去重 & 入库层 (Dedup & Persist)                    │
│  similarity_matcher.py → 哈希优先 + difflib 回退                    │
│  review_service.py → submit_to_review() → question_imports 暂存表   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 各层 Input/Output 总结

| 层 | Input | Output | 格式 |
|---|---|---|---|
| 输入层 | PDF/图片/TXT/Excel | bytes/filepath | 二进制 |
| OCR 识别层 (local) | bytes/numpy | `OcrPageResult[]` | `{text, bbox[[4,2]], conf}` |
| OCR 识别层 (api, 新增) | bytes | `PaddleOCRVLResult` | `{text, confidence, raw}` |
| 规则清洗层 | str | str | 纯文本 |
| AI 纠错层 | str + 可选图片 bytes | str | 纯文本 |
| 结构分析层 | str[] | `PageStructure` | `{mode, q_count, a_count}` |
| 结构冻结层 | 分类后 blocks | `frozen_option_registry` | `{(page,block_idx): {A: text, ...}}` |
| 分割层 | str[] + frozen_option_registry | `RawQuestion[]` | `{number, stem, options, answer}` |
| 题型分类层（Layer 1） | raw_text + option_lines | `classification dict` | `{has_options, reason, confidence}` |
| 标准化层 | `RawQuestion[]` | `NormalizedQuestion[]` | `{type, stem, opts, answer, ...}` |
| AI 修复层 | `NormalizedQuestion[]` | `NormalizedQuestion[]` | 同上（修复后） |
| 入库层 | `NormalizedQuestion[]` | `question_imports` | DB 记录 |

---

## 2. 代码结构审计

### 2.1 模块职责评估表

| 模块 | 行数 | 职责 | 单一职责 | 耦合度 |
|---|---|---|---|---|
| `pipeline_orchestrator.py` | ~4650 | 19 阶段编排（含 classify_questions + code_structure_reconstruct）+ 性能 Profile | 🟡 仍有降低空间 | 🟡 中 |
| `pipeline_stages/`（9 文件） | ~1380 | 9 独立 stage 实现（match/math_detect/table_detect/structure_freeze/code_structure...） | ✅ 各模块单一 | 🟢 低 |
| `question_pipeline.py` | 2921 | `QuestionNormalizer` + 向后兼容重导出 | 🟡 保留入口 | 🟢 低 |
| `question_ai_complete.py` | 741 | AI 补全 | ✅ 单一 | 🟢 低 |
| `question_ai_enrich.py` | 323 | AI 丰富 | ✅ 单一 | 🟢 低 |
| `question_draft_generator.py` | 134 | AI 生成草稿 | ✅ 单一 | 🟢 低 |
| `question_import_writer.py` | 749 | Excel/PDF 导入 + 审核操作 | ✅ 单一 | 🟢 低 |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 | ✅ 较好 | 🟡 中 |
| `text_normalizer.py` | 1115 | 规则清洗 + 统一 OCR 规范化入口 | ✅ 良好 | 🟢 低 |
| `ocr_fix/`（6 文件） | ~750 | 多模型 OCR 纠错路由（唯一路径） | ✅ 清晰 | 🟢 低 |
| `ocr_vl/paddleocr_vl_client.py` | ~430 | PaddleOCR-VL async HTTP 客户端 | ✅ 单一 | 🟢 低 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 | ✅ 清晰 | 🟢 低 |
| `ai_safety.py` | 284 | AI 编辑安全门禁 | ✅ 优秀 | 🟢 低 |
| `question_splitter.py` | 1301 | 题号+选项提取 | ✅ 良好 | 🟢 低 |
| `question_normalizer.py` | 1165 | Layer 0/1/3 集成：题干清洗 + 分类器门控 + 选项标准化 + OCR 质量门控 | ✅ 单一（职责合理增长） | 🟢 低 |
| `ai_repair.py` | 1116 | AI 修复 + Layer 4 选项不可变门控（含 code integrity gate） | ✅ 较好 | 🟢 低 |
| `code_integrity.py` | 520 | 代码块完整性检测 | ✅ 单一 | 🟢 低 |
| `question_type_classifier.py` | 172 | Layer 1 严格 has_options 门控（新建模块，纯规则） | ✅ 单一 | 🟢 低 |
| `batch_image_import_service.py` | ~1050 | 批量图片导入编排器（state machine + trace events + idempotency + ocr_mode 路由） | ✅ 良好 | 🟢 低 |
| `layout_router.py` | 76 | 生产固化路由决策（pure confidence-based） | ✅ 纯函数 | 🟢 低 |
| `evaluation/routing_metrics.py` | 217 | 路由决策指标收集 | ✅ 单一 | 🟢 低 |
| `evaluation/split_quality.py` | 111 | 分割质量加权评估 | ✅ 单一 | 🟢 低 |

### 2.2 关键结构问题（已修复摘要）

- **P5-2**: `pipeline_orchestrator.py` 9 个 stage 搬至 `pipeline_stages/`（4454→~4000 行）
- **P5-3**: `question_pipeline.py` 拆出 4 个模块（ai_complete/enrich/draft/import_writer）
- **OCR 清洗统一**: 3 处重复合并到 `text_normalizer.py:normalize_ocr_text()`
- **旧版路径清理**: `ocr_correction.py` 精简为 171 行包装层，纠错统一由 OCRFixRouter 处理
- **4 层 SSOT 架构（本期）**: 新建 `question_type_classifier.py` Layer 1 门控，`question_normalizer.py` 集成 Layer 0/1/3，`ai_repair.py` Layer 4 选项不可变扩展至全部题型，`pipeline_orchestrator.py` 新增 `classify_questions` enforcement 阶段
- **死代码清理（本期）**: 移除 `normalize_option_order`（Layer 0 禁止重排），收紧 `_CHOICE_KEYWORDS`（移除 `"下列"`、`"以下"` 单字防误判）

---

## 3. LLM 使用审计（重点）

### 3.1 所有 LLM 调用全览

| 调用点 | 模型 | 触发条件 | 视觉 |
|---|---|---|---|
| `ocr_vl/paddleocr_vl_adapter.py` | PaddleOCR-VL-1.6 | OCR 路由链首（每批噪声块） | ✅ 原图 |
| `ocr_fix/deepseek_adapter.py` | DeepSeek-v4-flash | VL 失败/不可用（回退） | ❌ |
| `ai_repair.py` | DeepSeek-v4-flash | 规则修复后仍有不达标题 | ❌ |
| `llm_text_structurer.py` | DeepSeek-v4-flash | 规则结构分析不足 | ❌ |
| `question_pipeline.py:enrich/complete` | DeepSeek-v4-flash | 人工触发/自动补全 | ❌ |

> ✅ Qwen-VL 已完全移除（qwen_adapter.py 删除 309 行）。路由链：PaddleOCR-VL → DeepSeek → Rule。

### 3.2 Hallucination 保护

**已有：**
- `deepseek_adapter.py`: 长度越界检查 + 题干丢失保护
- `llm_text_structurer.py`: 反幻觉检查（字段必须在原文中找到）
- `ai_safety.py:evaluate_and_trace()`: 变更前后 diff + 代码符号/中文比例/选项数保护

**缺失：**
- `complete→enrich` 串联无版本回退
- 代码场景无语义等价性检查

---

## 4. 失败案例分析

### 4.1 已知失败样本（17 回归 case + 5 BUGS case）

| 样本 | 根因 | 解决方式 |
|---|---|---|
| `faulty_case_1` | OCR `->` 识别为 `<-`+乱码 | ✅ 规则修复（`_fix_pointer_arrows`） |
| `faulty_case_2` | 双栏选项顺序 B→A→D→C | ✅ 栏阈值降低 |
| `faulty_case_3` | 数字字母混淆 0→O, 1→l | ✅ 字符映射 |
| `faulty_case_4` | 低置信水印未过滤 | ✅ 置信度阈值 |
| `watermark_fail_case` | 水印污染 → LLM 保留水印 | ✅ 品牌水印规则（P6-4） |
| `watermark_chart_case` | 水印+图表产生大量乱码 | ⚠️ 部分缓解 |
| `page_spread_case` | 跨页题号+答案不连接 | ⚠️ 部分修复 |
| `bugs_case1_stack` | VL confidence=0.0 被 gate 丢弃 | ✅ Fix A `0fed945` |
| `bugs_case2_treerecursion` | VL_REBUILD 被 `source_type=="pdf"` 阻断 | ✅ Fix B `be03159` |
| `bugs_case3_linkedlist` | VL 输出去掉了选项字母前缀 + `(>C` 代码类型噪声残留 + frozen 注册表阻塞题干重建 | ✅ 双源策略 `62f4870` + 代码结构重建 `e91a020` + transition 模式扩展/题干重剥离/冻结清理 `ad33620` |
| `bugs_case4_forloop` | 基线通过；`}` 断裂 + brace 告警残留 | ✅ 代码结构重建 `e91a020` |
| `bugs_case5_listinsert` | VL 输出将选项转为 LaTeX 符号 | ✅ 双源策略 `62f4870` |

### 4.2 根因分类

| 根因 | 占比 |
|---|---|
| PP-OCRv6 识别错误（含裁切/漏识别） | 40% |
| 版面分析错误 | 20% |
| 结构恢复错误 | 10% |
| PaddleOCR-VL 输出质量（缺前缀/LaTeX 污染/列表化） | 10% |
| VL confidence gate / pipeline routing | 10% |
| AI 纠错幻觉 | 5% |
| 代码场景特殊 | 5% |

> P6-3 新增 `ocr_failure_analyzer.py`（16 种分类），pipeline 完成后自动归因。

---

## 5. 性能与成本审计

### 5.1 LLM 成本估算

| 调用 | Tokens/100 页 | 成本 |
|---|---|---|
| PaddleOCR-VL 纠错 | 图片 | 外部 API 按次 |
| DeepSeek 纠错（回退） | 10K | ¥0.003 |
| DeepSeek 修复 | 36K | ¥0.011 |
| DeepSeek 补全+丰富 | 200K | ¥0.06 |
| **合计** | **~246K + API** | **~¥0.08 + 外部 API** |

### 5.2 Latency Bottleneck（本地 i7+3060, 100 页）

| 阶段 | 耗时 | 瓶颈 |
|---|---|---|
| PaddleOCR (GPU) | 10-25s | ✅ 可接受 |
| PaddleOCR-VL 纠错 | 15-40s | 🚨 外部 API（信号量=3） |
| DeepSeek 修复 | 10-30s | API 调用 |
| AI 补全 | 30-200s | 🚨 50 题串行 |
| **总计** | **~2-5min** | 可接受 |

> P6-2 内置性能 Profile（`diagnostics.performance_profile`），每 stage 耗时/IO/AI 调用/缓存命中率。

---

## 6. 最终结论

### 6.1 核心问题状态

| 优先级 | 问题 | 状态 |
|---|---|---|
| **P0** | 3 个内存缺陷（PDF bytes 驻留 + 双 OCR + store 大字段） | ✅ d7b2ae5, 04fd013 |
| **P0** | 旧版 `ocr_correction.py` 与新版并行 | ✅ edcfd0c |
| **P0** | OCR 清洗三处重复不同步 | ✅ cc419dd |
| **P0** | AI 纠错→修复无 diff 防护 | ✅ edcfd0c, 04fd013 |
| **P0** | 回归测试同义反复 | ✅ 058aea3, b63df47 |
| **P1** | 超级类拆分 | ✅ P5-2 + P5-3 |
| **P1** | 公式截图+审核提效 | ✅ c82c464 |
| **P1** | AI 补全并行化 | ⏳ |
| **P1** | 断点恢复 | ⏳ |
| **P9** | DAG 编排 + Batch-Image 并发一致性 | ✅ ede71f9, dce5aa4 |
| **Phase 2** | 路由策略固化 + Evaluation | ✅ 484d4e0, a9946af |
| **2026-06-23** | PaddleOCR-VL 客户端 `state`/`errorMsg`/JSONL 解析 bug | ✅ 本轮修复 |
| **2026-06-23** | `ocr_mode=api` 路由（跳过本地 OCR） | ✅ 本轮修复 |
| **P0** | 选项检测/修复路径不一致（split→normalize→repair 各自检测选项） | ✅ SSOT 冻结 + Layer 1 分类器 + Layer 4 不可变 |
| **P0** | AI repair 篡改 frozen/non-frozen 选项 | ✅ 773e8ef（3 规则不可变） |
| **P1** | `_CHOICE_KEYWORDS` 过宽导致非选择题误判 | ✅ 54fbeeb（移除 `"下列"`、`"以下"` 单字） |
| **P2** | `in "ABCD"` 子串匹配隐患 + 死代码 `normalize_option_order` | ✅ 773e8ef |
| **P0** | PaddleOCR-VL confidence=0.0 丢弃 VL 结果 | ✅ 0fed945（confidence gate override） |
| **P0** | VL_REBUILD PDF-only 限制导致图片导入结构无法恢复 | ✅ be03159（图片文件支持） |
| **P0** | VL 输出结构性损坏（缺前缀/LaTeX）→ 选项丢失 | ✅ 62f4870（双源策略 + repair） |
| **P0** | AI repair prompt 规则 10 禁止修改 `{}`，导致代码 brace 无法修复 | ✅ e91a020（独立 code_structure_reconstruct 阶段 + 专用 prompt） |
| **P1** | 管道前序阶段失败时 review 仍写入审核池，导致部分数据泄漏 | ✅ P5-3 skip review on prior failure |
| **P0** | 案例三残留：`(>C` 代码类型噪声因 transition 模式缺失未被清洗 | ✅ ad33620（新增 `在\w+中执行[：：]` 模式扩展 transition 检测） |
| **P0** | 案例三残留：VL_REBUILD 路径 splitter 空 option_lines 导致选项无法从题干剥离 | ✅ ad33620（normalize_schema 独立检测选项后回调 _extract_stem 重剥离） |
| **P0** | 案例三残留：VL_REBUILD 替换 blocks 后 frozen_option_registry 阻塞正则选项提取 | ✅ ad33620（VL_REBUILD 后将 frozen_option_registry 置 None） |
| **P2** | 代码类型噪声清洗无可观测性（无指标/无 drift 检测/无策略自适应） | ✅ cb33729（NoiseMetrics + KL drift 检测 + 自适应 safe_mode 切换，49 测试） |

### 6.2 改造路线图（压缩）

```
✅ 阶段一: P0 基础清理 + 回归基线 (b63df47)
✅ 阶段一B: P1 公式截图 + 审核提效 (c82c464)
✅ 阶段二B: P2 三项改造 (OCR 缓存/图片引用/跳过修复)
✅ 阶段二: P5 超级类拆分 (pipeline_stages/ + 4 模块)
✅ 阶段三: P6 验收+Profile+归因+精调+Dashboard+CI
✅ 阶段四: P7 生产运维 (观测/告警/清理/导出/Preflight/文档)
✅ 阶段五: P9 DAG + Batch-Image 并发 (ede71f9, dce5aa4)
✅ Phase 2: 路由策略固化 + Evaluation (484d4e0)
✅ 本轮: PaddleOCR-VL 客户端修复 + ocr_mode=api 路由
✅ **本轮后续: 4 层 SSOT 架构重构（773e8ef）**
  - Layer 1 question_type_classifier 严格 has_options 门控
  - Layer 0/3 option engine 不重排、不填充
  - Layer 4 AI repair 选项不可变（3 规则）
  - 代码审查修复（关键词收紧、死代码清理、子串匹配修复）
✅ **2026-06-24: BUGS 全 case 修复（0fed945 + be03159 + 62f4870 + e91a020）**
  - Fix A: VL confidence gate override（conﬁdence=0.0 不再丢弃结果）
  - Fix B: VL_REBUILD 取消 PDF 限制 + 图片文件支持
  - 双源 OCR 策略：PP-OCRv6 = 结构主源，VL = 语义回退
  - repair_option_structure()：VL 输出结构修复（LaTeX/列表/缺前缀）
  - force_options_probe()：debug 诊断函数
  - 全链路 TRACE 日志（6 阶段）
  - 代码结构重建阶段：修复 BUGS 案例三/四的 brace 不闭合 / 语句断裂问题
  - 审核池泄漏修复：前序阶段失败时跳过 review 阶段
  - **噪声治理 v2：NoiseMetrics + KL drift 检测 + 自适应 safe_mode 切换 (cb33729)**
  - **案例三修复补完：transition 模式扩展 / 题干重剥离 / VL_REBUILD 冻结清理 (ad33620)**

⏳ 待处理:
  - AI 补全并行化 (0.5d)
  - complete→enrich 版本回退 (1-2d)
  - 断点恢复最小子集 (2-3d)
  - 代码语义等价性检查 (1-2d)
  - 合并 token budget (0.5d)
  - raw_data 字段瘦身 (0.5d)
```

### 6.3 推荐新 Pipeline 结构

```
贯穿全局: 内存治理 ✅ + 性能 Profile ✅ + 失败归因 ✅ + 路由评估 ✅
  ├─ PDF bytes 落盘释放 | 消除双 OCR | store 瘦身 | review 分批 commit
  ├─ P6-2 per-stage 耗时/cache/AI/tokens | P6-3 16 种失败自动分类
  └─ Phase 2 routing_metrics + split_quality + _log_routing_stability

阶段 1: OCR 识别 (二选一)
  ├─ local: PaddleOCR (GPU/CPU) → OcrPageResult[]
  └─ api:   PaddleOCR-VL 远程 API → text (2026-06-23 新增)

阶段 2: 规则清洗 → text_normalizer (✅ 唯一入口)
阶段 3: AI 纠错 → OCRFixRouter: PP-OCRv6(结构主源) / PaddleOCR-VL → DeepSeek → Rule (✅ 唯一入口)
  ├─ PP-OCRv6 检测到选项时直接使用（VL_REBUILD 中优先，跳过 VL API）
  └─ VL 输出通过 repair_option_structure() 修复（缺前缀/LaTeX/列表化）
  └─ 客户端修复 (2026-06-23): data.state, errorMsg, layoutParsingResults 解析
阶段 4: 结构分析 + 页面分类 (不改)
	阶段 5: 结构冻结 → 纯正则选项锁定，split/repair 只读 (新增 deff5fc)
	阶段 6: 分割 + 答案匹配 (不改)
	阶段 7: 标准化 + Layer 1 分类门控 + Layer 4 选项不可变 (773e8ef)
	  ├─ Layer 0: 不重排、不填充
	  ├─ Layer 1: question_type_classifier → has_options 严格门控
	  └─ Layer 4: 3 规则选项不可变 (修改/删除→拒绝, 空+非冻结→允许恢复)
	阶段 7B: 代码结构重建 → code_structure_reconstruct (e91a020)
	  ├─ 检测: code_brace_unbalanced / code_block_incomplete / code_fence_unclosed
	  ├─ 修复: LLM 专用 prompt 闭合 {}、修复 OCR 符号错误、拼接断裂语句
	  └─ 保护: AI safety gate 验证变更，拒绝高风险修改
	阶段 8: 去重 + 入库 (不改)
```

---

## 附录：关键文件清单

### 核心管线

| 文件 | 行数 | 用途 |
|---|---|---|
| `features/pipeline_orchestrator.py` | ~4650 | 主编排器（19 阶段，含 classify_questions + code_structure_reconstruct） |
| `features/question_pipeline.py` | 2921 | 标准化管道 + 向后兼容重导出 |
| `features/batch_image_import_service.py` | ~1050 | 批量图片导入编排器（含 ocr_mode 路由） |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 |
| `features/text_normalizer.py` | 1115 | 统一 OCR 文本规范化（13 步） |
| `features/question_splitter.py` | 1301 | 题号+选项提取 |
| `features/ai_repair.py` | 1116 | AI 修复（Layer 4 选项不可变门控） |
| `features/code_integrity.py` | 520 | 代码块完整性检测 |
| `features/question_type_classifier.py` | 455 | Layer 1 题型分类门控 + force_options_probe() |
| `features/pipeline_stages/structure_freeze_stage.py` | 230 | 选项结构冻结（纯正则，split 前锁定选项） |
| `features/pipeline_stages/code_structure_stage.py` | 312 | 代码结构重建（LLM 修复 brace/indent/OCR 符号错误） |

### OCR 纠错

| 文件 | 行数 | 用途 |
|---|---|---|
| `ocr_vl/paddleocr_vl_client.py` | ~430 | PaddleOCR-VL async HTTP 客户端 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 |
| `ocr_fix/router.py` | 158 | 降级链策略路由（唯一入口） |
| `ocr_correction_common.py` | 254 | OCR 纠错通用逻辑 + repair_option_structure() |
| `ocr_fix/deepseek_adapter.py` | 126 | DeepSeek 纯文本纠错 |
| `ai_safety.py` | 284 | AI 编辑安全门禁 |

### Evaluation（Phase 2 新增）

| 文件 | 行数 | 用途 |
|---|---|---|
| `features/layout_router.py` | 76 | 固化路由决策（三档 confidence-based） |
| `evaluation/routing_metrics.py` | 217 | 路由决策指标收集 |
| `evaluation/split_quality.py` | 111 | 分割质量评估 |
| `scripts/run_ab_experiment.py` | 237 | A/B 实验 runner |

### 测试

| 文件 | 用途 |
|---|---|
| `tests/ocr_regression/runner.py` | ✅ 回归运行器（--baseline/--review/CI） |
| `tests/ocr_regression/cases/` | ✅ 17 个回归 case（9 合成 + 8 真实） |
| `tests/ocr_acceptance/run_acceptance.py` | ✅ 验收测试 runner |
| `tests/ocr_acceptance/cases/` | ✅ 10 类样本模板 |
| `tests/test_evaluation/test_routing_metrics.py` | Phase 2 路由指标测试 |

### 文档

| 文件 | 内容 |
|---|---|
| `docs/ocr/OPERATIONS.md` | 运维手册 |
| `docs/ocr/TROUBLESHOOTING.md` | 故障排查手册 |
| `docs/ocr/DEPLOY_CHECKLIST.md` | 发布检查清单 |
| `docs/architecture/OCR_FLOW.md` | OCR 导入流程架构 |

---

*报告结束。初版：2026-06-20，末次更新：2026-06-24（BUGS 全 case 修复 + 双源 OCR 策略）。*
