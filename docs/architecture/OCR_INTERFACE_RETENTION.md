# OCR-03 专用接口结构保留评估

2026-10-31，OCR-03 结构收口评估。范围来自 §332 有界映射：共享上传准入、Public chunk 恢复、Admin stage 恢复、批量图片、内部 OCR worker 协议及 v2 任务接口。本批未修改运行时/测试/CI；结论不代表 OCR-04 缺口已修复，也不证明真实 Admin/Public 请求、外部 OCR、存储、Redis、PostgreSQL 或生产闭环。

## 收口结论

`OCR-03 RETAIN`：路由层继续持有 HTTP/RBAC/响应协议，上传准入、恢复、批量图片和内部 worker 协议已有独立 owner 与本地契约。不因 `admin_imports.py` 2125行或 `batch_image_import_service.py` 1790行继续拆分；修改必须绑定具体缺陷、真实消费者或可测试性问题。真实环境行为归 `ENV-02..05`，`OCR-04` 保留独立 `DEFECT`。

## 子域处置

| 子域 | 现有结构证据 | 处置 |
| --- | --- | --- |
| 共享上传准入 | Admin/Public 上传共用 `start_import_pipeline`；顺序固定为 validate→admit→reserve→stage→status→queue，失败释放预约，入队拒绝先写 failed 再释放；31项准入契约通过 | `RETAIN` |
| Public chunk 恢复 | `imports.py` 校验创建者、paused/failed、PDF、页数与 SHA-256；读取 pending chunks 后暂存并投递 `resume_pipeline`，worker 重放 chunk；13项等价/幂等契约通过 | `RETAIN` |
| Admin stage 恢复 | `admin_imports.py` 读取 stage checkpoint/artifacts，重新上传源文件，恢复 options/subject/source 元数据，投递 `admin_resume`；队列拒绝时恢复 failed 状态；与 Public 恢复不合并 | `RETAIN` |
| 批量图片 | `batch_image_import_service.py` 持有 job/item/trace/SSE/汇总和执行 owner；路由负责一次 multipart 接收、准入与入队；16项优化/SSE契约通过 | `RETAIN` |
| 内部 OCR worker | `ocr_worker.py` 8路由统一 Worker-API-Key 鉴权，委托 `ocr_job_service`；claim/lease/heartbeat/start/complete/fail/release 状态机和幂等完成有39项服务/状态机契约 | `RETAIN` |
| v2 任务接口 | dispatcher 共9类任务，其中6类 OCR task handler（`import_pipeline`、`image_pipeline`、`excel_pipeline`、`resume_pipeline`、`admin_resume`、`batch_image`）已按类型保持 staging/fencing 顺序和参数装配；59项 handler/dispatcher 契约在 OCR-02 复验通过 | `RETAIN` |
| 真实环境 | 真实浏览器/JWT/RBAC、外部 OCR、对象存储、PostgreSQL并发、Redis队列和多worker未验证 | `ENV-BLOCKED`，归 `ENV-02..05` |

## 本批验证

- 源码哈希：20个 OCR-03 相关源文件与 §332 映射基线完全一致；无新增基线文件。
- 定向测试：16个选择文件，253项通过（51.61秒，1个既有 AsyncMock RuntimeWarning）。选择集合见证据目录 `pytest-selector.txt`。
- 静态检查：`ruff check app/ --ignore I001,F401,N818`、`python -m compileall -q app`、`git diff --check` 通过。
- 未重跑全量固定 CI/OpenAPI/readiness：本批无源码/测试/CI变更；不宣称新全量结果。

结果见 [结果清单](refactor-results/ocr-interface-retention-2026-10-31.json)。测试使用替身或隔离 SQLite，不证明真实浏览器、外部 OCR、存储、数据库、队列或生产行为。

## 停止条件

- 不因路由/服务文件长度继续拆分上传、恢复、批量图片或 worker 协议；后续修改须绑定具体缺陷或消费者。
- Public chunk 恢复与 Admin stage 恢复保持两条路径，不合并所有权或语义。
- OCR 执行后端与内部租约 worker API 保持两套边界；`OCR-04` artifact上传契约缺口不因本项关闭。
- 真实环境验收等待全部结构条目终态后执行，生产最后且另行授权。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
