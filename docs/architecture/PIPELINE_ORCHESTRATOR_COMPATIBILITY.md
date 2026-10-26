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
- `pipeline_orchestrator.py` 的 chunked 模式、coordinator 集成、VL rebuild 和真实 OCR 引擎调用未在本文档登记完整语义。
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
