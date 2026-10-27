# OCR 导入编排兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限学生端不可见的导入上传准入、暂存、队列投递、worker 分派与 OCR 修复链，不表示学习域、AI 分析或全栈阶段 0 完成。

## 1. 上传准入顺序

所有格式共用 `import_upload_service.start_import_pipeline`，按固定顺序执行，任一步失败不跳过后续补偿：

| 步骤 | 实现 | 失败行为 |
| --- | --- | --- |
| 1. 校验 | `_validate_upload`：文件名非空、大小非零、扩展名白名单、`UploadValidator.validate_file`、page_start/page_end 仅 PDF | 抛 `ValueError`，不创建记录、不暂存、不入队 |
| 2. 准入 | `admit_pipeline_record`：在入队前持久化 `pipeline_checkpoints` 记录（status=queued、source_sha256、created_by、chunk_size） | 抛异常，不获取预约、不暂存、不入队 |
| 3. 预约 | `_acquire_pipeline_reservation(pipeline_id, task_type)` | 失败不暂存不入队；成功后异常路径必须 release |
| 4. 暂存 | `async_store_file` + `_set_pipeline_store`/`_set_image_pipeline_status`（status=processing/queued、stages.upload=completed） | 失败走 release 后重抛 |
| 5. 入队 | `enqueue_import_pipeline`/`enqueue_image_pipeline`/`enqueue_excel_pipeline` | 被拒时写 failed 状态、走 release、抛 `_queue_rejection_message` |

关键不变量：准入记录在预约和暂存之前创建，因为持久 worker 在分派前以该记录做 DB fence。预约在暂存之前获取，失败时无暂存副作用。入队被拒时写 failed 状态再 release，不泄漏预约。

## 2. 格式路由与 pipeline_id 命名

| 格式 | 判定 | source_type | pipeline_id 前缀 | 入队函数 | worker task_type |
| --- | --- | --- | --- | --- | --- |
| PDF | `.pdf` | `pdf` | `pl_` | `enqueue_import_pipeline` | `import_pipeline` |
| TXT | `.txt` | `txt` | `pl_` | `enqueue_import_pipeline` | `import_pipeline` |
| Excel | `.xlsx`/`.xls` | `excel` | `xl_` | `enqueue_excel_pipeline` | `excel_pipeline` |
| 图片 | `.jpg`/`.jpeg`/`.png`/`.webp` | `image` | `img_` + hash[:8] | `enqueue_image_pipeline` | `image_pipeline` |

图片额外前置：`OCR_ENABLED` 必须为真、`LOCAL_IMPORT` 画像要求 `local_paddleocr_available()`、Content-Type 在 `_IMAGE_CONTENT_TYPES` 内。PDF 页范围由 `resolve_pdf_page_range` 解析并写入 options 和响应；非 PDF 传 page_start/page_end 在校验阶段拒绝。

## 3. 暂存不可变性与预约释放

- 暂存对象经 `async_store_file` 写入后，pipeline store/image status 记录 `staging_object_id`，后续 worker 通过该 ID 读取原始文件，不依赖上传临时路径。
- `start_document_upload`/`start_image_upload`/`start_excel_upload` 均在 `try` 块外获取预约，`except Exception` 中只调用 `_release_pipeline_reservation` 后重抛。入队被拒路径先写 failed 状态再触发 except→release。
- 预约释放只发生一次（`trace.count("release") == 1`），reserve 失败时不释放（未获取）。

## 4. Worker 分派与 fence

`task_queue_worker._process_task_v2` 按 task_type 分派：

| task_type | 处理 | fence |
| --- | --- | --- |
| import_pipeline / image_pipeline / excel_pipeline / resume_pipeline / admin_resume | 对应导入/恢复编排 | pipeline_id |
| batch_image | 批量图片 | pipeline_id |
| formula_batch | 公式批处理 | 不 fence（多 FormulaCard 记录） |
| answer_projection / error_diagnosis / prewarm_analysis | 投影/诊断/预热 | 不 fence |

`_FENCING_TASK_TYPES` = {import_pipeline, image_pipeline, excel_pipeline, resume_pipeline, admin_resume, batch_image}。fence 在分派前检查 pipeline_checkpoints 记录是否存在且属主，缺失则跳过任务（准入记录是 worker 的 DB fence）。

## 5. OCR 修复链

`ocr_fix.router.OCRFixRouter` 自动链：`paddleocr-vl → openai-compatible → rule_fallback`。

- `CandidateEvaluator` 作为主门禁：修复结果必须通过候选评估才接受。
- 乱码持久性检查：若原文和修复结果均含 `code_garbled_text` 标志，拒绝修复（保留原文优于接受另一种乱码）。
- `deepseek` 是 `openai-compatible` 的兼容别名，`DeepSeekFixer` 为 `OpenAICompatibleFixer` 子类。
- 链可由配置重排或裁剪；`_resolve_chain` 将 `deepseek`/`openai_compatible` 归一为 `openai-compatible`。

## 6. 可执行基线

- `backend/tests/test_services/test_import_upload_admission.py`：30 项真实测试覆盖成功顺序（validate→admit→reserve→stage→status→queue）、预约/暂存/入队/拒绝失败释放、非 PDF 页范围拒绝、准入失败不获取不入队、PDF 页范围转发。
- `backend/tests/test_services/test_import_upload_admission_record.py`：准入记录持久化。
- `backend/tests/architecture/test_import_upload_boundaries.py`：4 项架构测试确保上传准入与后台执行分离、无静态环。
- `backend/tests/architecture/test_ocr_fix_import_boundaries.py`、`test_ocr_readiness_boundaries.py`：OCR 修复导入边界与就绪门禁。

## 7. 未完成和未验证

- 上传准入测试使用 monkeypatch 替换暂存/入队/预约，不等于真实 Redis 队列或 staging 存储验收。
- `pipeline_orchestrator.py` 的规范定义现有 27 个阶段；检查点、工件恢复和 single-pass 执行循环基线见 `PIPELINE_ORCHESTRATOR_COMPATIBILITY.md`。各阶段实际算法、chunked/coordinator 集成、真实 OCR 引擎和 AI 修复执行仍需逐阶段审查，不按历史“16 阶段”描述判断完成度。
- 真实外部 OCR（PaddleOCR/PaddleOCR-VL/OpenAI 兼容）、图片/Excel/PDF 导入端到端、worker 多进程并发 fence 和队列满拒绝行为仍待环境可用后验收。
- SQLite 服务路径测试不等于生产 PostgreSQL/Redis 查询计划或并发 fence 验收。

## 8. 图片与后台执行阶段（2026-10-26）

- 图片后台由 `import_image_lifecycle.run_image_import_lifecycle` 组合 OCR/解析阶段、成功终态投影和完成持久化。普通失败先记录结构化日志和异常，再由服务原有失败路径调用 `persist_image_import_failure`；服务继续负责 checkpoint、预约释放和临时文件清理，不改变人工审核入库边界。
- 通用后台的 `import_background_execution.execute_import_background` 保留 start 日志、来源 digest 解析、独立 session、后台调用和 finish 日志顺序。后台失败与其补偿仍由原服务/失败模块处理，不能把成功路径的 finish 日志移到 finally。
- CI static 清单已纳入 image lifecycle/stages/completion 和 background execution/failure 契约，防止后续拆分遗漏完成持久化、失败补偿或端口转发。测试替身不构成外部 OCR 或完整 worker 验收。

## 9. VL 重建阶段（2026-10-27）

`ImportPipeline._run_vl_rebuild_blocks` 保持同步调用，返回 `list[dict] | None`；
`_run_split`、`run_split_stage` 及 OCR 回归 runner 同样保持原同步接口。
重建职责分为 `pipeline_vl_rebuild_guard/source/select/merge/publish/state`，分别负责
输入与配置、源文件准备、双源文字选择、原文选项合并、最终恢复发布和调用内状态。

| 边界 | 保持的行为 |
| --- | --- |
| 输入与配置 | 配置为空、扩展名判断在普通异常捕获外；token/URL/model 读取在捕获内。缺图立即返回，普通执行异常返回 `None` |
| 源文件 | PDF 全部页面渲染并关闭后才开始 OCR；尺寸按同页首条原 block 提供，默认读取 pixmap 尺寸；图片读取保留上下文退出语义 |
| 局部依赖 | router 在 token 校验后导入；profile/classifier 在源准备后捕获；本地 OCR 每页重新导入；recovery 每个有候选文字的页面重新导入 |
| PP/VL 选择 | PP 阶段赋值与日志失败保留既有部分状态；仅 PP 选项数小于 4 时调用 VL；未胜出的 VL 仍保留表格 metadata |
| 合并与发布 | 原文按行序和严格 `key.` 前缀补缺；recovery 门槛为 `max(2, 当前选项数)`；清理后即使文字为空仍发布 block |
| 异常与资源 | 后页普通异常丢弃全部本次重建结果；取消继续传播，资源退出或 PDF close 异常仍可能覆盖原异常 |

六组 `test_vl_rebuild_*_contract.py` 的 94 项测试已分别在 HEAD 拆分前方法和
拆分后实现上运行通过，包括真实同步协程桥接、逐页重新导入、原模块动态端口、
配置失败范围、动态异常/metadata 类型查找和测试替身恢复。
测试使用合成文件/OCR 结果，不依赖真实凭据。
`test_pipeline_vl_rebuild_boundaries.py` 限制同步接口、Python 3.11 语法、文件
300 行/函数 50 行、完整入口签名、逐 helper 字段/端口能力、惰性依赖和事务边界；
上述测试已加入 CI static 清单。PDF 契约逐页核对完整 VL 调用参数及结果对应关系，
PP 日志异常契约在 VL 无结果时核对已接受的 PP 文字仍保留。

这些证据仅验证当前 VL 重建拆分的兼容性。外部 OCR/AI 质量与可用性、完整
worker、生产导入及真机验收仍按第 7 节单独验证，不以测试替身或跳过结果替代。
