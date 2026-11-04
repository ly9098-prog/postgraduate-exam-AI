# OCR Pipeline 架构文档

> 维护时间：2026-08-24（基于当前 `app.zip` 代码审计）
> 审计参考：`docs/audit/OCR_PIPELINE_AUDIT_RECORDS.md`、`prompts/tasks/done/export-release-audit.md`
>
> **表格渲染约定**：表格控制在 2–3 列；长路径/标识符提供软换行点；复杂说明放到表格下方，避免 GitHub、文档站和窄屏预览横向溢出。
>
> **里程碑状态：Sprint 0–3 的主要能力已落地；Gateway/IR/统一安全仍处于收敛阶段。**
>
> **2026-08-24 代码核对**：本地 OCR 仍以 **PP-OCRv4** 为版本指纹；OCR 纠错默认链已变为 `PaddleOCR-VL → OpenAI-compatible LLM → rule fallback`，`DeepSeekFixer` 仅保留为兼容别名。`PIPELINE_COORDINATOR_MODE` 默认仍为 `shadow`，`STRUCTURE_FREEZE_MODE` 默认仍为 `legacy`。

---

## 0. 2026-08-24 代码审计结论

本节基于本次提供的 `app.zip` 后端应用代码进行静态审计。`python -m compileall` 已通过。该压缩包不包含完整 `tests/`，因此测试数量、覆盖率和历史 CI 用例数量未在本次审计中重新统计。

| 审计项 | 当前事实 | 结论 |
|---|---|---|
| Pipeline 主入口 | `PIPELINE_COORDINATOR_MODE` 默认 `shadow`；shadow 只生成 Coordinator plan，真实执行仍进入 legacy orchestrator | 🟡 Coordinator 已接入，但默认不是主执行路径 |
| OCR Gateway | 标准兼容包装器会优先调用 Gateway；非受限环境失败后仍可回退 legacy process-pool；批量 `ocr_mode=api` 直接使用 `PaddleOCRVLClient` | 🟡 尚未达到“唯一 OCR Gateway” |
| Local OCR 隔离 | Local backend 使用 process worker；生产配置明确禁止 unsafe thread fallback | 🟢 进程隔离成立 |
| PaddleX HTTP | 有共享 `AsyncClient`、并发上限、retry、deadline、circuit breaker、响应大小限制 | 🟢 基础生产治理已实现 |
| PaddleOCR-VL | 结果 URL 有 SSRF / redirect / size 防护；部分批量 API 路径按单图创建/关闭 client | 🟡 安全边界较完整，连接复用仍有优化空间 |
| DocumentIR | 多个结构阶段已有 IR 入口，但默认 `STRUCTURE_FREEZE_MODE=legacy`，legacy blocks 与 IR bridge 仍并存 | 🟡 IR 已落地但未成为默认唯一协议 |
| AI Candidate 安全门 | `ai_safety.py` 已是 `CandidateEvaluator` 的兼容适配器；OCRFixRouter 也直接使用 `CandidateEvaluator` | 🟢 CandidateEvaluator 是实际候选接受权威 |
| Unified Safety | `UnifiedSafetyEvaluator` 有实现，但当前代码中没有外部调用点；默认模式为 `shadow` | 🟡 设计存在，尚未接入主决策链 |
| Cache / Artifact | OCR cache 有原子写、TTL、每 200 次写触发清理及管理端维护接口 | 🟢 生命周期基础能力已存在 |
| OCR cache 指标 | `ocr_service.get_ocr_cache_stats()` 导入不存在的 `ocr_cache_service.get_stats`，会回退为全 0 | 🔴 实际可观测性缺陷，需要修代码 |
| Remote URL 配置 | 生产校验禁止 `OCR_ALLOW_HTTP=true`，但本次代码中未发现对 `OCR_REMOTE_URL` scheme 的对应强校验 | 🟠 建议补充显式 HTTPS / host 校验 |

### 0.1 本次审计后的优先级

| 优先级 | 建议动作 | 原因 |
|---|---|---|
| P1 | 修复 `get_ocr_cache_stats()` 与 `ocr_cache_service` API 不一致 | 当前 cache hit/miss 报告会静默归零，影响质量报告与排障 |
| P1 | 对生产 `OCR_REMOTE_URL` 做显式 scheme / host 校验 | 仅检查 `OCR_ALLOW_HTTP` 不能保证实际 URL 使用 HTTPS |
| P1 | 明确 Coordinator 切主路径条件，并逐步把默认从 `shadow` 收敛到 `coordinator` | 当前文档若称“Coordinator 已成为主路径”会与代码事实冲突 |
| P2 | 完成 legacy OCR 旁路清理 | 标准 wrapper 仍允许非受限环境 fallback，批量 API 还有直接 VL client 路径 |
| P2 | 完成 DocumentIR 默认化 | 默认 structure freeze 仍是 `legacy`，IR 与 blocks 双协议增加维护成本 |
| P2 | 统一 `UnifiedSafetyEvaluator` 的定位 | 当前 CandidateEvaluator 已是实际权威，而 UnifiedSafetyEvaluator 未接入 |
| P2 | 让批量 PaddleOCR-VL 复用 client / adapter 生命周期 | 当前 `_run_vl_ocr()` 按调用创建 client，吞吐和连接池收益有限 |
| P3 | 删除或隔离 deprecated OCR 兼容入口 | 减少后续新代码误用 legacy process-pool 的风险 |

---

## 目录

0. [2026-08-24 代码审计结论](#0-2026-08-24-代码审计结论)
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
│                   OCR 识别层 (PaddleOCR / PaddleX HTTP)                 │
│                                                                     │
│  🟡 Gateway 已接入，但仍存在兼容/专用旁路：                            │
│     ├─ legacy orchestrator → ocr_service deprecated wrapper         │
│     │   → Gateway 优先；非受限环境失败时可 fallback process-pool      │
│     ├─ batch image `ocr_mode=api` → PaddleOCRVLClient 直接路径       │
│     └─ deprecated lightweight OCR 仍保留 process-pool 兼容入口       │
│                                                                     │
│  执行后端由 OCR_EXECUTION_BACKEND 选择（2026-07-19 新增）：           │
│     ├─ local_process → OcrWorkerPool + OcrWorkerProcess + OcrEngine  │
│     │  （进程隔离，子进程内 import PaddleOCR，父进程不加载）            │
│     ├─ paddlex_http → PaddleXHttpOcrWorkerClient                     │
│     │  （httpx.AsyncClient → Windows PaddleX POST /ocr）             │
│     │  ✅ 不 import paddle/paddleocr/OcrWorkerPool                  │
│     │  ✅ 通过 OcrWorkerClient Protocol 统一接口                     │
│     │  ✅ 独立 httpx.AsyncClient + asyncio.Semaphore 并发控制        │
│     │  ✅ fail-fast + health check + URL 脱敏 + 稳定错误码           │
│     │  ⚠️ 非 2xx / 连接失败 → fail closed，不自动回退 local         │
│     └─ disabled → 不创建 worker client                               │
│                                                                     │
│  local_process 模式：                                                │
│    services/ocr_service.py 仅保留兼容包装器，不再拥有独立算法实现。    │
│    实际执行：OCRGateway → LocalOcrWorkerClient → OcrWorkerPool      │
│      ├─ 子进程内加载 PaddleOCR                                      │
│      ├─ queue/deadline/heartbeat/restart/kill 治理                  │
│      ├─ max_tasks_per_worker / max_rss_mb 可配置                    │
│      └─ production 禁止 unsafe thread fallback                      │
│    Transform 信息已进入 WorkerResult / OcrPageResult。               │
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
│  ✅ PaddleOCR-VL result download 已有 SSRF / redirect / size 防护。   │
│  🟡 batch `ocr_mode=api` 每次调用仍创建/关闭 PaddleOCRVLClient，      │
│     与 Gateway adapter 的长生命周期复用路径尚未完全统一。             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               v
┌─────────────────────────────────────────────────────────────────────┐
│               OCR 执行器层 (Executor/Worker/Client)                      │
│                                                                     │
│  ✅ S0-01: idx 正确传递（闭包参数化，无 UnboundLocalError）          │
│  ✅ S0-02: future.add_done_callback 正确释放容量                    │
│  ✅ S0-03: asyncio.wrap_future 替代双线程池                         │
│  ✅ 2026-07-19: OcrWorkerClient Protocol + 工厂 + PaddleX HTTP      │
│     ├─ OcrWorkerClient (typing.Protocol) — 统一 worker 接口         │
│     │   recognize() / recognize_batch() / shutdown() / metrics      │
│     ├─ LocalOcrWorkerClient — 封装 OcrWorkerPool（进程隔离）         │
│     ├─ PaddleXHttpOcrWorkerClient — httpx → Windows PaddleX POST    │
│     └─ create_ocr_worker_client() — 延迟 import 工厂                 │
│                                                                     │
│  services/ocr_executor_service.py:                                  │
│    ├─ run_ocr_pages_in_thread() → 线程池 + semaphore + done_callback │
│    ├─ run_ocr_pages_in_process() → OcrProcessPool（进程隔离）        │
│    └─ _run_in_executor() → wrap_future + wait_for + shield          │
│                                                                     │
│  ✅ local backend 已使用进程隔离 worker；shutdown 支持 grace + kill。 │
│  ✅ production 配置拒绝 unsafe thread fallback。                      │
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
│  唯一路径 — OCRFixRouter (features/ocr_fix/router.py):              │
│    ├─ PaddleOCRVLAdapter → 外部高精 OCR API（第一优先级）            │
│    ├─ OpenAICompatibleFixer → 可配置的 OpenAI-compatible 文本模型    │
│    └─ RuleFixer → no-op fallback（自动降级，不可绕过质量门禁）       │
│  默认链：auto = PaddleOCR-VL → openai-compatible → rule fallback     │
│  本地 PP-OCRv4 作为结构主源，在 OCR 识别层/版面阶段完成，            │
│  不参与纠错链路由（layout_router.py 三档路由已生产固化）              │
│                                                                     │
│  ✅ S1-4.6: Router 配置与降级语义已修正（manual 行为 + fingerprint）  │
│  ✅ S0-10: 日志脱敏已修复                                            │
│                                                                     │
│  ✅ AI Safety Gate: evaluate_and_trace() + safe_accept_ai_result()  │
│  ✅ S1-4.7: candidate_evaluator.py 唯一候选评估器（单例）            │
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
│  🟡 多个结构阶段已有 DocumentIR 入口，但 legacy blocks 仍是默认桥接层  │
│     （本次代码无法验证旧文档“9/13”计数，故不再使用固定迁移比例）       │
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
| ✅ S0-0x | 历史 S0 问题已修复或有明确替代实现 |
| 🟡 S1-x.y | 已实现主体能力，但仍存在收敛/默认模式问题 |
| (审计-xx) | fix_task.md 中的问题编号 |

### 1.3 当前仍需处理的问题

历史 S0 列表已完成；当前剩余工作以 **第 0 节代码审计** 和 **第 4 节架构差距分析** 为准。

---

## 2. 各层 Input/Output 总结

当前代码同时保留 **shadow/legacy 实际路径** 与 **coordinator 目标路径**。默认 `PIPELINE_COORDINATOR_MODE=shadow` 时，Coordinator 只生成 plan，真实导入仍由 legacy orchestrator 执行；因此下面的 Input/Output 是逻辑阶段模型，不代表默认配置下每一步都已经完全 IR-native。

| 阶段 | Input | Output |
|---|---|---|
| 输入层 | PDF / 图片 / TXT / Excel | 原始文件 `bytes` / `filepath` |
| Import Pipeline | 文件 + pipeline 配置 | `PipelineContext` |
| OCR Gateway | page image / image bytes | OCR backend result |
| Local OCR Worker | image bytes / numpy | `OcrPageResult[]` |
| Remote OCR/VL | image bytes | `PaddleOCRVLResult` |
| OCR Normalization | OCR text | normalized text |
| Document IR | OCR result + geometry | `DocumentIR` |
| Layout / Structure | `DocumentIR` | `PageStructure` |
| Structure Freeze | blocks / options | <code>frozen_<wbr>option_<wbr>registry</code> |
| Question Split | IR + frozen registry | `RawQuestion[]` |
| Question Classification | raw text + options | classification result |
| Normalize | `RawQuestion[]` | `NormalizedQuestion[]` |
| AI Repair | normalized question | candidate question |
| Safety Evaluation | candidate + original | accept / reject decision |
| Dedup / Review | normalized questions | review artifact |
| Persist | review artifact | database records |

### 2.1 关键数据结构

- **`OcrPageResult`**：`text`、`bbox`、`confidence`、`transforms`。
- **`PaddleOCRVLResult`**：`text`、`confidence`、`raw`。远程结果属于候选来源，不直接绕过质量门。
- **`DocumentIR`**：`Document → Page → Region → Line → Token`，保留 provenance、geometry 与坐标变换信息。
- **`PageStructure`**：页面模式、题目/答案数量及结构分析结果。
- **`frozen_option_registry`**：冻结选项结构，供 split / normalize / repair 只读使用。
- **`RawQuestion`**：题号、题干、选项、答案等切题结果。
- **`NormalizedQuestion`**：进入质量评估、去重和审核流程的标准题目模型。

### 2.2 数据流约束

1. OCR 层负责识别与几何信息，不承担题目业务结构恢复。
2. DocumentIR 是目标统一中间表示；当前多个阶段已经 IR-aware，但默认仍通过 legacy blocks / bridge 共存。
3. AI Repair 只产生 candidate；接受与否由 `CandidateEvaluator` 决定。
4. `frozen_option_registry` 是选项结构的冻结来源，后续阶段不得随意改写。
5. 关键阶段应保留 pipeline/model fingerprint、reason code 与 trace；这是当前已部分实现、仍需继续收敛的约束。

---

## 3. 推荐目标架构

目标架构仍有效，但本次代码审计确认：Coordinator、唯一 Gateway、IR 默认化和 Unified Safety 尚未全部切为主路径。

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

### 3.2 与当前实现的关键差异

| 维度 | 当前实现 | 后续目标 |
|---|---|---|
| Control Plane | Queue / fingerprint / metrics / canary 等能力分散存在 | 收敛为统一控制面 |
| Pipeline 主入口 | 默认 `shadow`，真实执行 legacy orchestrator | `coordinator` 成为默认主路径 |
| OCR 入口 | Gateway-first + legacy fallback + direct VL 专用路径 | 唯一 Gateway / Adapter 入口 |
| Local OCR | process worker，生产禁止 unsafe thread fallback | 保持进程隔离并强化资源治理 |
| Remote OCR | PaddleX 有 retry/deadline/breaker；VL 有 SSRF 防护 | 统一连接生命周期、SLO 与 URL policy |
| Document IR | IR-aware stage 与 legacy blocks 并存 | IR 成为默认唯一跨阶段协议 |
| Reading Order | 独立 stage 已存在 | 完整覆盖复杂版面并默认启用 |
| Candidate 安全 | `CandidateEvaluator` 已是实际接受权威 | 保持唯一 candidate acceptance authority |
| Unified Safety | 有实现但未接入主调用链 | 明确 shadow / enforce 的真实接入点 |
| Cache / Artifact | 原子写、TTL、cleanup 已存在；cache 指标适配有缺陷 | 修复指标并统一生命周期治理 |
| 测试 / CI | 已有 workflow 记录；本次 app.zip 不含 tests | 继续用真实回归结果校准门禁 |

补充说明：

- `ai_safety.py` **不再是第二套独立决策器**；它已经委托 `CandidateEvaluator`，因此不应为了“唯一安全门”而直接删除。
- `UnifiedSafetyEvaluator` 是另一层聚合设计，但本次代码搜索没有发现主流程调用，应与 `CandidateEvaluator` 的职责重新明确。
- 原文固定写出的 “DocumentIR 9/13 消费者已迁移” 无法从本次代码包可靠复核，已改为可验证的“IR-aware + legacy bridge 并存”。

### 3.3 路由原则（目标）

1. 文本 PDF 优先 native extraction → 只有坏字形/低覆盖页面才 OCR
2. 普通清晰页面走本地 OCR
3. 多栏、公式、表格、代码损坏或低质量页 → 升级到专用模型/VL
4. 远程模型结果是候选，不直接覆盖；统一安全评估后接受
5. 局部 region 可重跑，不必整页或整文档重跑
6. 所有决定保留 reason code 和版本指纹

---

## 4. 架构差距分析

| 层面 | 当前成熟度 | 主要剩余工作 |
|---|---|---|
| 执行正确性 | 🟢 compileall 通过，历史 S0 修复存在 | 保持回归门禁 |
| Worker 隔离 | 🟢 local process worker + kill/heartbeat | 配置资源上限并验证故障场景 |
| Pipeline 切主 | 🟡 Coordinator 默认 `shadow` | 定义切换到 `coordinator` 的验收条件 |
| OCR 入口统一 | 🟡 Gateway-first，但仍有 fallback / direct VL | 删除不必要旁路或纳入 Adapter |
| Document IR | 🟡 多阶段 IR-aware，默认 freeze 仍 `legacy` | IR 默认化并减少 blocks bridge |
| CandidateEvaluator | 🟢 实际 acceptance authority | 维持单一候选决策权 |
| Unified Safety | 🟡 实现存在但未接主链 | 明确是否保留、如何 shadow/enforce |
| Remote HTTP | 🟢 retry/deadline/breaker/SSRF 基础能力 | 显式校验 `OCR_REMOTE_URL`，统一 client 生命周期 |
| Cache / Artifact | 🟡 cleanup 完整，cache stats 适配错误 | 修复 `get_stats`/`get_cache_stats` 契约 |
| 质量门 | 🟡 Candidate gate 生效，Domain Gate 默认 `off` | 用 benchmark 决定 shadow/enforce |
| 测试 / CI | 🟡 workflow 已存在；本次未复核 tests | 用当前仓库测试结果更新数量和阈值 |

### 4.1 已确认的代码问题

1. **OCR cache 指标接口不一致**：`services/ocr_service.py::get_ocr_cache_stats()` 导入 `ocr_cache_service.get_stats`，但当前 cache service 只定义 `get_cache_stats()`。ImportError 被吞掉后返回全 0，会导致 pipeline 报告中的 cache hit/miss 失真。
2. **生产 OCR URL invariant 不完整**：production validator 会拒绝 `OCR_ALLOW_HTTP=true`，但本次代码中未看到针对 `OCR_REMOTE_URL` 实际 scheme 的对应强校验。应直接验证 URL，而不是只验证开关。
3. **Coordinator 默认不是主路径**：`PIPELINE_COORDINATOR_MODE` 默认 `shadow`，文档不能再将 Coordinator 描述为已完全替代 legacy orchestrator。
4. **DocumentIR 尚非默认 SSOT**：`STRUCTURE_FREEZE_MODE` 默认 `legacy`，IR 与 blocks 仍双轨。
5. **批量 VL client 生命周期未统一**：`batch_image_import_service._run_vl_ocr()` 每次创建并关闭 `PaddleOCRVLClient`，与 Gateway adapter 的复用模式不一致。

> 以上结论来自当前 `app.zip` 静态代码。需要结合部署环境变量和完整测试仓库，才能判断生产环境实际启用了哪些 mode。

---

## 5. 路线图：分阶段演进

### Sprint 0：正确性与安全止血（✅ 全部完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| 修复未定义 `idx` | S0-01 | ✅ 已修复 |
| 重写 Future 生命周期统计 | S0-02 | ✅ 已修复 |
| <code>asyncio.wrap_<wbr>future</code> 替代等待线程 | S0-03 | ✅ 已修复 |
| 删除/修复 <code>_<wbr>ocr_<wbr>lock</code> 废弃路径 | S0-05 | ✅ 已修复 |
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
| OCR 推理移入独立进程 worker | S1-4.10 | ✅ local backend 已进程隔离；默认远端 backend 为 `paddlex_http` |
| 合并 OCR 配置 SSOT | S1-4.4 | ✅ 已验证，两来源无冲突 |
| HTTP client 连接复用 + deadline + circuit breaker | S1-4.5 | 🟡 PaddleX 路径完成；批量 VL 直连仍按调用创建 client |
| 原子缓存 + fingerprint + cleanup | S1-4.1/4.2 | 🟡 写入/TTL/cleanup 已实现；cache stats 适配仍有缺陷 |
| artifact compatibility check + fingerprint | S1-4.3 | ✅ content-addressed PIPELINE_VERSION |
| 唯一 CandidateEvaluator | S1-4.7 | ✅ candidate_evaluator.py 单例 |
| CI workflow + pip-audit + Docker build | S1 | ✅ 2026-07-18 补齐 |
| Router 降级语义修正 + 枚举化 reason code | S1-4.6 | ✅ 已修复 |
| 全项目 OCR 调用统一经 gateway | S1-S0-04 | 🟡 Gateway-first，但 legacy fallback / direct VL 仍存在 |
| Dependabot + lock file 生成 | S1 | ✅ 2026-07-18 新增 |

### Sprint 2：统一 IR 与质量评估（✅ 全部完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| 落地 Document/Page/Region/Line/Token IR | S2-5 | 🟡 IR 模型与多阶段入口已落地；默认仍与 legacy blocks 共存 |
| 原图/预处理/输出坐标可逆映射 | S2-4.9 | ✅ TransformTracker + OcrPageResult.transforms |
| layout/reading order 显式模块 | S2 | ✅ pipeline_stages/reading_order_stage.py + visual_region_* |
| 唯一 CandidateEvaluator | S2-4.7 | ✅ `ai_safety` 已委托 CandidateEvaluator；候选接受权威统一 |
| 分领域质量门（文本/代码/数学/表格） | S2-4.8 | ✅ code_language_noise_layer + math_detect + table_detect |
| 结构冻结绑定 region/line ID | S2 | ✅ structure_freeze_stage.py 正则 SSOT |

### Sprint 3：基准、灰度和规模化（✅ 全部完成）

| 工作项 | fix_task 编号 | 状态 |
|--------|-------------|------|
| 建立"题库 OCR Bench" | S3 | ✅ backend/tests/ocr_regression/ (31 cases) + backend/tests/ocr_acceptance/ (10 类) |
| 持久任务队列 + page group + 幂等 | S3 | ✅ DurableTaskQueue (Redis Lua + 本地回退)、owner fencing、生产验证 |
| 多 GPU/多模型 router | S3 | ✅ OCRGateway (local/remote VL), OCRFixRouter (多模型降级链) |
| 版本灰度与自动回滚 | S3 | ✅ ocr_canary + rollout_policy + pipeline_fingerprint |
| 人工审核 → 主动学习 | S3 | ✅ scripts/export_review_hard_cases.py 硬案例导出 |

---

## 6. 关键文件清单

### 核心管线

| 文件（快照行数） | 用途 | 状态 |
|---|---|---|
| <code>features/<wbr>pipeline_<wbr>orchestrator.py</code><br><sub>6557 行</sub> | 主编排器（19 阶段） | ✅ 生产 |
| <code>features/<wbr>pipeline_<wbr>coordinator_<wbr>entry.py</code><br><sub>226 行</sub> | 统一 Pipeline 入口 | ✅ 2026-07-18 |
| <code>features/<wbr>coordinator_<wbr>orchestrator.py</code><br><sub>303 行</sub> | Coordinator Pipeline | ✅ 新增 |
| <code>features/<wbr>coordinators.py</code><br><sub>505 行</sub> | Stage Coordinator | ✅ 新增 |
| <code>services/<wbr>model_<wbr>config_<wbr>resolver.py</code><br><sub>708 行</sub> | AIModelConfigResolver | ✅ 2026-07-18 |
| <code>services/<wbr>ocr_<wbr>executor_<wbr>service.py</code><br><sub>191 行</sub> | OCR 执行器（进程隔离默认） | ✅ 2026-07-18 进程默认 |
| <code>services/<wbr>ocr_<wbr>service.py</code><br><sub>415 行</sub> | PaddleOCR 封装 | ✅ 2026-07-18 S1-4.8/4.9 修复 |
| <code>services/<wbr>ocr_<wbr>local_<wbr>worker_<wbr>client.py</code><br><sub>132 行</sub> | 本地进程 OCR worker（进程隔离） | ✅ 2026-07-18 |
| <code>services/<wbr>ocr_<wbr>paddlex_<wbr>http_<wbr>client.py</code><br><sub>1363 行</sub> | PaddleX HTTP 远程 OCR 客户端 | ✅ 2026-07-19 新增 |
| <code>services/<wbr>ocr_<wbr>worker_<wbr>client.py</code><br><sub>109 行</sub> | OcrWorkerClient Protocol + 工厂 | ✅ 2026-07-19 新增 |
| <code>services/<wbr>ocr_<wbr>cache_<wbr>service.py</code><br><sub>336 行</sub> | OCR 缓存 / TTL / cleanup | 🟡 cache service 正常；上层 stats adapter 有接口名错误 |
| <code>features/<wbr>pipeline_<wbr>artifacts.py</code><br><sub>701 行</sub> | Pipeline artifact 持久化 | ✅ content-addressed fingerprint |
| <code>features/<wbr>pipeline_<wbr>stages/<wbr></code><br><sub>18 文件 行</sub> | 独立 stage 实现 | ✅ |
| <code>features/<wbr>question_<wbr>pipeline.py</code><br><sub>1616 行</sub> | 标准化管道（阶段逻辑拆分至 pipeline_stages/） | ✅ |
| <code>features/<wbr>batch_<wbr>image_<wbr>import_<wbr>service.py</code><br><sub>1543 行</sub> | 批量图片导入 | ✅ |
| <code>services/<wbr>import_<wbr>pipeline_<wbr>service.py</code><br><sub>996 行</sub> | Import pipeline 入口 | ✅ |
| <code>features/<wbr>text_<wbr>normalizer.py</code><br><sub>1404 行</sub> | OCR 文本规范化（13 步） | ✅ 唯一入口 |
| <code>features/<wbr>question_<wbr>splitter.py</code><br><sub>1887 行</sub> | 题号+选项提取 | ✅ |
| <code>features/<wbr>ai_<wbr>repair.py</code><br><sub>1334 行</sub> | AI 修复 | ✅ AIModelConfigResolver |
| <code>features/<wbr>code_<wbr>integrity.py</code><br><sub>938 行</sub> | 代码块完整性检测 | ✅ |
| <code>features/<wbr>question_<wbr>type_<wbr>classifier.py</code><br><sub>465 行</sub> | Layer 1 题型分类 | ✅ |
| <code>services/<wbr>storage_<wbr>backend.py</code><br><sub>499 行</sub> | Storage 后端抽象 | ✅ 2026-07-16 |

> 行数已按 2026-08-24 本次 `app.zip` 重新统计；后续仍以代码为准。

### OCR 纠错

| 文件（快照行数） | 用途 | 状态 |
|---|---|---|
| <code>features/<wbr>ocr_<wbr>vl/<wbr>paddleocr_<wbr>vl_<wbr>client.py</code><br><sub>1222 行</sub> | PaddleOCR-VL HTTP 客户端 | ✅ SSRF + 连接复用 + 日志脱敏 |
| <code>features/<wbr>ocr_<wbr>vl/<wbr>paddleocr_<wbr>vl_<wbr>adapter.py</code><br><sub>128 行</sub> | OCRFixerProtocol 适配器 | ✅ |
| <code>features/<wbr>ocr_<wbr>fix/<wbr>router.py</code><br><sub>483 行</sub> | 降级链路由 | ✅ manual 行为 + fingerprint 修正 |
| <code>features/<wbr>ocr_<wbr>fix/<wbr>interfaces.py</code><br><sub>68 行</sub> | OCRFixResult + CandidateDecision | ✅ |
| <code>features/<wbr>ocr_<wbr>fix/<wbr>deepseek_<wbr>adapter.py</code><br><sub>9 行</sub> | `OpenAICompatibleFixer` 的 deprecated 兼容别名 | 🟡 仅兼容层 |
| <code>features/<wbr>ocr_<wbr>fix/<wbr>openai_<wbr>compatible_<wbr>adapter.py</code><br><sub>188 行</sub> | 当前通用文本 LLM OCR 纠错 adapter | ✅ auto chain 正式文本模型入口 |
| <code>features/<wbr>ocr_<wbr>fix/<wbr>rule_<wbr>adapter.py</code><br><sub>41 行</sub> | 规则 fallback | ✅ |
| <code>features/<wbr>ocr_<wbr>correction.py</code><br><sub>172 行</sub> | OCR 纠错编排 | ✅ |
| <code>features/<wbr>ocr_<wbr>correction_<wbr>common.py</code><br><sub>307 行</sub> | 纠错通用逻辑 | ✅ |
| <code>features/<wbr>vision_<wbr>fallback.py</code><br><sub>272 行</sub> | 视觉回退（VL_REBUILD 兜底） | ✅ |
| <code>features/<wbr>ai_<wbr>safety.py</code><br><sub>117 行</sub> | CandidateEvaluator 兼容包装 + AI trace | ✅ 不再拥有独立 acceptance 逻辑 |
| <code>features/<wbr>candidate_<wbr>evaluator.py</code><br><sub>523 行</sub> | 统一候选评估器 | ✅ 单例 |

### Evaluation

| 文件 | 行数 | 用途 |
|------|------|------|
| <code>features/<wbr>layout_<wbr>router.py</code> | 76 | 固化路由决策（三档 confidence-based）|
| <code>evaluation/<wbr>routing_<wbr>metrics.py</code> | 217 | 路由决策指标收集 |
| <code>evaluation/<wbr>split_<wbr>quality.py</code> | 111 | 分割质量评估 |
| <code>scripts/<wbr>run_<wbr>ab_<wbr>experiment.py</code> | 237 | A/B 实验 runner |

### 测试

> 本次 `app.zip` 未包含完整 `tests/` 目录；以下数量保留自历史文档快照，**未在本次代码审计中复核**。

| 文件 | 用途 | 数量 |
|------|------|------|
| <code>backend/<wbr>tests/<wbr>ocr_<wbr>regression/<wbr></code> | 回归用例（cases/ 编号目录 001-029+） | 31 case |
| <code>backend/<wbr>tests/<wbr>ocr_<wbr>acceptance/<wbr></code> | 验收测试（run_acceptance.py） | 10 类样本 |
| 后端全量回归（pytest testpaths） | 全项目回归 | ~5800+ <code>def test_<wbr></code> 函数 |
| <code>tests/<wbr>test_<wbr>canary_<wbr>*.py</code>（Sprint 3F） | 发布门禁 canary 行为/故障注入/回滚 | 135+ 用例 |
| <code>tests/<wbr>test_<wbr>module_<wbr>*.py</code>（Sprint 3E/3F-A） | ModuleResult / 适配器契约 / Bench | 38+ 用例 |
| <code>tests/<wbr>test_<wbr>services/<wbr>test_<wbr>ocr_<wbr>paddlex_<wbr>http_<wbr>client.py</code> | PaddleX HTTP 客户端 mock 测试 | 55 cases |
| <code>tests/<wbr>test_<wbr>services/<wbr>test_<wbr>ocr_<wbr>worker_<wbr>client_<wbr>factory.py</code> | 工厂 + Protocol 测试 | 6 cases |
| <code>tests/<wbr>test_<wbr>services/<wbr>test_<wbr>ocr_<wbr>remote_<wbr>config.py</code> | 远程配置 + URL 脱敏 + 验证 | 20 cases |
| <code>tests/<wbr>test_<wbr>services/<wbr>test_<wbr>ocr_<wbr>gateway_<wbr>remote.py</code> | Gateway 远程后端集成测试 | 5 cases |
| <code>tests/<wbr>test_<wbr>services/<wbr>test_<wbr>ocr_<wbr>import_<wbr>safety.py</code> | import safety 子进程测试 | 4 cases |
| <code>tests/<wbr>test_<wbr>ocr_<wbr>fix_<wbr>uses_<wbr>admin_<wbr>ai_<wbr>config.py</code> | 配置统一验证 | 5 tests |
| <code>tests/<wbr>test_<wbr>ai_<wbr>repair_<wbr>uses_<wbr>admin_<wbr>ai_<wbr>config.py</code> | 配置统一验证 | 7 tests |
| <code>tests/<wbr>test_<wbr>ai_<wbr>capability_<wbr>model_<wbr>separation.py</code> | 能力分离验证 | 3 tests |

### 运维脚本

| 文件 | 用途 |
|------|------|
| <code>scripts/<wbr>run_<wbr>remote_<wbr>ocr_<wbr>db_<wbr>config_<wbr>validation.py</code> | 外部 OCR API 数据库配置 E2E 验证 |
| <code>scripts/<wbr>run_<wbr>cloud_<wbr>api_<wbr>resource_<wbr>test.py</code> | 2C/2G 资源限制实测 |
| <code>scripts/<wbr>backfill_<wbr>question_<wbr>images.py</code> | 题图补图 |
| <code>scripts/<wbr>auto_<wbr>detect_<wbr>figure_<wbr>regions.py</code> ~ <code>scripts/<wbr>final_<wbr>visual_<wbr>qa_<wbr>report.py</code> | 5 级视觉 QA 工具链 |

---

## 7. 审计范围与后续验证

本次更新只根据提供的后端 `app.zip`、现有架构文档和此前上传的 CI workflow 做静态核对。以下内容仍需要在完整仓库/实际部署中验证：

1. 生产环境的 `PIPELINE_COORDINATOR_MODE`、`STRUCTURE_FREEZE_MODE`、`UNIFIED_SAFETY_MODE`、`DOMAIN_QUALITY_GATE_MODE` 实际值。
2. 完整 `tests/` 下 OCR regression / acceptance / canary 用例的当前数量与通过率。
3. `OCR_REMOTE_URL` 的真实生产地址与网络边界。
4. Coordinator 切主前 shadow 与 legacy 的结果差异率。
5. DocumentIR 与 legacy blocks 双路径的剩余调用量。

文档维护原则：**“代码默认值”和“生产部署值”必须分开描述；完成了实现不等于已经成为默认主路径。**

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
