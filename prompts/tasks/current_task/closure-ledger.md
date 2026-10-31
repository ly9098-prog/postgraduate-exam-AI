# 有限领域收口账本

> 2026-10-30 依据用户确认的 grilling Q1–Q3 建立。原计划仍是范围与验收来源，执行记录保存历史证据；本账本负责回答“现在做哪一项、做到哪里停止、还缺什么”，不是新一份功能需求。

## 收口规则

1. 每个业务批次先绑定一个 `OPEN` 条目；没有真实消费者、已登记缺陷或可测试性问题的“文件仍很长”不能新开批次。
2. 条目最终只能是以下四种处置之一：
   - `DONE`：结构职责已按本条目退出条件迁移，兼容证据齐全；可链接到单独的真实环境缺口。
   - `RETAIN`：已核查并决定保留现有结构，记录理由、现有门禁和仍有价值的测试。
   - `DEFECT`：存在具体行为、契约或可测试性缺陷；仅等价重构批次受原授权约束，业务修复另行确认。
   - `ENV-BLOCKED`：结论依赖当前不可用的真实环境；记录场景、所需能力、通过标准和解除条件。
3. `OPEN` 只表示尚未收口，不是允许无限追加工作的池。一个业务域只有在其全部条目均为四种终态、已识别消费者都有归属、真实环境缺口已移入最终验收表后才算结构收口。
4. 本账本中的 `PENDING-MAP` 条目只允许通过一次有界消费者/入口盘点转为具体条目；盘点范围必须写明文件和 API 注册面，不得靠无界热点搜索扩张。
5. 完整业务链路仍按原子本地提交交付。减少的是重复全量验证、无出口拆分和重复审查轮次，不是把无关链路硬塞进一个大提交。
6. 300/50 预算继续约束新增或拆出的业务模块；已有模块不能仅因超预算自动成为批次。

## 结构收口条目

| ID | 批次／消费者 | 当前证据 | 未决项与退出条件 | 状态 |
| --- | --- | --- | --- | --- |
| `MP-01` | 小程序公式库 Public API：公式目录、收藏、分页、详情/随机 | `8a341d4a`；`FORMULA_LIBRARY_COMPATIBILITY.md`；结果清单与固定 CI 已记录 | 本请求链已收口；剩余公式页面展示职责归 `MP-11` 的消费者盘点 | `DONE` |
| `MP-02` | 小程序导出请求生命周期：预览、创建、列表、下载、删除、重试、WebSocket | `0e5a0236`；`EXPORT_REQUEST_COMPATIBILITY.md`；文件/记录顺序和失败边界已刻画 | 生成器、processor、worker 未在本条改动；真实文件/COS/WS 验收归 `ENV-04` | `DONE` |
| `MP-03` | 小程序错题 Public API：列表、任务流、详情、更新、诊断和 AI 投影 | `29bb26bb`；`WRONG_BOOK_REQUEST_COMPATIBILITY.md`；既有缺陷已刻画 | 本请求链已收口；页面剩余组合若存在归消费者盘点，不按 helper 数量再开 | `DONE` |
| `MP-04` | 小程序刷题提交请求生命周期 | `c08ddccb`；`PRACTICE_SUBMISSION_COMPATIBILITY.md`；顺序重置/会话/发题事务边界保持 | 本请求链已收口；真实并发和数据库行为归最终环境验收 | `DONE` |
| `MP-05` | 小程序学习计划 GET/PUT/DELETE 请求链路 | `4feabf35`；`STUDY_PLAN_COMPATIBILITY.md`；活动读取、日快照、配置写入已分离 | 本请求链已收口；真实 PostgreSQL claim/lock 归最终环境验收 | `DONE` |
| `MP-06` | 小程序章节知识诊断请求、scope 和历史响应投影 | `d91fab53`；`KNOWLEDGE_DIAGNOSIS_COMPATIBILITY.md`；SQL 与调用顺序保持 | 只完成请求投影，不代表整个知识诊断领域完成；后续归 `MP-07` | `DONE` |
| `MP-07` | 知识诊断聚合/排名规则链 | 现有纯模块仅stdlib导入；service调用唯一聚合/排名，study-hub复用诊断service；三份直接规则测试139项、严格Ruff和编译通过，见 [兼容说明](../../../docs/architecture/KNOWLEDGE_DIAGNOSIS_COMPATIBILITY.md) 的保留评估 | 职责与独立测试能力已满足，355行既有实现保留，不为长度新开拆分；本条仅关闭规则评估，不替代知识地图/学习中心其余条目或真实环境验收 | `RETAIN` |
| `MP-08` | 小程序复习、统计和学习中心剩余 Public API | [职责核查](../../../docs/architecture/REVIEW_STATS_HUB_ASSESSMENT.md) §317：14消费契约（review5/stats8/hub overview1）归属核实；MP-17已交付诊断看板；固定静态CI465文件8049项、readiness69/cloud30/OpenAPI334路径通过 | 此有限范围结构收口，现有复习/学习中心及统计分层保留，不按长度再拆；MP-18既有SQL缺陷保留，MP-10/12..16及最终真实环境验收独立继续，不将本项当整小程序完成 | `DONE` |
| `MP-09` | 小程序记录、知识状态、薄弱知识点消费者判断 | 当前25页面和500第一方模块的调用/路径常量/模板映射未发现三个practice读取端点的直接静态消费；不是外部无调用证明 | 三个后端端点原样保留，不为本客户端新增拆分；考试9个已确认契约转归 `MP-14`。本条只关闭当前小程序消费判断，不宣称服务全域已验收 | `RETAIN` |
| `MP-10` | 小程序共享请求、上传、认证适配及后端依赖边界 | [客户端兼容说明](../../../docs/architecture/CLIENT_API_COMPATIBILITY.md) §8；`8b6e3f91`：八运行时模块逐字保留，预算/无环/导出门禁满足；直接26项通过，185命令最终组合证据通过（184复用+1定向复验），一次独立审查无P0–P3 | 不再拆共享传输；四项语义契约补齐，失效番茄钟源码门禁已修且106项通过，番茄钟业务另归MP-15。后端JWT/session/登录/头像组合归MP-12；导出file/WS归MP-02，真实网络留最终验收 | `RETAIN` |
| `MP-11` | 小程序页面职责与接口消费者的完整映射 | [消费者映射](../../../docs/architecture/MINIPROGRAM_CONSUMER_MAP.md)：25注册页、500第一方运行时JS、84静态契约形状（83HTTP/1WS）均有后端端点归属 | 有界静态盘点完成；动态入口已解析并保留限制。结构治理结论仍由对应条目审查，不能把模块可达当实际运行轨迹 | `DONE` |
| `MP-00` | 小程序消费者映射闸门 | `MP-11`范围及源文件哈希已登记；遗漏消费族补入 `MP-12`–`MP-16` | 仅关闭当前页面/接口归属盘点闸门，不声称小程序整体结构收口；新范围必须附新增消费者/缺陷证据 | `DONE` |
| `MP-12` | 小程序微信身份与用户信息/头像请求链 | [身份兼容说明](../../../docs/architecture/IDENTITY_SECURITY_COMPATIBILITY.md) §7；`3b3be730`；[结果清单](../../../docs/architecture/refactor-results/miniprogram-identity-retention-2026-10-30.json)：6契约、11运行时路径逐字保留；后端目标31+安全4、Node43、固定静态CI466文件8073项通过；一次独立审查无P0–P3（独立复验后端24/客户端43） | 保留现有路由、user/token/security与客户端身份/资料职责，补齐语义契约后停止拆分；真实微信、PostgreSQL原子轮换、Redis多进程和存储验收留最终阶段 | `RETAIN` |
| `MP-13` | 小程序知识地图与知识点详情（L2，§320） | [兼容说明](../../../docs/architecture/KNOWLEDGE_GRAPH_COMPATIBILITY.md) §7；`fb654637`及[结果清单](../../../docs/architecture/refactor-results/miniprogram-knowledge-map-retention-2026-10-30.json)：2消费契约、14运行时路径保持；40后端/9Page通过，467文件固定静态CI8077项通过，一次独立审查P3测试覆盖缺口修复并窄复核关闭 | 保留八模块后端及现有页面请求/缓存/视图职责，停止按长度拆分；原普通详情迟响应竞态单列MP-19 DEFECT，真实微信/PG验收留最终阶段 | `RETAIN` |
| `MP-14` | 小程序考试列表、历史、答题、交卷与结果（L3，§321） | [考试兼容说明](../../../docs/architecture/EXAM_ATTEMPT_COMPATIBILITY.md) §13；`9269e4cf`及[结果清单](../../../docs/architecture/refactor-results/miniprogram-exam-request-2026-10-30.json)：4页9契约，read/result纯投影177/116行，原34/当前49、Node407、readiness69/cloud30/OpenAPI334、471文件8125项固定静态CI通过；一次独立审查无P0–P3 | 响应职责已收口；保留原SQL/锁/幂等/草稿/判题与事务副作用，不按已有长函数再拆。真实PG锁/部分唯一索引并发、微信、Redis及外部预热留最终环境验收 | `DONE` |
| `MP-15` | 小程序番茄钟动作与统计消费链（L1，§322） | [学习数据兼容说明](../../../docs/architecture/LEARNING_DATA_COMPATIBILITY.md) §21及[结果清单](../../../docs/architecture/refactor-results/miniprogram-pomodoro-retention-2026-10-30.json)：两页13契约，331后端/23状态机/775Node和46/106/12/39稳定性检查通过；一次独立审查无P0–P3 | 保留现有状态机、窗口/日归属、统计/历史投影与同步控制器，不按2035行再拆；仅修CLI测试替身并提交ca236a30，2243冻结输入不变、CLI定向复验，复用§321固定CI471文件8125项。真实跨端、PG/Redis并发与worker留最终验收 | `RETAIN` |
| `MP-16` | 小程序错题AI、408教师与反馈消费链（L1，§323） | [AI兼容说明](../../../docs/architecture/AI_ANALYSIS_COMPATIBILITY.md) §16及[结果清单](../../../docs/architecture/refactor-results/miniprogram-ai-retention-2026-10-30.json)：`38f43a21`；五契约、原667/新增30与Node763通过，修当前教师源码门禁；473文件固定CI8155、readiness69/cloud30通过，一次审查无剩余P0–P3 | 现有分析/教师/反馈职责保留，无运行时改动；修正新增空缓存测试假设而未改宽松解析器。旧feature-integration脚本失败另归SHR-03；真实JWT/微信、AI/Redis/PG/worker最终验收。小程序有限账本全部终态，下一Admin映射 | `RETAIN` |
| `MP-17` | 小程序dashboard-insights完整诊断请求链（L2） | `05b62b44`；五个纯规则模块，原入口45/当前受影响111及审查后门禁18项通过；13 SQL表达式/11 async签名/聚合器AST保持，见 [兼容说明](../../../docs/architecture/DASHBOARD_INSIGHTS_COMPATIBILITY.md) | 请求链职责与兼容证据收口，一次独立审查P3门禁缺口已修复并窄复核关闭；既有回退SQL缺陷归MP-18，统计消费领域全量固定CI归MP-08，真实环境仍最后验收 | `DONE` |
| `MP-18` | 诊断薄弱知识点回退SQL既有连接歧义 | 原实现与当前直接入口契约均确认SQLAlchemy编译报multiple FROMS，13处查询表达式保持；见 [诊断看板兼容说明](../../../docs/architecture/DASHBOARD_INSIGHTS_COMPATIBILITY.md) | 作为既有业务缺陷保留，不用更多等价拆分替代修复；真正修复另行确认，须用隔离数据库回归证明版本归因与查询结果 | 2026-10-31已修：回退查询与同形态重复错题Top查询加 `.select_from(KnowledgePoint)`；新增真实sqlite回归（RED均抛InvalidRequestError）并入CI清单，契约测试改断言双方言可编译；真实PG未验，归ENV | `DONE` |
| `MP-19` | 知识详情普通读取与关系切换的既有迟响应竞态 | §320实际Page契约：先挂起point1普通读取，完成openRelation到point2，再释放旧响应，当前页面ID仍2但详情数据变回1；运行时逐字未改，见 [兼容说明](../../../docs/architecture/KNOWLEDGE_GRAPH_COMPATIBILITY.md) §7 | 保留并刻画已有语义；真正修复须另行授权并覆盖普通/强刷、关系切换、卸载与失败时序，不用继续拆分代替业务修复 | 2026-10-31已修：loadDetail记录请求id，卸载或id已变则丢弃成功/失败结果；刻画用例换成普通/后台/强刷/失败/卸载契约，17项通过，RED时6项在旧代码失败；仅Page端口证据，真实微信归ENV | `DONE` |
| `ADM-01` | `/questions`、`/review`及共享题库调用 | [题库兼容说明](../../../docs/architecture/ADMIN_QUESTION_COMPATIBILITY.md) §6及[结果](../../../docs/architecture/refactor-results/admin-question-retention-2026-10-30.json)：17消费契约、1116运行时路径保持；后端119、管理端143文件1769项（本域61文件508项），typecheck通过/lint0错138警告；新增13页面closure契约，一次审查关闭 | 保留现有query/filter/editor/owner/version/export/展示及后端revision/审计/事务职责，不按481/451行页面或既有service长度继续拆；4个无当前静态消费注册端点保留。冻结2246输入不变，复用§323固定CI8155；真实浏览器/JWT/PG/Redis/存储留最终环境验收 | `RETAIN` |
| `ADM-02` | 七页导入上传、审核、历史、任务、维护与题目列表 | [导入兼容说明](../../../docs/architecture/ADMIN_IMPORT_COMPATIBILITY.md) §326及[结果](../../../docs/architecture/refactor-results/admin-import-retention-2026-10-30.json)：31消费契约/12注册保留、1116运行时路径不变；新增19页面契约及1服务计数刻画，管理端1788、后端原组169+9xfail/改动两文件24通过；一次审查关闭 | 保留现有页面编排及review hooks/纯规则、上传/审核/发布/答案/管线owner；SSE测试默认值改为独立初始化，未改live计数器；已确认低风险计数缺陷单列ADM-08，条件迟响应交付归ENV-02，不当原生浏览器缺陷。OCR/worker剩余结构仍按原条目推进 | `RETAIN` |
| `ADM-03` | `/coverage`、`/knowledge-graph`、`/subjects`、`/syllabus` | [知识治理兼容说明](../../../docs/architecture/ADMIN_KNOWLEDGE_GOVERNANCE_COMPATIBILITY.md) §327及[结果](../../../docs/architecture/refactor-results/admin-knowledge-governance-retention-2026-10-30.json)：16消费契约/8注册保留、1116运行时不变，新增15页面契约；管理端1803、本域158、后端32通过，固定CI/OpenAPI按未变输入复用 | 保留四页请求/缓存/画布、科目目录事务和考纲生命周期owner；不因文件或函数长度继续拆。真实浏览器/JWT/PG锁/Redis归最终环境 | `RETAIN` |
| `ADM-04` | `/admin-users`、`/app-users`、`/audit-logs`、`/roles`、`/login`、`/` | [身份兼容说明](../../../docs/architecture/ADMIN_IDENTITY_COMPATIBILITY.md) §328及[结果](../../../docs/architecture/refactor-results/admin-identity-retention-2026-10-30.json)：18消费契约/7注册保留，1116运行时不变；新增18页面契约，管理端146文件1821项，后端原组99/改动RBAC7/身份门禁11分别通过 | 保留身份store/transport/JWT、两类用户、角色与审计owner；修正旧grouped测试并补commit后bump屏障，未改业务。固定CI/OpenAPI按未变输入和第三例外复用；真实JWT/cookie/PG/Redis留最终环境 | `RETAIN` |
| `ADM-05` | `/ai-settings`、`/recommendation/experiments`、`/recommendation/metrics`、`/recommendation/reports`、`/recommendation/strategies`、`/system/tasks` | [运行兼容说明](../../../docs/architecture/ADMIN_OPERATIONS_COMPATIBILITY.md) §329及[结果](../../../docs/architecture/refactor-results/admin-operations-retention-2026-10-30.json)：六页38消费契约/6注册保留，1116运行时路径不变；新增16页面端口契约，管理端1837/后端138通过，一次审查日期断言P3已关闭，独立16通过 | 保留模型注册/设置/向量、推荐策略/实验/指标/质量、诊断/调度/备份现有owner；取消异常路径清理另列ADM-09，不改业务；真实环境最终验收 | `RETAIN` |
| `ADM-06` | `/exams/[id]`、`/exams`、`/formulas/[id]`、`/formulas/categories`、`/formulas/new`、`/formulas` | [内容兼容说明](../../../docs/architecture/ADMIN_CONTENT_COMPATIBILITY.md) §330及[结果](../../../docs/architecture/refactor-results/admin-content-refactor-2026-10-30.json)：六页32契约/19注册保留，审核规则104行/最长30；原218/现235、管理端初次1856/最终19窄验，固定CI474文件8172、OpenAPI334/readiness69/cloud30新跑通过 | 状态/字段规则移入formula_review_rules，原helper签名/时钟查找及单条/批量事务顺序保持；其他39路由函数AST不变；其余现有CRUD/图资源/考试owner保留，一次独立审查无P0–P3，真实环境最终验收 | `DONE` |
| `ADM-07` | `/dashboard`；5归属契约及1条ADM-05共享诊断 | [仪表盘说明](../../../docs/architecture/ADMIN_DASHBOARD_COMPATIBILITY.md) §331及[结果](../../../docs/architecture/refactor-results/admin-dashboard-retention-2026-10-30.json)：3注册保留，1117运行时不变；新增9页面契约，管理端1865/后端34通过，固定CI等按未变输入复用§330 | 保留运营SQL/缓存/锁、纯规则和图表owner；上海日期、请求门禁与刷新屏障刻画，不合并小程序统计口径。一次独立审查无P0–P3，独立新增9通过；真实浏览器/JWT/PG/Redis归最终环境 | `RETAIN` |
| `ADM-08` | 低风险批量审核异常分支扣减此前成功计数 | §326真实approve_low_risk_questions入口刻画：首项duplicate置published/qid31，后项RuntimeError回pending，affected_count却0/skipped_count1；运行时未改，见[导入说明](../../../docs/architecture/ADMIN_IMPORT_COMPATIBILITY.md) | 作为既有计数缺陷保留；真正修复另行确认，须覆盖成功/重复/failed返回/异常顺序及事务边界，不以更多拆分代替业务修复 | 2026-10-31已修计数：删除异常分支 `affected -= 1`，刻画测试改期望affected=1并补4组顺序用例（RED 3例失败）；事务边界未改、未验真实PG，归ENV | `DONE` |
| `ADM-09` | Admin取消任务Redis读取异常路径未关闭客户端 | §329真实cancel_task入口隔离探针：hgetall抛RuntimeError，aclose.await_count为0；见[运行兼容说明](../../../docs/architecture/ADMIN_OPERATIONS_COMPATIBILITY.md)，运行时未改 | 2026-10-31 已修复：hgetall 置于 try/finally，各路径恰好关闭一次且先于 cancel_v2；`test_admin_tasks_cancel.py` 3项入CI固定清单，覆盖异常、不存在与正常路径的关闭次数及顺序；真实Redis池行为归ENV | `DONE` |
| `OCR-01` | OCR pipeline 冻结、VL 重绑定与跨页合并 | `99a09fcd`；`PIPELINE_ORCHESTRATOR_COMPATIBILITY.md`；恢复/门禁边界已记录 | 本链路已收口；诊断、工件和后台编排另列 | `DONE` |
| `OCR-02` | OCR诊断、工件/检查点和后台编排 | [OCR保留评估](../../../docs/architecture/OCR_BACKGROUND_RETENTION.md)及[结果](../../../docs/architecture/refactor-results/ocr-background-retention-2026-10-31.json)：§333十个子域处置完成；11源与§332映射一致、8个细分模块新增基线，定向1078项、Ruff、compileall和diff通过，审查4项记录问题已关闭 | 阶段元数据、single/chunk/resume、checkpoint/artifact、图片后台、worker编排和coordinator现状保留，不因orchestrator长度重拆；真实OCR/Redis/多worker/大文件归ENV-03..06，OCR-04独立DEFECT | `RETAIN` |
| `OCR-03` | OCR专用上传、Public/Admin恢复和任务接口 | [OCR接口保留评估](../../../docs/architecture/OCR_INTERFACE_RETENTION.md)及[结果](../../../docs/architecture/refactor-results/ocr-interface-retention-2026-10-31.json)：§334七个子域处置完成；20源哈希不变，定向253项、Ruff、compileall和diff通过 | 共享上传准入、Public chunk恢复、Admin stage恢复、批量图片、内部worker协议和v2任务接口保留，不因文件长度继续拆分；真实浏览器/OCR/PG/Redis/多worker归ENV-02..05，OCR-04独立DEFECT | `RETAIN` |
| `OCR-04` | 内部OCR worker artifact上传路径未注册 | §332映射：daemon调用POST /api/internal/ocr-worker/artifacts/upload，APIRouter冷注册376 operation无该路径，隔离ASGI404；证据见[OCR映射](../../../docs/architecture/OCR_CONSUMER_MAP.md) | 既有契约缺口保留，未证明真实部署承接/影响；修复另行授权并覆盖鉴权、流式hex-JSON、大小限制、重复上传、失败取消与worker等待；映射两路径已提交25e40e47 | 2026-10-31已修：新增上传路由与ocr_artifact_service，流式hex-JSON增量解码+SHA校验+原子替换，key/属主/状态/租约过期/发布前复核/大小限制/重复上传/中断清理均有39项HTTP契约（已入CI）；complete_job不核对文件、未接配额、真实worker与代理限制归ENV | `DONE` |
| `SHR-01` | 任务队列协议、状态机和 worker 消费（L3，§335） | 有界盘点：dispatcher 9类任务，`FENCING_TABLES` 仅注册7类（`answer_projection`/`error_diagnosis` 未注册，`_init_fencing_for_task` 对未注册类型静默跳过）；固定CI已含约50个队列/worker契约测试；新增1项静态刻画并入已在CI清单的 `test_task_queue_protocol_boundaries.py`（20项通过，Ruff通过） | 协议/状态机保留，不按长度重拆；两类未围栏任务是否有意属于待确认，已显式登记为豁免集合，缺口变化会令测试失败；真实租约/围栏竞态归ENV-05 | `RETAIN` |
| `SHR-02` | HTTP/worker/scheduler 生命周期与共享运行时（L3，§335） | 有界盘点：`main.py:203-210` 在 `PROCESS_ROLE=scheduler/all` 经 `start_http_scheduler_tasks` 启动，该路径不启动答案投影对账与调度健康监控（独立入口 `bootstrap.py:146,151` 启动），HTTP关停宽限固定30s（独立入口读 `WORKER_SHUTDOWN_GRACE_SEC`），outbox启动失败生产环境也仅告警；生产 `scheduler` 服务运行 `python -m app.scheduler_main`（`docker-compose.prod.yml:212`），不经该路径 | 潜在既有差异，非当前生产路径；未改运行时，修复另行授权并覆盖角色×任务矩阵、失败上报与关停时序；多角色/多worker真实行为归ENV-05 | 2026-10-31已修：HTTP scheduler/all 补启动答案投影对账与健康监控（失败仅警告），取消清单加入两任务，`cancel_and_wait_runtime_tasks(grace_seconds=WORKER_SHUTDOWN_GRACE_SEC)`；任务名序列与独立scheduler逐项一致，AST钉住宽限参数；outbox失败本就一致；生产仍走scheduler_main，真实多角色归ENV-05 | `DONE` |
| `SHR-03` | 跨域合约、静态依赖与长期门禁（L1，§335） | `miniprogram/scripts/test-408-feature-integration.js` 共7处过时源码位置断言（storage门面再导出、wrong-detail诊断流、pomodoro重启/统计、practice启动流、study-plan payload声明形式）已改指向当前职责模块；断言语义保持，未放宽白名单，运行时未改；该脚本及其余6个小程序Node脚本全部通过。该脚本不在CI清单 | 修复已登记的过时门禁；脚本仍不纳入后端固定CI，小程序无统一CI属既有状态，不新增 | `DONE` |

## 最终环境验收（必须最后执行）

以下条目不阻塞局部结构收口，但全部结构条目进入终态后，必须按顺序完成；生产环境操作只有在另行确认影响范围、备份和授权后才能执行。结构测试、Mock、SQLite、本地 Node 和模拟器不能替代这些证据。

| ID | 验收场景 | 所需能力 | 通过标准与解除条件 | 状态 |
| --- | --- | --- | --- | --- |
| `ENV-01` | 微信小程序真实编译、登录、分包加载和核心学习闭环 | 微信开发者工具、专用微信身份、测试HTTPS、真机 | §341/342的学习链与番茄钟恢复通过；§343补多空题及已提交响应丢失重试；§345确认工具桥接可用但登录未确认是专用测试身份，未交换openid。真实微信/HTTPS/真机/移动网络仍缺 | `PARTIAL` |
| `ENV-02` | Admin浏览器、JWT、RBAC、审计与导入审核 | 合成角色、浏览器、隔离后端；2026-11-01已授权缺陷修复 | §347补登录/单题审核同事务审计，真实隔离API验证；上传取消按钮、原生EOF、重置后新批次和主动迟回调拒绝通过。既有JWT/RBAC/角色审计证据保留；限定隔离检查通过，非生产HTTPS或真实OCR证明 | `PASS-ISOLATED` |
| `ENV-03` | PostgreSQL/Redis数据、锁、缓存、幂等和并发 | 本轮实际PG15.19/pgvector0.8.7、Redis7.2.5 | 迁移8/集成22项无失败跳过；两域token各8并发只1胜出、旧token401/后继200；Redis故障/缓存恢复、PG新库备份恢复通过。仅限定隔离技术检查通过，前序最终门禁未关闭 | `PASS-ISOLATED` |
| `ENV-04` | 外部AI/OCR、存储、导出文件与WebSocket | §345只读实测：启用AI配置0、OCR8080不可达、测试存储变量为空 | 正常/超时/取消/重试、文件校验/删除/重导出、重连和人工确认入库仍未验；不能用未配置AI时基础链路可用替代 | `BLOCKED` |
| `ENV-05` | worker/scheduler/outbox、多进程、重试与恢复 | 本轮私有PG/Redis、双worker+scheduler及新恢复目标 | 围栏29/Redis崩溃6/硬化23/进程恢复2通过；默认租约接管、旧owner拒绝、双任务outbox回执/投影收敛、PG/RDB分别新目标恢复通过。不是生产或跨存储原子恢复，仍受前序门禁约束 | `PASS-ISOLATED` |
| `ENV-06` | 生产最终验收与回滚演练 | 前序关闭、具体生产授权/窗口、有效生产备份/回滚制品 | §345公网只读TLS1.3约80天、live200、首页200、ready403；§340已有部署历史。前序未全关，隔离恢复不是生产备份，不能由本账本授权生产操作 | `BLOCKED` |

## 当前调度

结构条目均已进入终态，§336登记的六项缺陷已修复，安全修复/部署后续见§337–§340。历史映射、RETAIN及部署记录不能替代最终环境验收。

§341/342完成小程序三处修复和隔离学习/番茄钟链路，§343补多空题/响应丢失、Admin并发刷新、PG/Redis/多进程及备份恢复；§344补Admin角色变更审计、刷新失败退登录和导入页新旧任务归属；§345确认专用身份、外部服务及生产授权的实际阻塞。ENV-01部分通过、ENV-02审计失败、ENV-03/05隔离技术检查通过、ENV-04/06阻塞；最终门禁仍按顺序关闭，不由后序隔离证据覆盖前序缺口。下一步补专用微信身份/HTTPS/真机，确认审计修复范围并补上传阶段取消，取得受控外部测试能力；生产最后。详见[验收规划](../../../docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md)。本轮无提交、推送、上传或生产变更。

§346续接收尾：番茄钟四文件26项通过，三份业务修复跨WSL/Windows原项目/隔离副本SHA一致；只读console无目标异常命中，不是新的端到端验收。ENV-02已将缺口定位到 `admin_auth.login`、`admin_imports.approve_import_question_item`、`admin_import_service.approve_import_question`，后续可复用 `admin_audit_service.write_admin_audit` 并验证同事务提交；该结论仅覆盖已失败的登录/单题审核场景。未扩大Admin修复范围，六阶段状态不变。

阻塞审计结论：同一组前置条件连续三个目标轮次未解除，已无可继续执行的验收步骤，目标状态登记blocked；结构条目终态和六阶段状态均不改变。解除条件仍为专用微信身份/HTTPS/真机、明确Admin审计修复范围及上传取消范围、受控外部测试能力，以及前序关闭后的具体生产授权/窗口和有效备份/回滚制品。目标未完成，不能将已执行的隔离技术检查替代剩余真实环境门禁。

2026-11-01当前调度更新：用户已授权修复上述代码缺陷，§347已完成登录/单题审核审计、上传取消及迟回调归属修复和隔离复验，ENV-02转PASS-ISOLATED；上方blocked审计是2026-10-31历史。仍缺ENV-01身份/HTTPS/真机和ENV-04受控外部能力，生产最后。无提交/推送/生产操作；自审完成，独立审查未执行。

2026-11-01提交与准入复核（§348）：用户授权本地提交并继续修复；旧统计门禁已补齐为外层31/内部206项全通过，独立审查候选回滚疑点经真实依赖故障探针关闭（1通过），零未解决项；显式范围本地提交完成（小程序239dc7f9、Admin9087adf3、PG夹具432d9125、验收记录1315986c）。代码达到继续隔离验收标准。六阶段状态不变，继续隔离验收与最终生产准入分开；详细结论见 [提交与准入结果](../../../docs/architecture/refactor-results/acceptance-commit-readiness-2026-11-01.json)。任务历史重组维持未暂存边界。

2026-11-01专用身份续验（§349）：用户已授权自行创建测试身份/角色并清理，创建权限不再待确认。新合成副本通过真实API验证3个管理账号、2个角色及2个开发学习用户的权限隔离/同会话授权撤权/停用/跨域JWT拒绝；微信模拟器2题1对1错、错题详情/掌握/取消、另一用户读写404及自由计时completed68秒通过。退出后旧访问/刷新令牌401；清除15表34条本轮新增行后，79表逐行及计数与基线相同，旧数据库SHA不变，原模拟器存储恢复、临时API停止/凭据删除。DevTools测试号列表为0，真实身份交换未验。记录提交`7f6cd4cb`、账号可用性记录`b643465f`，本轮累计6个本地提交，未推送/生产操作；无新业务源码变更。仍需真实微信交换/HTTPS/真机、受控外部能力以及最后的生产窗口/有效备份/回滚制品，六阶段状态不变。详见 [专用身份验收结果](../../../docs/architecture/refactor-results/acceptance-owned-identities-2026-11-01.json)。

2026-11-01证据复核（§350）：MCP只读查询确认账号下3个AppID（2个名称带测试标记），当前验收项目匹配未标记测试用途的应用；testaccount列表0，ticket未查询，未用该项目调用wx.login。ENV-02当前源码哈希与隔离API/Chromium证据一致；ENV-03存档报告为迁移8、PG/Redis22、Pomodoro PG并发6零失败/跳过，迁移current=head；ENV-05 fencing29、Redis恢复6、队列硬化23、worker恢复2零失败/跳过，独立备份恢复和双worker+scheduler结果PASS。这里只比对源哈希和既有XML/JSON，没有重跑运行套件。故各阶段已完成的仅为限定隔离验收：ENV-02/03/05 PASS-ISOLATED，ENV-01 PARTIAL；最终顺序门禁仍未完成，ENV-04/06 BLOCKED。详见ENV规划§14。四卷容量100/98/100/46，共344条记录。验收文档显式路径提交`307a8df9`；当前本地共7个提交，未推送。

本轮结案提交：仅提交ENV验收规划与身份清理/阶段证据JSON（`307a8df9`），交接重组文件继续未暂存；当前HEAD `307a8df9`，本地 `origin/main` 引用 ahead 7，未推送、未操作生产。
