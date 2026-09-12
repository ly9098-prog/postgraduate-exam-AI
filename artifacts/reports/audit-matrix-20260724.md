# 生产审计矩阵 — current_task.md 全量评估

> 生成日期：2026-07-24 | 仓库：2240AI 考研学习助手 | 分支：main

## P0 项

| # | 文档要求 | 当前状态 | 代码路径 | 生产风险 | 修复方案 | 测试 |
|---|---------|---------|---------|---------|---------|------|
| **P0-1** | DurableTaskQueue 状态机 — 原子 Lua 操作、owner fencing、dead-letter/TTL/查询/重试 | ✅ 已实现 | `app/services/task_queue_service.py` L114-376 (Lua scripts), L420-1250 (DurableTaskQueue) | 低 | Redis Hash + List/ZSET + Lua 脚本已完整。enqueue/claim/heartbeat/complete/fail_retry/fail_dead/reaper/retry_claim 全部原子化。 | 已有 `test_queue_metrics.py`, `test_queue_integration.py` |
| **P0-2** | OCR 云端隔离 — cloud_api 永不导入/执行本地 PaddleOCR | ✅ 已修复 | `app/services/ocr_service.py` L231-237 (_is_cloud_api), `app/features/ocr_gateway.py` L98-128 (constructor) | 低 | 已修复 _is_cloud_api() 枚举 vs 字符串比较 bug；OCRGateway 改用 DeploymentProfile 枚举；_check_ocr_no_local_deps 不再用 find_spec | `test_cloud_ocr_isolation.py`, `test_cloud_profile_no_paddle_import.py`, `test_cloud_gateway_e2e.py` |
| **P0-3** | 生产配置 fail-fast — 所有同步/异步校验异常抛 SystemError | ✅ 已修复 | `app/services/production_config_validator.py` L73-89 (_is_restricted_environment), L242-264 (_check_ocr_no_local_deps) | 低 | _is_restricted_environment 已 fail-closed；_check_ocr_no_local_deps 改用 sys.modules 检查；main.py 已修复 import sys 和 log_event | `test_config_validator.py` |
| **P0-4** | web/worker/scheduler 角色拆分 | ✅ 已实现 | `app/main.py` L84-270 (lifespan role-based startup) | 低 | web=HTTP+入队；worker=pipeline+OCR+AI+reaper；scheduler=番茄钟+audit cleanup+token cleanup | 角色拆分在 main.py 中正确隔离 |
| **P0-5** | ResourceGuard 原子准入 — 超限不修改计数 | ⚠️ 部分 | `app/core/resource_guard.py` L55-71 (Lua), L209-234 (_redis_acquire_sync) | 中 | Lua 已修复为原子 check-and-increment；但仍用同步 Redis client；缺少 `async with acquire_pipeline()` context manager；缺少 async 路径的 fail-closed | `test_resource_guard.py` |
| **P0-6** | Staging 生命周期绑定 durable task | ✅ 已实现 | `app/services/staging_storage.py` L1-80+ | 低 | SHA-256 内容寻址 + metadata sidecar + lease + TTL cleanup | `test_staging_storage.py` |
| **P0-7** | PDF 单页流式处理 — cloud 同时最多持有一页 | ✅ 已实现 | `app/services/pdf_renderer_service.py` (iter_pages), `app/features/pipeline_orchestrator.py` (_execute_chunk page_window) | 低 | AsyncIterator[RenderedPage]；cloud page_window=1；config.PDF_RENDER_PAGE_WINDOW | 隐式覆盖于 pipeline 测试中 |
| **P0-8** | Scheduler 分布式锁 — strict lock with owner token | ✅ 已修复 | `app/core/cache.py` (expire method), `app/services/pomodoro_scheduler_service.py` | 低 | cache.expire() 已添加；pomodoro scheduler 支持 lease 续租 | `test_cache_expire.py`, `test_scheduler_lock.py` |

## P1 项

| # | 文档要求 | 当前状态 | 代码路径 | 生产风险 | 修复方案 | 测试 |
|---|---------|---------|---------|---------|---------|------|
| **P1-1** | BackgroundTasks 和事件循环 — 删除 /tmp BackgroundTasks；offload PIL/fitz/openpyxl | ✅ 基本完成 | `app/services/storage_backend.py` (COS sync offload), `app/api/v1/imports.py` L142-165 (fitz+hashlib to_thread) | 低 | COS SDK 已 offload 到 executor；resume 路径的 fitz/hashlib 已 to_thread | 隐式覆盖 |
| **P1-2** | SSE — 有界队列、Redis Pub/Sub、断开检测 | ✅ 已实现 | `app/api/v1/admin_imports.py` (maxsize=100, disconnect check), `app/services/sse_pubsub.py` (shared Redis), `app/features/batch_image_import_service.py` (create_task) | 低 | 有界队列 + oldest-trace drop；last_event_id 跟踪；共享 Redis client | `test_features/test_sse_merge_terminal.py` |
| **P1-3** | Readiness — strict Redis PING, OCR config 检查 | ✅ 已实现 | `app/main.py` L610-700 (/health/ready, /health/live) | 低 | /health/live 仅存活检查；/health/ready 检查 PG/Redis/Alembic/staging/role/OCR/draining | `test_api/test_health.py` |
| **P1-4** | 数据库性能 — ORDER BY random() 修复 | ✅ 已修复 | `app/services/question_service.py`, `app/api/v1/formulas.py`, `app/services/practice_service.py` (KP fallback) | 低 | count+random offset 替代 ORDER BY random() | `test_services/test_sql_optimization.py` |
| **P1-5** | Prometheus 指标 | ❌ 未实现 | — | 低 | HTTP metrics、task queue metrics、OCR metrics 等未暴露 /metrics 端点 | 无 |
| **P1-6** | OCR client 增强 — batch_ocr、semaphore、jitter | ✅ 已实现 | `app/features/ocr_vl/paddleocr_vl_client.py` (batch_ocr, _jitter_delay, _acquire_semaphore) | 低 | asyncio.Semaphore + 指数退避 jitter + circuit breaker | `test_services/test_ocr_paddlex_http_client.py` |
| **P1-7** | EXPLAIN ANALYZE 输出 | ❌ 未执行 | — | 中 | 需要实际数据库环境执行并保存结果 | 无 |

## 文档输出项（第 7、9 节）

| # | 要求 | 状态 |
|---|------|------|
| 1 | 审计矩阵 | ✅ 本文档 |
| 2 | 修复后架构及不变量 | ⚠️ 待补充 |
| 3 | 实际修改文件清单 | ⚠️ 待补充 |
| 4 | 新增/修改环境变量 | ⚠️ 待补充 |
| 5 | Alembic migration | ❌ 待评估 |
| 6 | 完整测试执行结果 | ❌ 待运行 |
| 7 | 旧配置兼容 + 回滚方案 | ⚠️ 待补充 |
| 8 | web/worker/scheduler 部署步骤 | ❌ 待补充 |
| 9 | 压测方法和验收结论 | ❌ 待补充 |
| 10 | 仍未解决的风险 | ⚠️ 待补充 |

## 本次会话修复的关键 Bug

1. **`ocr_service._is_cloud_api()` 永远返回 False** — `DeploymentProfile` 枚举与字符串 `"cloud_api"` 比较恒 False，导致 cloud_api 所有 OCR 防护完全失效
2. **main.py 缺少 `import sys`** — 启动时 `sys.modules` 检查会引发 NameError
3. **main.py 缺少 `log_event` 导入** — staging sweep 日志记录会引发 NameError
4. **ResourceGuard `_LUA_ACQUIRE_SEM` 原子性缺陷** — 先 INCR 后检查容量，并发可全部超限
5. **`_check_ocr_no_local_deps` 使用 `find_spec`** — 违反 P0-3 硬约束
6. **`_is_restricted_environment` fail-open** — 异常时返回 False 跳过所有生产检查
7. **OCRGateway profile 使用字符串比较** — 非枚举比较，类型不安全
