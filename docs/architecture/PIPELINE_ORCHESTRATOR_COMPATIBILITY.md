# 导入流水线编排兼容基线

核对日期：2026-10-26。对应重构计划阶段 0；范围包括 `pipeline_orchestrator.py` 的阶段定义、single-pass 执行循环、检查点生命周期、工件恢复和内存释放，不表示各阶段算法、学习域、AI 分析或全栈阶段 0 完成。

## 1. 阶段定义（`pipeline_definition.py`）

纯元数据模块，不导入 orchestrator/artifacts/runtime，避免循环依赖。27 个阶段在 `PipelineDefinition._STAGES` 中按规范顺序定义：

| # | 阶段 | 业务域 | 条件 | 可恢复工件 |
| --- | --- | --- | --- | --- |
| 1 | extract | ocr | 总是 | — |
| 2 | wangdao_preprocess | parse | `enable_wangdao_preprocess`（默认关） | — |
| 3 | normalize_text | parse | 总是 | — |
| 4 | ocr_correction | ai_correct | `enable_ocr_correction`（默认开） | — |
| 5 | layout_reconstruction | parse | 总是 | — |
| 6 | layout_router | parse | 总是 | — |
| 7 | visual_region_detect | parse | `enable_visual_region_detect`（默认开） | — |
| 8 | analyze_structure | parse | 总是 | — |
| 9 | classify_pages | parse | 总是 | — |
| 10 | structure_freeze | parse | 总是 | — |
| 11 | split | parse | 总是 | split.json |
| 12 | question_bbox | parse | 总是 | — |
| 13 | match | parse | 总是 | match.json |
| 14 | normalize_schema | parse | 总是 | normalize_schema.json |
| 15 | code_language_noise_clean | parse | `enable_code_language_noise_clean`（默认开） | — |
| 16 | code_structure_reconstruct | parse | `enable_code_structure_reconstruct`（默认开） | — |
| 17 | classify_questions | parse | 总是 | — |
| 18 | batch_validation | parse | 总是 | — |
| 19 | batch_dedup | parse | `enable_batch_dedup`（默认开） | — |
| 20 | repair | ai_correct | `enable_ai_repair`（默认开） | repair.json |
| 21 | ai_validation | parse | `enable_ai_repair`（默认开） | — |
| 22 | similarity_match | parse | `enable_similarity_match`（默认开） | — |
| 23 | visual_region_assign | parse | `enable_visual_region_assign`（默认开） | — |
| 24 | math_detect | parse | `enable_math_detect`（默认开） | math_detect.json |
| 25 | table_detect | parse | `enable_table_detect`（默认开） | table_detect.json |
| 26 | visual_region_crop | parse | `enable_visual_region_crop`（默认开） | — |
| 27 | review | save | 总是 | review_commit_state.json |

`enabled_stages(options)` 按 option_key 过滤；`stage_index` 返回规范位置；`resumable_artifacts` 返回可恢复阶段→文件名映射；`business_map` 返回阶段→业务域映射。

## 2. 检查点生命周期

### 2.1 写入 `_write_stage_checkpoint`

- 每个阶段完成或失败后写入（仅 single-pass 模式；chunked 模式有自己的 `pipeline_checkpoint.py`）。
- 存储轻量元数据：`completed_stages`、`current_stage`、`stage_statuses`（仅 status/duration_ms/error，剥离大字段）、`failed_stage`、`error`、`source_type`、`source_file`、`subject`、`options`、`updated_at`。
- 进程内 dict + Redis（`import:pipeline:stage_ckpt:{pipeline_id}`，TTL 24h）；Redis 写入失败静默（不阻塞流水线）。
- `_prune_stage_checkpoints` 在超过 `_MAX_STAGE_CKPT_SIZE`（200）时按插入顺序驱逐最旧条目。

### 2.2 读取 `_get_stage_checkpoint`

- 优先读进程内 dict，其次 Redis；Redis 数据回填进程内。
- 缺失返回 None，不抛异常。

### 2.3 清除 `_clear_stage_checkpoint`

- 流水线成功完成后调用，移除进程内和 Redis 检查点。

## 3. 工件恢复 `_restore_from_artifacts`

- 恢复优先级（最先进优先）：table_detect → math_detect → repair → normalize_schema → split。
- 每个候选：`artifact_exists` → `check_artifact_compatibility`（拒绝版本不匹配）→ `load_artifact`。
- 恢复后用 `stages_before(stage_name)` 从规范顺序推导可跳过的前序阶段（不再硬编码 preceding 集合）。
- 返回 `(restored_stage, skipped_stages_set)`；跳过的阶段标记 completed、duration_ms=0。

## 4. 阶段执行与内存释放

- `ImportPipeline.run` 按 `self.stages` 顺序执行；每个阶段结果 `data.update(result)`。
- 大字段在最后消费者后立即释放：
  - `normalize_text` 后释放 `raw_blocks`
  - `ocr_correction` 后释放 `file_content`/`page_images`（PaddleOCR-VL 是最后消费者）
  - `split` 后释放 `file_path`，评估 split_quality 和 routing_metrics
  - `match` 后释放 `normalized_blocks`
  - `normalize_schema` 后释放 `raw_questions`/`matched`/`unmatched`
- `review` 阶段在 `overall_status=="failed"` 时跳过（防止部分数据进入审核池）。
- 普通阶段异常 → `overall_status="failed"`、记录 error、写失败检查点；`extract` / `normalize_text` 失败后中断，其余阶段继续执行但跳过 review。`ocr_correction` 失败释放文件字节、路径和图像后继续；其他早期中断也释放这些输入。

## 5. 可执行基线

- `backend/tests/pipeline/test_pipeline_definition.py`：18 项测试覆盖 27 阶段快照、可恢复工件、业务域、条件启用矩阵、runner 方法存在性及元数据模块导入。
- `backend/tests/test_features/test_pipeline_checkpoint_compatibility.py`：新增 6 项测试覆盖检查点 write→read→clear 往返、缺失返回 None、大字段剥离、失败检查点记录 error、prune 驱逐。
- `backend/tests/test_features/test_artifact_resume_equivalence.py`：7 项测试覆盖完整运行=从 normalize_schema/repair 恢复、恢复后仍运行后续阶段、版本不匹配拒绝、损坏工件返回 None、无工件不恢复。
- `backend/tests/pipeline/` 下 20+ 项编排器、协调器、指纹、回滚和 profile 集成测试。
- 新增 `test_single_pass_execution_contract.py` / `test_single_pass_state_contract.py` 的 73 项刻画调用真实 single-pass 循环和 `PipelineStage.run_async`，以合成阶段和副作用端口隔离外部依赖。2026-10-26 连同检查点、恢复与阶段定义共 104 项通过；这些替身不验证各阶段的实际 OCR/AI 算法。

## 6. 未完成和未验证

- 检查点测试使用进程内 dict，不验证 Redis 持久化、跨进程共享和 TTL 过期行为。
- 工件恢复测试使用合成数据，不等于真实 PDF/图片导入的端到端恢复验收。
- chunked 逐阶段执行、coordinator 集成、VL rebuild 和真实 OCR 引擎调用未在本文档登记完整语义；chunked 顶层编排边界见第 13 节。
- 真实 Redis 检查点、多 worker 并发恢复、大文件（400 页扫描 PDF）内存释放和外部 OCR/AI 故障恢复仍待环境可用后验收。

## 7. Single-pass 执行循环刻画（2026-10-26）

- 对规范 27 个阶段逐一注入普通失败和取消。普通失败经过 `PipelineStage` 记录 `failed/error`，由循环决定中断或继续；取消保留异常身份，既不写失败检查点，也不写终态 marker，当前 stage 状态保留 `running`。
- 正常完成及普通失败后继续执行的阶段有前后 progress；extract / normalize_text 失败直接中断，取消传播也不保证后回调。普通 observer 异常被忽略，取消仍传播。从工件恢复跳过的阶段标为 completed、耗时为 0，不调用 progress、不单独写检查点或工件。仅有 completed_stages 的检查点仍重跑阶段；它本身不包含恢复输出。
- single-pass 在首阶段前写初始检查点；每阶段成功后写检查点，再尝试保存工件；成功后清检查点、写 completed marker，失败则保留检查点并写 failed marker。chunk pass 通过非 `None` 的共享 hash 集合辨识，不写这些全局检查点、工件或 marker。
- 初始检查点写失败阻止执行第一阶段。成功 stage 后的检查点错误会使整个 pass 失败，即便 stage 自身已 completed；此时 error 可为 `None`，已追加的 completed_stages 不回退，review 被跳过。这是既有行为的记录，不能将其表述为数据库提交或事务回滚。
- 文件字节与图像保留到 OCR correction，路径保留到 split；raw_blocks 在 normalize_text 后释放，normalized_blocks 在 match 后释放，raw_questions/matched/unmatched 在 normalize_schema 后释放。normalized block count 在结果写入时缓存，后续清理不使计数归零。
- chunk 页范围通过新 options 字典覆盖，保留调用方字典及其内层对象引用；共享 hash index 与已见 hash 集合仍按原引用传递。split 质量与 routing 观察器普通失败仅记录 warning，不使 stage 失败。实际文件删除、数据库提交与外部调用均未在这些合成测试中执行。
- 工件恢复用例同时检查首个恢复后阶段和最终数据都收到原恢复题目；mutation 将恢复端口参数替换为 `data.copy()` 时，新增断言明确拒绝丢失恢复数据的循环。

## 8. 完成阶段的数据清理与观察（2026-10-26）

- `pipeline_stage_completion.complete_stage_data` 承接阶段完成后的输入释放与 split 质量/routing 观察；调用仍位于结果合并、normalized block count 缓存和 metrics 更新之后、checkpoint 和工件保存之前。失败阶段的输入补偿和终态 marker 继续由原循环负责。
- 原始文件字节/图像保留到 OCR correction，路径保留到 split；保留 `pop` 顺序及结果对象引用。split 先释放路径，再收集质量结果，最后 routing 读取包含该质量结果的当前 data。两个观察器按原时点导入，普通异常仍 warning，取消传播；warning 回调在调用时读取原 orchestrator 的当前 logger。
- 新模块 54 行，三个函数 21/14/7 行；fresh import 不加载 orchestrator、观察器、配置或数据库。原 single-pass 入口 382→340 行，仍超 50 行，整个编排器仍待继续治理，不能将本批表述为编排完成。
- 新增 4 项观察契约先在原实现通过，与前批合计 77 项；当前核心 108 项及 pipeline、chunk/resume、工件等相关 376 项通过。作者对原分支和新实现的 2,000 组输入清理、观察、warning 与取消差分一致；测试使用合成数据，不代表外部 OCR/AI 或真实大文件内存验收。

## 9. 提取源、单次 OCR 与练习区间（2026-10-26）

- `ImportPipeline._run_extract` 保留同步签名与原模块 globals，入口 222→30 行；`pipeline_extract_stage.py` 负责源选择，`pipeline_extract_pdf.py` 负责 PDF 文本层、单次 OCR 及 region 处理，`pipeline_extract_diagnostics.py` 负责结果和诊断投影。三个新业务模块分别 70/198/89 行，全部函数不超过 50 行。
- PDF 仍优先 truthy file_path，非 PDF 优先 file_content（包括空 bytes），再回退 path；已有结构化 OCR blocks 逐 mapping 浅复制，嵌套 geometry 引用保留。PDF 文本总量严格小于 100 字符且启用 OCR 才尝试一次 `_ocr_scanned_pdf`，不在此阶段调用 VL。
- OCR blocks 一旦接受就设置成功标记，随后练习区间检测或筛选失败仍保留当时的 OCR/region 部分状态；不因后续检测失败重试 OCR 或输出“本地 OCR 无结果”的 VL 提示。只有启用 exercise detection、非 exam、没有 truthy 用户页范围时检测，region 包含首尾页并保持原 block 顺序与身份。
- 诊断仍在提取后分四次遍历，保留 page/page_index 回退、整数转换、去重排序、getter 次数及异常优先级。原 `_extract_pdf_blocks`、`_ocr_scanned_pdf`、文本转换、logger 与 builtin patch 端口仍在原表达式时点读取；取消直接传播，不被普通 fallback 捕获。
- 新增源/OCR/region 刻画先在原实现通过：初始 51 项（含旧提取 12 项），扩充后修改前 69 项，最终保存的原实现重放 70 项；新版同组加架构门禁 97 项、相关编排和图片阶段 282 项通过。相关回归有 7 条 AsyncMock 未 await 警告，未屏蔽；测试没有调用真实 OCR 引擎，不证明扫描 PDF 或外部服务验收完成。
- 独立只读审查原版 70 项、当前含门禁 97 项通过；补充 1,024 组结果/部分状态/引用/遍历差分和 48 条动态端口/异常/取消轨迹一致，18 个 helper 与 2 个入口违规 mutation 均被门禁拒绝，无 P0–P3 发现。作者与独立证据分开记录，未扩展为完整 worker 或真实 OCR 验收。

## 10. 分割输入、恢复与重叠去重（2026-10-26）

- `ImportPipeline._run_split` 保留原签名、docstring 和模块 globals，入口 473→29 行；`pipeline_split_stage` 按原顺序调用 input、rebuild、prose、fallback、overlap、result，`pipeline_split_state` 仅保存本次调用的局部状态。八个新模块均不超过 300 行，所有函数不超过 50 行。
- 跨页合并只有在存在 links 时接受替换 blocks 和 warnings；book/PDF 布局过滤仍读取原 normalized blocks，可能覆盖此前合并，过滤普通失败则保留已接受的输入。VL 重建成功后先发布 blocks、清空 layout、切回 standard，再按原冻结 registry 重映射；缺输入或无结果回退 layout_enhanced。
- 初始 raw question count/hash 和 prose 风险计数仍在过滤前采集；book/PDF 先过滤 prose，视觉回退成功后再次过滤并累积计数，每次 preview 上限 20。无题号的普通文档仍生成低置信人工审核项，book/PDF 不生成该回退项；没有纯 AI/OCR 自动入库路径。
- chunk overlap 仅在 seen 集合与 logical_end 都不是 `None` 时启用，只有已见 hash 且 page_start 大于 logical_end 才丢弃；保留题目的 hash 在下一题计算前更新共享集合，后续异常不撤销已完成的集合更新。末题贴近边界且有 A/B/C、缺 D/E 才发出截断告警。
- 保留动态原模块与 builtin 查找、对象引用、视觉检测普通异常边界和取消传播；最终顺序仍为多空题诊断、应用冻结选项、逐题日志、返回结果。`test_split_stage_input_contract.py`、`test_split_stage_result_contract.py`、`test_split_stage_ports_contract.py`、`test_split_stage_prose_contract.py` 与 `test_pipeline_split_boundaries.py` 已接入静态 CI；fresh import 不初始化 orchestrator、OCR、配置或数据库。
- 以上兼容检查使用合成输入和现有本地测试，不代表真实 OCR/AI、扫描 PDF、大文件内存或完整跨进程 worker 验收。single-pass、chunked runner、OCR correction router 及编排器其他职责仍需继续治理。

## 11. OCR router 分类、调用与候选发布（2026-10-26）

- `_run_ocr_correction_router` 保留原 async 签名与历史模块依赖，委托 `pipeline_ocr_router_stage`；分类、预算/并发调用、失败与元数据投影、安全门与领域质量观察、候选发布、敏感内容过滤和最终指标分别落在同前缀模块。本次状态与候选对象只承接局部变量，不拥有数据库事务或队列。
- 全部 blocks 先完成分类和分类指标，再导入预算函数并创建并发上限为 3 的 semaphore。每个候选先按估算 token 的三倍检查预算，再调用 router；用量优先读取 `metadata.router_call_stats.tokens_used`，在返回任务结果前记账。预算拒绝不调用模型；调用或记账失败均作为该块失败保留原对象。
- `gather(return_exceptions=True)` 保留输入结果顺序。单个子任务取消按该块失败处理，父阶段取消向外传播；分类、结果安全门和最终指标等阶段自身异常继续传播。空块、未选中块及失败块保留原对象；正常返回的候选先浅复制，再保留 table/table_image/table_caption 布局元数据，包括候选未改动或被拒绝的情况。
- 文本变化且置信度为正才进入 CandidateEvaluator；PaddleOCR-VL 保留零/缺失置信度例外。领域质量门处于 shadow/enforce 时仍只记录该路径的观察结果，文本发布继续使用 CandidateEvaluator 的 decision；本批没有新增 enforce 策略。先构建兼容 safety trace，再按接受/拒绝分支发布。最后敏感过滤可能修改透传原块，再汇总模型名、flush 指标并返回。
- 保留原模块 globals/builtin 动态读取，以及预算函数在分类后的导入捕获、CandidateDecision 在 evaluator 调用前的导入捕获。新模块均满足 300 行/50 行预算；架构门禁覆盖 async、嵌套函数与 lambda，并约束依赖、端口别名、resolver 使用和 fresh import。
- execution/result/ports 三组契约及架构门禁已接入静态 CI。验证使用合成预算、模型和指标端口；没有真实 OCR/AI、Redis 预算争用、生产数据库或完整 worker 验收，不代表全栈预算治理已经完成。
- 2026-10-29：`_build_router_config` 117→7 行，保留原 async 签名并委托 `pipeline_ocr_router_config`。基础 opts、OCR_FIX→AI_REPAIR 解析、admin_ai_configs 过滤配置和 rolling-upgrade 别名按原顺序执行；模型解析仍在原调用点局部导入，外层失败继续降级并保留 logger 动态查找。新模块 144 行、最长函数 26 行，`test_ocr_router_config_contract.py` 与既有 Admin 配置契约、router 架构门禁共同接入静态 CI。

## 12. Single-pass 输入、恢复、执行和收尾（2026-10-26）

- `_run_single_pass` 保留 19 个 keyword-only 参数及默认值，通过 `pipeline_single_pass_stage` 编排本次调用的 input、checkpoint、execution、loop 和 result；`pipeline_single_pass_state` 保存调用输入与局部状态。七个新业务模块均不超过 300 行，所有函数不超过 50 行，fresh import 不初始化原 orchestrator、模型配置或数据库。
- 先创建阶段并记录开始，再处理页范围和可选 vision 配置，随后创建同一个 live data，写初始检查点并恢复工件。修正入口历史 docstring：completed_stages 元数据本身不能恢复输出；接受的工件会写入后续阶段实际使用的 data，并指定跳过的阶段。options 的页范围覆盖仍为浅复制，共享 hash、图像和配置引用保留。
- 阶段成功后依次合并结果、缓存 normalized block count、更新 metrics、释放输入、写检查点和保存工件。上述副作用普通失败可能使 pass 失败而 stage 仍为 completed；失败检查点写入异常直接传播，不提前释放输入或写终态。恢复跳过、review 隔离、progress 前后回调和取消传播保持原有边界。
- 完成后仍先处理检查点和 marker，再生成 stats、diagnostics、结束时间、quality/performance/routing、工件清单和完成事件。原模块 globals/builtin 在原表达式时点动态读取，保留观察器修改当前 data 和替换后续端口的行为。
- preparation、terminal、ports 三组新增契约及 single-pass 架构门禁接入静态 CI；既有 execution/state/observation 契约继续执行。completion 旧门禁沿实际委托链检查唯一清理入口和无重复观察器，签名门禁锁定参数名、顺序、类型和默认值；契约同时覆盖 warnings 在 metrics/checkpoint 前合并，以及结构化起止事件的字段、时序和异常传播。测试以合成阶段和副作用端口刻画行为，不验证真实 Redis、外部 OCR/AI、扫描 PDF、生产数据库或完整跨进程 worker；chunked 和 coordinator 的剩余职责仍待治理。

## 13. Chunked 初始化、独立会话与终态发布（2026-10-27）

- `_run_chunked` 保留原 async 签名、默认值和函数内 checkpoint 模块、GlobalHashIndex 类的导入时点。`pipeline_chunked_state` 保存本次输入与局部状态；`input` 负责配置、检查点初始化、索引加载及开始事件；`execution` 持有逐 chunk 循环和索引清理；`result` 负责最终检查点、聚合和响应。原模块 globals/builtin 在原表达式位置动态读取，checkpoint 模块属性仍在每次调用前读取。
- 初始化记录在一个短 session 内写 parent/chunks；索引加载使用另一个 session；各 chunk 和最终状态分别使用独立 session。先保存实际水印配置，再加载一次共享索引。只有索引加载 session 的普通异常降级为无索引，取消继续传播；构造索引失败不在降级范围。索引成功时浅复制 shared 并附加索引，保留其他字段及嵌套对象引用。
- chunk 返回 `failed` 时记录错误并继续后续 chunk；循环边界未捕获的异常或取消会传播，清理索引后不写最终状态。清理的 finally 仍只包围循环，不覆盖初始化、索引加载或开始事件；清理异常可能替代原异常并保留异常上下文。原 docstring 的“永不抛出”描述已改正，本批未扩大异常吞并或清理范围。
- session 退出后才追加和观察 outcome。若非标准 session 抑制了执行异常，首次 outcome 尚未赋值时仍抛 UnboundLocalError；后续循环仍可能复用上一 outcome 的原引用。本批只刻画该兼容行为，不改变 session 抑制策略。
- 最终状态按是否出现 `failed` 取 paused/completed，先写最终检查点并退出 session，再失效进度缓存，随后聚合、合并风险、取时间和代表 batch、记录结束事件并返回。代表 batch 实际取首个非空 batch_id，不额外筛选成功状态；未知 chunk 状态也不会自动变成失败。响应保留 chunk、风险对象引用，索引 stats 仅浅复制；这些历史约定没有在本批改写。
- 四组 chunked 刻画契约、架构门禁及既有 chunk runner/resume/status 测试接入静态 CI。替身契约验证调用顺序、共享引用和失败/取消，既有隔离 SQLite 用例覆盖检查点与恢复路径；它们不等于生产 PostgreSQL、Redis 检查点、真实 OCR/AI、多 worker 或备份恢复验收。

## 14. 暂停流水线恢复编排（2026-10-27）

- `resume_pipeline_background` 保留 keyword-only 签名及入口时导入的 SQL 查询、checkpoint 模块、索引类和模型。`pipeline_resume_input` 负责查询、科目恢复及分块元数据，`context` 负责模式、水印和索引，`execution` 负责启动与重放，`result` 负责最终状态，`state` 只承接本次调用的局部状态及原模块动态端口。
- caller session 用于 parent、pending、全部 chunk 和实时水印查询。hash 加载、已见 hash 恢复、running 发布、每个 replay chunk 和最终状态各用独立 session。pending 保留返回顺序；页数为 parent 非零页数或最后一个有序 chunk 的 page_end，末块由最后一个 chunk_index 判定。只有 completed 且 batch_id 非空的记录进入索引加载，空列表仍传 `None`。
- 仅当传入 subject_id 为 `None` 时尝试 checkpoint 科目恢复，普通失败只记 debug；当前 checkpoint 模块缺少该可选属性时也保留此降级。无 pending 时直接用 caller session 写 completed/finished 并失效缓存；此提前返回不会额外读取 failed 数量。无 parent 或无全部 chunk 时告警返回。
- truthy 水印快照优先反序列化；空或无法解析为有效规则时告警后读实时规则。历史空快照告警后走同一实时路径；实时加载普通失败或空规则回退默认规则。反序列化自身异常及取消继续传播。options 仍为顶层浅拷贝；共享水印、策略、索引与已见 hash 保持原引用。
- hash 构造异常传播，只有 load session 内的普通异常降级为无 index。清理 finally 仅覆盖 replay 循环，先清 question index 再清 import index；初始化、seen hash 恢复及 running 发布失败不会扩大清理范围。`seen_hashes` 和 `outcome` 仍是执行函数局部变量，保留非标准 session 抑制异常后的未赋值错误及上次 outcome 复用边界。source_type/source_file 在每个 chunk 参数求值时重新读取 parent 属性。
- replay 普通异常或取消若未被既有 session 抑制，清理后传播，不写终态。正常 replay 后在独立 session 用 `use_cache=False` 读 progress；只要 outcome 精确为 `failed` 或持久化 failed_chunks 大于零就写 paused，其余写 completed，只有 completed 设置 finished。先退出最终 session，再失效进度缓存。
- 三组恢复刻画契约和架构门禁接入静态 CI；测试使用合成端口刻画顺序、逐块完整参数、查询模型与等值条件、对象引用、水印独立内容快照、错误与取消，并运行既有隔离 SQLite 恢复用例。门禁限制逐 helper 的 state 字段与端口，拒绝 session factory 派生别名，并在跳过入口首条语句前确认它是 docstring。独立原版/新版差分及逆还原 AST 也用于核对本批兼容性；这些证据不代表外部 OCR/AI、生产 PostgreSQL/Redis、多 worker 并发恢复、真实 PDF 或备份恢复验收。编排器剩余 OCR/VL 等大函数继续治理。

## 15. OCR 后端选择与导入后台包装器（2026-10-28）

- `import_pipeline_service` 三个超预算函数收敛：`_run_ocr_via_configured_backend`
  71→40、`_run_pipeline_with_db` 78→50、`_run_image_pipeline_with_db` 58→37；新增
  `_resolve_ocr_backend_ports`（19）、`_select_ocr_backend_result`（5）、
  `_validate_ocr_backend_result`（12）、`_shutdown_temporary_ocr_client`（6）、
  `_bind_image_pipeline_context`（21）、`_cleanup_image_pipeline_temp_file`（8）、
  `_log_pipeline_background_crash`（22）、`_record_pipeline_background_crash`（14）、
  `_cleanup_pipeline_temp_file`（8），全部满足 300/50 预算。
- OCR 后端语义保持：函数内延迟导入 `get_runtime_config/sanitize_url/get_gateway/
  create_ocr_worker_client` 后仍先判 `enabled`（未启用报“OCR 功能未启用”）再判
  `execution_backend == "disabled"`，随后按 backend/远端 URL（空则 `-`）/GPU 记录
  选择日志；Gateway 为真时走 `recognize_pages([(1, image_bytes)])` 且不建临时客户端，
  否则建 worker client 并走 `recognize_batch([(1, image_bytes)])`，为空结果报
  “OCR 后端未返回识别结果”；结果必须 status 成功且无 `failed`，否则报
  `OCR 后端调用失败: <stable_code|ocr.backend_failed>: <detail|unknown>`，文本空白报
  “OCR 后端返回成功，但未识别到文本”；异常按 `OCR failed: %s` 记录后原样抛出，
  仅自建客户端在 finally 关闭，关闭失败只记 warning 不改变结果。
- 后台包装器语义保持：`_run_pipeline_with_db` 仍先绑定 trace/request/pipeline/
  source_type/source_file 上下文，再以 `ImportBackgroundExecutionRequest` 注入
  `async_session`、`run_pipeline_background` 与模块 logger 调用
  `execute_import_background`；异常时按原格式记录 app 日志、向 `postgraduate-ai`
  事件流写 level=error（含 error_type 与截断 300 字符的 message）、持久化失败后重抛；
  finally 先释放资源预约再删除临时文件，未配置路径或文件不存在时不删除，删除失败
  仅 warning。图片路径保留 `ensure_image_checkpoint(ImageStageCheckpointRequest(...))`
  → `run_image_import_lifecycle(lifecycle)` 顺序、失败时 `_record_image_failure` +
  `persist_image_import_failure` 后重抛，以及 upload 阶段标签与 start 事件。
- 22 项固定契约在拆分前的原实现（AST 提取原三函数运行）与拆分后均通过，覆盖配置
  拒绝、Gateway/临时客户端两路、空结果、失败码与兜底 detail、空白/非 dict 结果、
  异常原样传播与关闭失败降级、远端 URL 清洗与占位符、页面下标与单页参数、后台请求
  字段与注入身份、崩溃日志/事件/持久化字段与 300 字符截断、清理顺序与空路径/删除
  失败，以及图片检查点字段、生命周期失败与清理。26 个故障变体全部被拒绝
  （证据 `/tmp/ocr-import-execution-mutants-2wrg1bep`）。
- 反向展开九个 helper 并按六项已记录归一化（端口解析折叠、结果选择/校验折叠、
  临时客户端关闭折叠、清理折叠、崩溃日志/持久化折叠并回置 `import traceback`、
  图片前导折叠）后，三个入口函数与原实现 AST 一致；本模块其余定义不变
  （`/tmp/ocr-import-execution-ast-report.json`）。
- 3 项架构门禁（`tests/architecture/test_ocr_import_execution_boundaries.py`）约束
  九 helper 与方法预算、入口不内联函数级导入、解析/校验/收尾顺序与单点文案，以及
  清理“先释放后删除”的顺序，含“把 300 字符截断改成 100”“把释放挪到删除之后”
  两项反向自检。
- 定向回归：OCR 服务/适配/网关/失败/回退、云档案隔离与相关架构门禁合计
  393 passed、1 xfailed；pipeline/import/worker v2 相关契约合计 395 passed、
  2 xfailed。严格 Ruff（沿用既有 `--ignore I001,F401,N818`，该文件在 HEAD 即存在
  同类提示）、format、compileall 与 diff-check 通过。
- 仍未执行真实外部 OCR/AI、生产 PostgreSQL/Redis、多 worker 并发导入或备份恢复；
  `import_pipeline_service` 内 `run_resume_background`（47）及其余 OCR/流水线大函数
  继续治理。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 410 个测试文件：
  6986 passed、0 failed、64 条既有弃用 warning，451.03 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。

## 16. 冻结投影、VL 重绑定与跨页合并（2026-10-29）

- 本批以完整链路交付：`pipeline_frozen_options` 负责冻结选项应用，
  `pipeline_freeze_comparison` 负责双轨诊断，`pipeline_freeze_rebinding` 负责 VL
  重建后的内容保留和绑定丢失报告，`pipeline_cross_page_merge` 负责链接检测与合并。
  原编排器五个私有入口保留签名及同步单次委托，复用既有 namespace resolver，
  在使用时读取原模块 logger、辅助入口和 builtin；函数级导入仍在原执行位置捕获。
- 冻结选项仍是权威替换：先校验 checksum（普通失败只告警），再按页和块文本映射，
  按 registry 字符串 key 的字典序取首个 truthy 选项；保留先检查原 key、后转字符串的
  历史口径。无匹配不改问题，成功原地写 option_lines/has_options/is_frozen。
  双轨对比保留 set 迭代的同 key 首值、差异字段和顺序、50 条截断及 binding_lost 计数。
- VL 重绑定仅索引 normalized_text 的 A–F 标记，不回退 text；未匹配的 legacy
  选项仍保留原内容并报告丢失。IR list 浅复制且保留 entry 身份，其他值保持引用；
  丢失列表仍经 set 去重，不新增稳定排序。
- 跨页禁用、少于两块和无 DocumentIR 时保持原 list 身份；DocumentIR 解析在
  try 外，解析错误继续传播。检测结果先写 cross_page_links 再调用实时合并入口；
  普通失败返回原 blocks 和已写入链接/告警，保留失败前的块修改，不新增回滚。
  CancelledError 等 BaseException 继续传播。页文本和结果类型每次合并调用延迟导入，
  同一调用内不重新捕获；logger 继续实时读取。
- 合并仍浅复制列表、原地修改块，只处理首个源页块；保留 revision 守卫、文本已存在
  时只更新 revision、按链接序号形成 revision 和 trace 字段。页索引仍用于原来的
  pages[source_idx] 取 region，索引不一致时可能在文本写入后报错；这是刻画并保留的
  既有行为，不在本次重构中修复。
- 新入口契约和预算/能力门禁接入静态 CI。原实现/当前实现契约、逆展开 AST、
  带字段序/引用/日志/异常的种子差分与批末验证结果集中记录于
  `refactor-results/ocr-freeze-cross-page-2026-10-29.json`。额外全目录 architecture
  扫描发现两项既有 legacy-name 门禁失败：旧 freeze/router/split 模块已使用
  normalized_blocks 而未列入历史白名单；隔离本批新增模块后同样复现，未扩大白名单。
  本批新模块不新增该命名命中。该已知基线不等于静态 CI 固定清单失败。
- 本地替身与静态清单重放不代表真实 PDF、外部 PaddleOCR/LLM、生产 PostgreSQL/Redis、
  多 worker 或备份恢复验收；编排器其他职责与全栈未完成项继续按交接治理。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
