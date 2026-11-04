# OCR-02 诊断、工件与后台编排保留评估

2026-10-31，OCR-02 结构收口评估。本评估依据 §332 的39个后端源映射、既有专项兼容文档、当前源码哈希和本批定向测试，未修改运行时/测试/CI。结论只覆盖 `OCR_CONSUMER_MAP.md` 登记的 OCR-02 子域，不代表 OCR-03 接口结构、OCR-04 契约缺口或真实环境验收。

## 收口结论

`OCR-02 RETAIN`：诊断、工件/检查点和后台编排已有明确 owner 与本地契约；未发现需要因结构继续拆分的已登记缺陷。`pipeline_orchestrator.py` 当前4003行不是继续拆分理由；single-pass、chunked、resume、工件和后台执行入口已经由独立模块与架构门禁约束。真实外部 OCR/AI、Redis 检查点、多 worker 并发和大文件内存行为归最终环境验收。

## 子域处置

| 子域 | 现有结构证据 | 处置 |
| --- | --- | --- |
| 27阶段元数据 | `pipeline_definition.py` 是唯一阶段顺序/元数据来源，18项直接契约覆盖阶段快照、可恢复工件、业务域和 runner 入口 | `RETAIN` |
| single-pass | `pipeline_single_pass_*` 分离输入、状态、循环、checkpoint、执行和结果；入口保留原19个 keyword-only 参数，49项直接契约通过 | `RETAIN` |
| chunked | `pipeline_chunked_*` 分离初始化、独立会话执行、聚合与终态；77项直接契约通过，隔离 SQLite 恢复用例保留 | `RETAIN` |
| resume | `pipeline_resume_*` 分离查询/科目恢复、上下文、重放和最终状态；61项直接契约覆盖调用顺序、水印、取消和失败 | `RETAIN` |
| 工件与版本兼容 | `pipeline_artifacts.py` 持有 schema v5、路径校验、版本拒绝和恢复；7项等价测试覆盖完整运行=恢复、后续阶段、版本不匹配与损坏工件 | `RETAIN` |
| stage checkpoint | `pipeline_checkpoint.py` 持有 single/chunked 检查点、失败记录和 Prune；12项兼容/基础测试通过 | `RETAIN` |
| 图片与通用后台 | `import_image_lifecycle` 组合 OCR/解析/成功持久化，`import_background_execution` 保留独立 session 与日志顺序；10项生命周期/后台契约通过 | `RETAIN` |
| worker v2 编排 | 六类 OCR 任务 handler 的 fencing/staging 顺序保持：`import_pipeline` 先 fence 后解析；`batch_image` 先 fence 后逐项解析；`image/excel/resume/admin_resume` 先解析后 fence；59项 handler/dispatcher 契约通过 | `RETAIN` |
| coordinator | 默认 `shadow`：旧 orchestrator 执行、coordinator 仅计划；`coordinator` 模式 Correction/Validation/Persistence `NOT_IMPLEMENTED`，DocumentStructure/DomainParsing/Review 部分 | `RETAIN`（未完成替代，不作为迁移目标） |
| 真实环境 | 真实 Redis TTL/恢复、外部 OCR/AI 失败、多 worker 竞争、大文件内存和生产部署未执行 | `ENV-BLOCKED`，归 `ENV-03..06` |

OCR-04 daemon artifact 上传路径未注册是独立契约缺口，继续由 `OCR-04 DEFECT` 承接，不因 OCR-02 保留而被覆盖或修复。

## 本批验证

- 源码哈希：11个文件与 §332 映射基线一致，8个 single/chunk/resume 细分模块为本轮新增独立基线；19个当前哈希全部记录在证据目录 `source-baseline.json`。`pipeline_orchestrator.py` 仍为4003行并保持 `ef01f909...`。
- 定向测试：`tests/pipeline` 及 checkpoint/artifact/single-pass/chunked/resume/background/image/worker-v2 相关选择集合，1078项通过；最终复验76.03秒（首轮81.69秒）。
- 静态检查：`ruff check app/ --ignore I001,F401,N818` 通过；`python -m compileall -q app` 通过；`git diff --check` 通过。
- 未重跑全量固定 CI/OpenAPI/readiness：本批无源码/测试/CI 变更，输入冻结不变；不宣称新全量结果。

完整命令、选择集合和结果见 [结果清单](refactor-results/ocr-background-retention-2026-10-31.json)。测试使用替身或隔离 SQLite，不证明真实外部 OCR、Redis、PostgreSQL、多 worker 或生产闭环。

2026-10-31 一次独立只读审查发现4项记录问题：worker fencing/staging顺序过度概括、源码基线覆盖扩大、pytest选择集合不可复现、库存文档混入错误相对链接。上述问题已修正并以相同选择集合复验1078项通过；独立窄复核确认P0–P3全部关闭且无新增问题。审查结果见证据目录 `review-result.json`。

## 停止条件

- 不再因 `pipeline_orchestrator.py` 长度或函数数量重拆 single-pass/chunked/resume/artifact/checkpoint/background/worker 已收口链路。
- 修改 OCR-02 子域必须绑定新的具体缺陷或消费者，并沿用对应兼容契约；不得重开无出口热点池。
- `coordinator` 模式仅保持现状。若要替换 legacy/shadow，需另行取得用户授权、补齐未实现阶段并给出影子对比与回滚证据。
- OCR-03 继续按上传准入、Public chunk 恢复、Admin stage 恢复、批量图片与 worker 协议处置；OCR-04 修复另行授权。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
