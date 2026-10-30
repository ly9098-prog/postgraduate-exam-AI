# Admin 导入审核与任务兼容基线

2026-10-30，§326，ADM-02，L2。有限范围为七个现有页面及31个静态消费契约；另12个已注册但无当前浏览器静态消费形状的接口保留。一次独立只读审查无P0–P3遗留，结构评估 RETAIN；本轮业务运行时保持。独立复验新增前端19项、两后端文件24项通过。完整调用位置和后端handler见[Admin消费者映射](ADMIN_CONSUMER_MAP.md)，本轮命令/输入基线及例外见[结果清单](refactor-results/admin-import-retention-2026-10-30.json)。

## 有限职责与停止条件

| 页面 | 既有权威职责及处置 |
| --- | --- |
| `/imports/batch-image`（批量图片） | 一个批次一次multipart上传；同一owner管理SSE去重、首轮状态同步、2500ms轮询、重置/卸载清理；纯统计/去重已有独立函数，保留 |
| `/imports/tasks`（任务上传） | CSV专用诊断与普通pipeline上传分流；任务状态/质量导航保留，页面只装配参数与展示 |
| `/imports/text-import`（文本导入） | 解析、暂存编辑、有效题目导入；LaTeX和结构校验使用已有纯工具，不提前发布正式题库 |
| `/imports/history`（历史批次） | 列表/详情读模型与显式发布/删除mutation保留 |
| `/imports/maintenance`（维护） | 告警投影及dry-run/确认后清理交互保留；本轮仅请求替身，未清理真实工件 |
| `/imports/questions`（题目列表） | review-queue与完整详情查询范围、只读展示保留 |
| `/imports/review`（导入审核） | query/filter/drawer/session/action/answer/complete/image hooks、reducer和展示组件已有职责，1018行页面组合不单独触发拆分 |

现有117个前端模块中72个是非测试源文件。后端继续由API持有RBAC、错误/响应及commit/rollback/幂等协议，admin_import_service持有审核、风险/视觉阻断、KP/来源和条目状态；发布、答案补录、上传准入、管线与批量图片执行复用各自既有owner。OCR执行/恢复和共享worker/队列的剩余结构范围仍归OCR-02/03、SHR-01/02，本条不提前关闭这些条目。

## 请求、状态与契约证据

- 新增19项契约调用六个真实页面函数，以隔离的state/ref/query/mutation/request/SSE端口和假时钟执行原闭包。批量图片覆盖单次上传、并发界限、终态清理、SSE去重/出错同步、watchdog、重置/卸载及一次总结失效；其余覆盖CSV/PDF、有效文本导入、历史发布/删除、维护dry-run和URL筛选。导入审核已有hook/reducer/组件契约随全套Vitest运行。
- 端口替身不挂载DOM，不模拟React调度；只有指定资源清理与总结effect被显式执行，不能据此声称所有effect、浏览器或原生fetch均已验证。初次加载因AuthStore隔离不完整失败（0用例），补齐mock后19项通过，业务未改。
- 管理端最终144文件1788项通过，其中本域46文件412项；typecheck通过、lint0错误/138警告，无运行时/构建配置变化未跑build。
- 后端首轮14文件168通过/1失败/9xfail；失败是共享SSE计数器已被前组累加，初始值测试误依赖进程顺序。仅把初始值断言改为独立执行模块定义；原live dict、共享引用和累计值保持。原顺序复跑169通过/9xfail/1既有warning；再补低风险计数刻画后，两份改动测试最终24通过。不能把这些结果写成一次170项完整组合运行。
- 1116运行时路径保持。§323固定CI473文件8155项按2244未变输入、两份不在固定命令内的测试窄复验复用；§321OpenAPI334快照同理复用，并非本轮新跑完整CI/冷schema。相同哈希字典只引用已提交的§325结果、selector及摘要，例外逐项写明。

## 已确认的既有缺陷 ADM-08

`approve_low_risk_questions` 在后项发布抛异常时，会扣减此前成功项的affected_count。真实服务入口刻画：第一项匹配已有正式题并置published/question_id31，第二项RuntimeError后回到pending；最终却返回affected_count0、skipped_count1。风险判定和publisher使用替身，未证明真实PG事务；此处确认的是原函数的计数逻辑。

2026-10-31 已修复计数：删除异常分支中的 `affected -= 1`，已成功项不再被后项异常扣减。`test_admin_import_service.py` 将上述刻画改为期望 `affected_count=1/skipped_count=1`，并新增 4 组顺序用例（全成功、异常在前后、成功后接 failed 返回与异常、异常后接 duplicate），旧代码上共 3 例失败（改期望的刻画用例加 2 组顺序用例；全成功与「异常在前」两组本就通过，只作为边界）。失败/异常项仍回到 pending、清空审核人与时间，状态码和响应结构不变。

事务边界未改：单项异常在函数内被吞掉，函数正常返回，`admin_imports.py` 端点仅在 `ValueError` 时回滚，其余无条件提交。因此 `publish_single_question` 中途异常留在会话里的部分写入（已 add/flush 的 Question 等）会随本次提交一并落库；修复前即如此，不是回归。本次未引入 savepoint，也未用真实 PG 验证，归 ENV-02..05。

## 最终环境验收补充

批量图片本地条件刻画：请求端口即使收到abort仍成功交付旧响应时，重置并启动job-2后，按相同seq会写入job-1的状态和题数。真实API客户端传递AbortSignal给fetch，但页面在await后不复核批次；当前证据不能证明原生fetch/body取消会产生这种交付时序，故不将此当作已确认线上缺陷。ENV-02必须记录真实重置/新任务与响应、取消、SSE/轮询的时序，再决定是否需要单独修复。

真实Admin会话/RBAC、PG锁与并发、Redis/SSE/worker、外部AI/OCR、存储和清理均未验收；旧batch-answer两个CLI脚本也未执行，不将服务替身视为端到端验收。全部结构工作处置后再按ENV表验收，生产最后且另行授权。
