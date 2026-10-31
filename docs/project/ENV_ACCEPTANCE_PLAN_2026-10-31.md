# ENV-01..06 最终环境验收规划与执行记录

更新：2026-11-01，Asia/Shanghai。生产依据为 [DEPLOY_PLAN.md](DEPLOY_PLAN.md)，入口为 `deploy/docker-compose.prod.yml` 和 `deploy/scripts/deploy.sh`。小程序三处修复及隔离验收保留；2026-11-01经授权修复ENV-02登录/单题审核审计、上传取消和重置后迟响应竞态，隔离API/浏览器复验通过，见§11；旧统计门禁和提交准入收尾见§12。最终环境验收尚未全部通过。

## 1. 当前结论与范围

| 项目 | 本轮结果 | 不包含的证据 |
| --- | --- | --- |
| 小程序编译 | 微信开发者工具实际重新编译，登录页及 study 分包可加载 | 上传体验版、发布正式版、真机 |
| 刷题 | 首例4题2对2错；续验未答/部分作答、超时恢复、多空题UI及已提交响应丢失恢复；最终8答题、6会话、3错题 | 真实微信身份、生产用户答题；模拟器SQLite的8条outbox仍pending，不能套用另一PG夹具的投影完成证据 |
| 错题 | 列表/详情、答案与解析、标记掌握、取消掌握、手工错因及返回刷新通过；重新编译后数据仍在 | 删除真实错题、外部 AI 成功路径 |
| 今日复习 | 将隔离测试题的调度时间置为到期，完成 1 题复习；结果页 100%，1 个复习会话和1条复习记录；调度 repetitions=1 | 生产到期任务、跨日/多设备并发 |
| 番茄钟自由计时 | 启动、暂停、继续、页面隐藏/返回、暂停与运行中会话重新编译后恢复、结束确认/取消/完成通过；隔离 API 超时后完成操作持久化、恢复后同步通过 | 真实微信身份、真机后台保活、真实移动网络切换、五小时连续运行 |
| 生产只读预检 | 公网 `/health/live` 返回 200/`{"status":"ok"}`；首页跟随跳转到 `/dashboard` 为200；匿名用户信息接口为403 JSON | Admin 登录、RBAC、readiness、镜像一致性、备份恢复或回滚 |
| Admin浏览器 | 登录/RBAC/菜单、并发401单飞、刷新失败退登录、角色变更审计通过；2026-11-01登录/单题审核成功审计、上传取消及迟响应归属修复后复验通过 | 生产HTTPS/Secure cookie、实际外部OCR不在此证据内；批量/拒绝等其他审核审计未由单题证据覆盖 |
| 隔离基础设施 | PostgreSQL15/pgvector、Redis7、迁移/并发/故障恢复；两worker和scheduler的outbox/投影收敛；PG与Redis分别备份到新目标恢复 | 不等于生产恢复、跨存储一致时间点恢复或全部六阶段完成 |
| 外部能力就绪 | Admin AI模型配置0个启用、OCR 8080不可达、测试存储变量为空，故不会伪造AI/OCR/文件成功路径 | 不代表ENV-04失败原因之外的业务链路失效；基础学习链路仍应在未配置AI时可用 |
| 生产公网基线 | 域名解析到指定服务器，TLS1.3证书剩余约80天；匿名live200、首页200、受保护ready403 | 无生产登录/readiness凭据，未验证镜像、迁移、worker、备份或回滚 |

运行版本：开发者工具 `2.02.2607271`，基础库 `3.10.3`。使用单独导入的 `D:\workspace\postgraduate-ai-acceptance-20261031\miniprogram`，真实运行本地 FastAPI 和隔离 SQLite 数据库。登录使用开发入口；这不能替代真实微信登录。交互通过开发者工具 MCP 的页面导航、组件事件和页面/组件处理函数完成，截图核对显示结果；不是物理真机点击验收。

原 Windows 项目累计仅同步三处业务修复；其 `config.js` 保持原值（`LOCAL_DEBUG=false`），最终三个文件与WSL/验收副本SHA256一致。模拟器及Admin浏览器仍使用本地API/SQLite；另行启动仅绑定回环的PG15/Redis7，以及测试专属UNIX socket Redis、多个worker/scheduler。后者有独立迁移和进程证据，不得混算为同一模拟器数据库已完成投影。无生产凭据写入仓库，数据均为合成数据。

详细结果见 [结构化记录](../architecture/refactor-results/miniprogram-environment-acceptance-2026-10-31.json)。本机原始证据位于 `~/.cache/postgraduate-ai/acceptance/2026-10-31/`，包括 MCP 调用记录、截图、数据库计数及测试日志。原始证据不是跨机器可移植附件。

## 2. 本轮修复与验证边界

1. `utils/pomodoro-task-types.js` 重复定义九个函数。保留一份相同实现，恢复 Babel 编译；新测试先复现严格语法失败，再验证存储选择/会话归属。普通 CommonJS 加载可能接受重复函数，不能作为此问题的语法门禁。
2. `practice.js` 实际导入 `filter408SubjectTree`，却把不存在的 `filterSubjectTree` 传给科目加载控制器。修正显式映射；加载真实 `Page` 定义的回归先失败，再通过。
3. 精确架构模板同步这一处合法变更；边界测试增加错误简写回退的拒绝断言，保留原检查强度。
4. 用户补报 `options.maxMs is not a function`：自由计时上限控制器调用 `maxMs()`，页面适配器却注入数字。将 `buildFreeTimerLimitPageCapabilities` 改为 `maxMs: () => FREE_TIMER_MAX_MS`；其余使用数字上限的恢复/同步契约保持不变。新增适配器连接控制器的计时、自动结束和恢复回归，三项修复前均复现同一 TypeError，修复后通过。

533 个已跟踪第一方运行时 JS 的严格 Babel 解析通过。相关 89 个 Node 脚本首次88通过，1个精确模板检查因本次修复变化而失败；模板同步后，边界与科目加载合计13项定向复验通过。另有任务类型新回归及配置、代码渲染、导出错误、多空题等检查通过，5个渲染fixture的31项检查通过。原始MCP记录和数据库结果另经9项证据断言核对。以上是组合证据，不是新跑全仓CI。

2026-10-31检查点：旧 `scripts/test-pomodoro-practice-stats.js` 报告29通过、12失败，失败检查仍针对拆分前源码位置；该脚本失败时退出1；此前串行命令的总退出码0来自后续通过的命令，不能误当成该脚本通过。当时保留失败记录，未扩大为旧脚本治理；相关运行链以实际模拟器、数据库证据及当前职责测试说明，当时未执行独立审查和本地提交。2026-11-01已修复该门禁，见§12；原失败证据保留。

### 2.1 番茄钟补充验证

- 本次定向检查79项通过；`tests/test-pomodoro-*.js` 与 `scripts/test-pomodoro-free-timer-limit.js` 合计137个独立Node脚本全部退出0。此集合不包含前述仍有12项旧断言失败的 `scripts/test-pomodoro-practice-stats.js`；本次未重跑该旧脚本，也不宣称全仓CI通过。
- 本次按已跟踪JS清单排除 `tests/`、`scripts/`、`miniprogram_npm/`、`node_modules/`，540个文件以Babel `sourceType=module` 严格解析通过；覆盖清单与先前533文件统计不同，以本次证据为准。
- 同一合成会话暂停后重新编译，从首页再次进入番茄钟，恢复相同会话与 `00:00:52`；继续、跳转刷题再返回、打开结束确认、取消和在线完成均通过。另一个运行中会话重新编译后也恢复同一会话并继续计时。编译触发接口本身不返回编译结果，已等待新运行时首页出现再导航；编译期间读到旧页或导航被重启覆盖不计通过。
- 网络子场景暂停本轮隔离API进程，超过30秒请求超时后，本地界面空闲且保留1条 `complete`，服务端仍为 `paused`；恢复同一进程后排空队列，服务端变为 `completed`，重复排空未增加会话。故障仅作用于 `/tmp/postgraduate-wechat-acceptance/runtime/`，进程已恢复。最初wx.request模拟未产生预期失败回调，不计通过证据，已撤销模拟。
- 五小时边界使用隔离SQLite合成会话调整起始时间，经真实API读取和页面恢复后显示 `04:59:50`，实际计时器随后自动结束；服务端为 `completed`、`actual_duration=18000`，页面空闲。本次三个合成番茄钟会话均已完成；这是边界加速验收，未连续运行五小时。
- 原始证据新增 `pomodoro-runtime.jsonl`、`pomodoro-maxms-red.log`、`pomodoro-maxms-green.log`、`pomodoro-node-tests/`、`pomodoro-strict-syntax.json`、`pomodoro-offline-*.json` 及对应截图，均在本地证据目录。番茄钟网络补偿通过不代表刷题网络重放、真实网络切换或ENV-01整体通过。

### 2.2 刷题未答与请求超时恢复

全部4题未答时触发交卷，页面不进入提交状态，也未新增会话。答1题、留3题时出现“还有3题未完成”确认，取消后保留已答1题。再次确认提交时短时暂停隔离API超过30秒请求超时，本地保留 `pending` 快照与同一 `request_id`，显示“交卷结果未确认”，服务端尚未新增会话。恢复API、关闭提示后由原页面重试，进入结果页，显示1对/0错/3跳过、作答正确率100%。

数据库只新增1个会话、1条答题、1条outbox；会话 `question_count=4`、`answered_count=1`、`correct_count=1`、`wrong_count=0`，持久化request_id与超时快照一致。累计practice_records5、practice_sessions2、wrong_questions2、outbox5；复习与番茄钟记录未改变。该场景验证请求未确认后的同一提交恢复，不是PG并发重放或“服务端已提交但响应丢失”的单独验收。

证据新增 `practice-recovery-runtime.jsonl`、`practice-timeout-pending.json`、`practice-timeout-recovered.json`、`practice-submit-request-outcomes.json` 及结果截图；最新控制台仍无目标运行错误。此为§342检查点；多空题及响应丢失续验见下节。

### 2.3 多空题与服务端已提交但响应丢失

通过既有 `question_imports` 和人工审核发布一题合成多空题：只选空1时完整作答计数为0；空1=A、空2=B时计数为1。完整交卷结果5题、1答、1对、0错，数据库答案为 `1:A;2:B`。部分选择的探索交卷曾产生0作答完成会话，按未答统计；不能将原4道单选全未答阻止交卷的证据泛化到所有多空题部分选择情况。

独立故障网关8001已收到上游交卷200后丢弃响应。重试的 `request_id` 与请求体SHA256相同，上游再次返回200，页面最终进入结果页；同一request_id只有1个会话和1条答题。故障网关已停止，验收副本配置已恢复本地API。证据：`practice-response-loss.json`、`gateway-requests.jsonl`、`multiblank-success-result.json`及对应截图。

最终SQLite为8答题、6会话、3错题、1复习会话/1复习记录、3个已完成番茄钟、8条pending outbox，见 `learning-database-final.json`。其中包含部分多空题探索会话；不是6次全部正确的验收。另一隔离PG的双worker消费证据不代表这8条SQLite outbox已消费。

开发者工具桥接可用且登录未过期，但当前登录未被确认为专用测试身份，未找到已确认的测试AppID/账号映射。为避免处理非测试微信身份，本轮没有发起 `wx.login` 到后端的真实身份交换，见 `env01-identity-readiness.json`。`.env.ci` 中存在WeChat变量名不等于其对应专用测试账号；未输出变量值。

## 3. 分阶段验收板

按 ENV-01 → ENV-02 → ENV-03 → ENV-04 → ENV-05 → ENV-06 顺序关闭最终门禁。隔离技术检查可提前执行；`PASS-ISOLATED` 仅表示该阶段限定的隔离检查通过，前序缺口仍未关闭，不能据此进入生产。故障只注入本轮拥有的临时资源。

| ID | 当前状态 | 剩余所需能力 | 必须提交的通过证据 |
| --- | --- | --- | --- |
| ENV-01 | PARTIAL | 专用真实微信身份、测试HTTPS、真机和真实网络切换 | 模拟器学习链、番茄钟恢复、多空题与响应丢失子场景通过；真实身份/设备仍待验 |
| ENV-02 | PASS-ISOLATED | 限定隔离技术检查通过，仍受ENV-01及最终生产门禁约束 | 已发现的登录/单题审核审计缺陷修复并由真实隔离API验证；上传按钮取消、原生连接EOF、取消后新批次及拒绝迟响应通过；详见§11 |
| ENV-03 | PASS-ISOLATED | 证据已形成，仍受前序最终门禁约束 | 迁移8、PG/Redis集成22项零失败零跳过；真实两域刷新轮换、缓存故障、PG新库恢复通过 |
| ENV-04 | BLOCKED | 缺受控外部AI/OCR、测试存储、HTTPS/WS网关 | 外部成功/超时/取消/重试、文件校验/清理、WS重连与人工确认仍未验 |
| ENV-05 | PASS-ISOLATED | 证据已形成，仍受前序最终门禁约束 | 队列/PG围栏29、Redis崩溃6、队列硬化23、worker进程恢复2项；双worker+scheduler及PG/RDB新目标恢复通过 |
| ENV-06 | BLOCKED | 前序未全关；缺生产窗口、具体操作授权及已核验的生产备份/回滚制品 | 本轮只有公网匿名预检，未执行生产部署、备份、恢复或回滚 |

初查PATH未找到Docker/psql；续验已在本地证据目录解包PG15客户端/服务端及pgvector，并实际启动5433和6380隔离服务，不再将“未安装Docker”误写为“没有PG验收”。软件版本为PG15.19、pgvector0.8.7、Redis7.2.5。Admin合成身份和Chromium已准备；外部服务与真机条件仍缺。临时服务收尾状态见结构化结果，不复用生产资源。

## 4. ENV-01 剩余步骤

1. 在专用测试项目中连接测试HTTPS后端，通过真实 `wx.login` 完成身份交换；账号/数据由测试环境提供，禁止借用生产真实用户数据。当前工具登录既未确认是专用测试身份，本轮便不交换；开发登录通过只能关闭本地子场景。
2. 重复编译、冷启动、study 分包进入；记录工具版本、SDK、设备、网络、API环境和源码哈希。当前两项修复必须保留回归。
3. 已有4题样例、未答/部分作答、多空题完整答案、超时与响应丢失恢复证据；在真实身份/HTTPS环境复验返回、主动取消、后台恢复及多空题部分选择的交卷提示，比较界面与服务端记录。
4. 从结果页及错题本进入详情，验证错因、掌握/取消、刷新；从到期复习完成提交并核对调度。AI不可用时基础解析与答题仍应可用。
5. 在适用真机复验登录、分包、交互与返回；记录不适用项及理由，不能用模拟器截图替代。

自由计时冷恢复、确认取消及API超时补偿见§2.1；刷题未答/部分作答与超时恢复见§2.2；多空题及响应丢失见§2.3。这些模拟器子场景不解除真实微信身份、HTTPS、真机与真实移动网络的剩余条件。

## 5. ENV-02 浏览器与人工审核

已运行Chromium155.0.8059.12、隔离Admin3000/API8000。三种合成角色分别登录：super_admin读取管理员/角色接口200，admin/user均403，受限菜单隐藏相应入口。刷新cookie为HttpOnly，path `/api/admin/v1/auth`，本地Secure=false；HTTPS生产Secure仍须另验。

浏览器在真实题库页面对首轮两个读请求注入无效bearer，并将refresh请求挂起到两个401都到达：两个请求各返回401，只产生一次refresh200，重试均200，登录态保留。使用未修改的客户端/后端；这是受控故障注入，不是自然过期。证据 `admin-concurrent-refresh.json` 和截图；旧单次401记录不冒充并发证据。

**2026-10-31失败记录**：登录后仅更新last_login；人工审核将合成导入置published并写reviewed_by，但当时 `audit_logs` 只有 `system.init_super_admin`，没有登录/审核审计。详见 `admin-api-rbac-audit-evidence.json`。2026-11-01已获授权修复并复验，见§11；原失败证据保留。

续验通过真实Admin API创建合成管理员、从user角色改为admin并停用；audit_logs新增 `admin_user.create`、`admin_user.update`、`admin_user.delete`，角色变更审计子场景通过，见 `env02-role-change-audit.json`。合成账号已停用，未输出凭据。另将首个业务读请求和refresh均注入401，页面从 `/dashboard` 跳到 `/login?next=%2Fdashboard`，sessionStorage access token清除、无可用refresh cookie；刷新失败退回登录通过，见 `admin-refresh-failure.json`。

批量图片导入页不使用外部OCR：浏览器先经路由拦截把旧任务status/SSE挂起，重置并发起新批次后释放旧响应；旧status/SSE均以 `net::ERR_ABORTED` 结束，new.png/4题/NEW_CURRENT_EVENT正确显示，晚到old.png/77题/OLD_STALE_EVENT均未出现。

为排除Playwright拦截本身导致断开，另通过8002本地原生HTTP网关走真实fetch/socket：重置时网关分别观察到旧status与SSE连接的EOF；在upload响应被挂起时导航离开页面，网关观察到upload请求EOF。证据 `env02-import-native-cancel-body.json`、`env02-import-native-unmount.json` 和合并摘要 `env02-import-cancel-ownership-final.json`。

2026-10-31仍有上传阶段无可见取消控件的缺口，且单元刻画允许中止后晚到响应覆盖新队列；原生fetch取消成功不能证明所有回调时序安全。2026-11-01已增加上传阶段取消按钮及当前批次检查，见§11。

启动隔离 API/Admin；按 `admin-frontend/package.json` 可先运行 `npm run typecheck`、`npm run lint`、`npm run test`，构建相关场景再执行 `npm run build`。这些命令是前置检查，不替代浏览器验收。

浏览器使用专用测试账号分别验证：登录与HttpOnly刷新cookie；多个同时401只产生一次刷新；刷新失败退回登录；受限角色403和菜单；登录/角色/单题审核审计。上述隔离场景已有证据；测试导入保留 `question_imports` 和人工确认，不能将合成OCR结果直接发布。

导入页覆盖批量图片重置/新任务时旧fetch与body取消、迟响应、旧SSE事件和新轮询归属；轮询阶段重置、原生socket EOF、unmount upload取消的原有证据保留。上传按钮取消及主动送达晚到回调的回归见§11。

每例记录浏览器版本、账号角色别名、请求次数/状态、脱敏审计ID和截图；不导出cookie、Authorization或AI凭据。

## 6. ENV-03 PG/Redis 与迁移

本轮使用解包的PG15.19/pgvector0.8.7和Redis7.2.5：5433/6380绑定127.0.0.1，数据库和目录由验收专用。`env_acceptance`、空库迁移目标及故障夹具相互隔离。若后续需容器复现，可使用已有 `deploy/docker-compose.test.yml`；以下Compose命令是复现方案，本轮没有执行Docker命令：

```bash
docker compose -p postgraduate-env-20261031 -f deploy/docker-compose.test.yml up -d
```

在隔离测试配置中设置 `APP_ENV=test`，`DATABASE_URL` 指向新建的迁移目标，`TEST_DATABASE_URL` / `PRACTICE_TEST_POSTGRES_URL` 指向相应一次性测试库，`TEST_REDIS_URL` 指向专用测试实例；实际测试fixture可能要求不同库名，执行前按各测试的owned资源规则核对。禁止把生产连接串放入这些变量。

```bash
cd backend
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic current
.venv/bin/python -m alembic heads
.venv/bin/python -m pytest \
  tests/integration/test_postgres_integration.py \
  tests/integration/test_practice_submit_postgres.py \
  tests/integration/test_pomodoro_postgres_concurrency.py \
  tests/integration/test_redis_integration.py -v --tb=short
```

实际current/head均为 `v19_pomodoro_subject_allocations`。空库完整迁移8项、PG/Redis集成22项均零失败/零跳过；另做迁移降级/再升级，日志保留。并发提交同request只一胜出、不同payload冲突、outbox写入失败全事务回滚、番茄钟advisory锁与FOR UPDATE均有真实PG证据。修正的仅是番茄钟并发测试夹具：异步fixture声明、V19分摊表、合法科目树、UTC时间；未改后端业务。

实际目录：81表、138外键、51个pg_catalog CHECK、53个UNIQUE约束、81主键、385索引（151唯一），pgvector和番茄钟部分唯一索引存在。旧信息模式统计735个CHECK包含NOT NULL，不与pg_catalog的51个CHECK混用。真实Redis进程SIGKILL/重启证明严格缓存fail-closed、普通缓存本地降级、科目树失效和持久值恢复。

小程序和Admin刷新接口分别用同一token发8个并发ASGI HTTP请求，连接真实PG/Redis：每域1个200、7个401，旧token重放401，后继token200；用户表最终3枚token、1枚有效。无Mock/SQLite；不是微信初始登录或HTTPS网关验收。证据 `env03-refresh-token-rotation.json`。

PG备份从迁移库克隆合成源，补2条答题/2条pending outbox；`pg_dump`使用导出的repeatable-read快照，恢复到新库。81表的行数/逐表哈希、70序列、迁移和pgvector版本相同；323约束与385索引仅对varchar数组→text数组的等价cast作窄规范化，12个CHECK与1个部分索引还逐一验证全部允许值、非法值和NULL，结果相同。原始表达式哈希差异保留，不宣称原SQL逐字相同。见 `env03-env05-backup-restore.json`，不等于生产备份恢复。

`pytest --help` 未发现 `--run-integration`，不要使用Compose注释中的过时参数。

以上隔离技术检查已形成可复核证据，阶段记 `PASS-ISOLATED`；前序未关闭，不能宣布最终环境验收完成。日志/结果位于证据目录，不能用单元测试或SQLite替代。

## 7. ENV-04 外部服务、文件与WS

本轮只读核对隔离环境：数据库无启用的AI模型配置，OCR远程8080不可达，测试存储变量缺失；因此没有把未配置AI/OCR时的基础刷题可用性冒充外部成功路径。详见 `env04-external-readiness.json`。

测试环境通过 Admin API/数据库管理加密的AI模型配置；不把key/base URL/model当环境变量同步。OCR按既有 `PaddleOCR-VL → LLM纠错 → rule fallback` 和质量门禁验收。使用固定、无个人数据的图片/PDF与测试存储前缀。

先验证正常识别/解析/人工确认，再注入超时、取消和可重试失败，核对导入状态、租约、工件SHA/大小及发布前校验。检查代理请求体上限、磁盘/总量配额、TTL清理和大文件；未通过不得以本地接口测试替代真实网关。

导出覆盖预览、创建、下载并打开PDF/DOCX、删除测试文件、重导出、失败补偿。通过真实网关验证 `Sec-WebSocket-Protocol` 携带bearer凭据、重连、HTTP轮询降级与超时；日志/URL不得泄露token。本轮仅验证AI未配置时基础学习链路仍可用。

## 8. ENV-05 队列与进程恢复

已完成队列/PG围栏29、Redis真实崩溃恢复6、队列硬化23、worker进程恢复2项，均零失败/零跳过。真实SIGTERM排空当前任务并保留pending；SIGKILL后等待默认约600秒租约，替代worker接管，旧owner的heartbeat/complete/fail被拒绝；重复投递不重复写业务状态。进程恢复两例耗时648.94秒，不是缩短租约的Mock。

两个未修改的 `app.worker_main` 与一个 `app.scheduler_main` 在独立迁移PG/Redis运行。任务 `answer_projection:9001/9002` 由不同worker领取，两条outbox均published、队列均completed，学习行为/复习/掌握度/难度投影均收敛；三进程退出码0。详见 `env05-multiprocess-outbox-scheduler.json`。

PG恢复见§6；另通过真实 `DurableTaskQueue.enqueue_v2` 创建相同的两条pending任务，Redis SAVE生成RDB，复制到全新的私有Redis进程，核对全部key类型/值哈希、TTL和任务状态一致，两进程退出0，见 `env05-redis-backup-restore.json`。PG恢复和Redis恢复分别验证，不是跨存储原子时间点恢复演练；不覆盖生产备份制品。

阶段记 `PASS-ISOLATED`，前序最终门禁仍未关闭。33份原 `/tmp/worker-runtime-*` / `queue-recovery-*` 证据与日志已脱敏归档到持久证据目录 `owned-runtime-artifacts/`，附SHA256清单。以下保留候选命令，便于复现：

在ENV-03专用资源上运行真实 `app.worker_main` 和 `app.scheduler_main`，至少两个worker；`web` 不承担独立worker角色。现有候选测试：

```bash
cd backend
.venv/bin/python -m pytest \
  tests/integration/test_queue_fencing.py \
  tests/integration/test_postgres_fencing.py \
  tests/integration/test_queue_redis_recovery.py \
  tests/integration/test_worker_process_recovery.py -v --tb=short
```

执行前核对测试选择和所需owned资源；测试通过后仍需记录多进程故障注入：领取后进程退出、超出租约、旧持有者迟到完成、Redis短暂不可用、重复投递、取消、SIGTERM宽限、死信与恢复。按job/request/outbox标识核对，不把进程存活视为任务完成。

最终模拟器SQLite的8条outbox仍为pending；只有独立PG夹具中的两条outbox有消费者回执与投影收敛证据。二者边界保留，禁止写成模拟器全部投影已完成。不在生产注入故障。

## 9. ENV-06 生产验收与回滚窗口

### 9.1 已知基线与只读预检

2026-10-31续查公网只读基线：`www.xzshub.top` 解析到部署文档指定服务器，TLS1.3证书约剩80天；`/health/live` 200、首页200、匿名 `/health/ready` 由nginx返回403。该结果证明公网入口存活，不证明生产镜像、迁移、数据库、队列或备份一致；详见 `env06-production-public-readonly.json`。

生产按指定部署文档使用当前服务器和 `/opt/22408-ai`，不使用历史服务器。历史卷§339/§340记录2026-10-31安全修复及全量重构已部署；这属于既有记录。本轮仅新验证了公网匿名健康与路由，不等于重新完成部署验收。

部署文档§6的旧数据量、numeric ID偏移迁移策略和§8的旧head是历史快照，不得直接照抄。跨环境记录匹配统一使用 `sync_uuid`，禁止按numeric ID修改生产记录；实际服务包括worker，以当前Compose及运行配置核对。

前五阶段关闭后，先只读核对：服务/角色、镜像ID、源码清单、实际配置画像、迁移current/head、卷挂载、磁盘、健康/任务积压。不要打印完整 `docker compose config`、`docker inspect` 环境变量或服务器 `.env`。

```bash
cd /opt/22408-ai
df -h /
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml config --services
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml ps
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml images
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml exec -T app alembic current
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml exec -T app alembic heads
```

readiness/metrics采用既有受保护的运维访问方式；本轮没有读取其凭据。scheduler/worker无HTTP，必须核对日志/任务进度，不能给它们假设HTTP健康地址。

### 9.2 若需要补发布

本轮只有小程序运行时修复，没有后端schema变更；本机同步不等于上传体验版。只有另行明确发布范围，才执行对应发布。

如后续确需更新生产后端，先给出并确认文件清单、服务范围、维护窗口、备份与回滚制品，然后：

1. 保存当前可回滚镜像ID/标签、部署源码快照和迁移版本；核验历史回滚标签实际存在，不直接假定§339/§340的标签仍可用。
2. 运行 `bash deploy/scripts/deploy.sh backup`，核对PG与Redis备份有效性、业务记录计数，并在隔离目标恢复验证。文件大小/`DBSIZE>0`不足以证明恢复一致。
3. rsync先干跑，排除服务器`.env`、证书、密钥和运行数据；若有删除，单独列清并确认，不能默认执行带删除同步。
4. 先构建新镜像并冒烟；若有新迁移，使用新镜像 `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml run --rm app alembic upgrade head`，不能直接用旧容器内的 `deploy.sh migrate` 获取尚未包含的迁移。
5. 分别替换已授权的app/scheduler/worker/admin；保留PG/Redis及其卷。当前 `update-all` 只覆盖app/scheduler/admin，worker必须显式覆盖。构建失败时不替换运行容器。
6. app/admin重建后reload nginx重新解析upstream；nginx配置文件inode或内容变更时必须在授权范围内 `--force-recreate nginx`，只reload不能保证换绑挂载文件。
7. 核对health/live、受保护ready、Admin、角色任务、关键链路及错误日志/5xx。容器健康成功不能替代微信/审核/队列业务验收。

### 9.3 回滚演练

先在隔离环境验证回滚制品和恢复步骤；生产最终验证在批准窗口内进行。应用回滚使用已确认旧镜像/源码，替换受影响服务并reload nginx，再执行相同关键链路；不使用破坏本地工作的git回退命令。

数据库回退必须针对**本次实际迁移**评估，禁止照抄部署文档§8历史版本 `812ba6628ff1`。当前本轮无新迁移，默认不降级数据库；必要恢复采用已验证备份和单独的数据影响方案。

`deploy.sh redis-restore` 会停止Redis并替换AOF/RDB，仅在已确认的数据恢复方案和维护窗口使用。生产不执行 `down`、删volume、`build --no-cache`、`system prune -a`。验收完成需同时留存备份/恢复计数、回滚后健康、业务与队列收敛证据。

## 10. 下一步与交付状态

下一步需要ENV-01专用微信身份/测试HTTPS/真机及ENV-04受控外部能力；ENV-02已发现的代码缺陷经授权修复，限定隔离技术检查通过。ENV-03/05限定隔离技术检查保留通过；ENV-06仍受前序、生产凭据/窗口/授权和真实备份制品阻塞，公网基线仅为2026-10-31只读结果。不能将这些状态写为六阶段全通过。

截至§347未提交、推送、上传小程序或执行生产部署/迁移/恢复/回滚；故障只作用于本轮临时资源。当时旧番茄钟源码断言仍失败且未独立审查；§348已补齐该门禁、完成独立审查并获授权本地提交，见§12。临时服务关闭与证据保留状态写入结构化结果和交接摘要；生产运维仍以用户指定DEPLOY_PLAN及实际配置为准。

### 10.1 2026-10-31番茄钟修复续接收尾与审计修复边界

续接时复跑自由计时恢复、页面适配器契约、计时更新和上限控制器四个测试文件，26项通过、0失败、0跳过。三个业务修复文件在WSL、Windows原项目与隔离验收副本的SHA256均一致。通过现有微信工具只读查询当前页面栈与缓存console，未命中 `options.maxMs`、`GLOBAL_ERROR`、`GLOBAL_UNHANDLED` 或重复声明异常；本次没有重新启动已关闭的隔离API，也没有新跑番茄钟端到端场景。此前§2.1的模拟器证据仍按原范围使用。

ENV-02已定位到以下具体入口，供后续有界修复；本次没有修改Admin业务：

- `backend/app/api/v1/admin_auth.py:122` 的 `login` 成功分支生成令牌、更新 `last_login_at/last_login_ip` 后提交，没有在该函数调用审计写入。
- `backend/app/api/v1/admin_imports.py:591` 的 `approve_import_question_item` 调用审核服务后直接提交；`backend/app/services/admin_import_service.py:899` 的 `approve_import_question` 更新审核人并发布题目，没有在这两个函数写审计。该边界对应已失败的单题人工审核场景，不能泛化为全部导入、批量审核或公式审核均缺审计。
- 现有 `backend/app/services/admin_audit_service.py:36` 的 `write_admin_audit` 只向当前session添加审计实体，不自行提交。后续若获授权修复，应复用该入口并验证业务与成功审计同事务提交/回滚，且不记录密码或令牌；批量、拒绝和失败登录是另需明确的回归范围，不宣称已验证。

代码图谱generation为 `2026-10-31T09:32:18Z`：上述四个后端路径为metadata_match且无已记录覆盖缺口；番茄钟适配器及两个修改测试为metadata_changed，结论依据本轮直接源码/diff读取与Node执行，不把旧索引当成修复后的证明。覆盖信号为best effort，不是完整性证明。

六阶段状态保持不变；真实身份/HTTPS/真机、受控外部服务以及生产授权/备份/窗口仍未具备。证据在本地 `pomodoro-followup-closeout/verification.json` 与 `admin-audit-boundaries.json`；没有新增提交、部署、真实身份交换或生产数据操作，也没有新增独立审查。

### 10.2 2026-10-31目标阻塞审计（修复授权已由§11更新）

同一组剩余前置条件连续三个目标轮次未解除，本次将目标登记为blocked。原始目标仍为完成剩余ENV验收，未缩减范围、未标记完成。前一目标轮次新增了Admin导入验证和审计边界证据，分类为progress；当前重核仅确认阻塞仍在，没有新的可执行验收步骤。

现状复核：隔离数据库启用AI配置0项；隔离API运行脚本的测试微信及COS配置为空；3000/8000/8002/8080/5433/6380均无本地监听。没有待观察的验收进程，也没有新提供的专用测试身份、设备、外部能力或生产窗口。缺少本地8080监听不单独证明远程OCR当前不可达；ENV-04仍缺受控外部能力，未改写此前远程探针的结论。

恢复条件：

1. ENV-01提供专用微信测试身份与AppID映射、测试HTTPS及真机/移动网络。
2. ENV-02明确登录和单题审核审计的修复范围，并决定上传阶段可见取消控件是否纳入；已有实现入口见§10.1。
3. ENV-04提供受控AI/OCR、测试存储和HTTPS/WS网关，继续真实外部链路验收。
4. ENV-06在前序门禁关闭后，按用户指定DEPLOY_PLAN落实具体生产验收授权/窗口、有效生产备份与回滚制品；不由持续目标自动扩大生产权限。

本次未修改业务代码、重跑已通过集合或启动服务；证据 `goal-blocked-audit/audit.json`，工作区原有改动与验收数据保留。

## 11. 2026-11-01 已发现缺陷修复与隔离复验

用户明确授权“修复这些发现的问题”，本批处理登录成功审计、单题导入审核通过审计、上传阶段取消及同链路的迟响应归属。没有将身份/真机、外部服务或生产前置条件改写为代码缺陷；没有扩展到批次/拒绝/公式审核或失败登录的新审计功能。

- Admin登录成功写 `system.login`（low），与登录时间/IP同事务；单题首次审核通过写 `import.approve`（important），与审核/发布同事务。审计包括操作者、资源、IP、User-Agent；审核detail仅含 `batch_id/question_id/status`，不存密码或令牌。审计写入失败时业务更新回滚，登录不返回成功cookie；失败登录、发布失败和重复审核不写成功审计。
- 上传阶段显示“取消上传”，复用AbortController与资源清理。上传/状态请求在await后、SSE回调和watchdog创建前检查当前批次身份及中止状态，避免中止后晚到响应覆盖新批次或重建计时器。这里取消的是本页上传请求和跟踪，不能保证已被服务器接收的OCR任务停止。
- 回归先RED后GREEN：新增后端6项中4项先因缺审计失败；前端21项中3项先因缺取消按钮/迟回调污染失败。修复后后端API定向41项、审计/鉴权/导入与幂等服务85项、导入页21项通过。新后端文件已加入固定CI清单。
- `.github/workflows/ci.yml` 固定静态集合8336项、mocked readiness69项均零失败/错误/跳过；前者有65条warning，未将warning计为失败或隐去。管理端typecheck、lint、150文件1869项测试及build均通过，lint为0错误/138警告。实时隔离API导出的OpenAPI经7.8.0工具生成TypeScript并通过现有关键响应合约tsc；首次离线缓存探针失败保留，联网使用项目既定生成脚本后通过，无新增项目依赖。
- 独立合成数据库副本+真实API：实际登录、实际人工审核/发布写入两类审计；重复审核422、失败登录401，无额外成功审计，字段持久化且无凭据。实际发布服务未mock。该副本没有写回原验收数据库。
- Chromium真实页面：1440px/390px均能操作取消按钮，无窄屏水平溢出；原生网关观察上传取消的EOF，浏览器为 `net::ERR_ABORTED`，重置后new.png/4题新批次正常。网关只控制上传/任务响应，不代表真实OCR/AI成功；单元回归另主动投递取消后的旧状态/SSE事件，确认不会污染新任务或重建旧watchdog。

证据根 `~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/`，结果见 [ENV-02修复清单](../architecture/refactor-results/env02-defect-fixes-2026-11-01.json)。ENV-02为PASS-ISOLATED，ENV-01仍PARTIAL、ENV-03/05保留PASS-ISOLATED、ENV-04/06仍BLOCKED。§347检查点自审完成，未独立审查或提交；随后§12已完成独立审查与授权本地提交，未推送/生产部署。适用真实PG/Redis、生产HTTPS/Secure cookie等完整可靠性环境未在本批重跑，不宣称所有GitHub工作流或最终环境门禁通过。

## 12. 2026-11-01 提交与继续验收准入复核

用户授权提交，并要求不满足继续验收标准时继续修复。旧番茄钟统计入口复现29通过/12失败后，改为运行当前控制器、适配器、持久化与结果职责的25个行为测试文件，保留统计格式化、WXML、趋势与结果恢复检查。修复后外层31项、内部206项全部通过，内部零跳过；两组计数包含入口与子进程关系，不相加为唯一用例总数。

新增真实提交适配器联通回归，验证先持久化再POST、服务端批次与request_id、扣除后台的冻结时长，以及墙钟跳变和网络失败后复用同一请求体。仅在独立Node进程内将接口路径改错或移除后台扣时，回归均失败；模拟子进程退出7时旧入口退出1，不能吞掉失败。没有为通过门禁修改业务运行时。

提交前源哈希与已通过的后端8336静态、69 readiness、管理端1869/typecheck/lint/build及OpenAPI契约输入一致，复用其原范围证据；仅新增/修改的Node检查做定向复验，不宣称所有GitHub工作流通过。独立审查已完成，唯一回滚疑点经真实get_db依赖、flush后提交故障与新会话查询验证关闭（1项通过）；没有为此修改业务源。显式路径提交及最终保护检查见 [提交与准入结果](../architecture/refactor-results/acceptance-commit-readiness-2026-11-01.json)。

代码回归通过允许继续适用的隔离验收，完整ENV-01..06仍需专用微信测试身份/AppID映射、测试HTTPS、真机/移动网络、受控AI/OCR/存储/网关以及最后的生产窗口和有效备份/回滚制品。当前只读核查新合成SQLite副本仍为0个启用AI配置；临时服务未运行不是代码缺陷，本地8080无监听也不证明远程OCR当前不可用。本轮不修改生产、不推送；原始失败记录及此前环境证据保留各自时间与范围。

本地源码提交：小程序 `239dc7f9`、Admin `9087adf3`、PG验收夹具 `432d9125`。记录随本节提交；任务交接分卷维持原未暂存边界，无关改动保留。
