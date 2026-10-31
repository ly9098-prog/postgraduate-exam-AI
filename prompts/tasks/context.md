# 重构与最终环境验收交接摘要

更新：2026-11-01（Asia/Shanghai）。最新验收证据基线为 `307a8df9`（该证据提交时本地 `origin/main` 引用 ahead 7，未推送）；整体ENV-BLOCKED（最终验收未完成），代码已达到继续隔离验收标准；当前轮专用合成身份/角色续验及清理完成，并复核ENV-02/03/05既有证据与当前源码一致。最终门禁未全关。旧交接快照保留；修复快照在 `~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/before/`。

## 当前任务与授权

- 用户要求修复小程序报错、操控微信开发者工具验收刷题/错题链路，并继续ENV-01..06；生产明确参考 `docs/project/DEPLOY_PLAN.md`。
- 有限结构条目已经终态，§336六项业务缺陷与§337–340安全/部署历史保留。入口：`current_task.md` → `current_task/closure-ledger.md`，不再无界拆分。
- 2026-11-01用户授权“修复这些发现的问题”：本批修复Admin登录成功、单题审核通过审计及上传阶段取消/迟响应归属；使用原合成验收数据库的独立副本验证。未授权或执行生产部署、迁移、重启、恢复或回滚，后续已按用户明确要求完成4个本地提交，未推送或上传小程序。
- 用户已授权自行创建测试身份/角色并在验收后删除，§349已落实；不再将创建合成身份的权限当阻塞。2026-10-31目标blocked审计保留为历史；真实微信交换/真机、外部能力和生产前置仍缺。完整ENV目标未完成，不用隔离检查替代其余门禁。

## 已完成

- §350：重核ENV-01前置：WeChat MCP可用，账号有3个AppID（2个名称有测试标记），当前验收项目匹配未标记为测试的应用；测试号列表0，本轮未查/设ticket，也未触发provider wx.login。已有合成用户身份已按§349删除。ENV-02源码哈希与隔离API/浏览器报告匹配；ENV-03迁移8/PG-Redis22/番茄钟PG并发6、ENV-05 fencing29/Redis恢复6/队列硬化23/worker恢复2的存档JUnit报告全零失败/跳过，PG/Redis恢复与worker投影证据PASS。只是复核且未重跑；阶段仍是ENV-02/03/05 PASS-ISOLATED，ENV-01 PARTIAL，最终门禁未全关。规划与结构化审计记录在§14和 `acceptance-owned-identities-2026-11-01.json`。
- §349：新合成副本创建3个管理账号、2个自定义角色、2个开发学习用户；真实API验证RBAC、同会话授权/撤权、跨JWT域拒绝及停用后旧令牌/新登录401。微信模拟器完成2题1对1错、错题详情/掌握/取消，另一用户读写该错题404；自由计时completed68秒/暂停14秒，退出后两域学习令牌均失效。旧运行时请求失败在restore mock+重编译后排除，仅计成功链路；本次直接调用endSession，不新增结束确认声明。清理15表34条新增行，79表逐行/计数与基线相同，旧副本SHA不变；恢复原11项模拟器存储、删除本轮凭据、停API。另核验DevTools测试号账户列表为0，故真实身份交换仍待验。结果 `acceptance-owned-identities-2026-11-01.json`，记录提交 `7f6cd4cb`、账号可用性记录 `b643465f`；无业务源码变更或生产操作。
- §348：用户授权本地提交并继续修复准入缺口；旧统计脚本改跑当前职责行为门禁，外层31/内部206项全通过、0跳过，新增真实提交适配器联通与进程内变异校验。独立审查唯一回滚疑点经真实依赖/flush后提交故障验证关闭（1项通过），未改业务源；4个显式范围提交完成（小程序239dc7f9、Admin9087adf3、PG夹具432d9125、验收记录1315986c）。达到继续隔离验收的代码标准；环境条件继续见阶段表。结果 `docs/architecture/refactor-results/acceptance-commit-readiness-2026-11-01.json`。

- §347：登录成功写system.login(low)，单题导入审核写import.approve(important)，均与业务更新同事务；审计存储失败回滚、失败登录/失败发布/重复审核不写成功审计。新增上传阶段“取消上传”，在请求await后/SSE回调/watchdog创建前校验当前批次。先RED后GREEN：后端新增6项4失败、前端21项3失败；修复后API41/服务85、固定静态8336/readiness69、管理端150文件1869项/typecheck/lint/build及生成OpenAPI合约通过。真实隔离API验证两类成功审计，实际发布未mock；Chromium1440/390px取消按钮、原生EOF/ERR_ABORTED及new.png/4题新批次通过。网关任务响应不是外部OCR证明。结果 `docs/architecture/refactor-results/env02-defect-fixes-2026-11-01.json`。
- §341：删除 `pomodoro-task-types.js` 九个重复函数声明；刷题科目加载器显式传入已导入的 `filter408SubjectTree`。严格语法/真实Page连接回归先RED后GREEN；同步精确模板与拒绝错误简写门禁。
- §342：修复用户报错 `options.maxMs is not a function`，仅把 `buildFreeTimerLimitPageCapabilities.maxMs` 改为 `() => FREE_TIMER_MAX_MS`；其余数字上限契约不变。三个适配器/控制器连接回归RED→GREEN，定向79项、番茄钟137个Node脚本、540个运行时JS严格解析通过。2026-10-31旧 `scripts/test-pomodoro-practice-stats.js` 曾29通过/12源码断言失败；已由§348修复，不宣称全仓CI通过。
- §346续接收尾：四个番茄钟测试文件26项通过、0失败/跳过；三份业务修复在WSL/Windows原项目/隔离副本SHA一致。现有微信工具只读缓存未命中目标异常，当前仍在刷题结果页；没有重启隔离API或新跑番茄钟端到端。ENV-02具体边界为 `admin_auth.login` 成功提交、`admin_imports.approve_import_question_item` 与 `admin_import_service.approve_import_question`；现有 `write_admin_audit` 不自行提交，后续修复须验证同事务语义。本次未改Admin业务，不将单题审核缺口泛化到其他审核；证据 `pomodoro-followup-closeout/`。
- 原Windows项目与隔离验收副本只同步三个业务文件，最终SHA256与WSL一致；原项目 `LOCAL_DEBUG=false`，验收副本true。实际验收项目 `D:\workspace\postgraduate-ai-acceptance-20261031\miniprogram`，工具2.02.2607271/SDK3.10.3，开发登录，API8000/SQLite。
- 模拟器刷题→错题→复习、自由计时启动/暂停/继续、离开返回、运行/暂停会话重编译恢复、结束确认/取消完成、API超时后本地补偿均通过。五小时为调整合成起始时间的边界加速，非连续五小时或真机。
- §343/§344：补齐多空题完整作答（空1=A、空2=B，落库 `1:A;2:B`）和服务端已提交200但响应丢失后的同request_id/同请求体重试。部分多空题探索交卷曾产生0答题完成会话，按未答统计，不将单选全未答阻止泛化到该场景。最终SQLite：8答题/6会话/3错题，1复习会话/1记录，3个已完成番茄钟，8条outbox仍pending。
- 2026-10-31 Admin浏览器检查点：Chromium155.0.8059.12，三种合成角色登录、管理员/角色接口200或403和受限菜单通过。受控首轮2个并发401只产生1个refresh200，重试均200。当时登录和人工审核无审计，初查audit_logs只有system.init_super_admin；后续角色变更另有三条审计。原失败证据保留，缺陷已由§347修复。
- §344续验：真实Admin API创建合成管理员、user→admin并停用，audit_logs出现admin_user.create/update/delete，角色变更审计通过。批量图片页曾在上传阶段无可见停止按钮；上传完成后挂起旧status/SSE，重置并发起新批次，旧status/SSE均net::ERR_ABORTED，晚到old.png/77题/OLD_STALE_EVENT未进入新任务，new.png/4题/新事件正确显示。路由拦截观察旧status/SSE断开；另经原生8002 HTTP网关在reset时观察到旧status/SSE EOF、离开页面时upload EOF。当时上传阶段无可见取消控件的交互缺口已由§347修复。
- 真实隔离PG15.19/pgvector0.8.7和Redis7.2.5：空库迁移8、PG/Redis集成22项均0失败0跳过。current=head=`v19_pomodoro_subject_allocations`，并发提交/幂等冲突、事务/outbox回滚、番茄钟advisory/行锁、缓存失效及Redis崩溃恢复通过。仅修番茄钟测试夹具的异步fixture/V19表/合法科目/UTC时间，未改后端业务。
- 两域真实刷新轮换：未修改FastAPI ASGI接口+PG/Redis，每域同token并发8次，1个200/7个401，旧token重放401、后继token200；用户token共3枚/1枚有效。不是初始微信登录/HTTPS验收。
- ENV-05：队列/PG围栏29、Redis真实崩溃6、队列硬化23、真实worker进程恢复2项通过。SIGTERM排空；SIGKILL后等待默认约600秒租约接管，旧owner操作拒绝。两个worker_main+一个scheduler_main分别领取2条answer_projection任务，outbox均published、队列completed、学习投影收敛，三进程退出0；不是SQLite那8条outbox的消费证据。
- 隔离备份恢复：PG合成源2答题/2pending outbox，pg_dump快照→新库恢复，81表逐表哈希、70序列、迁移/pgvector一致。323约束/385索引只窄规范化等价数组cast；12CHECK/1部分索引另验允许值/非法值/NULL判定一致。Redis真实enqueue_v2→SAVE/RDB→新进程，key类型/值哈希/TTL/两任务状态一致。不是生产或跨存储原子时间点恢复。

## 验收状态与剩余

| 阶段 | 状态 | 剩余 |
| --- | --- | --- |
| ENV-01 | PARTIAL | 专用微信身份、测试HTTPS、真机与真实移动网络；复核部分多空题交卷提示（工具登录未确认是测试身份，未交换openid） |
| ENV-02 | PASS-ISOLATED | 2026-11-01已修复并验证已发现缺陷；真实外部OCR/HTTPS及前序最终门禁未由此关闭；批次/拒绝等审计未由单题证据覆盖 |
| ENV-03 | PASS-ISOLATED | 限定隔离技术检查通过；仍受前序最终门禁约束 |
| ENV-04 | BLOCKED | 实测启用AI配置0、OCR8080不可达、测试存储变量为空，缺受控AI/OCR、存储、HTTPS/WS网关 |
| ENV-05 | PASS-ISOLATED | 限定隔离技术检查通过；仍受前序最终门禁约束 |
| ENV-06 | BLOCKED | 公网TLS/live/首页只读通过、ready403；前序未全关，缺生产窗口/凭据/有效备份和回滚制品 |

`PASS-ISOLATED`不是按顺序关闭所有最终门禁，也不授权生产。生产匿名live200/dashboard200/users-me403只是先前本轮公网预检，未重新核对完整生产镜像/ready/业务。现有部署≠最终验收通过。

## 证据与运行资源

- [验收规划与执行记录](../../docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md)，[结构化结果](../../docs/architecture/refactor-results/miniprogram-environment-acceptance-2026-10-31.json)。持久证据根：`~/.cache/postgraduate-ai/acceptance/2026-10-31/`。
- 重点：`learning-database-final.json`、`practice-response-loss.json`、`admin-concurrent-refresh.json`、`env02-import-reset-ownership-summary.json`、`env02-role-change-audit.json`、`env-integration-suite-summary.json`、`env03-refresh-token-rotation.json`、`env03-env05-backup-restore.json`、`env05-redis-backup-restore.json`、`env05-multiprocess-outbox-scheduler.json`。
- 33份原/tmp的worker/queue证据与日志已归档到 `owned-runtime-artifacts/`，附哈希清单；六份复现脚本归档到 `harnesses/`；`backups/`保留PG dump、RDB和SQLite备份，目录700/文件600，不能提交。此前备份/浏览器探针失败已保留并排除，不覆盖成通过。
- 初查无Docker/psql后，续验已在证据目录解包PG15/pgvector，实际使用5433和6380；不要复用旧“未执行PG”结论。当前临时服务的最终关闭情况以结构化结果 `runtime_cleanup` 为准；恢复前核查端口/PID。
- 私密合成身份文件 `/tmp/postgraduate-wechat-acceptance/runtime/admin-test-identities.json`（600）及浏览器state不可打印/提交。刷新失败退登录、角色审计、原生socket取消均已验；API/Admin/8002网关已停止，3000/8000/8002不监听。ENV-04实测无启用AI、OCR8080不可达、无测试存储；ENV-06公网只读live200/首页200/ready403，TLS约80天，均不能关闭阶段。
- 2026-11-01复验证据根 `~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/`；新副本 `/tmp/postgraduate-env02-fixes-20261101/acceptance.db`，不与原SQLite计数混算。临时服务启动/关闭见该目录runtime.json；不输出或提交合成身份、令牌和运行日志。旧公网基线仅为2026-10-31记录，本批未复查生产。
- 专用身份续验：`~/.cache/postgraduate-ai/acceptance/2026-11-01-identities/`，隔离副本 `/tmp/postgraduate-identity-acceptance-20261101/acceptance.db` 已清除本轮新增身份/记录并恢复基线行集。`cleanup-verification.json`、`learning-ownership.json`、`identity-rbac.json`及6份无凭据复现脚本保留；私密身份清单/模拟器存储备份已删除，8000关闭，不混用其他副本计数。

## 下一步与保护

- 优先解决ENV-01专用身份/HTTPS/真机与ENV-04受控外部能力，再进入ENV-06。ENV-02已发现缺陷已获授权修复，生产最后处理，先核查DEPLOY_PLAN与实际配置、窗口、有效备份/回滚制品；本轮隔离恢复不是生产备份。
- 生产update-all不含worker；新迁移先build后用新镜像run；nginx文件bind mount换inode需force-recreate。匹配生产记录只用sync_uuid，不按本地numeric id修改生产。
- 保留已有文档、删除和未跟踪内容；`backend/service_compatibility.py`是无关诊断文本，不lint/提交。只允许显式路径暂存，禁止add-A/amend/reset/checkout。§350后当前卷46节、四卷共344条记录；ENV阶段不变。代码自审及独立审查完成、零未解决发现；本次仅证据复核和文档更新，不重跑套件或重复独立代码审查。本轮提交数量以最终git日志为准，未推送/部署或写系统记忆。任务交接分卷的既有重组保持未暂存。
- 代码图谱通过本地stdio可用，project `home-lmh-projects-postgraduate-ai`，generation `2026-10-31T09:32:18Z`，68045节点/236032边；相关刷新/队列/import/client路径已核对，无已记录缺口且metadata_match，非完整性证明。Graphify缺graph.json，显式文档读取作为回退。
