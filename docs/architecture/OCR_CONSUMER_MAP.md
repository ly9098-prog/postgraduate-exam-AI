# OCR 有限消费者映射

2026-10-30，OCR-02/03 有界映射。本映射只回答“实际入口、调用方、职责归属和下一步核查边界”，不是 OCR 结构验收，也不证明真实外部 OCR、Redis、多 worker 或生产闭环。结构化明细见 [结果清单](refactor-results/ocr-consumer-map-2026-10-30.json)。

## 入口与消费者

| 边界 | 入口／消费者 | 归属 |
| --- | --- | --- |
| Admin 上传 | `/api/admin/v1/imports/upload`、`questions-csv`、`segment-image/upload`、`batch-image/upload` | `admin_imports.py` 负责 RBAC/HTTP/文件流；`import_upload_service` 与三类格式上传 owner 负责准入、暂存、预约和入队 |
| Admin 恢复与工件 | `pipelines/{id}/resume`、`cleanup`、`cleanup/expired`、`pipelines`、`maintenance/cleanup` | Admin 恢复走 stage checkpoint + 重新上传源文件；工件清理仅维护既有 owner，不代表存储已验收 |
| Public 导入 | `/api/v1/import/pipeline/upload`、`pipelines/{id}`、`pipelines/{id}/resume` | Public 上传复用 `start_import_pipeline`；Public 恢复重放 chunk，不是 Admin stage 恢复 |
| 后台任务 | v2 dispatcher 消费 `import_pipeline`、`image_pipeline`、`excel_pipeline`、`resume_pipeline`、`admin_resume`、`batch_image` | 每类 handler 在取得 staging 后先执行 fencing 检查，再进入对应执行入口；旧 handler 保留为兼容层 |
| OCR 执行 | `OcrRuntimeConfig` → `create_ocr_worker_client` → `local_process` / `paddlex_http` / `disabled` | 这是 OCRGateway 按配置创建的执行后端，不属于内部租约 worker API |
| 内部 OCR worker | `/api/internal/ocr-worker/jobs/*` | 独立 `WorkerAPIClient` + daemon 轮询/租约/心跳协议；当前 8 个路由均要求 worker 凭据 |
| 统一编排 | `pipeline_coordinator_entry.run_pipeline` | 环境默认 `shadow`：旧 orchestrator 执行，coordinator 仅计划；`coordinator` 模式仍是未完成实现，不能当作已完成替代 |

当前小程序 538 个第一方源文件的既有映射哈希核对未漂移，未发现对 Public 导入 API 的直接静态消费。该结论不是外部调用不存在或接口可删除的证据。

## 职责与停止条件

- `pipeline_definition.py` 是 27 阶段唯一元数据来源；single-pass、chunked、恢复、冻结、工件和图片生命周期均有已提交兼容文档。后续不得因 `pipeline_orchestrator.py` 仍长而重拆已收口链路。
- Admin 恢复仅允许 failed/interrupted；读取 stage checkpoint 和 artifact 清单后重新暂存文件并入队，队列拒绝返回 503 并将 store 置 failed。Public 恢复重放 pending chunks 并维护共享 hash/水印语义，两者不得合并。
- v2 handler 的 fencing 位置保持：先解析 staging，再校验 fence/cancel，最后执行业务。Excel handler 额外读取文件内容；图片和批量图片 handler 对缺失 staging 抛错。
- OCR 执行后端必须保持配置语义：`paddlex_http` 不回退本地 CPU；`disabled` 返回 None；未知后端抛错。内部 OCR worker API 则持有 job claim/lease/heartbeat/start/complete/fail/release 协议。
- `coordinator` 模式中 Correction、Validation、Persistence 仍返回 `NOT_IMPLEMENTED`，DocumentStructure/DomainParsing/Review 为部分实现。没有影子运行对比或替换授权，不得把该路径作为默认结构治理目标。

## 新登记缺陷

`OCR-04 DEFECT`：`ocr_worker/daemon.py` 的 `_upload_artifact` 会向 `POST /api/internal/ocr-worker/artifacts/upload` 流式提交结果，但当前 `api_router` 冷注册的 376 个 operation 中没有该路径；隔离 ASGI 探针返回 404。此为仓库当前契约缺口，未验证真实部署是否由反向代理或其他服务承接，也未证明生产影响。修复须另行授权，并覆盖鉴权、流式 hex-JSON、大小限制、重复上传、失败/取消与 worker 等待语义。

2026-10-31 已修复：新增 `POST /api/internal/ocr-worker/artifacts/upload`（`api/internal/ocr_worker.py`）与 `services/ocr_artifact_service.py`。路由沿用 `Worker-API-Key` 鉴权；请求体按 daemon 的 hex-JSON 格式增量解码到同目录临时文件，边写边算 SHA-256，与声明值一致才 fsync 并原子替换到 `<OCR_WORKER_ARTIFACT_DIR>/ocr-results/<job_id>/document.ir.json`（空则为 `<STAGING_STORAGE_DIR>/worker-artifacts`）。约束：`job_id` 须为 32 位小写十六进制且 `key` 必须等于该作业自己的键（拒绝路径穿越）；作业须处于 running/uploading 且 `lease_owner` 等于当前 worker（未知 404、状态不符 409、属主不符 403）；completed 作业只接受与已记录 `output_sha256` 相同的内容；未完成作业重复上传以最后一次成功为准；声明长度或解码字节超过 `OCR_WORKER_ARTIFACT_MAX_BYTES`（默认 64MiB，请求体上限为其两倍加头部）返回 413；SHA 不符 422，格式/截断/奇数长度十六进制 400，存储目录不可用 503；连接中断或任一失败都会删除临时文件，不留半成品。worker 的 `complete` 在上传响应之后发起，因此“等待”语义由响应时机保证。授权还要求租约未过期（请求体不带 lease token，只能以 `lease_owner` 加过期时间判断）；流式接收期间租约可能丢失或作业被取消，所以在原子替换前会重新读取作业并再次授权，失败则不发布。校验读取后立即回滚以释放连接，fsync 与替换放入线程执行，写盘/替换的 `OSError` 映射为 503，目录与文件权限为 0750/0640。2026-10-31 安全审计修复：HTTP `POST /jobs/{job_id}/complete` 现经 `complete_job(verify_artifact=True)` 在租约校验后、状态迁移前核对上传结果：`output_artifact_key` 必须等于该作业的规范键，存储文件须存在（非符号链接）、不超过 `OCR_WORKER_ARTIFACT_MAX_BYTES`、SHA-256 与 `output_sha256` 一致且内容为 JSON 对象，任一不符返回 409 且作业保持未完成（可重试）；服务层默认不校验以保持既有调用兼容。限制：校验与替换之间仍有极小窗口，且无跨进程文件锁；（2026-10-31 审计修复）上传在发布前统计已存产物总量（不含本作业旧副本），超过 `OCR_WORKER_ARTIFACT_TOTAL_MAX_BYTES`（默认 2GiB）返回 507 且不发布；`staging_cleanup` 定时任务同时调用 `cleanup_expired_artifacts`，删除超过 `STAGING_RETENTION_SEC` 的产物和超过 1 小时的临时文件并回收空目录（completed 作业校验后无读取方）；配额检查与原子替换在同一个跨进程 `flock`（`<产物目录>/.quota.lock`）临界区内完成，并发上传不会合计超限（统计为逐次遍历目录，量大时持锁时间随文件数增长）；请求体最大约为 `OCR_WORKER_ARTIFACT_MAX_BYTES` 的两倍，反向代理（如 nginx 默认 1MB）若未放宽会先于本接口拒绝，需随部署配置核对；真实 worker 与 PostgreSQL 行为未验证，归 ENV。

## 下一步

1. OCR-02：以诊断/工件/恢复/后台编排的现有兼容文档和调用链为输入，逐项给出 `DONE`/`RETAIN`/`DEFECT`/`ENV-BLOCKED`，不为长度新开拆分。
2. OCR-03：处理上传准入、Public/Admin 恢复、批量图片和 worker 接口的剩余结构条目；`OCR-04` 单独等待修复授权。
3. SHR-01..03：在 OCR 结构条目终态后继续共享队列、运行时生命周期和旧门禁治理。

真实外部 OCR、PG/Redis、多 worker、备份恢复和生产操作均不在本映射中执行，继续归 ENV-04..06；生产最后且另行授权。
