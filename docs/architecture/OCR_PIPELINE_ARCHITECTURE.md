# OCR Pipeline 架构文档

> 维护时间：2026-07-18
> 审计参考：`docs/audit/OCR_PIPELINE_AUDIT_RECORDS.md`、`prompts/tasks/fix_task.md`
>
> **修复进展：Sprint 0 ✅ | Sprint 1 ✅ | Sprint 2 ✅ | Sprint 3 (4/5 ✅ 1 ⏳)**

---

## 目录

1. [现状架构](#1-现状架构)
2. [各层 Input/Output 总结](#2-各层-inputoutput-总结)
3. [推荐目标架构](#3-推荐目标架构)
4. [架构差距分析](#4-架构差距分析)
5. [路线图：分阶段演进](#5-路线图分阶段演进)
6. [关键文件清单](#6-关键文件清单)

---

## 1. 现状架构

### 1.1 Pipeline 分层结构（当前实现）

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
│  ✅ 双入口: App=小程序导入, Admin=后台导入, 共享 service 层           │
│  ✅ 旧入口 410 Gone, OpenAPI 已清理                                  │
│  ✅ Coordinator Pipeline 接入 (2026-07-18)                          │
│     └─ pipeline_coordinator_entry.run_pipeline() 三模式             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   OCR 识别层 (PaddleOCR / PaddleOCR-VL)              │
│                                                                     │
│  ⚠️ 本层存在多重执行入口（S0-04 未完全修复）：                         │
│     ├─ features/pipeline_orchestrator.py 直接调用                    │
│     ├─ features/question_pipeline.py 直接调用                       │
│     ├─ features/batch_image_import_service.py 调用                   │
│     └─ services/ocr_service.py 自身创建线程池                        │
│                                                                     │
│  local 模式:                                                        │
│    services/ocr_service.py (当前 ~773 行, 报告记录 637):             │
│      ├─ _get_ocr()          → PaddleOCR 单例 (GPU/CPU, 延迟加载)    │
│      │  ✅ 状态机: UNINITIALIZED/READY/RESETTING/FAILED             │
│      │  ✅ 三重锁: _state_lock + _inference_lock + _init_lock       │
│      ├─ ocr_pages_with_boxes()  → PDF 逐页 OCR + bounding boxes    │
│      ├─ ocr_image()         → 单图 OCR                              │
│      ├─ ocr_pages()         → 纯文本 OCR (无 box)                   │
│      ├─ 预处理: EXIF 转正 + 缩放 + 裁边 + 自适应增强 + 旋转检测      │
│      └─ 后处理: clean_ocr_text() → 代码围栏 + 乱码移除 + 箭头修复   │
│      ⚠️ 低置信过滤可能误删代码/公式/英文选项（S1-4.8）               │
│      ⚠️ 预处理不可逆，缺坐标变换记录（S1-4.9）                       │
│                                                                     │
│  api 模式 (ocr_mode=api, 2026-06-23 新增):                          │
│    batch_image_import_service._run_vl_ocr()                         │
│      → AIModelConfigResolver.resolve_for_capability(OCR_FIX) DB 解析│
│      → PaddleOCRVLClient.ocr_image() (异步提交+轮询)                │
│      → 跳过本地 OCR + pipeline 纠错阶段                             │
│                                                                     │
│  ✅ 配置统一 (2026-07-18)                                            │
│     └─ AIModelConfigResolver + AICapability.OCR_FIX/AI_REPAIR       │
│                                                                     │
│  ⚠️ PaddleOCR-VL 客户端缺生产级 HTTP 生命周期治理（S1-4.5）           │
│     └─ 每次提交/轮询/下载可能新建 httpx.AsyncClient                  │
│     └─ 缺少 SSRF 保护、大小限制、redirect 验证（S0-09 未修复）       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│               OCR 执行器层 (Executor/Worker)                          │
│                                                                     │
│  ✅ S0-01: idx 正确传递（闭包参数化，无 UnboundLocalError）          │
│  ✅ S0-02: future.add_done_callback 正确释放容量                    │
│  ✅ S0-03: asyncio.wrap_future 替代双线程池                         │
│                                                                     │
│  services/ocr_executor_service.py:                                  │
│    ├─ run_ocr_pages_in_thread() → 线程池 + semaphore + done_callback │
│    ├─ run_ocr_pages_in_process() → OcrProcessPool（进程隔离）        │
│    └─ _run_in_executor() → wrap_future + wait_for + shield          │
│                                                                     │
│  ⚠️ S1-4.10: 线程无法真正取消，原生崩溃可能带走 API 进程              │
│     └─ 进程隔离已实现但非默认路径                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   规则清洗层 (Rule-based Normalization)               │
│  features/text_normalizer.py (1115行) — ImportTextNormalizer         │
│    ├─ normalize() → 13 步管线                                        │
│    └─ 所有字符映射统一维护                                           │
│  ✅ 唯一入口（历史重复已合并）                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│              AI OCR 纠错层 (Multi-Model Correction)                  │
│  唯一路径 — OCRFixRouter (ocr_fix/router.py):                       │
│    ├─ PP-OCRv6 (local) → 结构主源                                   │
│    ├─ PaddleOCRVLAdapter → 外部高精 OCR API                         │
│    ├─ DeepSeekFixer → 纯文本纠错                                    │
│    └─ RuleFixer → no-op fallback                                    │
│                                                                     │
│  ⚠️ S1-4.6: Router 配置与降级语义缺陷                                 │
│     ├─ manual 空配置行为与注释不一致                                 │
│     └─ 任意异常文本进 model_used（S0-10 部分修复）                   │
│                                                                     │
│  ✅ AI Safety Gate: evaluate_and_trace() + safe_accept_ai_result()  │
│  ⚠️ S1-4.7: 多入口安全门可能不一致                                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   结构分析 & 分割层 (Structure & Split)               │
│  structure_analyzer.py — Q/A/Analysis 区域检测                       │
│  question_splitter.py — 题号+选项提取 + 跨页恢复                     │
│  page_classifier.py → 页面分类                                      │
│  visual_boundary_detector.py → 视觉边界检测                         │
│                                                                     │
│  ✅ DocumentIR 写路径迁移（2026-07-18）：9/13 消费者已迁移            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   结构冻结层 (Structure Freeze)                       │
│  pipeline_stages/structure_freeze_stage.py — 纯正则选项冻结          │
│  ✅ 输出 frozen_option_registry → split/normalize/repair 只读       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   分割层 & 答案匹配 (Split & Match)                    │
│  读取 frozen_option_registry，优先使用冻结选项                       │
│  answer_matcher.py → 题号精确匹配 + 序列回退                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   标准化层 (Normalize)                                │
│  question_normalizer.py → Layer 0/1/3                               │
│  batch_validation.py → 跨题结构完整性验证                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│               代码结构重建层 (Code Structure Reconstruct)              │
│  ✅ pre/post integrity flag 对比，防假成功                           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                    AI 修复层 (AI Repair)                              │
│  ai_repair.py → Layer 4 两阶段修复: 罗马数字 + 标准批量              │
│  ✅ AIModelConfigResolver 统一配置来源                               │
│  ✅ 选项不可变门控（3 规则）                                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│                   去重 & 入库层 (Dedup & Persist)                    │
│  similarity_matcher.py → 哈希优先 + difflib 回退                    │
│  review_service.py → submit_to_review() → question_imports 暂存表   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 已修复标注

| 标注 | 含义 |
|------|------|
| ✅ S0-0x | 已修复的 S0 问题（共 7/8） |
| ⚠️ S1-x.y | 已知但未修复的 S1 问题 |
| (审计-xx) | fix_task.md 中的问题编号 |

### 1.3 未修复的 S0 问题

（已全部修复 ✅）

（全部已修复 ✅）

---

## 2. 各层 Input/Output 总结

| 层 | Input | Output | 格式 |
|---|---|---|---|
| 输入层 | PDF/图片/TXT/Excel | bytes/filepath | 二进制 |
| OCR 识别层 (local) | bytes/numpy | `OcrPageResult[]` | `{text, bbox[[4,2]], conf}` |
| OCR 识别层 (api) | bytes | `PaddleOCRVLResult` | `{text, confidence, raw}` |
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

## 3. 推荐目标架构

来自 `prompts/tasks/fix_task.md §7`，当前未完全实现。

### 3.1 目标架构图

```
                    ┌──────────── Control Plane ────────────┐
                    │ Job/Queue · Idempotency · Quota       │
                    │ Model Registry · Config Fingerprint    │
                    │ Metrics · Trace · Benchmark · Rollout  │
                    └────────────────────────────────────────┘
                                      │
Input → Type/Safety → Native Text Probe → Page Renderer/Stream
                                      │
                          OCR Gateway / Router（唯一入口）
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
             Local OCR Worker   Remote OCR/VL      Layout/Table/Formula
             (process-isolated)  (bounded client)   specialized modules
                    └─────────────────┼──────────────────┘
                                      ↓
                         Canonical Document IR
                         + provenance + geometry
                                      ↓
                    Reading Order / Header-Watermark
                                      ↓
                 Domain Parser: question / option / answer
                                      ↓
             Candidate Correction → Single Safety Evaluator
                                      ↓
                   Cross-question Validation / Dedup
                                      ↓
                 Review Artifact → Transactional Persist
```

### 3.2 与现状的关键差异

| 维度 | 现状 | 目标 |
|------|------|------|
| **Control Plane** | 不存在统一控制面 | Job/Queue、Idempotency、Quota、Model Registry、Config Fingerprint、Metrics、Benchmark、Rollout |
| **OCR 入口** | 多重路径：orchestrator/pipeline/batch_service/ocr_service 直接调用 | 唯一 OCR Gateway / Router |
| **Local OCR** | Web 进程内线程池，无法真正隔离 | 独立 worker 进程，超时可 kill |
| **Remote OCR** | httpx 客户端缺连接复用和 SSRF 防护 | bounded HTTP client + circuit breaker + deadline |
| **Document IR** | blocks dict 文本+box，缺统一结构 | `Document→Page→Region→Line→Word` 层次，含 provenance + geometry |
| **Reading Order** | 无显式阶段 | 显式 Reading Order / Header-Watermark 阶段 |
| **安全评估** | 多入口（router/orchestrator/wrapper） | 唯一 `CandidateEvaluator` |
| **质量门** | 通用规则可能误删代码/公式 | 按文本/代码/数学/表格/图片题分领域校准 |
| **缓存** | 直接写 JSON，fingerprint 不完整 | 原子写入 + 完整版本指紋 + 后台 janitor |
| **测试/CI** | 测试文件存在但无 lock/Docker/CI | pyproject.toml/lock、Docker、CI、import smoke test |

### 3.3 路由原则（目标）

1. 文本 PDF 优先 native extraction → 只有坏字形/低覆盖页面才 OCR
2. 普通清晰页面走本地 OCR
3. 多栏、公式、表格、代码损坏或低质量页 → 升级到专用模型/VL
4. 远程模型结果是候选，不直接覆盖；统一安全评估后接受
5. 局部 region 可重跑，不必整页或整文档重跑
6. 所有决定保留 reason code 和版本指纹

---

## 4. 架构差距分析

| 层面 | 现状成熟度 | 目标成熟度 | 关键差距 |
|------|-----------|-----------|---------|
| 执行正确性 | 🟢 S0 7/8 已修复 | 🟢 全修复 | S0-09 (SSRF), S0-10 (日志) 未修复 |
| 执行隔离 | 🟡 进程池存在但非默认 | 🟢 默认进程隔离 | 线程池默认路径风险 |
| OCR 入口统一 | 🟡 Coordinator 已创建但旧路径仍存在 | 🟢 唯一 Gateway | `pipeline_orchestrator` 等多处直接调用 |
| 配置统一 | 🟢 AIModelConfigResolver | 🟢 | ✅ |
| Document IR | 🟡 已创建 `_from_ir` 路径，9/13 消费者已迁移 | 🟢 完整 IR | 阅读顺序、坐标变换记录未落地 |
| pipeline 入口 | 🟢 coordinator_entry 三模式 | 🟢 | ✅ |
| 缓存/artifact | 🟡 fingerprint 存在但不完整 | 🟢 完整版本校验 | S1-4.1/4.2/4.3 |
| VL 客户端 | 🟡 功能正常，缺生产级治理 | 🟢 bounded client + SSRF | S1-4.5, S0-09 |
| 测试/CI | 🟡 测试存在但缺 lock/CI | 🟢 完整 CI 流水线 | 无 Docker/CI 配置 |
| 生产验证 | 🟢 2C/2G 实测 + Redis 修复 | 🟢 | ✅ |

---

## 5. 路线图：分阶段演进

### Sprint 0：正确性与安全止血（✅ 全部完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| 修复未定义 `idx` | S0-01 | ✅ 已修复 |
| 重写 Future 生命周期统计 | S0-02 | ✅ 已修复 |
| `asyncio.wrap_future` 替代等待线程 | S0-03 | ✅ 已修复 |
| 删除/修复 `_ocr_lock` 废弃路径 | S0-05 | ✅ 已修复 |
| OCR reset 加锁 + 状态机 | S0-06 | ✅ 已修复 |
| 视觉阶段补入恢复顺序 | S0-07 | ✅ 已修复 |
| pipeline ID 路径校验 | S0-08 | ✅ 已修复 |
| VL 结果下载 SSRF/大小/重定向边界 | S0-09 | ✅ 已实现 |
| OCR 原文日志脱敏 | S0-10 | ✅ 2026-07-18 修复 |
| Router 空配置行为修正 | manual | ✅ 已修复 |
| Router fingerprint 补充 API key | S1-4.6 | ✅ 2026-07-18 修复 |

### Sprint 1：执行与可复现性重构（✅ 全部完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| OCR 推理移入独立进程 worker（默认）| S1-4.10 | ✅ 2026-07-18 实现 |
| 合并 OCR 配置 SSOT | S1-4.4 | ✅ 已验证，两来源无冲突 |
| HTTP client 连接复用 + deadline + circuit breaker | S1-4.5 | ✅ 已实现（共享 client + 重试 + SSRF） |
| 原子缓存 + 完整 fingerprint + 后台 janitor | S1-4.1/4.2 | ✅ 已实现（tempfile+fsync+replace + 全维度 fingerprint）|
| artifact compatibility check + fingerprint | S1-4.3 | ✅ content-addressed PIPELINE_VERSION |
| 唯一 CandidateEvaluator | S1-4.7 | ✅ candidate_evaluator.py 单例 |
| CI workflow + pip-audit + Docker build | S1 | ✅ 2026-07-18 补齐 |
| Router 降级语义修正 + 枚举化 reason code | S1-4.6 | ✅ 已修复 |
| 全项目 OCR 调用统一经 gateway | S1-S0-04 | ✅ 进程池默认 + 共享线程池 |
| Dependabot + lock file 生成 | S1 | ✅ 2026-07-18 新增 |

### Sprint 2：统一 IR 与质量评估（✅ 全部完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| 落地 Document/Page/Region/Line/Token IR | S2-5 | ✅ document_ir.py 完整模型，9/13 消费者已迁移 |
| 原图/预处理/输出坐标可逆映射 | S2-4.9 | ✅ TransformTracker + OcrPageResult.transforms |
| layout/reading order 显式模块 | S2 | ✅ pipeline_stages/reading_order_stage.py + visual_region_* |
| 唯一 CandidateEvaluator | S2-4.7 | ✅ candidate_evaluator.py 单例 |
| 分领域质量门（文本/代码/数学/表格） | S2-4.8 | ✅ code_language_noise_layer + math_detect + table_detect |
| 结构冻结绑定 region/line ID | S2 | ✅ structure_freeze_stage.py 正则 SSOT |

### Sprint 3：基准、灰度和规模化（部分完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| 建立"题库 OCR Bench" | S3 | ✅ tests/ocr_regression/ (17 cases) + tests/ocr_acceptance/ (10 类) |
| 持久任务队列 + page group + 幂等 | S3 | ✅ task_queue_service (Redis + 本地回退) |
| 多 GPU/多模型 router | S3 | ✅ OCRGateway (local/remote VL), OCRFixRouter (多模型降级链) |
| 版本灰度与自动回滚 | S3 | ✅ ocr_canary + rollout_policy + pipeline_fingerprint |
| 人工审核 → 主动学习 | S3 | ✅ scripts/export_review_hard_cases.py 硬案例导出 |

---

## 6. 关键文件清单

### 核心管线

| 文件 | 行数 | 用途 | 状态 |
|------|------|------|------|
| `features/pipeline_orchestrator.py` | ~4871 | 主编排器（19 阶段）| ✅ 生产 |
| `features/pipeline_coordinator_entry.py` | 210 | 统一 Pipeline 入口 | ✅ 2026-07-18 |
| `features/coordinator_orchestrator.py` | 280 | Coordinator Pipeline | ✅ 新增 |
| `features/coordinators.py` | ~180 | 9 个 Stage Coordinator | ✅ 新增 |
| `services/model_config_resolver.py` | ~600 | AIModelConfigResolver | ✅ 2026-07-18 |
| `services/ocr_executor_service.py` | ~400 | OCR 执行器（进程隔离默认）| ✅ 2026-07-18 进程默认 |
| `services/ocr_service.py` | ~773 | PaddleOCR 封装 | ✅ 2026-07-18 S1-4.8/4.9 修复 |
| `services/ocr_cache_service.py` | ~130 | OCR 缓存 | ✅ 原子写入 + 全维度 fingerprint |
| `features/pipeline_artifacts.py` | 559 | Pipeline artifact 持久化 | ✅ content-addressed fingerprint |
| `features/pipeline_stages/` | 9 文件 | 独立 stage 实现 | ✅ |
| `features/question_pipeline.py` | 2921 | 标准化管道 | ✅ |
| `features/batch_image_import_service.py` | ~1391 | 批量图片导入 | ✅ |
| `services/import_pipeline_service.py` | ~400 | Import pipeline 入口 | ✅ |
| `features/text_normalizer.py` | 1400 | OCR 文本规范化（13 步）| ✅ 唯一入口 |
| `features/question_splitter.py` | 1437 | 题号+选项提取 | ✅ |
| `features/ai_repair.py` | 1164 | AI 修复 | ✅ AIModelConfigResolver |
| `features/code_integrity.py` | 938 | 代码块完整性检测 | ✅ |
| `features/question_type_classifier.py` | 454 | Layer 1 题型分类 | ✅ |
| `services/storage_backend.py` | 235 | Storage 后端抽象 | ✅ 2026-07-16 |

### OCR 纠错

| 文件 | 行数 | 用途 | 状态 |
|------|------|------|------|
| `ocr_vl/paddleocr_vl_client.py` | ~567 | PaddleOCR-VL HTTP 客户端 | ✅ SSRF + 连接复用 + 日志脱敏 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 | ✅ |
| `ocr_fix/router.py` | 428 | 降级链路由 | ✅ manual 行为 + fingerprint 修正 |
| `ocr_fix/interfaces.py` | 68 | OCRFixResult + CandidateDecision | ✅ |
| `ocr_fix/deepseek_adapter.py` | 177 | DeepSeek 纯文本纠错 | ✅ |
| `ocr_fix/rule_adapter.py` | 41 | 规则 fallback | ✅ |
| `ai_safety.py` | 284 | AI 编辑安全门禁 | ⚠️ 渐被 CandidateEvaluator 替代 |
| `features/candidate_evaluator.py` | ~340 | 统一候选评估器 | ✅ 单例 |
| `ocr_correction_common.py` | 254 | 纠错通用逻辑 | ✅ |

### Evaluation

| 文件 | 行数 | 用途 |
|------|------|------|
| `features/layout_router.py` | 76 | 固化路由决策（三档 confidence-based）|
| `evaluation/routing_metrics.py` | 217 | 路由决策指标收集 |
| `evaluation/split_quality.py` | 111 | 分割质量评估 |
| `scripts/run_ab_experiment.py` | 237 | A/B 实验 runner |

### 测试

| 文件 | 用途 | 数量 |
|------|------|------|
| `tests/ocr_regression/` | 回归用例 | 17 case |
| `tests/ocr_acceptance/` | 验收测试 | 10 类样本 |
| Sprint 4D 测试集 | 全量回归 | 91 tests |
| `tests/test_ocr_fix_uses_admin_ai_config.py` | 配置统一验证 | 5 tests |
| `tests/test_ai_repair_uses_admin_ai_config.py` | 配置统一验证 | 7 tests |
| `tests/test_ai_capability_model_separation.py` | 能力分离验证 | 3 tests |

### 运维脚本

| 文件 | 用途 |
|------|------|
| `scripts/run_remote_ocr_db_config_validation.py` | 外部 OCR API 数据库配置 E2E 验证 |
| `scripts/run_cloud_api_resource_test.py` | 2C/2G 资源限制实测 |
| `scripts/backfill_question_images.py` | 题图补图 |
| `scripts/auto_detect_figure_regions.py` ~ `scripts/final_visual_qa_report.py` | 5 级视觉 QA 工具链 |
