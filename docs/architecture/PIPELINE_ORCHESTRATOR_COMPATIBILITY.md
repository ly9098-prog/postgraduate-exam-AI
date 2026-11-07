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

## 拆分内容索引（2026-11-08）

原 §6 起的编号批记（重构批次登记）已迁至 [[docs/architecture/PIPELINE_ORCHESTRATOR_HISTORY.md|PIPELINE_ORCHESTRATOR_HISTORY]]，编号沿用；新批记继续登记在该历史文件，本文件只维护稳定契约。

| 原章节 | 内容 | 现位置 |
|--------|------|--------|
| §6 | 未完成和未验证（原编号沿用） |
| §7 | Single-pass 执行循环刻画（2026-10-26）（原编号沿用） |
| §8 | 完成阶段的数据清理与观察（2026-10-26）（原编号沿用） |
| §9 | 提取源、单次 OCR 与练习区间（2026-10-26）（原编号沿用） |
| §10 | 分割输入、恢复与重叠去重（2026-10-26）（原编号沿用） |
| §11 | OCR router 分类、调用与候选发布（2026-10-26）（原编号沿用） |
| §12 | Single-pass 输入、恢复、执行和收尾（2026-10-26）（原编号沿用） |
| §13 | Chunked 初始化、独立会话与终态发布（2026-10-27）（原编号沿用） |
| §14 | 暂停流水线恢复编排（2026-10-27）（原编号沿用） |
| §15 | OCR 后端选择与导入后台包装器（2026-10-28）（原编号沿用） |
| §16 | 冻结投影、VL 重绑定与跨页合并（2026-10-29）（原编号沿用） |

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/PIPELINE_ORCHESTRATOR_HISTORY.md|PIPELINE_ORCHESTRATOR_HISTORY]] — 编号批记历史（§6 起）
