# OCR 管线优化 / 修复 / 工程审计方案

**审计日期：** 2026-07-16  
**审计对象：** `/app` 中的 OCR、文档解析、题目结构化、AI 纠错、缓存、断点恢复与入库链路  
**代码包 SHA-256：** `4d747ef61eb1318124d8cc9d77ec113f2d48a2a7469f96ad3e03533631164ba1`  
**历史审计报告 SHA-256：** `74da95c718eb50b5b37a38165b757e73067357790092c85cd7286b254d0e4a42`

---

## 1. 结论摘要

这套 OCR 管线的方向是对的：已有本地 PaddleOCR、远程 PaddleOCR-VL、规则清洗、候选纠错、安全门、结构冻结、代码题专项修复、断点恢复、视觉区域处理和审核入库，业务覆盖面较完整。

但从当前代码包看，**还不适合直接以“已完成工程审计、可稳定发布”作为结论**。最重要的问题不在 OCR 模型本身，而在执行层、状态一致性、可复现性和中间数据模型：

1. **执行器存在可复现的异常覆盖和超时后队列永久污染问题。**
2. **所谓统一 OCR 执行入口并未统一，仍存在多条同步调用和嵌套线程池。**
3. **线程超时不能终止 Paddle 原生推理，超时后实际并发可能超过限制。**
4. **断点恢复的阶段顺序与真实 Pipeline 已经漂移。**
5. **缓存和 artifact 的版本指纹不足，可能静默复用错误结果。**
6. **OCR 的文本、坐标、置信度、阅读顺序没有形成统一、可追溯的结构化 IR。**
7. **远程 VL 客户端缺少连接复用、严格重试策略、结果下载边界和 SSRF 防护。**
8. **随包未提供测试、依赖锁、容器和 CI，历史报告中大量“已修复/已测试”结论无法在本包复验。**

建议把整改分为四个层次：

- **S0：阻断发布的正确性修复**——并发、超时、路径、阶段顺序、敏感日志。
- **S1：工程稳定性重构**——进程隔离、统一执行入口、原子缓存、远程客户端治理、测试与依赖可复现。
- **S2：质量架构升级**——统一 Document IR、阅读顺序、候选评估、领域化质量门和完整基准集。
- **S3：规模化与持续优化**——任务队列、多 GPU 路由、主动学习、模型/规则灰度、成本与质量联合路由。

---

## 2. 审计范围、方法与限制

### 2.1 已完成的检查

- 解包并扫描全部源码：642 个文件，其中 318 个 Python 文件。
- Python 语法编译检查：`compileall` 通过。
- OCR 执行器并发与超时逻辑静态审查。
- 构造最小函数复现执行器异常覆盖与超时计数泄漏。
- OCR 单例、缓存、artifact、阶段编排、VL HTTP 客户端、安全门、日志和配置检查。
- 将当前代码与随附历史审计报告逐项交叉核对。
- 参考官方 GitHub 仓库中的 PaddleOCR、docTR、Surya、olmOCR、MinerU、Docling 的数据模型、基准、部署与扩展做法。

### 2.2 当前无法验证的内容

代码包中没有发现以下内容：

- `tests/` 或 `test/`
- `pyproject.toml`、`requirements.txt` 或依赖锁文件
- Dockerfile
- `.github/workflows` 或其他 CI 配置
- 模型文件、运行配置、数据库迁移和真实回归样本

因此，本报告能确认源码级缺陷和结构问题，但无法完成：

- PaddleOCR/PaddleOCR-VL 真实模型精度复测
- GPU 显存、吞吐和长文档峰值内存实测
- 数据库并发、事务与迁移兼容性全链路验证
- 历史报告声称的数百个测试用例复验
- 生产流量下的错误率、缓存命中率和成本校准

这些项目在整改完成后必须进入发布门禁，而不能继续以文档中的“已修复”状态替代可执行证据。

---

## 3. 高优先级问题清单

### 3.1 S0-01：多页 OCR 异常分支引用未定义变量

**位置**

- `services/ocr_executor_service.py:147-157`
- `services/ocr_executor_service.py:180-190`

**问题**

`asyncio.as_completed(tasks)` 的异常分支使用 `idx`，但该变量只存在于列表推导式及内部协程中，异常发生时外层没有可用的页码。实际结果是：原始 OCR 异常会被新的 `UnboundLocalError` 覆盖，失败页也无法正确落空或归因。

**影响**

- 掩盖真正的 Paddle、图片解码或内存异常。
- 失败页定位错误。
- 监控错误类型失真，自动重试和故障归因失效。

**修复**

让每个任务无论成功失败都携带页码：

```python
async def run_page(idx: int, png: bytes):
    try:
        value = await ...
        return idx, value, None
    except Exception as exc:
        return idx, None, exc
```

或维护 `task -> page_index` 映射。不要在异常处理器中依赖协程内部局部变量。

**验收测试**

- 任意一页抛 `ValueError` 时，返回结果中只将该页标记失败。
- 日志保留原始异常类型和对应页码。
- 其他页面不受影响。

---

### 3.2 S0-02：超时任务永久占用“pending”计数，最终毒化队列

**位置**

- `services/ocr_executor_service.py:204-243`
- `services/ocr_executor_service.py:264-276`

**问题**

队列深度以 `submitted - completed` 计算。任务超时时只增加 `timed_out`，没有在底层线程最终结束后增加 `completed`。Python 线程又无法被强制终止，因此任务虽然稍后完成，统计仍永久认为它处于 pending。

已用最小慢函数复现：底层线程结束后，统计仍为 `submitted=1, completed=0, timed_out=1, pending=1`。

**影响**

- 多次超时后，即使没有实际任务，系统也会永久返回 `OcrQueueFullError`。
- 超时后 `asyncio.Semaphore` 已释放，但底层 OCR 仍运行，实际推理并发可超过配置上限。
- 监控中的 running、pending、timeout 无法反映真实状态。

**修复**

- 队列容量必须覆盖底层 Future 的完整生命周期，而不是调用者等待生命周期。
- 在 `future.add_done_callback(...)` 中统一：释放容量、移除 running、累计 finished，并区分 success/error/late-after-timeout。
- 将指标拆为：`accepted`、`queued`、`running`、`caller_timed_out`、`finished`、`failed`、`late_finished`。
- 在彻底改造前，不能把线程超时当成真正取消；应明确标记“调用端超时，后台仍运行”。

**推荐实现**

```python
cf = executor.submit(fn, *args)
af = asyncio.wrap_future(cf)
try:
    return await asyncio.wait_for(asyncio.shield(af), timeout)
finally:
    # 不在这里释放底层容量；由 cf.done_callback 释放
```

对于本地 Paddle 推理，最终方案应采用独立进程，超时才能通过终止 worker 实现真正隔离。

---

### 3.3 S0-03：执行器额外占用默认线程池线程

**位置**

- `services/ocr_executor_service.py:214-227`

**问题**

代码先通过自有 `ThreadPoolExecutor.submit()` 运行 OCR，又通过 `loop.run_in_executor(None, future.result)` 在默认线程池等待结果。一次 OCR 至少占用一个实际推理线程和一个等待线程。

**影响**

- 默认线程池被无意义占用。
- 高并发下线程数、上下文切换和内存增加。
- 默认线程池中的其他 FastAPI/文件 IO 任务可能被饥饿。

**修复**

使用 `asyncio.wrap_future(concurrent_future)`，不要再启动一个等待线程；或直接把自定义 executor 传给 `loop.run_in_executor(executor, fn, *args)`。

---

### 3.4 S0-04：“统一 OCR 执行入口”与代码现实不一致

**位置举例**

- `features/pipeline_orchestrator.py:761,772,777`
- `features/question_pipeline.py:1203`
- `features/question_import_writer.py:161`
- `services/import_service.py:228`
- `services/ocr_service.py:646-726`

**问题**

执行器文件声明所有本地 OCR 必须经统一服务，但主 Pipeline 及其他模块仍直接调用同步 `ocr_pages()` / `ocr_pages_with_boxes()`。`ocr_service.py` 自身也创建线程池。主编排器外层又使用线程卸载，形成嵌套线程池和多套限流。

此外，OCR 推理实际受全局 `_ocr_inference_lock` 串行化，多 worker 线程通常只是排队，并不产生有效并行。

**影响**

- `OCR_MAX_WORKERS`、`OCR_EXECUTOR_WORKERS`、`OCR_MAX_CONCURRENCY` 的语义不确定。
- 队列上限和超时不能覆盖所有调用。
- 可能出现线程池套线程池、锁内排队、大对象同时驻留。

**修复**

建立唯一边界：

- `ocr_engine.py`：只负责单页同步推理，不创建线程。
- `ocr_worker`：拥有模型、执行队列、超时、进程生命周期。
- `ocr_gateway`：唯一异步调用入口，批量接口只负责调度。
- 禁止领域模块直接 import `ocr_service.ocr_*`，可用架构测试/静态检查强制。

---

### 3.5 S0-05：已废弃函数存在必然 ImportError

**位置**

- `features/exercise_region_detector.py:366`
- `services/ocr_service.py:38`

**问题**

前者 import `app.services.ocr_service._ocr_lock`，实际模块只有 `_ocr_inference_lock`。虽然函数标注废弃，但仍保留为可调用代码。

**影响**

调用该兼容路径时直接失败；语法编译无法发现这类运行时导入错误。

**修复**

- 若没有调用方，删除废弃实现和导出。
- 若必须兼容，使用正式公开 API，不导入模块私有锁。
- CI 增加“全模块 import smoke test”。

---

### 3.6 S0-06：OCR 单例 reset 存在并发竞态

**位置**

- `services/ocr_service.py:44-53`
- `features/pipeline_orchestrator.py:768-779`

**问题**

`_reset_ocr()` 修改模型单例时没有持有初始化锁或推理锁，可能与另一线程正在使用模型同时发生。

**影响**

- 原生资源在使用中被替换或泄漏。
- GPU 上下文、模型状态和错误恢复不可预测。
- 失败页重试可能影响其他请求。

**修复**

短期：reset 必须持有状态锁和推理锁，采用 `UNINITIALIZED / READY / RESETTING / FAILED` 状态机。  
长期：一进程一模型，worker 失败或超时后重启进程，不在 Web 进程内热重置原生模型。

---

### 3.7 S0-07：断点恢复阶段顺序与真实 Pipeline 漂移

**位置**

- `features/pipeline_orchestrator.py:1960-2010`
- `features/pipeline_artifacts.py:47-71`

**问题**

真实 Pipeline 包含但 `CANONICAL_STAGE_ORDER` 缺少：

- `visual_region_detect`
- `question_bbox`
- `visual_region_assign`
- `visual_region_crop`

两个模块都宣称自己是阶段顺序的事实来源，实际上已经产生双 SSOT。

**影响**

- resume 时阶段跳过、重跑或 artifact 恢复顺序可能错误。
- 与视觉区域相关的数据可能丢失或重复写入。
- 可选 stage 配置变化后兼容判断不可靠。

**修复**

用一个声明式 `PipelineDefinition` 生成：运行阶段、阶段顺序、依赖关系、artifact schema、指标名和可恢复边界。禁止手工维护第二份列表。

每个 stage 至少声明：

```text
name, version, dependencies, enabled_if, input_schema,
output_schema, checkpointable, idempotent, retry_policy
```

---

### 3.8 S0-08：artifact 路径需要严格防穿越

**位置**

- `features/pipeline_artifacts.py:126-139`
- artifact cleanup 相关路径拼接

**问题**

`pipeline_id` 被直接拼入 artifact 根目录。当前生成 ID 看起来安全，但 resume/admin 路由和未来调用者可能传入外部值。

**影响**

恶意或异常 ID 可能造成越权读取、写入或递归删除。

**修复**

- ID 只允许固定前缀和 `[A-Za-z0-9_-]`。
- `candidate.resolve().relative_to(root.resolve())` 校验。
- artifact 目录权限 0700。
- cleanup 只接受数据库中已存在且归属当前用户/租户的记录。

---

### 3.9 S0-09：远程结果 URL 下载缺少 SSRF 和大小边界

**位置**

- `features/ocr_vl/paddleocr_vl_client.py:476-488`

**问题**

客户端对 API 返回的结果 URL 直接发起请求，并将整个响应读入内存。未见主机白名单、协议限制、重定向限制、最大响应体和 JSONL 行数限制。

**影响**

- 若上游服务或链路被污染，可能访问内网地址或本机元数据服务。
- 超大或无限响应导致内存消耗。
- 重定向可能绕过初始域名检查。

**修复**

- 只允许 `https`，域名/端口白名单，禁止私网、环回、链路本地地址。
- 禁止或逐跳验证 redirect。
- 流式下载；限制总字节数、单行长度、行数和解压后大小。
- 优先让任务查询接口直接返回结构化结果，或使用短时签名对象存储 URL。

---

### 3.10 S0-10：日志可能泄露题目/试卷原文

**位置举例**

- `features/batch_image_import_service.py:674-677`
- `features/pipeline_orchestrator.py:2712-2717`
- 其他 OCR 前后文本日志

**问题**

日志会输出较长 OCR 文本片段及外部任务错误内容。试卷、用户上传材料和答案可能属于受限数据。

**修复**

- 默认只记录 hash、长度、字符分布、页码、错误码和 trace ID。
- 原始文本仅写入加密、权限隔离、短 TTL 的 debug artifact，且必须显式开启。
- 统一日志脱敏器，禁止把任意 exception/上游 body 直接作为 metric label 或 `model_used`。

---

## 4. S1 工程稳定性问题

### 4.1 缓存键缺少关键版本维度

**位置**

- `services/ocr_cache_service.py:35-48`

当前配置 hash 未充分覆盖：

- OCR 引擎与模型精确版本/权重 digest
- Paddle/PaddleOCR 版本
- 预处理算法版本
- 旋转、裁边、缩放策略版本
- CPU/GPU/推理后端
- 输出 schema 版本
- 代码提交版本

这会导致模型或预处理改变后命中旧缓存，产生难以察觉的“旧结果漂移”。

**方案**

使用内容寻址 key：

```text
sha256(input_bytes + engine_fingerprint + preprocess_fingerprint + schema_version)
```

缓存 manifest 要保留每个维度，便于审计和定向失效。

### 4.2 缓存写入不原子，清理在请求热路径全量扫描

**位置**

- `services/ocr_cache_service.py:96-127`

**问题**

- 直接写最终 JSON 文件，进程崩溃或并发读写可能看到半文件。
- 每若干次写入同步扫描整个缓存目录，缓存增长后形成尾延迟尖峰。
- 进程内命中统计在多 worker 下没有全局意义。

**方案**

- `tempfile -> fsync -> os.replace` 原子提交。
- 使用 SQLite/LMDB 或对象存储 metadata，而非大量无索引 JSON 文件。
- 配额、LRU/TTL 与后台 janitor；不要在 OCR worker 热路径全盘扫描。
- 指标进入 Prometheus/OpenTelemetry。

### 4.3 artifact 兼容性检查过弱

**位置**

- `features/pipeline_artifacts.py:73-76`
- `features/pipeline_artifacts.py:234-260`
- `_json_fallback` 相关代码

**问题**

- Pipeline 版本长期固定为字符串 `1`。
- 缺少源文件 hash、option hash、模型版本、规则版本、stage schema hash、代码 commit。
- legacy artifact 无 metadata 时仍被视为兼容。
- 未支持类型会被 `str()` 静默序列化，恢复时可能不可逆。

**方案**

- 生产默认拒绝无 metadata artifact。
- 每 stage 输出使用 Pydantic/JSON Schema，显式 schema version 与 migration。
- manifest 包含 source、config、model、code、stage fingerprint 和 checksum。
- 只允许白名单类型序列化；不允许通用 `str()` 降级。

### 4.4 OCR 运行配置存在多套来源

`core/config.py` 与 `core/ocr_profile.py` 同时控制 worker、并发和 timeout，调用者又可能传局部值。

**方案**

建立一个不可变 `OcrRuntimeConfig`，启动时完成校验并注入各组件。配置日志输出最终生效值及来源，但隐藏密钥。

### 4.5 远程 VL 客户端缺少生产级 HTTP 生命周期治理

当前每次提交、轮询、下载都可能新建 `httpx.AsyncClient`，未充分利用连接池。重试也没有区分可重试错误与永久错误。

**方案**

- 应用生命周期内复用一个 client。
- 明确 connect/read/write/pool timeout 和 connection limits。
- 只重试网络瞬断、408、429、部分 5xx；4xx 参数错误直接失败。
- 429 尊重 `Retry-After`，指数退避加 full jitter。
- 增加 circuit breaker、并发舱壁和远端依赖健康指标。
- poll 单次请求和 sleep 都必须受“剩余 deadline”约束。
- 任务取消时尽可能调用远端取消接口。
- multipart MIME 根据真实文件类型设置，而非固定 PNG。

### 4.6 Router 配置与降级语义存在缺陷

**位置**

- `features/ocr_fix/router.py:221-232`
- adapter 缓存与 `configure()`
- `model_used=f"degraded_{last_error}"`

**问题**

- manual 策略未选模型时，注释称走 rule，实际返回自动链第一项。
- 运行时更新配置后，已缓存 adapter 不一定重建，密钥/base URL/model 可能仍是旧值。
- 任意异常文本被放进 `model_used`，容易造成敏感信息泄露和高基数指标。

**方案**

- 使用枚举化 reason code。
- 配置 fingerprint 改变时重建对应 adapter。
- 明确定义 manual 空配置是校验失败、rule-only 还是 auto，不允许注释与行为不同。

### 4.7 安全门重复且可能不一致

OCRFixRouter、主编排器和兼容包装层都可能再次执行安全检查。多个入口若规则版本不同，会出现同一个候选在一处接受、另一处拒绝。

**方案**

建立唯一 `CandidateEvaluator`，输出：

```text
accepted_text, decision, reason_codes, diff,
quality_before, quality_after, provenance, evaluator_version
```

后续模块只消费决策，不重复实现 acceptance policy。

### 4.8 低置信度规则会误删代码、公式和英文选项

**位置**

- `services/ocr_service.py:605-620`

低置信且不含中文的行会被过滤。这对代码、英文、公式、变量、A/B/C/D 选项尤其危险。

**方案**

OCR 识别层不做不可逆删除，只标记置信度和可疑原因；由拥有页面位置、跨页重复、题型和代码区域上下文的质量层决定是否过滤。水印应基于位置、透明度/置信、跨页重复和版面类别，而不是“是否含中文”。

### 4.9 预处理策略不可逆且缺少坐标变换记录

EXIF、裁边、旋转、缩放、增强全部直接作用于图片，若策略误判会伤害公式、彩色图形、边缘题干，并使坐标难以映射回原图。

**方案**

- 保留原图和预处理版本。
- 每个变换记录 3×3 仿射/透视矩阵。
- 只有质量探针触发时才生成增强候选。
- 通过可校准分数选择候选，而非无条件全处理。
- bbox/polygon 最终统一映射回原始页面坐标系。

### 4.10 Web 进程内运行原生 OCR 风险过高

线程无法真正取消，Paddle/BLAS/CUDA 原生崩溃可能带走整个 API 进程。

**推荐架构**

- 独立 OCR worker 进程或服务。
- 一进程一模型/一 GPU shard。
- 有界队列、心跳、最大任务数、内存阈值和周期回收。
- worker 超时或 GPU OOM 时隔离重启。
- API 只负责提交、查询与返回，不持有模型。

---

## 5. S2 质量架构问题：缺少统一 Document IR

当前主要接口将全文字符串与 box 列表分开返回，box 中未稳定携带对应文本；后续结构解析依赖字符串顺序和重复正则。这样很难正确处理多栏、旋转、图文混排、跨页、代码、表格和回溯来源。

参考 docTR 的 `Document -> Page -> Block -> Line -> Word` 嵌套对象、Surya 的 polygon/label/reading-order/confidence 输出，以及 PaddleOCR/PP-Structure 的结构化 JSON/Markdown与细粒度坐标，建议引入领域无关的统一 IR。

### 5.1 建议数据模型

```python
DocumentIR
  document_id
  source_hash
  pages: list[PageIR]
  pipeline_fingerprint

PageIR
  page_index
  width, height
  original_asset_ref
  transforms
  regions: list[RegionIR]

RegionIR
  region_id
  type: text | code | formula | table | figure | header | footer | option
  polygon
  reading_order
  confidence
  lines: list[LineIR]
  provenance

LineIR
  line_id
  text
  polygon
  confidence
  tokens
  language/script
  flags
  provenance
```

`provenance` 至少记录：识别引擎、模型版本、输入版本、adapter、是否 AI 修改、原文本、diff、规则版本和 trace ID。

### 5.2 IR 带来的收益

- 文本与坐标不再失配。
- 可同时保留 PaddleOCR、VL 和规则候选，而非过早覆盖。
- 选项冻结可绑定 region/line ID，而不是字符串位置。
- 支持可视化审核、定向重跑和局部修复。
- 结构质量指标可以在 region/line 层计算。
- 下游题目解析与 OCR 引擎解耦。

---

## 6. 参考优秀 GitHub 项目后的可借鉴做法

> 以下只借鉴工程方法，不建议直接复制全部模型或架构。模型选择仍需用本业务试卷数据验证。

| 项目                      | 值得借鉴的做法                                               | 本项目落地建议                                               |
| ------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| `PaddlePaddle/PaddleOCR`  | 完整 tests/benchmark/deploy 目录；结构化 JSON/Markdown；细粒度坐标；模块级 latency/memory benchmark；可选依赖拆分；多后端和多进程部署 | 保留 Paddle 作为识别底座，但补齐可执行 benchmark、模型 fingerprint、坐标 IR、后端能力矩阵和部署基线 |
| `mindee/doctr`            | 明确的 Document/Page/Block/Line/Word/Artefact 嵌套模型；旋转 box 语义清楚；layout region 与 OCR 结果统一 | 建立统一 Document IR，保留 polygon、方向、layout type 和文本层级 |
| `datalab-to/surya`        | OCR、layout、reading order、table 分为明确能力；输出包含 polygon、label、position、confidence、raw/error；公开吞吐与质量基准 | 将阅读顺序作为显式阶段和字段；每个模块输出结构化置信度、错误和原始响应；建立分模块基准 |
| `allenai/olmocr`          | 7,000+ case / 1,400 document 的综合 benchmark；覆盖旧扫描、数学、表格、页眉页脚、多栏、长小字；百万页任务队列和外部 inference server | 建立业务版“题库 OCR Bench”，按场景分桶；大任务用持久队列、page group、并发上限和幂等 workspace |
| `opendatalab/MinerU`      | native-text / OCR / VLM 双或混合引擎；滑动窗口降低长文档内存；流式落盘；异步任务 API、路由、多 GPU 负载均衡；丰富中间格式与可视化 | 先判定文本 PDF 与扫描 PDF；长文档分窗、逐页落盘；把 OCR worker、router 和 API 分开；保留可视化中间产物 |
| `docling-project/docling` | 统一、可序列化且尽量无损的文档表示；本地/隔离环境运行；多 OCR/VLM 后端适配 | adapter 只负责转换到统一 IR；业务解析不感知具体 OCR/VLM 返回格式 |

### 6.1 不建议照搬的内容

- 不要因 VLM 在公开 benchmark 表现好就让它无条件覆盖本地 OCR。
- 不要将 OCR、结构解析和题库业务 schema 绑成一个巨大模型调用。
- 不要把所有页面都送入高成本 VLM；应使用质量/布局/风险路由。
- 不要以通用 CER/WER 替代业务指标，题号、选项、答案、代码符号的错误权重更高。

---

## 7. 推荐目标架构

```text
                    ┌──────────── Control Plane ────────────┐
                    │ Job/Queue · Idempotency · Quota       │
                    │ Model Registry · Config Fingerprint    │
                    │ Metrics · Trace · Benchmark · Rollout  │
                    └────────────────────────────────────────┘
                                      │
Input → Type/Safety → Native Text Probe → Page Renderer/Stream
                                      │
                          OCR Gateway / Router
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

### 7.1 路由原则

1. 文本 PDF 优先 native extraction，只有坏字形/低覆盖页面才 OCR。
2. 普通清晰页面走本地 OCR。
3. 多栏、公式、表格、代码损坏或低质量页才升级到专用模型/VL。
4. 远程模型结果是候选，不直接覆盖；统一安全评估后接受。
5. 局部 region 可重跑，不必整页或整文档重跑。
6. 所有决定保留 reason code 和版本指纹。

---

## 8. 分阶段整改计划

### Sprint 0：正确性与安全止血（必须先完成）

1. 修复两处未定义 `idx`。
2. 重写 executor Future 生命周期统计；禁止超时后提前释放底层并发容量。
3. 用 `asyncio.wrap_future` 去除等待线程。
4. 删除/修复 `_ocr_lock` 废弃路径。
5. OCR reset 加锁，临时限制同一进程仅一个推理任务。
6. 将 4 个视觉阶段补入恢复顺序；随后立即改为声明式单 SSOT。
7. pipeline ID 路径校验和 artifact 删除权限校验。
8. VL 结果下载加 SSRF、大小、重定向和 JSONL 边界。
9. OCR 原文日志默认关闭，错误信息结构化脱敏。
10. manual router 空配置行为修正；禁止错误文本进入 `model_used`。

**发布门禁**

- 上述缺陷均有失败测试先行和修复后回归。
- 1,000 次 timeout/exception 注入后队列 pending 回到 0。
- 任一页失败不影响其他页，且原始异常不被覆盖。
- 路径穿越、私网 URL 和超大响应测试全部拒绝。

### Sprint 1：执行与可复现性重构

1. OCR 推理移入独立进程 worker。
2. 全项目 OCR 调用统一经 gateway；静态检查禁止直接 import engine。
3. 合并 OCR 配置 SSOT。
4. HTTP client 连接复用、deadline、retry、jitter、circuit breaker。
5. 原子缓存、完整 fingerprint、后台清理和容量配额。
6. artifact typed schema、checksum、source/config/model/code fingerprint。
7. 拒绝无 metadata legacy artifact，或提供显式离线迁移工具。
8. 补齐 `pyproject.toml`/lock、Docker、CI、模型兼容矩阵。
9. 增加 import smoke test、mypy/pyright、ruff、Bandit/Semgrep 和依赖漏洞扫描。

**发布门禁**

- worker crash/OOM/timeout 不导致 API 进程退出。
- 相同输入+相同 fingerprint 结果可复现；任一关键版本变化缓存必失效。
- 并发、重试和恢复测试在 CI 中稳定通过。

### Sprint 2：统一 IR 与质量评估

1. 落地 Document/Page/Region/Line/Token IR。
2. 原图坐标、预处理坐标和输出坐标可逆映射。
3. layout、reading order、watermark/header/footer 变为显式模块。
4. 安全门合并为唯一 CandidateEvaluator。
5. 质量门按文本、代码、数学、表格、图片题分别校准。
6. 低置信内容不在 OCR 层删除，而是带 flag 流向验证层。
7. 结构冻结改为 region/line ID 绑定。
8. 审核 UI 使用 IR 显示原图、bbox、候选、diff 和来源。

### Sprint 3：基准、灰度和规模化

1. 建立“题库 OCR Bench”。
2. 用持久任务队列支持 page group、幂等、重试和多 worker。
3. 多 GPU/多模型 router，按质量、成本、延迟与数据敏感度路由。
4. 模型/规则版本灰度与自动回滚。
5. 人工审核结果进入主动学习和 hard-case 采样。
6. 形成每次发布的质量、性能、成本、安全审计包。

---

## 9. 测试与评测方案

### 9.1 单元测试

必须新增的回归用例：

- page task 抛异常时保留页码和原始异常。
- timeout 后 future 晚完成，capacity 和 pending 正确释放。
- 同时 timeout 数超过 queue size 后系统仍可恢复。
- reset 与 inference 并发时状态安全。
- manual router 空配置。
- configure 后 adapter 重建。
- cache 半写、并发写、旧 fingerprint 失效。
- artifact 路径穿越、checksum 损坏、schema 不兼容。
- VL 结果私网 URL、重定向、超大 body、畸形 JSONL。
- 非中文低置信代码/公式不能被直接删除。

### 9.2 契约测试

为 PaddleOCR-VL API 建 mock server，覆盖：

- submit 成功/失败
- 401/403/404
- 408/429 + Retry-After
- 500/502/503
- state 迁移和未知 state
- poll deadline
- result inline / result URL
- 取消、重复查询和幂等

### 9.3 属性与变形测试

- 同一页轻微亮度、压缩、DPI 变化，不应改变题号和选项集合。
- 页边增加空白不应改变阅读顺序。
- 旋转后恢复应能映射回原坐标。
- 分批处理与整批处理结果应等价。
- resume 与从头执行的最终结果应等价。

### 9.4 故障注入

- worker kill、GPU OOM、磁盘满、缓存损坏、数据库暂时不可用。
- 远程 API 高延迟、连接复位、429、部分返回、重复 job。
- 超长 PDF、坏页、加密 PDF、空白页、巨型图片和解压炸弹。

### 9.5 业务基准集

至少按以下维度分桶，每桶独立报告而非只给总平均值：

- 清晰扫描 / 低 DPI / 模糊 / 倾斜 / 手机拍照
- 单栏 / 双栏 / 多栏 / 跨页题目
- 代码题：括号、缩进、箭头、比较运算符、泛型、指针
- 数学：上下标、分式、矩阵、LaTeX
- 表格、流程图、题图、坐标图
- 水印、页眉页脚、页码、装订线
- 中文、英文、混排、特殊符号
- 选择题、判断题、填空、简答、组合题

建议参考 olmOCR-Bench 的“按困难场景分桶”方法，但建立自己的业务样本和评分权重。

---

## 10. 指标体系与建议门槛

以下为**建议目标**，不是当前系统已达到的数值。上线前先记录 baseline，再确定正式门槛。

### 10.1 识别与结构质量

- 字符错误率 CER / 词错误率 WER
- 题号 exact match
- 选项集合 exact match 与选项顺序准确率
- 答案 exact match
- 代码 token exact match、括号平衡、语法可解析率
- 数学表达式规范化后等价率
- layout region F1 / mAP
- reading-order Kendall tau 或 pairwise accuracy
- 表格 TEDS / cell match
- 静默损坏率：无异常但结果错误，必须作为最高权重指标

### 10.2 稳定性与性能

- page success / retry / terminal failure rate
- p50/p95/p99 page latency、document latency
- queue depth、queue wait、worker utilization
- timeout 后 late-finish 数
- peak RSS、GPU memory、每页临时磁盘
- cache hit/stale-reject/corrupt rate
- resume success/equivalence rate
- remote API 429/5xx/circuit-open rate

### 10.3 AI 纠错安全

- 候选接受率、拒绝原因分布
- 原文丢失率、选项修改率、答案修改率
- hallucination / unsupported insertion rate
- 每个 adapter 的真实增益：`quality_after - quality_before`
- 人工审核回滚率

所有指标必须带版本维度，但限制 label 基数；异常文本不能作为 label。

---

## 11. 对现有审计报告的复核意见

现有报告的架构梳理和历史修复记录有价值，但当前代码与报告存在明显版本差异：

- 当前 `pipeline_orchestrator.py` 约 5,498 行，而报告记录约 4,871 行。
- 当前 `question_splitter.py` 约 1,846 行，而报告记录约 1,437 行。
- 当前 `question_pipeline.py` 约 1,569 行，而报告记录 2,921 行，说明已发生进一步拆分或报告未同步。
- 当前 `ocr_service.py` 约 773 行，而报告记录 637 行。
- 当前 `paddleocr_vl_client.py` 约 567 行，而报告记录约 430 行。
- 报告声称存在多组测试，但随包没有测试文件，无法验证其与当前源码是否同版本。
- 报告把断点恢复称为已完成，但当前 canonical order 已漏掉 4 个实际 stage。

因此建议将历史报告中的状态拆为：

- **Verified**：当前包中可通过代码与自动测试确认。
- **Partially verified**：代码存在，但缺真实依赖/数据验证。
- **Unverified**：仅文档声称完成，当前包没有测试或证据。
- **Regressed**：曾声称修复，但当前代码又出现不一致或新缺陷。

发布审计不能仅使用 commit 号或“✅”作为证据，必须附：测试名、测试结果、基准版本、输入集 hash、运行环境和 artifact。

---

## 12. 建议的交付物清单

整改结束后，每次发布至少应生成：

1. `ARCHITECTURE.md`：目标架构、数据流和 trust boundary。
2. `PIPELINE_SPEC.yaml`：唯一 stage 定义和版本。
3. `DOCUMENT_IR.schema.json`：统一中间结构。
4. `MODEL_MANIFEST.json`：权重 digest、框架版本、后端和许可。
5. `BENCHMARK_REPORT.md/json`：按场景的质量、性能、成本。
6. `REGRESSION_CASES/`：脱敏样本、期待结果和评分器。
7. `THREAT_MODEL.md`：上传、PDF 渲染、远程 URL、artifact、日志风险。
8. `SBOM` 与依赖漏洞报告。
9. `MIGRATION.md`：artifact/cache/schema 迁移与回滚。
10. `RELEASE_EVIDENCE/`：CI、压力、故障注入、灰度、回滚演练结果。

---

## 13. 最终优先级表

| 优先级 | 工作项                                         | 不修复的主要风险                     |
| ------ | ---------------------------------------------- | ------------------------------------ |
| S0     | executor 异常页码、timeout 计数/容量、额外线程 | 队列永久不可用、异常被覆盖、并发失控 |
| S0     | 统一执行入口与 reset 竞态                      | 资源失控、进程不稳定、配置失效       |
| S0     | stage order 单一事实源                         | 断点恢复产生错误或不一致结果         |
| S0     | artifact 路径与远程 URL 防护                   | 路径穿越、SSRF、内存攻击             |
| S0     | 原文日志脱敏                                   | 试卷、题目、答案泄露                 |
| S1     | OCR 进程隔离                                   | 原生崩溃/OOM/卡死拖垮 API            |
| S1     | cache/artifact fingerprint 和原子写            | 静默复用旧结果、恢复损坏             |
| S1     | 测试、lock、Docker、CI                         | 结论不可复现、升级易回归             |
| S2     | Document IR 与阅读顺序                         | 文本/坐标失配、复杂布局脆弱          |
| S2     | 单一候选安全评估与领域质量门                   | AI 幻觉、误删代码/公式、规则不一致   |
| S3     | 业务 benchmark、灰度、多 worker/router         | 无法量化提升，规模化后质量失控       |

**总体建议：先停止继续向主编排器叠加规则，完成 S0/S1 的执行与状态基础设施治理；随后再推进模型、VL prompt 或更多 AI 修复。当前最大的收益来源不是再加一个模型，而是消除静默错误、保证可恢复和建立可度量的统一数据层。**

---

## 参考的官方 GitHub 项目

- `PaddlePaddle/PaddleOCR`
- `mindee/doctr`
- `datalab-to/surya`
- `allenai/olmocr`
- `opendatalab/MinerU`
- `docling-project/docling`
