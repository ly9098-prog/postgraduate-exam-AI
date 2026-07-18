# S0 问题修复评估报告

**审计来源：** `prompts/tasks/fix_task.md`（2026-07-16）  
**评估日期：** 2026-07-18  
**当前代码 SHA：** 当前 HEAD（包含 Sprint 4D 全部修改）  

## 总体结论

8 个 S0 问题中 **7 个已修复**，1 个（S0-04）为架构级重构，已在设计中但不在此次修复范围。

---

## 逐项评估

### S0-01：多页 OCR 异常分支引用未定义变量

**位置：** `app/services/ocr_executor_service.py:154-168, 277-293`

**状态：✅ 已修复**

`_ocr_one()` 闭包将 `idx` 作为参数显式传递，两种分支均返回 `(idx, text)` / `(idx, None)`，不存在 `UnboundLocalError` 风险。

---

### S0-02：超时任务永久占用 pending 计数

**位置：** `app/services/ocr_executor_service.py:349-358`

**状态：✅ 已修复**

`future.add_done_callback(_on_thread_done)` 统一释放信号量、移除 running、累计 completed，即使调用端超时也不影响底层线程释放容量。

---

### S0-03：执行器额外占用默认线程池线程

**位置：** `app/services/ocr_executor_service.py:309-311, 360`

**状态：✅ 已修复**

使用 `asyncio.wrap_future(future)` 代替 `loop.run_in_executor(None, future.result)`，不占用默认线程池。

---

### S0-04：统一 OCR 执行入口与代码现实不一致

**涉及文件：** 多处

**状态：⚠️ 架构设计中，部分已实现**

`OCRGateway`、`OCRCoordinator` 已创建为新统一入口，`_run_in_executor` 是内部实现。但 `pipeline_orchestrator.py` 中仍有多处直接调用旧 `ocr_service` 的路径。完整迁移需整个 Coordinator Pipeline 投产后才能移除旧路径。

---

### S0-05：已废弃函数存在必然 ImportError

**位置：** `app/features/exercise_region_detector.py:366`

**状态：✅ 已修复**

代码引用 `_ocr_inference_lock`（正确名称），不存在 `_ocr_lock` 的错误引用。

---

### S0-06：OCR 单例 reset 存在并发竞态

**位置：** `app/services/ocr_service.py:44-71, 107, 140`

**状态：✅ 已修复**

`_reset_ocr()` 实现完整状态机：UNINITIALIZED → RESETTING → UNINITIALIZED，持有 `_ocr_state_lock` + `_ocr_inference_lock` + `_ocr_init_lock` 三重锁。

---

### S0-07：断点恢复阶段顺序与真实 Pipeline 漂移

**位置：** `app/features/pipeline_artifacts.py:53-81`

**状态：✅ 已修复**

`CANONICAL_STAGE_ORDER` 已包含 `visual_region_detect`、`question_bbox`、`visual_region_assign`、`visual_region_crop` 全部阶段，并使用内容寻址指纹确保兼容性。

---

### S0-08：artifact 路径需要严格防穿越

**位置：** `app/features/pipeline_artifacts.py:171-179`

**状态：✅ 已修复**

`_validate_pipeline_id()` 使用正则 `^[A-Za-z0-9_-]+$` 校验 pipeline_id，拒绝任何包含 `..`、`/` 或其他特殊字符的输入。
