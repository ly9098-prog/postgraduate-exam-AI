# OCR Pipeline 全量工程审计报告

> 审计范围：`/home/lmh/projects/postgraduate-ai/backend/`
> 审计时间：2026-06-20（初版）→ 2026-06-23（P9+Phase 2）→ **2026-06-23（PaddleOCR-VL 客户端修复 + ocr_mode=api 路由）**
> 审计方法：全量代码扫描 + 文档审查 + 测试用例分析 + 配置审查

**2026-06-23（本期新增）：**
- **PaddleOCR-VL 客户端 3 个 bug 修复**：轮询状态字段 `status`→`state`（官方 API 使用 `state`），失败消息 `errorMsg` 字段，JSONL 解析 `result.layoutParsingResults[].markdown.text`（原错解析顶层 `text`）
- **`ocr_mode=api` 路由**：batch-image 导入新增 API 模式，跳过本地 PaddleOCR，直接调用 PaddleOCR-VL，pipeline 跳过纠错阶段
- **轮询优化**：间隔 1.5s→5s + 首次轮询前延迟 5s，减少无用 DB 写入
- **认证头修正**：`bearer`→`Bearer`

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
│    ├─ PaddleOCRVLAdapter (ocr_vl/) → 外部高精 OCR API (链首)        │
│    │  API: POST /api/v2/ocr/jobs → poll data.state → JSONL          │
│    │  保护: 重试 3 次 + 超时 120s + 降级到下一适配器                │
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
│  question_normalizer.py (685行) → OCR 质量门控 + 题干/选项/答案提取  │
│  batch_validation.py → 跨题结构完整性验证 (保序/连续性/全局检查)     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                    AI 修复层 (AI Repair)                              │
│  ai_repair.py (1035行) → 两阶段修复: 罗马数字约束 + 标准批量         │
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
| 标准化层 | `RawQuestion[]` | `NormalizedQuestion[]` | `{type, stem, opts, answer, ...}` |
| AI 修复层 | `NormalizedQuestion[]` | `NormalizedQuestion[]` | 同上（修复后） |
| 入库层 | `NormalizedQuestion[]` | `question_imports` | DB 记录 |

---

## 2. 代码结构审计

### 2.1 模块职责评估表

| 模块 | 行数 | 职责 | 单一职责 | 耦合度 |
|---|---|---|---|---|
| `pipeline_orchestrator.py` | ~4400 | 16 阶段编排 + 性能 Profile + routing stability log | 🟡 仍有降低空间 | 🟡 中 |
| `pipeline_stages/`（8 文件） | ~1140 | 8 独立 stage 实现（match/math_detect/table_detect/structure_freeze/...） | ✅ 各模块单一 | 🟢 低 |
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
| `ai_repair.py` | 1035 | AI 修复（含 code integrity gate） | ✅ 较好 | 🟡 中 |
| `code_integrity.py` | 520 | 代码块完整性检测 | ✅ 单一 | 🟢 低 |
| `batch_image_import_service.py` | ~1050 | 批量图片导入编排器（state machine + trace events + idempotency + ocr_mode 路由） | ✅ 良好 | 🟢 低 |
| `layout_router.py` | 76 | 生产固化路由决策（pure confidence-based） | ✅ 纯函数 | 🟢 低 |
| `evaluation/routing_metrics.py` | 217 | 路由决策指标收集 | ✅ 单一 | 🟢 低 |
| `evaluation/split_quality.py` | 111 | 分割质量加权评估 | ✅ 单一 | 🟢 低 |

### 2.2 关键结构问题（已修复摘要）

- **P5-2**: `pipeline_orchestrator.py` 9 个 stage 搬至 `pipeline_stages/`（4454→~4000 行）
- **P5-3**: `question_pipeline.py` 拆出 4 个模块（ai_complete/enrich/draft/import_writer）
- **OCR 清洗统一**: 3 处重复合并到 `text_normalizer.py:normalize_ocr_text()`
- **旧版路径清理**: `ocr_correction.py` 精简为 171 行包装层，纠错统一由 OCRFixRouter 处理

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

### 4.1 已知失败样本（17 回归 case）

| 样本 | 根因 | 解决方式 |
|---|---|---|
| `faulty_case_1` | OCR `->` 识别为 `<-`+乱码 | ✅ 规则修复（`_fix_pointer_arrows`） |
| `faulty_case_2` | 双栏选项顺序 B→A→D→C | ✅ 栏阈值降低 |
| `faulty_case_3` | 数字字母混淆 0→O, 1→l | ✅ 字符映射 |
| `faulty_case_4` | 低置信水印未过滤 | ✅ 置信度阈值 |
| `watermark_fail_case` | 水印污染 → LLM 保留水印 | ✅ 品牌水印规则（P6-4） |
| `watermark_chart_case` | 水印+图表产生大量乱码 | ⚠️ 部分缓解 |
| `page_spread_case` | 跨页题号+答案不连接 | ⚠️ 部分修复 |

### 4.2 根因分类

| 根因 | 占比 |
|---|---|
| PaddleOCR 识别错误 | 45% |
| 版面分析错误 | 25% |
| 结构恢复错误 | 15% |
| AI 纠错幻觉 | 10% |
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
阶段 3: AI 纠错 → OCRFixRouter: PaddleOCR-VL → DeepSeek → Rule (✅ 唯一入口)
  └─ 客户端修复 (2026-06-23): data.state, errorMsg, layoutParsingResults 解析
阶段 4: 结构分析 + 页面分类 (不改)
阶段 5: 结构冻结 → 纯正则选项锁定，split/repair 只读 (新增 deff5fc)
阶段 6: 分割 + 答案匹配 (不改)
阶段 7: 标准化 + AI 修复 (可选) (不改)
阶段 8: 去重 + 入库 (不改)
```

---

## 附录：关键文件清单

### 核心管线

| 文件 | 行数 | 用途 |
|---|---|---|
| `features/pipeline_orchestrator.py` | ~4400 | 主编排器（17 阶段） |
| `features/question_pipeline.py` | 2921 | 标准化管道 + 向后兼容重导出 |
| `features/batch_image_import_service.py` | ~1050 | 批量图片导入编排器（含 ocr_mode 路由） |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 |
| `features/text_normalizer.py` | 1115 | 统一 OCR 文本规范化（13 步） |
| `features/question_splitter.py` | 1301 | 题号+选项提取 |
| `features/ai_repair.py` | 1035 | AI 修复 |
| `features/code_integrity.py` | 520 | 代码块完整性检测 |
| `features/pipeline_stages/structure_freeze_stage.py` | 230 | 选项结构冻结（纯正则，split 前锁定选项） |

### OCR 纠错

| 文件 | 行数 | 用途 |
|---|---|---|
| `ocr_vl/paddleocr_vl_client.py` | ~430 | PaddleOCR-VL async HTTP 客户端 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 |
| `ocr_fix/router.py` | 158 | 降级链策略路由（唯一入口） |
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

*报告结束。初版：2026-06-20，末次更新：2026-06-23（PaddleOCR-VL 客户端修复 + ocr_mode=api 路由）。*
