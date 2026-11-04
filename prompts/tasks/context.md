# 当前任务与历史验收交接

## 2026-11-05 当前任务：冷启动会话还原

- 以 `prompts/tasks/current_task.md` 的新任务为准；旧 Obsidian 链接任务已结束，本轮不再继续复核旧任务。
- 已实现默认冷启动在登录后依次解析待确认刷题提交、单槽刷题/复习标记、番茄钟，直接 reLaunch；热启动和显式目标保持原入口。
- 新模块：`miniprogram/utils/launch-session-store.js`、`launch-resume.js`、practice `utils/cold-resume-controller.js`、review-today `utils/review-active-state.js`；页面冻结字面量、app.js/home.js 未改。
- 完成作答/切题/onHide 快照、交卷接管/退出清除、复习阶段标记与用户归属检查。自动鉴权失效保留恢复状态，显式登出清除。番茄钟快照写入附加 ownerId。
- 最终本地回归：新增 36 项定向测试通过，全量 `node --test tests/test-*.js` 2597/2597 通过，受影响相邻 50 项、渲染 fixture 5/31、架构守卫、包体/媒体预算通过；新增测试已登记 reliability。`scripts/test-*.js` 25/28，3 个失败在未修改 HEAD 基线同样失败。
- 单会话审查发现并已修复两项 P2：其他账号保留下来的番茄钟快照会被旧页面入口恢复；刷题冷恢复后科目树为空。均有先失败后通过的回归和归属/科目加载修复。
- 文档：`docs/frontend/LAUNCH_RESUME.md`，包含本地边界和完整手工清单。尚未做微信编译、模拟器、真机、原生返回按钮及编译包扫描；未提交、推送、部署或同步 Windows 镜像。
- 保留本轮开始前的所有无关修改、删除与未跟踪文件。实施计划 `prompts/tasks/launch-resume-plan.md`；本地验证输出 `/tmp/postgraduate-launch-resume-20261105/`（临时证据，不提交）。

## 历史重构与最终环境验收摘要

更新：2026-11-02（Asia/Shanghai）。最新验收证据基线为 `307a8df9`（该证据提交时本地 `origin/main` 引用 ahead 7，未推送）；整体ENV-BLOCKED（最终验收未完成），代码已达到继续隔离验收标准；当前轮专用合成身份/角色续验及清理完成，并复核ENV-02/03/05既有证据与当前源码一致。最终门禁未全关。旧交接快照保留；修复快照在 `~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/before/`。

## 历史任务与授权（2026-11-02 及以前）

- 当时请求：按 `docs/development/` 复核 §358 新代码的内聚性与耦合性，不符则修复、提交并部署。§359完成本轮职责拆分、异常边界及前端刷新修复，代码已提交 `9742993a`，后端于 2026-11-02 03:17 部署完成；微信端由用户手动发布。
- 上一请求：首页四科掌握概览四张卡全部显示无数据；§357已定位并修复成长快照应用链回归，微信工具编译/模拟器/真机仍待验。
- 用户要求修复小程序报错、操控微信开发者工具验收刷题/错题链路，并继续ENV-01..06；生产明确参考 `docs/project/DEPLOY_PLAN.md`。
- 有限结构条目已经终态，§336六项业务缺陷与§337–340安全/部署历史保留。入口：`current_task.md` → `current_task/closure-ledger.md`，不再无界拆分。
- 2026-11-01用户授权“修复这些发现的问题”：§347修复Admin登录成功、单题审核通过审计及上传阶段取消/迟响应归属；使用原合成验收数据库的独立副本验证。该批当时未授权或执行生产操作，后续按用户明确要求完成4个本地提交，未推送或上传小程序。
- §352用户先明确授权生产空表删除，随后要求回滚；17表已从本轮新备份恢复并完成验证。该次授权不延伸为后续任意删表或部署授权，详细记录见 `docs/project/PRODUCTION_TABLE_ROLLBACK_2026-11-01.md`。
- 用户已授权自行创建测试身份/角色并在验收后删除，§349已落实；不再将创建合成身份的权限当阻塞。2026-10-31目标blocked审计保留为历史；真实微信交换/真机、外部能力和生产前置仍缺。完整ENV目标未完成，不用隔离检查替代其余门禁。

## 已完成

- §359：完成 development 内聚/耦合复核和修复。Admin CRUD 882→626 行，连接诊断独立325行；共享探测/URL校验/额度标记，公开候选入口，提交后探测best-effort且记录异常，模型不存在共享冷却，准备对象不可变替换。前端只更新可用性字段，结构化失败去重、普通失败刷新，静默检查持续重试直到恢复；保留JSON格式错误分类。后端1435项/小程序2564项/fixture5/31通过，Ruff正确性及债务不增、format、compileall、YAML和边界通过。代码提交 `9742993a`；2026-11-02 03:17（Asia/Shanghai）部署 app/worker/scheduler，18份源码逐容器匹配、重启/启动错误0，内部ready200、公网健康200，81表/71序列/384索引/V19及保护服务配置不变。服务器备份 `/data/backups/ai_health_review_20261102T030950`，详见[部署记录](../../docs/project/PRODUCTION_AI_MODEL_HEALTH_REVIEW_DEPLOY_2026-11-02.md)。未调用真实模型、未改模型配置、未推送；微信端手动发布和真实设备验收仍待完成，既有长文件/长函数不宣称全量合规。

- §358：错题详情 AI 可用性问题按用户确认的探测方案完成：按 `model_config_id + config_fingerprint` 将真实模型探测结果写入 Redis，成功共享 30 秒，临时故障 `30/60/120/300` 秒退避，额度/鉴权/模型不存在冷却 5 分钟；健康备用模型继续可用。首次分析、重新生成和 AI 老师通过同一门禁，已有分析/老师结果/题库解析保留；老师禁用返回 HTTP 503 结构化原因并直接展示在面板。管理员保存相关配置会强制重探，只有与已保存配置完全匹配的测试连接才能解锁。小程序加载/`onShow` 检查可用性，检查动画上限 5 秒，后端 `checking` 按 2 秒重试；明确 HTTP 失败不再进入旧恢复轮询。后端 AI 回归 1083 项、小程序全量 2557 项、5 个渲染 fixture 31 项通过，Ruff（项目登记的 I001/F401/N818 债务除外）、compileall/diff-check 通过；formatter 仅报告 `ai_service.py` 既有空行差异，未在部署后改写该文件以保持源码 SHA 一致。已部署 app/worker/scheduler 三个后端角色（23:38，Asia/Shanghai），运行源码 SHA 一致、重启 0、启动错误匹配 0，内部 ready 200、公网 live/health/login 200；81 表/71 序列/384 索引及 V19 迁移未变，Admin/PG/Redis/nginx 未重建。服务器证据 `/data/backups/wrong_detail_ai_availability_20261101T231332`，详见[部署记录](../../docs/project/PRODUCTION_AI_ANALYSIS_AVAILABILITY_DEPLOY_2026-11-01.md)和[结构化结果](../../docs/architecture/refactor-results/wrong-detail-ai-availability-2026-11-01.json)。未调用真实生产模型、未修改 Admin 模型配置；此前 403 仍可能需核对凭据/Base URL/权限，微信工具/真机与完整 ENV 验收未完成。
- §357：首页四科掌握概览全空定位到`12d1968e`拆分回归。`loadGrowthSnapshot()`成功/异常守卫均写反，成功响应也不进入`_applyGrowthResponses()`；`_buildGrowthContext()`漏传`plan`并引用未声明变量，`ReferenceError`又被反向守卫静默吞掉。现已恢复“仅过期返回”并显式传入`plan`；接口协议、统计查询和掌握度映射未改。按编码规范将成长请求、掌握度、展示投影、快照编排、动画和页面控制下沉为6个`pages/home/utils/growth-*.js`模块，原画布方法下沉到`home-canvas.js`，四接口改用命名响应，`home.js`由1450行降至793行并纳入800行中央预算。先RED后GREEN，新测试7项通过并加入reliability固定清单，页面预算3项、408集成、v6 UI、Study UI、API客户端14项、存储边界14项、包体/媒体预算、主包体积及Node语法通过。见[结果](../../docs/architecture/refactor-results/home-mastery-growth-load-fix-2026-11-01.json)和[缺陷记录](../../docs/project/BUGS_HISTORY.md)。未做微信工具编译/模拟器/真机，未提交/推送/部署，ENV状态不变。
- §356：2026-11-01 20:41:35按用户明确授权部署一个后端运行文件，app/worker/scheduler新镜像及运行源码SHA一致；三个角色重启0/启动错误匹配0、内部ready200、app健康，公网live/health/首页/login200。首轮探针漏带生产Host误判400并回滚，补齐Host后重试成功；保留原日志，不放宽可信主机校验。81表名称/schema/OID及完整schema不变，V19未迁移，PG/Redis/nginx/Admin容器及配置不变；当前PG/RDB备份、旧源码及三个回滚镜像保留。见[AI后端部署记录](../../docs/project/PRODUCTION_AI_ANALYSIS_DEPLOY_2026-11-01.md)和[结构化结果](../../docs/architecture/refactor-results/wrong-detail-ai-production-deploy-2026-11-01.json)。微信由用户手动发布，真实模型403尚未解决，ENV状态不变。
- §355：模型277 ms返回403且无备用模型后，失败字典被当作成功结果复核导致500；小程序又对该明确失败入队并轮询，44次间隔共180秒。现后端直返完整失败/缓存保留响应，首次生成和重新生成仅对网络响应丢失或408/502/504恢复，明确HTTP失败立即结束加载并保留旧解析。599项后端、174项错题详情Node、43项渲染不变性及31项fixture回归通过，严格Ruff/format/compileall通过；自审完成，独立审查、真实模型、微信工具编译/真机未执行。源码基线`3f25d7fc`，新修改未提交；后端后续按§356部署，结果`docs/architecture/refactor-results/wrong-detail-ai-loading-fix-2026-11-01.json`。实际生成仍需核对Admin模型配置的凭据/Base URL/服务权限，ENV状态不变。
- §354：用户明确要求更新运行版本，已构建并替换app/worker/scheduler/Admin，nginx检查/reload完成；新镜像后端源码SHA匹配既有验收版本，新Admin BUILD_ID及“取消上传”JS资源已在公网验证。内部ready200、公网live/health/首页/login200，四服务重启0/启动错误匹配0；PG/Redis/nginx未重启，81表OID及830个恢复后schema对象一致，迁移仍V19，配置哈希不变。当前PG/RDB备份、四旧镜像回滚标签保留；无迁移或业务源码改动。见[运行更新记录](../../docs/project/PRODUCTION_RUNTIME_UPDATE_2026-11-01.md)和[结构化结果](../../docs/architecture/refactor-results/production-runtime-update-2026-11-01.json)，不等于完整ENV-06验收。
- §353：用户确认保留新增工作区变化后，按此前授权同步2个后端、2个Admin运行文件。四文件哈希匹配此前ENV-02验收版本；旧服务器文件备份于 `/data/backups/source_sync_20261101T053249Z_co6jr670/`，同步后SHA一致、checksum dry-run差异0。仅服务器源码同步，未构建/重启，运行镜像尚未包含修复；不上传测试、离线脚本或环境配置。详见[操作记录](../../docs/project/PRODUCTION_TABLE_ROLLBACK_2026-11-01.md)§353补记。
- §352：按用户授权先备份、持锁复核17表为0行后删除；用户要求回滚后，已限定恢复17表、12序列及默认值/索引/约束，其他64表名称/schema/OID不变，迁移头未改。完整schema前后830段无缺失/新增，829段逐字一致，1段等价数组cast通过10种判定检查；12序列状态与备份一致。公网live/health/首页200。当前PG备份及证据在生产 `/data/backups/postgres/pre_drop_empty_20261101T051459Z_jondm9/`。未重启或同步代码；checksum dry-run确认2个后端和2个Admin运行文件存在差异，代码同步仍待处理。见[恢复记录](../../docs/project/PRODUCTION_TABLE_ROLLBACK_2026-11-01.md)。
- §351（历史）：生产只读检查发现17张空表仍有代码消费者，当时未删表或创建备份；该轮“没有新代码”的本地判断已由§352服务器checksum比对补充，不能作为当前服务器同步结论。
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
| ENV-06 | BLOCKED | 前序未全关，完整生产业务及PG+Redis恢复未完成；§352已有17表恢复，§354更新四服务、§356/§358/§359更新AI后端三个角色并完成限定部署检查，不能替代最终验收 |

`PASS-ISOLATED`不是按顺序关闭所有最终门禁，也不授权生产。§354/§356/§358/§359已按各自明确授权核对运行镜像、内部ready及限定公网健康；未完成真实外部模型、微信发布后链路或生产账号业务验收。现有部署≠最终验收通过。

## 证据与运行资源

- [验收规划与执行记录](../../docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md)，[结构化结果](../../docs/architecture/refactor-results/miniprogram-environment-acceptance-2026-10-31.json)。持久证据根：`~/.cache/postgraduate-ai/acceptance/2026-10-31/`。
- 重点：`learning-database-final.json`、`practice-response-loss.json`、`admin-concurrent-refresh.json`、`env02-import-reset-ownership-summary.json`、`env02-role-change-audit.json`、`env-integration-suite-summary.json`、`env03-refresh-token-rotation.json`、`env03-env05-backup-restore.json`、`env05-redis-backup-restore.json`、`env05-multiprocess-outbox-scheduler.json`。
- 33份原/tmp的worker/queue证据与日志已归档到 `owned-runtime-artifacts/`，附哈希清单；六份复现脚本归档到 `harnesses/`；`backups/`保留PG dump、RDB和SQLite备份，目录700/文件600，不能提交。此前备份/浏览器探针失败已保留并排除，不覆盖成通过。
- 初查无Docker/psql后，续验已在证据目录解包PG15/pgvector，实际使用5433和6380；不要复用旧“未执行PG”结论。当前临时服务的最终关闭情况以结构化结果 `runtime_cleanup` 为准；恢复前核查端口/PID。
- 私密合成身份文件 `/tmp/postgraduate-wechat-acceptance/runtime/admin-test-identities.json`（600）及浏览器state不可打印/提交。刷新失败退登录、角色审计、原生socket取消均已验；API/Admin/8002网关已停止，3000/8000/8002不监听。ENV-04实测无启用AI、OCR8080不可达、无测试存储；ENV-06公网只读live200/首页200/ready403，TLS约80天，均不能关闭阶段。
- 2026-11-01复验证据根 `~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/`；新副本 `/tmp/postgraduate-env02-fixes-20261101/acceptance.db`，不与原SQLite计数混算。临时服务启动/关闭见该目录runtime.json；不输出或提交合成身份、令牌和运行日志。旧公网基线仅为2026-10-31记录，本批未复查生产。
- 专用身份续验：`~/.cache/postgraduate-ai/acceptance/2026-11-01-identities/`，隔离副本 `/tmp/postgraduate-identity-acceptance-20261101/acceptance.db` 已清除本轮新增身份/记录并恢复基线行集。`cleanup-verification.json`、`learning-ownership.json`、`identity-rbac.json`及6份无凭据复现脚本保留；私密身份清单/模拟器存储备份已删除，8000关闭，不混用其他副本计数。

## 下一步与保护

- 小程序§358可用性禁用提示、§355恢复边界和§357成长修复均需微信开发者工具重新编译并由用户手动发布；模拟器/真机业务验收仍未完成。实际AI生成仍需核对Admin模型配置的凭据/Base URL/权限；本轮未主动调用真实模型或修改配置。优先解决ENV-01专用身份/HTTPS/真机与ENV-04受控外部能力，再进入ENV-06。§352生产17张表已恢复，不继续删表；§354/§356/§358/§359已按明确授权更新运行镜像，当前备份/回滚镜像保留。生产完整业务及PG/Redis恢复未在本次限定部署验证中完成；停止扩展生产操作，后续依具体验收范围与授权处理。
- 生产update-all不含worker；新迁移先build后用新镜像run；nginx文件bind mount换inode需force-recreate。匹配生产记录只用sync_uuid，不按本地numeric id修改生产。
- 保留已有文档、删除和未跟踪内容；用户已确认保留`11332141`及后续`.zcodeignore`删除、`error_log.txt`新增、`nul\r`消失，不处理无关文件。`backend/service_compatibility.py`是无关诊断文本，不lint/提交。只允许显式路径暂存，禁止add-A/amend/reset/checkout。§359后当前卷55节、四卷共353条记录；ENV阶段不变。生产删除及恢复见§352，源码同步见§353，运行部署见§354/§356/§358/§359；§359完成本次规范复核与AI可用性后端部署，未推送小程序、未改模型配置。
- 历史代码图谱通过本地stdio可用（本次会话未暴露MCP，§359直接核对已定位源码），project `home-lmh-projects-postgraduate-ai`，generation `2026-10-31T09:32:18Z`，68045节点/236032边；相关刷新/队列/import/client路径已核对，无已记录缺口且metadata_match，非完整性证明。Graphify缺graph.json，显式文档读取作为回退。
