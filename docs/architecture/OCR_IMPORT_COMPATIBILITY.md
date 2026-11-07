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

## 拆分内容索引（2026-11-08）

原 §6 起的编号批记（重构批次登记）已迁至 [[docs/architecture/OCR_IMPORT_HISTORY.md|OCR_IMPORT_HISTORY]]，编号沿用；新批记继续登记在该历史文件，本文件只维护稳定契约。

| 原章节 | 内容 | 现位置 |
|--------|------|--------|
| §6 | 可执行基线（原编号沿用） |
| §7 | 未完成和未验证（原编号沿用） |
| §8 | 图片与后台执行阶段（2026-10-26）（原编号沿用） |
| §9 | VL 重建阶段（2026-10-27）（原编号沿用） |
| §10 | 结构冻结模式编排（2026-10-27）（原编号沿用） |
| §11 | IR 冻结来源与题目绑定（2026-10-27）（原编号沿用） |
| §12 | 扫描 PDF 本地 OCR 编排拆分（2026-10-27）（原编号沿用） |
| §13 | 扫描 PDF 资源清理与批次页码校验（2026-10-27）（原编号沿用） |
| §14 | OCR 适配器失败状态与逐页回退（2026-10-27）（原编号沿用） |
| §15 | 视觉区域裁剪与原题快照编排（2026-10-27）（原编号沿用） |

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_IMPORT_HISTORY.md|OCR_IMPORT_HISTORY]] — 编号批记历史（§6 起）
