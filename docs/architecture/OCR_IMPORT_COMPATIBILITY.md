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

## 10. 结构冻结模式编排（2026-10-27）

`ImportPipeline._run_structure_freeze` 保留同步签名，将调用内状态、IR 尝试、
模式选择、灰度策略、结果投影和 dual 日志分别交给
`pipeline_freeze_state/orchestration/canary/projection/dual`。阶段顺序保持
`classify_pages → structure_freeze → split`；同步阶段仍由既有 runner 调度，
取消等待不能据此推断后台线程已经终止。

| 边界 | 保持的行为 |
| --- | --- |
| legacy 与未知模式 | 先运行 legacy 并读取其 registry；legacy 立即返回原对象；未知模式仍先尝试 IR，再告警返回原对象 |
| 异常范围 | DocumentIR 获取在捕获外；仅首次 IR 导入、执行和 registry 读取捕获普通异常；转换、策略、比较和日志失败继续传播；取消不被普通异常吞掉 |
| 局部导入 | IR 成功投影重新导入 converter；canary 成功使用初次捕获的 converter；canary 三个策略函数在开关检查前局部导入 |
| 灰度与诊断 | kill-switch 保留短路，比较仅执行一次；空 IR 强制回退；dual 仅记录前 10 条差异并保留 legacy 输出 |
| 结果与查找 | 保留原 registry、结构、警告列表的引用/复制语义及警告顺序去重；端口先读取原模块实时 globals，再读取原入口绑定的 canonical builtins 字典 |

修改原模块 `__builtins__` 键不会改变已存在函数绑定的内置字典，resolver 因此不从
该键重新取 builtins；修改 canonical 字典或原模块同名全局仍按原时序可见。
新增契约使用同一份测试分别验证拆分前入口（`1f5d5c28`）和拆分后实现，
各 128 项通过；原有冻结、IR 绑定、灰度故障注入和阶段定义七文件另有 104 项通过。
架构门禁另有 44 项通过，限制完整同步入口、300/50 预算、逐职责能力和惰性依赖。
契约包含运行前内容快照、canary checker 的首次导入捕获，以及未绑定 converter 的
`UnboundLocalError` 类型、消息和异常上下文。
最终源码哈希固定后，本地重放 CI static 全量清单为 5410 项通过、无跳过。
专项契约的隔离守卫未记录真实 `.env` 读取、网络或数据库连接尝试；
这些结果不构成外部 OCR/AI、完整 worker 或生产验收。

### 10.1 拆分时确认的 IR → split 协议缺口（修复见第 11 节）

`freeze_from_document_ir` 按 `region_id` 生成 registry；
`freeze_registry_to_block_format` 仅转换选项条目，保留 region 键。
真实 split 和 `_apply_frozen_options` 按 `page:block_index` 消费。
因此 IR/canary 成功路径虽能返回选项映射，却未实现下游冻结标记、冻结选项剥离和
冻结选项覆盖的完整绑定；legacy/dual 的 block 键不受此缺口影响。
比较器核对选项内容，不验证这些键能否被 split 寻址，故 canary 通过不能证明绑定闭环。

真实 builder → freeze → split 的单 block 合成案例已复现上述区别：
legacy/dual 的 `1:0` 能标记冻结并剥离 raw text 中的选项；IR/canary 的 region 键不能。
该案例的 regex 仍可恢复选项，不能据此声称所有选项丢失。
第 10 节的拆分批次保持既有行为；绑定修复须基于可验证的 region/block 来源关系，
覆盖多 block 同页、聚合/过滤/重排及无法确定绑定时的回退，不能靠文本或位置 zip 猜测。

真实 normalize → layout → freeze → split 的同页双题合成探针还确认：layout 会把
多个 region 聚成一个 page block；该 block 内重复的 A/B 字母可能在 IR 冻结时只保留首组。
将这一 registry 简单改键为 `1:0` 后，第二题会被错误注入第一题选项；
不注入冻结结果的对照仍可分别解析两题。因此绑定修复还须在最终 split 边界确认
选项唯一归属；聚页多题等无法证明安全的范围不能强行接受候选冻结数据。

## 11. IR 冻结来源与题目绑定（2026-10-27）

IR / canary 的冻结选项现在通过来源计划传入真实 splitter；能证明唯一归属的题目
接受冻结选项，无法证明的题目保留文本或分组选项解析结果。默认 legacy / dual
继续使用原 block registry。此修复不把 region ID 简单重命名为 block key。

### 11.1 捕获、投影和消费

| 层次 | 实现事实 |
| --- | --- |
| `document_ir_builder` | 构建开始记录原输入顺序、唯一坐标和 normalized_text 摘要；创建每个 RegionIR 时记录其来源索引；构建结束丢弃临时对象 ID 查找表，不修改输入 blocks |
| `freeze_source_binding` | 私有 capture 校验 region 的页、成员顺序、ID、revision 和文本；重复实例、region ID、坐标及非法坐标均不发布计划；公开 DocumentIR codec 不包含此私有 capture |
| freeze projection | 成功分支附带 `freeze_block_binding` v1：generation、完整有序输入摘要、region/source 映射、独立选项快照及校验和；IR 空结果或 canary 策略回退时，仅通过显式来源坐标绑定选中的 legacy 选项 |
| `pipeline_split_binding` | 显式 `freeze_mode=ir/ir_canary` 进入新消费策略；重建前清空旧 registry，向 splitter 传计划；缺失或无效计划仍禁止最终 `_apply_frozen_options` 再次按文本子串注入 |
| `question_freeze_binding` | 使用实际 `filtered_boundaries` 和有限 block 内容区间证明唯一归属；每题参与的全部来源必须完整归属该题；允许一题多来源，冲突选项或共享来源拒绝冻结 |

计划是独立 JSON 数据，不保存对象引用或原选项的可变别名；内容校验和用于发现
后续修改与损坏，不是鉴权或签名。JSON roundtrip 和通用 artifact save/load 均有
结果回归。正常 split 工件保存已完成绑定的 raw_questions；实际阶段保存/恢复探针
也验证冻结与回退结果原样保留。恢复的 DocumentIR 若没有构建时 capture，
不按文本或 region 顺序补造来源。

### 11.2 输入变化与回退

- 跨页链接被接纳、book/PDF layout filter 成功或 VL rebuild 成功后，旧来源计划失效；即使返回相同内容，也不假定来源关系已被保留。
- 输入内容、坐标、顺序或成员变化使完整视图校验失败。SEPARATED 模式跳过 answer-only 页面时仍使用原来源索引，不按消费子集重新编号。
- book 内部裁剪改变全文起点时停止冻结，不把裁剪后的题目位置套用到旧 page_map。
- 一个来源覆盖两道实际题目时，两题均不接受该来源；同页其他来源独立、归属明确的题目仍可冻结。
- 分组选项题保留 groups；未接受冻结的 IR 题目不接受无题级来源的页级 layout 选项注入。
- 跨页选项恢复遇到任一参与题已经接受新冻结绑定时跳过该配对，防止重写冻结选项或另一道冻结题。

canary 的原比较与回退策略继续运行；选中的 legacy 结果也须经过新来源消费检查。
kill-switch 直接返回原 legacy 结果的行为保留。新增
`freeze_binding_diagnostics` 记录解析期与最终接受数量，以及缺失来源、输入变换、
共享来源、冲突、分组和校验失败等原因，不保存新增原文副本。

### 11.3 工件与验证范围

该批将 pipeline artifact schema 从 2 提升为 3（当前版本见第 14 节），兼容检查拒绝带旧版本元数据的工件，
防止直接恢复修复前的 split 结果；检查不会删除原工件。无元数据工件仍遵循既有
`REJECT_LEGACY_ARTIFACTS` 配置，本批未改变这一兼容开关。

固定旧提交 `06e906fb` 的 10 项真实回归为 5 失败、5 通过：四项暴露 IR/canary
没有冻结，两题聚页的 canary 回退还暴露真实选项串题。相同用例在修复后全部通过。
新增安全、恢复和阶段执行矩阵同时核对单题、同页独立题、多来源单题、聚页回退、
同页混合接受/拒绝、非法来源、IR 变动、输入变换、book 裁剪、分组、恢复和最终注入。
实际 `PipelineStage.run_async` 与 `complete_pass_stage` 的组合回归验证同步线程执行和
阶段数据合并会保留来源计划；这不等于完整 worker 或生产队列验收。

当前相关契约和门禁合并重放 554 项通过，隔离守卫未记录网络、数据库连接或真实
`.env` 读取尝试。源码哈希固定后的 CI static 全量重放为 5497 项通过、无跳过。
四类内存变体（忽略共享来源、恢复无来源页级 layout 注入、误用消费子集索引、
恢复最终 legacy 注入）均被结果断言拒绝；实际阶段工件保存/恢复另有 4 项探针通过。
外部 OCR/AI、完整 worker、生产 Redis、真机和生产导入仍按第 7 节单独验收。

## 12. 扫描 PDF 本地 OCR 编排拆分（2026-10-27）

`_ocr_scanned_pdf` 从 220 行缩为 20 行同步入口，保留参数、默认值和 docstring。
新增职责模块在导入时不创建引擎或读取配置；配置及 OCR 包仍在调用时导入。

| 模块 | 职责与兼容边界 |
| --- | --- |
| `pipeline_scanned_state` | 单次调用状态；原模块全局变量按调用时查询，未定义名称继续回退 Python builtins |
| `pipeline_scanned_inputs` | 原顺序导入、cloud_api 拒绝、profile/限额捕获、打开 PDF、页范围、初始标签与进度 |
| `pipeline_scanned_batch` | 逐页 DPI 渲染、按批 reset 与文本回退重试、原字段及 boxes 引用投影 |
| `pipeline_scanned_execution` | 批间超时、进度发布、批处理范围的 finally 关闭文档 |
| `pipeline_scanned_output` | 超时优先于截断警告、失败页列表别名、清理进度、构建 DocumentIR 与汇总标签 |

所有新增生产文件不超过 300 行、函数不超过 50 行。配置/profile 与两个 OCR 函数
在打开文档前捕获，reset 函数仍每批导入；失败回退只传本批存在的页面。
原来即使没有失败页也会 reset 的行为保持。空白文本跳过、文本原始空白、页码排序、
block_index、尺寸、boxes 原引用、两个失败页字段共用同一列表等均由结果契约覆盖。

### 12.1 基线与验证

旧测试文件 `test_pipeline_orchestrator.py` 存在同名测试类覆盖；该文件里较早定义的
扫描 PDF 范围、回退等测试不会被 pytest 收集。本批新增两个独立契约模块，未把
这些被覆盖的历史用例算作已执行，也未扩大修改到其他同名类。

相同 38 项行为契约分别在原函数和拆分后入口通过；10 项结构门禁通过。
四种内存错误变体（改变旋转参数、移除 reset、取消结果排序、复制失败页列表）
均被真实结果断言拒绝。上述行为契约和结构门禁已加入 CI static 显式清单。
相关 extract/split/freeze 与扫描 PDF 合并重放 687 项通过，隔离守卫没有记录网络、
数据库连接或真实 `.env` 读取尝试。将职责函数内联、还原 state/port 后，函数体 AST
与原实现一致；入口签名和 docstring、orchestrator 其余定义 AST 也一致。
固定源码哈希后，按当前 CI YAML 的 static 显式清单本地重放，5545 项通过、
无跳过，另有 15 条已有 datetime 弃用警告；这不是远程 CI 或外部服务验收。
依赖方向检查另有 22 项通过。独立进程导入五个职责模块时，未加载配置、
数据库、OCR 服务、fitz 或原 orchestrator。

### 12.2 仍保留的既有行为与验收边界

以下为提交 `93aa4bb4` 时的历史基线；后续修复及剩余边界见第 13 节：

- 文档打开后、批循环 try 之前的 len/标签/初始化异常仍可能没有 close。
- 批内异常或取消会 close，但不清除进度；close 自身抛错也不执行结果收尾。
- 超时只在批间检查，不能中断正在执行的 OCR 或同步线程。
- OCR 返回未渲染过的异常页码时仍可能因尺寸查询抛出 KeyError。

这些边界已有独立结果断言，后续修复需明确更新兼容契约。本函数在 cloud_api
部署仍被拒绝；合成 PDF/引擎回归不构成真实 PaddleOCR、外部 OCR/AI、完整 worker、
生产 Redis 或真机验收。本批没有修改小程序和管理端。

## 13. 扫描 PDF 资源清理与批次页码校验（2026-10-27）

本批修复第 12 节记录的初始化文档泄漏、失败后残留进度，以及异常 OCR 页码
可能复用前一批尺寸而被错误接纳的问题。批间超时仍不终止正在执行的同步 OCR。

### 13.1 文档与进度生命周期

配置/profile/限额捕获顺序保持；打开文档是 load 的最后一个步骤。取得文档后，
len、标签、范围和初始进度都在 execution 的异常保护范围内。成功、普通失败和
BaseException（含注入的 CancelledError）均执行一次文档关闭，并清理已发布进度。
尚未发布进度的初始化失败不会删除已有的同 ID 进度。

关闭或进度清理再失败时，已有的主异常或取消继续传播，附加异常类型说明；
没有主异常时，关闭/清理失败仍会使调用失败，不生成成功结果。关闭和进度清理
同时失败时保留先发生的关闭异常。成功路径仍在 DocumentIR 构建前关闭并清理进度。
原模块 live port 查询和调用前 OCR 函数捕获保持。

### 13.2 页码完整性与回退

`pipeline_scanned_results` 在 reset、文本回退和 block 投影前校验交付结果：

- 必须是 dict，键集合必须与本批实际渲染页面完全一致；空映射、缺页、额外页和前一批页码均拒绝。
- 键必须是严格 int；bool、float、字符串或其他类型不能通过数值相等混入。
- 每个结果的 page_index 必须是严格 int，且与对应键一致。

校验模块只使用普通 Python 类型注解，不直接依赖原始 OCR 类型；Gateway 的
adapter 类型边界门禁保持。

不满足约束时抛出不含原文的 ValueError；本次 OCR 不返回部分成功结果。
现有 extract attempt 会保留原提取内容，并继续既有 OCR correction 降级路径；
取消继续向外传播。正常 `failed=True` 页仍执行原有 reset/文本回退，合法文本、
boxes 引用、页序、字段和失败页列表别名保持。

该校验针对适配器交付的映射，不验证 OCR 识别正确率。提交 `3ecfd078` 当时尚未处理的下层问题是
`ocr_service._legacy_ocr_pages_with_boxes` 会把缺失 entry 或 executor 异常转换成
`failed=False` 的空结果；该批未改适配器，后续修复见第 14 节。

### 13.3 工件兼容与证据

artifact schema 从 3 提升为 4，防止从修复前已生成的下游工件跳过页码校验。
真实 save/restore 测试覆盖 split、normalize_schema、repair、math_detect、table_detect：
带版本 3 元数据的工件被拒绝，文件摘要、调用方 data 和 completed 列表保持；
当前版本仍可恢复。实际 single-pass 恢复与 skip 判断也确认，旧工件不会导致
extract 被跳过。无元数据工件仍遵循既有 REJECT_LEGACY_ARTIFACTS 配置，未删除旧工件。

固定提交 `93aa4bb4` 的五个生产模块显式装载后，同一组 34 项可靠性用例为
32 失败、2 通过；修复后全部通过。版本调整前，5 类带版本 3 元数据的工件
均可被真实恢复；调整后均拒绝。新旧版本恢复及真实 pass 路由合计 11 项通过。
七种内存错误变体（初始化移出保护、无条件清理进度、清理掩盖主异常、跳过页映射
校验、忽略 payload 页码、放宽页码类型、恢复版本 3）全部被结果断言拒绝。
新增契约与门禁合并 95 项、相关 extract/split/freeze 合并 734 项通过；隔离守卫
未记录网络、数据库连接或真实 `.env` 读取尝试。真实 OCR/AI、完整 worker、生产、
微信真机验收不由这些本地合成测试替代。
去掉直接原始类型依赖后的最终相关重放连同 Gateway 边界、依赖方向门禁共
758 项通过；七种错误变体在最终源码上再次全部被拒绝。
固定最终源码哈希后，当前 CI YAML static 清单本地完整重放为 5592 项通过、
无跳过，另有 15 条已有 datetime 弃用警告；这不是远程 CI 或外部服务验收。

## 14. OCR 适配器失败状态与逐页回退（2026-10-27）

本批修复第 13 节记录的下层失败状态丢失，以及同类 Gateway 混合结果问题。
变更位于既有 `ocr_service` 适配边界，未新增 OCR 算法或本地引擎入口。

| 路径 | 实现行为 |
| --- | --- |
| legacy boxed | 缺失 entry、None 或空 dict 产生 failed=True / ocr.legacy_missing_result；调用或映射读取发生普通异常时，所有请求页产生 failed=True / ocr.legacy_execution_failed |
| Gateway boxed | WorkerResult 的非 success 状态优先，失败载荷中的残留文本/boxes 不接纳；沿用外层 page_index 和 stable_error_code，无错误码时使用 ocr.gateway_execution_failed |
| Gateway 缺少载荷 | success 状态下缺失、空或非 dict 载荷仍是失败，使用 ocr.gateway_missing_result |
| Gateway text | 只有 worker success、dict 载荷且载荷未报告 failed 时返回文本；其他页返回原接口约定的空字符串 |
| Gateway 整批判定 | 无结果、全部 worker 失败或全部载荷不可用时，继续原有非受限环境 legacy 降级；受限环境拒绝本地降级；部分成功继续保留可用页，不重做整批 |

显式 `text=""` 的合法空白结果仍成功；不会仅因空白文本触发额外文本 OCR。
legacy 返回的有效 OcrPageResult 对象保留原实例，合法 boxes/transforms 引用保持。
新增失败结果使用稳定错误码，不把原异常文本复制到新增 error 字段；原日志边界保持。
CancelledError、KeyboardInterrupt 等 BaseException 继续传播；cloud legacy guard 仍在
executor 导入前运行。五个修改/新增职责函数均不超过 50 行；其余服务函数 AST 不变。

### 14.1 包装器到流水线的结果验证

合成 executor / gateway 配合真实同步包装器与 `_ocr_scanned_pdf`，验证缺页会按原图片
触发文本回退、有效页不重做、失败载荷不会串到另一页、可恢复页保留、未恢复页进入
`_ocr_runtime_failed_pages` / `_ocr_text_fallback_unavailable_pages`，以及取消后的文档关闭
和进度清理。混合文本回退中失败页的残留文字也不会被接纳。

固定提交 `3ecfd078` 的原判定/转换、legacy boxed 和文本函数重放，同组 57 项行为
用例为 40 失败、17 通过；修复后全部通过。八类内存错误变体分别恢复缺页成功、
executor 异常成功、忽略 worker 状态、无载荷成功、失败文本泄漏、旧整批判定、
真实空白误判失败和旧工件版本，均被结果断言拒绝。

### 14.2 恢复门禁与验证范围

artifact schema 从 4 提升为 5，防止恢复修复前漏页的下游工件后跳过新的失败处理。
版本 3 / 4 工件在五类可恢复阶段均被拒绝，原文件及调用方恢复状态保持；当前版本
仍可恢复。真实 pass 恢复/skip 判断也覆盖两个旧版本，相关工件契约共 17 项通过。
无元数据工件仍遵循既有 REJECT_LEGACY_ARTIFACTS 配置，未删除任何旧工件。

本批适配器、调用链、旧回退、预算和恢复契约合并 88 项通过；相关 extract/split/freeze、
适配器和依赖门禁合并 835 项通过，隔离守卫未记录网络、数据库连接或真实 `.env` 读取尝试。
cloud profile 隔离 30 项通过：运行器保留已安装依赖的 PYTHONUSERBASE，HOME/cwd 仍在
临时目录，未通过真实环境文件补齐凭据。上述均为合成端口与导入隔离证据，不等于
真实 PaddleOCR、外部 OCR/AI、完整 worker 或生产导入验收。
固定最终源码哈希后，当前 CI YAML static 清单本地完整重放为 5669 项通过、
无跳过；55 条弃用警告来自 datetime 和兼容 OCR 包装器调用。

## 15. 视觉区域裁剪与原题快照编排（2026-10-27）

- `_run_visual_region_crop` 从 204 行收敛至 16 行，保留原签名、docstring 和返回结构。
  `pipeline_visual_crop.py` 按题组合区域投影与快照发布；`pipeline_visual_crop_regions.py`
  负责区域重建、截图/表格合并与风险标记；`pipeline_visual_crop_snapshot.py` 保留快照
  执行器、上传和普通异常降级。独立 state 只持有本次调用的依赖和输出，不管理数据库。
- 无页面图片时只复制并累加 `source_snapshot_failed`，返回原 questions 引用与原 warning，
  不获取 storage。其余路径先获取一次 storage，按 pipeline ID 的 MD5 前 8 位生成虚拟
  import ID，并固定本次月份；逐题依次投影 segments、发布 snapshot，不并发或重排。
- 区域 ID 的去重范围仍为单题；有 ID 的无 bbox 区域也占据去重位置，空 ID 不阻止后续
  裁剪。只有四元素 list/tuple bbox 转成 tuple 后触发裁剪，不新增数值校验。未知区域类型与坐标枚举沿用 UNKNOWN /
  IMAGE_PIXELS 回退，confidence、alt、option_key 和 requires_review 保留原默认与转换。
- 原生 table 的 region ID 匹配后，原 table 对象获得 source/fallback image URL；只有
  没有结构化 table 或任一 table 需要复核时才追加截图。已有同 type/region ID/URL 的图片
  不重复追加；warning 仍按原输入 ID 和裁剪结果页码生成，不因裁剪器替换区域 ID 改写。
  segments 列表与 parsed_content 外壳按原方式复制，既有 table 与内层对象保持原引用。
- snapshot 沿用原页码 key，不把字符串转换为整数。四元 question_bbox 交给 image executor，
  坐标仍为 cropper 的 IMAGE_PIXELS；否则用 file_io executor 读取整页。PNG 非空才按
  MD5 前 12 位命名并上传，storage key 仍为 `YYYYMM/snapshots/…`。缺页或空字节保留原
  静默行为；只有不存在 parsed_content 键时创建含捕获 stem 的字典，不覆盖已有 None/字符串。
- storage、VisualRegion 构造器及 crop-and-upload 回调在循环前绑定；坐标/区域枚举每个
  区域重新导入，snapshot 的 executor、crop 函数与坐标来源在原分支内重新导入。快照失败
  日志继续读取 pipeline 当前 ID，普通错误追加风险标记后继续下一题；区域错误和取消继续
  传播，已完成的 segments 投影保持，不新增隐式回退、事务、后台任务或工件版本变更。
- 90 项区域/快照/端口契约在拆分前后均通过，含真实 asyncio Task 的裁剪、读取、上传取消；
  另有 6 项架构检查约束依赖、预算、入口绑定及独立导入。反向展开 helper 并还原 state 字段
  后，业务 AST 与原实现一致，原编排器其他函数一致。本地测试不替代真实图片存储服务、
  外部 OCR/AI、完整 worker、微信或生产导入验收；OCR 其余大函数仍未全部收敛。
- 10 个故障变体均被契约拦截，覆盖重复裁剪/表格截图、缺失表格回退、丢失 parsed_content
  扩展字段、覆盖既有 None、快照坐标或 bbox 错误、缺少页面风险标记、warning ID 改写与
  吞掉取消。未修改的对照版本 90 项通过；变体运行无收集错误，隔离守卫无违规尝试。
  最终关联裁剪、表格、extract/split/freeze、OCR 适配与依赖门禁合并 1097 项通过、
  无跳过，40 条警告来自既有 OCR 兼容包装器的弃用提示；隔离守卫未记录网络、数据库连接
  或真实 `.env` 读取尝试。新增业务模块均满足 300 行/50 行预算与 Python 3.11 语法要求。
