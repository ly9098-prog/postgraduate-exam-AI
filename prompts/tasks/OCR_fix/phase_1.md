你负责 OCR 整改 P1：建立唯一、可限流、可取消、可崩溃隔离的本地 OCR 执行边界。

### 当前问题

- 多个业务模块直接调用 `ocr_pages*`。
- `OCR_USE_PROCESS_POOL` 默认 false。
- `ProcessPoolExecutor.shutdown(wait=False)` 不等于杀死运行中 worker。
- executor process path 逐页串行，外层用默认线程池等待。
- `ocr_service.ocr_pages*` 自己向共享 thread pool 提交，造成边界混乱。
- Paddle 推理仍可能存在 Web 进程内运行路径。

### 目标架构

业务模块 -> `OCRGateway` -> LocalWorkerAdapter / RemoteAdapter  
LocalWorkerAdapter -> 有界 IPC 客户端 -> 独立 worker process/service -> 单页同步 engine

`ocr_engine` 只负责单页同步推理，不创建线程、进程、async task 或业务对象。

### 必做任务

1. 拆出纯同步单页 engine：
   - 输入：bytes + immutable runtime config。
   - 输出：包含 line text、polygon/bbox、confidence、transform、provenance 的结构对象。
   - 不吞异常，不返回“失败但看似空成功”。
2. 实现真正可终止的 worker：
   - 可选：长期 worker subprocess + pipe/socket；或独立 worker service。
   - 超时必须终止对应进程并等待回收。
   - 对 Python 版本支持 `terminate_workers/kill_workers` 时可使用；否则显式持有 Process 并 terminate/kill。
   - worker crash 后自动重建，旧任务明确失败，不重复完成。
3. 实现有界队列和完整生命周期指标：
   - accepted、queued、running、caller_timed_out、finished、failed、late_finished、crashed、restarted。
   - capacity 只能在底层 worker task 真正结束/被杀后释放。
4. 支持受控并行：
   - 单 GPU shard 一进程一模型。
   - CPU 可配置多个 worker，但必须避免每请求重复加载模型。
   - 批量页面可以并发提交，但返回结果按 page index 稳定排序。
5. 迁移所有调用方：
   - `pipeline_orchestrator`
   - `question_pipeline`
   - `question_import_writer`
   - `import_service`
   - image pipeline
   - exercise/region detector
   - 其他静态检查发现的调用方
6. `ocr_service.ocr_pages*` 只保留明确 deprecated compatibility wrapper，并内部调用 gateway/client；业务层禁止使用。
7. 合并配置：
   - `OcrRuntimeConfig` 必须实际被 gateway、worker、engine 使用。
   - 删除或降级重复配置来源。
   - 默认生产路径为 process-isolated；测试环境可使用 fake adapter。
8. shutdown：
   - 应用关闭时停止接单、等待/取消队列、终止 worker、清理共享内存和临时文件。

### 回归测试

- 单页异常保留页码和原始异常分类。
- 1,000 次 timeout 后 pending/running/capacity 全归零。
- 卡死函数被真实 kill，PID 消失。
- SIGSEGV/SIGKILL worker 不影响 API 进程。
- 重启后下一任务成功。
- 多页结果顺序稳定。
- 取消请求不泄漏 semaphore/lease/temp file。
- 静态架构测试证明业务层没有直接 engine import。

### 验收输出

- 执行架构图。
- worker 生命周期状态机。
- 关键测试命令与结果。
- 吞吐、内存和超时前后对比。
- 删除/保留的兼容 API 清单。