# OCR Pipeline 全量工程审计报告

> 审计范围：`/home/lmh/projects/postgraduate-ai/backend/`
> 审计时间：2026-06-20（初版）→ 2026-07-08（末次更新：乱码代码持久检测 + code_structure 防假成功 + 答案透传修复）
> 审计方法：全量代码扫描 + 文档审查 + 测试用例分析 + 配置审查

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
│  app/api/router.py — 聚合入口                                        │
│  ├─ app/api/v1/router.py (public API)                               │
│  │   └─ /api/v1/import/pipeline/upload                              │
│  │      → import_pipeline_service.start_import_pipeline()           │
│  └─ app/api/admin/router.py (admin API)                             │
│      └─ /api/admin/v1/imports/upload                                │
│         → import_pipeline_service.start_import_pipeline()           │
│                                                                     │
│  ✅ 双入口架构: App=小程序导入, Admin=后台导入, 共享 service 层       │
│  ✅ 旧入口 410 Gone, OpenAPI 已清理, 无重复路径                      │
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
│  question_normalizer.py (1454行) → Layer 0/1/3: 题干清洗 + 分类器门控 + 选项标准化 + 题号防御转换  │
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
| `pipeline_orchestrator.py` | ~4871 | 19 阶段编排（含 classify_questions + code_structure_reconstruct）+ 性能 Profile + artifact 断点恢复 | 🟡 仍有降低空间 | 🟡 中 |
| `pipeline_stages/`（9 文件） | ~1380 | 9 独立 stage 实现（match/math_detect/table_detect/structure_freeze/code_structure...） | ✅ 各模块单一 | 🟢 低 |
| `question_pipeline.py` | 2921 | `QuestionNormalizer` + 向后兼容重导出 | 🟡 保留入口 | 🟢 低 |
| `question_ai_complete.py` | 741 | AI 补全 | ✅ 单一 | 🟢 低 |
| `question_ai_enrich.py` | 323 | AI 丰富 | ✅ 单一 | 🟢 低 |
| `question_draft_generator.py` | 134 | AI 生成草稿 | ✅ 单一 | 🟢 低 |
| `question_import_writer.py` | 749 | Excel/PDF 导入 + 审核操作 | ✅ 单一 | 🟢 低 |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 | ✅ 较好 | 🟡 中 |
| `text_normalizer.py` | 1400 | 规则清洗 + 统一 OCR 规范化入口 | ✅ 良好 | 🟢 低 |
| `ocr_fix/`（6 文件） | ~750 | 多模型 OCR 纠错路由（唯一路径） | ✅ 清晰 | 🟢 低 |
| `ocr_vl/paddleocr_vl_client.py` | ~430 | PaddleOCR-VL async HTTP 客户端 | ✅ 单一 | 🟢 低 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 | ✅ 清晰 | 🟢 低 |
| `ai_safety.py` | 284 | AI 编辑安全门禁 | ✅ 优秀 | 🟢 低 |
| `question_splitter.py` | 1437 | 题号+选项提取 | ✅ 良好 | 🟢 低 |
| `question_normalizer.py` | 1454 | Layer 0/1/3 集成：题干清洗 + 分类器门控 + 选项标准化 + OCR 质量门控 + 题号防御转换 | ✅ 单一（职责合理增长） | 🟢 低 |
| `ai_repair.py` | 1164 | AI 修复 + Layer 4 选项不可变门控（含 code integrity gate） | ✅ 较好 | 🟢 低 |
| `code_integrity.py` | 938 | 代码块完整性检测 + 乱码代码块识别 + 代码区域隔离 | ✅ 单一 | 🟢 低 |
| `question_type_classifier.py` | 454 | Layer 1 严格 has_options 门控 + force_options_probe() | ✅ 单一 | 🟢 低 |
| `batch_image_import_service.py` | ~1391 | 批量图片导入编排器（state machine + trace events + idempotency + request_id 幂等 + merge_status 守卫 + ocr_mode 路由 + 断点恢复） | 🟡 职责增长中 | 🟢 低 |
| `pipeline_artifacts.py` | 559 | Pipeline artifact 持久化、兼容性检查、断点恢复 | ✅ 单一 | 🟢 低 |
| `ocr_fix/router.py` | 428 | OCR 纠错降级链路由 + 候选结果评估安全门禁 + 乱码代码持久检测 | ✅ 良好 | 🟢 低 |
| `ocr_mode.py` | 89 | OCR 模式解析（local/api）+ 依赖校验 | ✅ 单一 | 🟢 低 |
| `pipeline_enums.py` | 139 | Pipeline 状态枚举 + 状态转换守卫 + trace mapping（SSOT） | ✅ 单一 | 🟢 低 |
| `time_utils.py` | 24 | 统一 UTC 时间工具 | ✅ 单一 | 🟢 低 |
| `layout_router.py` | 76 | 生产固化路由决策（pure confidence-based） | ✅ 纯函数 | 🟢 低 |
| `evaluation/routing_metrics.py` | 217 | 路由决策指标收集 | ✅ 单一 | 🟢 低 |
| `evaluation/split_quality.py` | 111 | 分割质量加权评估 | ✅ 单一 | 🟢 低 |
| `services/import_pipeline_service.py` | ~370 | Import pipeline 公共逻辑（统一导入/Pipeline 状态/后台任务） | ✅ 单一 | 🟢 低 |
| `api/router.py` / `api/v1/router.py` / `api/admin/router.py` | 3 files | 三层聚合 Router，main.py 仅 include_router(api_router) | ✅ 单一 | 🟢 低 |

### 2.2 关键结构问题（已修复摘要）

- **P5-2**: `pipeline_orchestrator.py` 9 个 stage 搬至 `pipeline_stages/`（4454→~4000 行）
- **P5-3**: `question_pipeline.py` 拆出 4 个模块（ai_complete/enrich/draft/import_writer）
- **OCR 清洗统一**: 3 处重复合并到 `text_normalizer.py:normalize_ocr_text()`
- **旧版路径清理**: `ocr_correction.py` 精简为 171 行包装层，纠错统一由 OCRFixRouter 处理
- **4 层 SSOT 架构（本期）**: 新建 `question_type_classifier.py` Layer 1 门控，`question_normalizer.py` 集成 Layer 0/1/3，`ai_repair.py` Layer 4 选项不可变扩展至全部题型，`pipeline_orchestrator.py` 新增 `classify_questions` enforcement 阶段
- **死代码清理（本期）**: 移除 `normalize_option_order`（Layer 0 禁止重排），收紧 `_CHOICE_KEYWORDS`（移除 `"下列"`、`"以下"` 单字防误判）
- **API Router 入口层重构（2026-07-04）**：`services/import_pipeline_service.py` 新建，导入公共逻辑从 `app.api.v1.imports` 抽离至 service 层；`app/api/router.py` / `app/api/v1/router.py` / `app/api/admin/router.py` 三层聚合，`main.py` include 从 37 降为 1；`admin_imports.py` 不再 import `app.api.v1.imports`，消除 API Router 间业务函数交叉引用；旧导入/审核/AI 补全接口（共 12 个）统一下线为 410 Gone；Admin 前缀统一 `/api/v1/admin/watermark-rules` → `/api/admin/v1/watermark-rules`
- **乱码代码持久检测（`ad0d237`）**：`ocr_fix/router.py` 和 `deepseek_adapter.py` 新增基于 `detect_code_block_integrity` 的乱码持久检查 —— 纯文本 LLM 无法可靠修复乱码代码，当修复前后 `code_garbled_text` flag 均存在且分数未显著改善（≥80%）时拒绝输出，退回原文
- **code_structure_reconstruct 防假成功（`ad0d237`）**：`code_structure_stage.py` 修复 LLM 修复后盲目清除所有结构 flag 的问题 —— 新增 pre/post 完整性对比，仅移除已解决的 flag，持久 flag 重新追加；`code_fixed` 基于实际解决的 flag 数而非模型自我报告；confidence 仅在乱码被解决时提升；`code_garbled_text` 和 `code_line_break_suspicious` 加入 `_CODE_STRUCTURE_FLAGS`
- **答案透传修复（`ad0d237`）**：`normalize_schema_stage.py` 和 `review_stage.py` 日志字段从 `parsed_answer` 修正为 `answer`；`question_normalizer.py` `normalize_questions()` 新增 `question_number` 和 `number` 的双向 int 防御转换，解决 string/int 类型不一致导致匹配失败的问题

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
| `bugs_case5_listinsert` | VL 输出将选项转为 LaTeX 符号 → 双源策略修复；PP-OCR 重跑文本与原始文本各有不同选项损坏（重跑：A 正确 B 乱码，原始：B 正确 A 乱码）| ✅ 双源策略 `62f4870` + Phase 3 original_raw_text merge + noise layer hallucination 清洗 + AI repair incomplete_options 兜底 |

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
| **P0** | 案例五残留：PP-OCR 重跑文本与原始文本各有不同选项损坏，VL_REBUILD 合并后仍缺选项 B；AI repair 因 system prompt 禁止修改 options 无法恢复 | ✅ Phase 3 original_raw_text merge（重跑文本 A 正确 B 乱码 + 原始文本 B 正确 A 乱码 → 合并得 4 选项）+ ai_repair incomplete_options trigger（兜底恢复） |
| **P1** | Pipeline store 终态条目未清理，内存持续增长 | ✅ Phase 5：移除 auto-eviction，改为 LRU prune 上限控制，终态条目保留供 SSE 轮询 |
| **P1** | Pipeline 断点恢复无可兼容性检查，版本不匹配时静默失败 | ✅ Phase 5：`check_artifact_compatibility()` + `stages_before()` 规范排序 |
| **P2** | OCR fix 路由缺少适配器候选评估安全门禁 | ✅ Phase 5：`CandidateDecision`/`CandidateEvaluation` + `risk_flags` + `safety` 字段 |
| **P2** | OCR 模式解析分散在各路由，无统一校验入口 | ✅ Phase 5：`ocr_mode.py` 集中式 mode 解析 + 依赖校验 |
| **P2** | Pipeline 状态值在模块间硬编码漂移 | ✅ Phase 5：`pipeline_enums.py` 枚举 SSOT + 状态转换守卫 |
| **P2** | `datetime.utcnow()` 弃用警告（~112 处）| ✅ Phase 5：统一替换为 `time_utils.utcnow()`，零项目自身弃用警告 |
| **P1** | 并发 merge 请求重复执行 `_merge_image_texts` | ✅ Phase 5 补丁：`merge_status == "running"` guard 在入口检查并发 |
| **P1** | `create_batch_job` 并发相同 request_id 产生重复 job | ✅ Phase 5 补丁：`ImportBatchJob.request_id` 唯一索引 + IntegrityError 捕获返回已有 job |
| **P2** | 同批去重 key `question_hash` 跨科目假阳（不同科目相同哈希误判为 dup） | ✅ Phase 5 补丁：去重 key 改为 `(subject, question_hash)` 元组 |
| **P2** | API Router 入口点过多、相同导入逻辑多条路径并行、Admin 非标准前缀 | ✅ 2026-07-04：Service 抽离 + 12 个旧入口 410 + Router 聚合 + 前缀统一 |
| **P3** | Trace event docstring 过时（声称 item-level 需要 FOR UPDATE 锁）| ✅ Phase 5 补丁：更新 docstring，明确 `id` 为增量读取依据 |
| **P0** | OCR fix 适配器输出乱码代码未经验证直接接受 | ✅ `ad0d237`：`router.py` + `deepseek_adapter.py` 新增基于 `detect_code_block_integrity` 的规则检测，乱码未显著改善时拒绝 |
| **P0** | `code_structure_reconstruct` 标记 `code_fixed=True` 即使乱码未解决 | ✅ `ad0d237`：pre/post integrity flag 对比，仅移除已解决 flag，confidence 仅乱码解决后提升 |
| **P1** | 审核日志字段名 `parsed_answer` 与实际字段 `answer` 不匹配 | ✅ `ad0d237`：`normalize_schema_stage.py` + `review_stage.py` 日志字段修正 |
| **P1** | `normalize_questions` 中 `question_number` 类型不一致（str/int）导致匹配失败 | ✅ `ad0d237`：双向 int 防御转换 |

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
| `features/pipeline_orchestrator.py` | ~4871 | 主编排器（19 阶段，含 classify_questions + code_structure_reconstruct）+ artifact 断点恢复 |
| `features/question_pipeline.py` | 2921 | 标准化管道 + 向后兼容重导出 |
| `features/batch_image_import_service.py` | ~1391 | 批量图片导入编排器（state machine + trace events + idempotency + request_id 幂等 + merge_status 守卫 + ocr_mode 路由 + 断点恢复） |
| `features/pipeline_artifacts.py` | 559 | Pipeline artifact 持久化、兼容性检查、断点恢复 |
| `services/import_pipeline_service.py` | ~400 | Import pipeline 公共逻辑（统一导入/Pipeline 状态/后台任务） |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 |
| `features/text_normalizer.py` | 1400 | 统一 OCR 文本规范化（13 步） |
| `features/question_splitter.py` | 1437 | 题号+选项提取 |
| `features/ai_repair.py` | 1164 | AI 修复（Layer 4 选项不可变门控） |
| `features/code_integrity.py` | 938 | 代码块完整性检测 + 乱码代码块识别 + 代码区域隔离 |
| `features/question_type_classifier.py` | 454 | Layer 1 题型分类门控 + force_options_probe() |
| `features/pipeline_stages/structure_freeze_stage.py` | 230 | 选项结构冻结（纯正则，split 前锁定选项） |
| `features/pipeline_stages/code_structure_stage.py` | 366 | 代码结构重建（LLM 修复 brace/indent/OCR 符号错误）+ pre/post integrity 防假成功 |
| `features/ocr_mode.py` | 89 | OCR 模式解析（local/api）+ 依赖校验 |
| `models/pipeline_enums.py` | 139 | Pipeline 状态枚举 + 状态转换守卫 + trace mapping（SSOT） |
| `core/time_utils.py` | 24 | 统一 UTC 时间工具 |

### OCR 纠错

| 文件 | 行数 | 用途 |
|---|---|---|
| `ocr_vl/paddleocr_vl_client.py` | ~430 | PaddleOCR-VL async HTTP 客户端 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 |
| `ocr_fix/router.py` | 428 | 降级链策略路由（唯一入口）+ 候选结果评估安全门禁 + 乱码代码持久检测 |
| `ocr_fix/interfaces.py` | 68 | OCRFixResult + CandidateDecision + CandidateEvaluation 接口定义 |
| `ocr_correction_common.py` | 254 | OCR 纠错通用逻辑 + repair_option_structure() |
| `ocr_fix/deepseek_adapter.py` | 177 | DeepSeek 纯文本纠错 + 乱码持久检查 + 题干丢失保护 |
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
| `tests/test_ocr_code_question_repair.py` | 460 行，22 个测试：答案透传（4）、乱码拒绝（7）、防假成功（3）、VL+frozen 合并（4）、回归断言（4） |

### 文档

| 文件 | 内容 |
|---|---|
| `docs/ocr/OPERATIONS.md` | 运维手册 |
| `docs/ocr/TROUBLESHOOTING.md` | 故障排查手册 |
| `docs/ocr/DEPLOY_CHECKLIST.md` | 发布检查清单 |
| `docs/architecture/OCR_FLOW.md` | OCR 导入流程架构 |

---

*报告结束。初版：2026-06-20，末次更新：2026-07-04。*
