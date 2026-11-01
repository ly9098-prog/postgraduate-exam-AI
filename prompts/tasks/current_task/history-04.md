# 重构执行记录 · 第 04 卷

> 原记录编号：§305–§345；41/100 批次。保留原编号和原文顺序，合并标题按覆盖编号计数。历史状态不代表当前验收结论。

[任务入口](../current_task.md) · [原计划](plan.md) · [上一卷](history-03.md)

<!-- original-history:start -->

## 三百零五、小程序公式库 Public API 完整链路（2026-10-29，`8a341d4a`）

按新优先级一次批次完成目录/计数/筛选、普通与收藏分页、卡片投影、详情/随机和收藏写入，19历史入口迁至五个职责模块，原题卡分类薄入口保留；行为边界见 `docs/architecture/FORMULA_LIBRARY_COMPATIBILITY.md`，命令/结果/hash集中于 `docs/architecture/refactor-results/miniprogram-formula-interface-2026-10-29.json`。定向86、逆展开19函数与20原签名/装饰器/注解/docstring一致、1320种子差分及实际OpenAPI对象相等；固定CI静态7654、readiness69、cloud30通过，一次独立只读review无P0–P3。

显式12路径本地提交，21保护/12冻结/暂存blob同进程失败即止校验，提交后HEAD blob与工作区hash匹配、索引空、author lmh且无AI attribution。证据 `/tmp/miniprogram-formula-interface-batch/`；禁止重跑extract.py。未push/部署/生产或用户数据操作；本节及context/workflow交接更新保留未暂存。NEXT先盘点小程序导出Public API整链，核实消费者、测试、事务/文件/任务边界；exams已知入口薄，AI服务长函数中的依赖装配不机械拆分。全部小程序接口与真实微信/生产鉴权/外部资源尚未验收，整体ACTIVE。


## 三百零六、小程序导出 Public API 请求生命周期（2026-10-30，`0e5a0236`）

以完整请求生命周期为一个批次收敛预览/创建/列表/详情、下载/文件响应、删除、重试/原记录重导出、WebSocket及响应投影；原19入口委托七个职责模块，健康/能力/唤醒薄实现保留，生成器/processor/worker保持原实现。兼容边界见 `docs/architecture/EXPORT_REQUEST_COMPATIBILITY.md`；命令、数量、预算与源码hash集中于 `docs/architecture/refactor-results/miniprogram-export-interface-2026-10-30.json`。原/当前50直接契约、114定向、19逆展开/22原声明与语句/12helper、800种子差分及实际OpenAPI对象一致；固定CI452文件/7768passed、readiness69/cloud30、严格Ruff/compileall/diff通过。一次独立只读review无P0–P3，独立114测试通过。

原三项源码字符串断言改为假存储/路径的直接行为验证；保留幂等冲突回滚后捕获user ID、删除snapshot→外部文件→记录顺序及失败/取消边界、retry二次config读取、reexport同记录旧文件/时间相等差异和WS上下文finally。显式16路径本地提交，21保护/16冻结/staged及HEAD blob同进程失败即止校验并提交后复核，索引空、author lmh/noAI attribution；无push/部署/真实文件删除或生产操作。

证据 `/tmp/miniprogram-export-interface-batch/`，禁止重跑extract.py/build_gate.py；本节/context/workflow更新保留未暂存。等CI时只读侦察api/v1范围52模块/477函数，包含Admin文件，搜索分页已取完但不等于完整语义审计；错题消费者及23路由/helper、enrich_wq与单次聚合富化查询已定位，NEXT完整核实错题请求/清洗/富化链路；practice提交/列表/知识状态仍有缓存和响应编排候选。接口优先级不变，真实微信/生产DB鉴权/COS文件/多worker/WS网关及完整全栈验收未执行，整体ACTIVE。


## 三百零七、小程序错题 Public API 完整请求链路（2026-10-30，`29bb26bb`）

一次批次收敛错题列表/任务流/详情、更新/批量、诊断读取/确认/建议，以及文本/选项清洗、当前Question/历史version复习富化与AI响应投影；20入口迁至六模块，三个统计/分类薄入口保留。原23函数声明/描述/顺序及模块常量、20逆展开语句/3helper保持；`**extra` 中ports字段通过位置专用注入保持兼容。既有service、事务、缓存顺序、AI错误/取消和原对象部分修改保持。兼容说明见 `docs/architecture/WRONG_BOOK_REQUEST_COMPATIBILITY.md`，命令/数量/hash见 `docs/architecture/refactor-results/miniprogram-wrong-interface-2026-10-30.json`。

原/当前46契约、7门禁、原组合101及末版53增量通过；一次独立只读review无P0–P3，独立5文件102通过，末版1300种子差分与实际OpenAPI一致。固定CI456文件/7868passed、readiness69/cloud30、严格Ruff/compileall/diff/YAML通过。显式13路径本地提交，21保护/13冻结/staged与HEAD blob同进程失败即止校验、提交后索引空；author lmh/noAI attribution，无push/部署/生产用户数据操作。

证据 `/tmp/miniprogram-wrong-interface-batch/`，禁止重跑extract.py/build_gate.py；本节/context/workflow更新未暂存。NEXT小程序实际调用的practice提交/顺序重置/会话接口请求编排；只读图已定位practice11函数及API测试，记录/knowledge-states/weak-knowledge-points的客户端消费尚未确认，不能仅凭负检索认定无调用。真实微信/AI/生产PostgreSQL/Redis/完整学习闭环与其余全栈验收未完成，整体ACTIVE。


## 三百零八、小程序刷题提交请求生命周期（2026-10-30，`c08ddccb`）

按真实刷题页/结果恢复调用链，一次批次收敛提交路由的诊断、service错误映射、缓存失效和响应装配至一个请求模块；原签名/鉴权/schema、11声明、10保留函数体与已有发题/提交事务编排保持。顺序重置和会话scope/knowledge-summary已是薄入口，补契约保留，不为行数再拆。兼容边界见 `docs/architecture/PRACTICE_SUBMISSION_COMPATIBILITY.md` §24，命令/数字/hash见 `docs/architecture/refactor-results/miniprogram-practice-request-2026-10-30.json`。

原/当前定向契约、逆展开与900差分、实际OpenAPI一致；固定CI458文件7914passed，readiness69/cloud30通过。一次独立审查发现的P3函数内导入/数据库调用门禁缺口已加固并复核关闭，无剩余P0–P3；全量收集于门禁加固前，末版37契约+16门禁53项另行通过，未把新增负例冒称已进本次全量。业务源码在全量启动后未变。显式8路径同进程失败即止校验与本地提交，21保护/8冻结/staged及HEAD blob匹配，索引空，author lmh/noAI attribution，无push/生产/用户数据操作。

证据 `/tmp/miniprogram-practice-request-batch/`，禁止重跑extract.py；本节/context/workflow交接更新保留未暂存。下一步继续其余小程序Public API语义覆盖盘点，复习调用适配器9结果、review路由9函数及stats/plan/hub16函数仅作scout；已读取复习三个修改入口，暂不因其19–23行而再拆，需核对底层service与现有门禁。记录/知识状态消费者未确认。真实微信、PostgreSQL/Redis、多worker、外部服务与完整全栈验收仍未完成，整体ACTIVE。


## 三百零九、小程序学习计划完整请求链路（2026-10-30，`4feabf35`）

按小程序学习计划 GET 概览、PUT 保存、DELETE 停用的真实调用链，一次批次收敛四来源活动日期、日快照 claim/更新和配置写入。活动读取与快照/配置分别进入两个职责模块，service 保留四个历史签名与其他函数原体；动态端口、查询顺序、唯一冲突、部分写入和取消边界保持。新模块与函数满足 300/50 预算，无新增例外。兼容边界见 `docs/architecture/STUDY_PLAN_COMPATIBILITY.md` §9；命令、实际行数、验证结果和源码哈希集中于 `docs/architecture/refactor-results/miniprogram-study-plan-2026-10-30.json`。

原/当前最终契约、精确逆展开、带预期分支断言的差分和独立进程 OpenAPI 对照通过；最终固定 CI、readiness、cloud 检查通过，业务及测试源码在全量启动后未变。独立审查指出的差分注入失效、未批准预算例外、逆展开失败与长度误记均已修复复核关闭，无剩余 P0–P3；旧 differential.py/inverse.py 日志已明确撤销验收效力。

显式九路径同进程失败即止核对保护/冻结/staged blob并本地提交，提交后 HEAD blob与工作区一致、索引空、维护者身份及无 AI attribution 检查通过。证据 `/tmp/miniprogram-study-plan-batch/`；禁止重跑 extract.py/repair_structure.py。本节、context/workflow 的后续交接更新保留未暂存，既有文件删除与诊断数据保持，无push/部署/生产或用户数据操作。NEXT复习、统计与学习中心的真实消费者及 service 语义覆盖；记录/知识状态仍无可靠消费者确认，不按负检索判无调用。真实微信、PostgreSQL 行锁/跨设备并发及其余全栈验收未完成，整体ACTIVE。


## 三百一十、小程序章节知识诊断完整请求链路（2026-10-30，`d91fab53`）

按统计页与学习中心的真实消费，一次批次将历史scope清洗、根章节/最近会话/汇总及响应投影集中至一个纯模块；service保留原三个声明、SQL与map/history/aggregate/rank编排，薄路由/schema/auth及既有聚合/排名规则保持。使用时动态helper、最近先截五条再过滤、accuracy/coverage不同口径、响应引用/字段序、错误与取消边界保持。兼容说明见 `docs/architecture/KNOWLEDGE_DIAGNOSIS_COMPATIBILITY.md`，命令/数量/预算/hash见 `docs/architecture/refactor-results/miniprogram-knowledge-diagnosis-2026-10-30.json`。

原实现刻画、最终原/当前契约、完整逆展开、带预期分支差分与冷进程OpenAPI一致；固定CI、readiness/cloud、严格Ruff/compileall/diff通过。一次独立只读审查无P0–P3，独立回放通过；业务/测试/CI在全量启动后未变。显式八路径同进程失败即止保护/冻结/staged/blob校验并本地提交，21保护与提交前后HEADblob一致，索引空、author lmh/noAI attribution，无push/部署/生产用户数据操作。

证据 `/tmp/miniprogram-knowledge-diagnosis-batch/`，禁止重跑extract.py/build_gate.py。本节/context/workflow交接更新未暂存，原有删除与诊断文本保留。既有356行聚合/排名模块未改，不能视为整个知识领域完成；NEXT按真实消费者评估该完整规则链并盘点其他小程序Public API，再Admin和OCR。微信/JWT、PostgreSQL/Redis及完整全栈验收仍未完成，整体ACTIVE。


## 三百一十一、任务记录分卷与每轮文档同步（2026-10-30）

按用户要求将原任务长文拆到 `prompts/tasks/current_task/`：原计划单列 `plan.md`，执行记录分为四卷，每卷最多100批次；合并标题按覆盖编号计数并整体保留，原编号、顺序及全部正文不变。`current_task.md` 改为当前状态、优先级、记录索引和下一步入口；第04卷继续追加。原文拼接还原一致：原304个覆盖编号加本节共305个，四卷容量100/98/100/7，29个本地链接通过；独立只读审查无P0–P3，并另以原始字节验证完整无损。

工作流明确“适用验证/独立审查 → 同步任务入口/当前卷/context/专项文档与结果 → 检查一致性 → 按已授权范围提交及回填提交事实 → 核对完成后进入下一轮”。用户随后纠正：收尾需更新的是 `MEMORY.md` 协作记忆。仓库内没有该文件，按当前环境允许机制写入记忆增量，不直接修改生成索引或在仓库另建副本；`MEMORY_SYSTEM.md` 两份业务架构文档均保持不变。未受影响的专项文档记录已核对无需修改，不虚构实现或验收。任务目录和上级导航的“current_task已完成”旧描述同步修正。

本轮仅调整文档，不修改业务代码/测试/CI，不重新运行无关全量测试，不推送/部署或操作生产/用户数据；原有删除和诊断文本保留，既有任务文件改动继续留在工作区。最近业务提交仍为d91fab53，整体ACTIVE；完成文档核验后继续评估小程序知识诊断聚合/排名整条规则链。


## 三百一十二、有限领域收口与风险分层工作流（2026-10-30）

用户通过 grilling 明确同意 Q1/Q2/Q3：把剩余工作转成有限领域账本，按真实消费者和具体结构/可测试性问题调度；以 DONE/RETAIN/DEFECT/ENV-BLOCKED 处置条目，允许有证据地保留现状；以 L1/L2/L3 风险分层取代每批精确重放全量固定 CI，临时逆展开和大量差分不再作为固定交付物；结构治理与真实环境验收分开，生产验收留到全部重构完成后的最后阶段，生产操作仍需另行授权。

新增 current_task/closure-ledger.md，从已有提交和兼容文档迁入已完成请求链及 OCR 冻结链的证据，未审查领域仍 OPEN/PENDING-MAP，不冒称全部领域收口。工作流、任务入口、分卷说明、源码盘点导航与 ROADMAP 同步；plan.md 只在原文标记之前增加当前执行补充，原计划正文与 §311 及此前历史保持原文。下一步固定为 MP-00/MP-11 小程序页面→请求→端点/消费者映射，映射前不启动新的热点拆分。

本轮为纯文档 L1，核验范围为新增/修改文档的链接、容量、原文保留、账本条目、调度与生产最后阶段表述及工作区保护；不修改业务/测试/CI，不重跑无关业务全量测试。证据与最终检查结果在 /tmp/refactor-workflow-convergence-2026-10-30/；文档继续保留既有未暂存边界，无提交/push/部署/生产或用户数据操作。文档检查通过：原计划和全部原始历史逐字还原，§311正文保留，四卷100/98/100/8共306记录、25本地链接、31唯一账本条目；7157条非本轮路径与快照一致。一次独立只读审查发现的P3容量旧值已最小修复并复核关闭，无剩余P0–P3；协作记忆增量已按允许机制写入。API/兼容说明及结果清单已核对，无需修改，旧业务验收日期与数字未刷新。文档门禁完成后再进入下一步。


## 三百一十三、小程序页面与接口消费者有界映射（2026-10-30）

按§312的新门禁完成MP-00/MP-11静态消费者映射：当前app.json25页面（主包2/分包23），图索引924模块分页取完，当前500第一方运行时JS与Git文件集合一致；509初始候选metadata_match，140排除/遗漏明细只作为best-effort证据。AST require/组件JSON/公共app根映射84个可能消费契约形状（83HTTP/1WebSocket），唯一匹配26个Public注册模块中的153项声明；共享服务模块可达不代表其所有导出被每页实际调用。动态统计前缀、公式目录变量、四种番茄钟动作、导出文件/WS、刷新与头像上传均单独解析。

映射正文 docs/architecture/MINIPROGRAM_CONSUMER_MAP.md，端点/后端函数/直接服务依赖/候选页面/调用点和553源文件哈希在 refactor-results/miniprogram-consumer-map-2026-10-30.json。仅将MP-00/MP-11盘点闸门标记DONE，不称小程序结构或环境完成；补入MP-12身份/MP-13知识地图/MP-14考试/MP-15番茄钟/MP-16小程序AI五组OPEN消费族。MP-09只关闭当前客户端消费判断并保留三条practice读取接口，不声称外部无调用；考试归MP-14。下一项固定为MP-07规则评估，职责/测试已满足则保留，不按356行继续拆分。

本轮L1纯文档与静态证据，不修改业务/测试/CI、不运行业务全量CI或任何真实/生产请求。一次独立只读审查复核注册页/源集合/路由与553哈希，发现的P3公式目录传输表述已改为实际api.request(GET,url)并复核关闭，无剩余P0–P3。文档检查通过：30本地链接、36唯一账本条目、7159非本轮路径与快照一致，原计划和§312及此前历史完整保留，当前四卷100/98/100/9共307记录。协作记忆增量已写入；既有API/兼容文档与旧业务结果清单已核对无需修改。证据 /tmp/miniprogram-consumer-map-2026-10-30/；保持任务文件未暂存边界和全部用户既有改动/删除/诊断文本，不push/部署/操作用户数据。生产验收留至全部结构重构完成后的最后阶段，授权边界不变。


## 三百一十四、知识诊断纯规则保留评估（2026-10-30）

按§313有限队列评估MP-07，而非继续按355行热点拆分。knowledge_diagnosis_logic仅依赖stdlib，聚合与排名是现有纯规则权威；当前service读取/清洗后调用aggregate_session_stats与rank_chapter_recommendations，study-hub章节任务复用同一diagnosis service。图对service过时、projection未跟踪的部分已用当前AST核实，不据旧图行号推断。现有三份直接规则测试139项通过，严格Ruff/单模块编译通过；祖先归因/去重、时间窗口、计数/coverage、评分/分类/非重叠与回填、推荐投影及原异常行为均按已有契约保留。

决定MP-07 RETAIN，不新增业务模块/接口/适配层或测试，不用无关全量固定CI替代规则证据；仅关闭这项规则评估，不声称整个知识地图/学习中心或全栈阶段收口。补充KNOWLEDGE_DIAGNOSIS_COMPATIBILITY.md的保留依据，结果/命令/hash见 refactor-results/knowledge-diagnosis-retention-2026-10-30.json，证据 /tmp/knowledge-diagnosis-retention-2026-10-30/。一次独立只读审查确认保留依据，独立回放139passed；P3旧长度数字已核实当前355并修正复核关闭，无剩余P0–P3。文档/源码保护检查通过：31本地链接、36账本条目、553映射源哈希和7规则/测试哈希均匹配，7161非本轮路径未变；协作记忆增量已写入。原计划与此前历史完整保留，当前四卷100/98/100/10。

下一项MP-08：按5个review/8个stats/1个hub overview实际契约和现有门禁，逐条决定保留或登记具体结构缺陷；不按service长度开批次。本轮没有业务/测试/CI改动、暂存或提交，无push/部署/生产及用户数据操作；最终真实环境和生产验收顺序保持不变。


## 三百一十五、复习／统计／学习中心职责核查与诊断看板缺口（2026-10-30）

按MP-08当前5个review/8个stats/1个hub overview契约核查真实消费链。复习已有版本/锁/幂等/SM-2、批改与会话/任务状态辅助职责，学习中心已有科目/候选/任务构建/完成项排序/token职责，保留两条现有子链，不按service长度再拆。统计已有查询/投影分层继续保留，但dashboard页实际消费的stats/dashboard-insights经函数内导入进入独立service，其SQL、纯评分与响应投影仍混在度量函数中；现有stats分层门禁不覆盖这些规则，登记MP-17（L2）为一个完整诊断请求链，MP-08整体仍OPEN，不把评估冒充已实现。

19个API/service契约/架构门禁文件263passed（58.64s），应用compileall通过。7现有业务文件严格Ruff报告review_scheduler14个既有F401，7文件与HEAD逐字一致；原CI参数忽略I001/F401/N818后通过，未扩忽略规则/移除兼容导入，未冒称严格全通过。没有业务/测试/CI修改，本轮不重放全量固定CI，不做真实微信/PG/Redis/外部或生产请求。

职责结论与退出条件在 docs/architecture/REVIEW_STATS_HUB_ASSESSMENT.md，精确命令/26源哈希/结果在 refactor-results/miniprogram-review-stats-hub-assessment-2026-10-30.json；复习/学习数据/学习决策兼容文档追加本次结论。独立只读审查完成，无剩余P0–P3；26源哈希、7文件HEAD一致性及测试/Ruff证据均复核通过，未重复整套测试。文档结构与工作区保护检查及协作记忆增量已完成，结果见证据目录verification-result.json；原计划与§314及此前历史保持，四卷100/98/100/11。证据 /tmp/miniprogram-review-stats-hub-2026-10-30/，保留所有既有改动/删除/诊断文本和任务未暂存边界，不提交/push/部署/操作生产及用户数据。

下一批MP-17先刻画八个诊断输出、include_subjects/include_topics、cache与metric错误/取消等原行为，再按完整请求链抽纯评分/投影；原SQL/参数/时间范围、async入口/gather共享session、lookup时机与异常分类保持，不夹带并发或统计业务修复。完成MP-17后回填MP-08，再按原优先级处理其余小程序链路，生产验收仍最后进行。


## 三百一十六、诊断看板完整请求链纯规则分离（2026-10-30）

绑定MP-17（L2），按dashboard页→stats/dashboard-insights→service完整链路交付，七项度量及action plan的纯评分/响应归quality/topic/speed/balance/action五模块，service936→548行，五模块最大149行、函数最大35行。SQL/时钟/方言与缓存/异步聚合仍归service；不按原查询函数或文件长度继续拆分。13处SQL执行表达式、11async签名、两个查询辅助函数与整个聚合器AST保持，速度分类仍在科目查询前，时间serializer仍逐行动态解析。

原始service入口/API契约45passed0.91s；当前8份相关测试/门禁111passed12.85s，严格Ruff/compileall/diff通过，4新测试同步固定CI。缓存命中身份/开关/错误、metric取消值/父请求取消、阈值/评分/新复习标签/重复分组/投影均有语义断言。没有重放全量固定CI：本批不是MP-08领域收口，MP-08仍OPEN，下一项先做其消费覆盖与领域门禁。原fallback SQL在当前SQLAlchemy编译报multiple FROMS，原/现测试均刻画，登记MP-18 DEFECT，未夹带业务修复。

兼容边界见DASHBOARD_INSIGHTS_COMPATIBILITY.md，结果/哈希见refactor-results/miniprogram-dashboard-insights-2026-10-30.json，证据/tmp/dashboard-insights-request-2026-10-30/。一次独立审查发现P3纯模块门禁漏拦参数数据库操作，补9类属性调用检查及5负例后，主执行定向18passed0.08s，审查者18passed0.09s窄复核关闭，无剩余P0–P3；审查者另在修复前独立回放4新测试71passed1.42s。业务源码未再改动。显式13路径本地提交 `05b62b444791ea02252a09e5828e11f1a77b1e0b`，暂存集合/工作区/HEAD blob一致，7183路径保护检查通过，索引空、author lmh/无AI attribution。最终文档检查及协作记忆增量已完成；原计划/历史保留、四卷310记录、38账本条目和源码哈希均核实，结果见verification-result.json。MP-17 DONE；下一轮回到MP-08领域覆盖/全量门禁，未提前开始。原计划与§315及此前历史保持，四卷100/98/100/12。原有改动/删除/诊断文本与任务未暂存边界保持；不push/部署/操作生产或用户数据。真实环境及生产验收仍留整个结构重构之后最后进行。


## 三百一十七、复习／统计／学习中心有限领域结构收口（2026-10-30）

回到MP-08，精确核对消费者映射的14契约（review5/stats8/hub overview1），站点、候选页面、当前路由函数与调用清单逐项登记。复习/学习中心和既有统计职责保留，dashboard-insights具体缺口已由MP-17提交05b62b44解决；不再因service长度新增拆分。原回退SQL问题仍MP-18 DEFECT，真实环境仍ENV-01..06 WAITING-FINAL，不混进结构“待完成”池。本轮只关闭MP-08这有限范围，不关闭其余小程序/管理端/OCR条目。

当前CI工作流固定静态清单465文件8049passed（pytest541.80s，墙钟546.56s）；readiness替身69passed、cloud隔离30passed、原/现服务冷进程OpenAPI334路径完全一致。按既有CI参数的应用Ruff及compileall通过，未冒称清理所有旧严格Ruff债务。46当前证据源哈希、553消费者映射哈希和2238应用/测试/CI保护路径匹配，没有业务/测试/CI修改；“固定静态清单通过”不包括所有GitHub Actions构建、数据库、管理端或真实环境作业。

一次独立领域审查核对14契约集合/调用点/路由/候选页面及现有职责，未发现P0–P3；最终CI/哈希/限定完成声明窄复核通过；P3交接文档残留旧OPEN/下一步已明确历史限定并窄复核关闭，无剩余P0–P3，不重复业务测试或启动第二份CI。结果docs/architecture/refactor-results/review-stats-hub-closure-2026-10-30.json，职责说明REVIEW_STATS_HUB_ASSESSMENT.md追加§317更新；证据/tmp/review-stats-hub-closure-2026-10-30/。文档保护检查及协作记忆增量已按允许机制完成，verification-result.json与protected-after-docs.json为本轮门禁/新保护基线，才进入下一轮；原计划与§316及此前历史保留，四卷100/98/100/13共311记录。

MP-08 DONE，下一项MP-10共享请求/上传/刷新适配，和MP-12身份链明确职责归属；按既有门禁与实际缺陷决定保留或一个完整链路批次，再MP-13..16。业务HEAD保持05b62b44，本轮不新增提交，任务/相关文档保持未暂存，所有既有改动/删除/诊断文本保留。无push/部署/生产或用户数据操作，生产验收仍最后进行。


## 三百一十八、共享传输保留评估与契约补齐（2026-10-30）

MP-10核对api门面及error/correlation/transport/clock/auth/request/upload八模块，运行时逐字保留，现有300/50及无环/导出同一实例门禁满足，不开新拆分。MP-12继续负责登录/退出、资料/头像组合、session及服务端用户JWT身份策略；MP-02保留文件/流式下载/WebSocket专有传输。按84静态契约归属记录范围，不把模块可达当每页真实执行证明。

原直接契约/门禁22通过，发现标题声称上传401/header时钟覆盖却没有对应断言，补四项实际语义用例后26通过：上传同trace/新request-id/token/无JSON头及第二401止、普通请求第二401止、主动刷新网络失败等1500ms仅重试一次并阻止原HTTP、过期时钟样本Dateheader回退。仅修改测试，未改鉴权/缓存/时钟/存储/平台行为。Node语法/diff通过。

当前reliability小程序步骤306物理行/185逻辑命令，初次在20停止（番茄钟韧性105通过1失败）；继续审计余165命令后唯一失败仍20。真实backend start_session已先查幂等键再活跃检查，失败只因测试要求旧active=await写法；本轮将该门禁限定函数内await调用顺序，后端不改，定向复跑106通过，复用其余184命令证据。不是修复后重跑了一次全shell；初次/审计exit1证据保留。MP-15仍OPEN，本轮不冒称番茄钟业务已收口。后端与固定CI不变，复用§317的465文件8049项，不重复全量。

兼容CLIENT_API_COMPATIBILITY.md追加§8；精确证据/哈希/预算口径见refactor-results/miniprogram-transport-retention-2026-10-30.json，临时证据/tmp/miniprogram-transport-assessment-2026-10-30/。一次独立审查无P0–P3；审查者独立定向26 API/106韧性通过，未重跑整套reliability。显式4路径本地提交 `8b6e3f91ba1b355b65e2ad6a0c1f3f549539a4b2`，暂存集合/工作区/HEAD blob一致，7185路径保护检查通过，索引空、author lmh且无AI attribution。最终文档检查与协作记忆增量已完成，结果和新保护基线见verification-result.json/protected-after-docs.json，才进入下一轮。原计划与§317及此前历史保留，四卷100/98/100/14共312记录。MP-10 RETAIN，下一MP-12身份链，随后MP-13..16。既有改动/删除/诊断文本和任务未暂存边界保持，无push/部署/生产及用户数据操作，真实/生产验收仍最后进行。


## 三百一十九、微信身份与用户资料请求链保留及契约补齐（2026-10-30）

MP-12精确对应当前6消费契约：auth/login/refresh/logout、GET/PUT users/me、POST users/me/avatar。现有路由协议/限流、user_service微信身份与资料/头像、token_service刷新哈希/单次轮换/撤销、security用户JWT/nbf分工明确，客户端auth与登录页已有会话/资料组合及生命周期/协议/跳转辅助职责。保留运行时，不因既有65/56行usecase再拆，不改变Admin/User域或token/存储策略；账户注销等未被当前客户端消费的额外端点不进入本批执行。

原隔离基线17通过；既有token/user兼容文件补14端口契约（总24项）并注册固定CI：登录顺序、刷新账号检查/消费/issue先后、头像读上限/关闭/HTTP错误、commit失败回滚只清新对象、持久化后清旧对象、昵称身份/退出登录撤销顺序。目标3文件31passed，另4项JWT/nbf/刷新安全定向通过。未运行fixture来源未核实的旧test_auth_session，也不把其旧grace注释当实现事实。新测试用synthetic模型/端口，不访问开发库/生产库或真实头像存储。

客户端已有contract补7语义用例，包含微信session/四key写失败回滚、头像先传后昵称并保留新URL、头像失败不发PUT、logout等待撤销尝试后清本地、协议写失败回滚、页面销毁后迟到登录先补协议再退出。客户端/边界/storage共43通过，精确reliability命令112当前19项通过；复用§318其余184条相关输入未变的命令证据，不冒称新完整mini shell。当前固定静态CI466文件8073passed64warnings（pytest560.47s，墙钟565.84s），2238后端/app/tests/CI冻结路径不变；严格Ruff修改测试、Node语法、appcompileall/diff通过。不是全部GitHub Actions或真实环境验收。

依据IDENTITY_SECURITY_COMPATIBILITY.md追加§7与refactor-results/miniprogram-identity-retention-2026-10-30.json，MP-12决定RETAIN。一次独立实现/测试审查未发现P0–P3，审查者独立回放后端兼容文件24通过（1.18s）及客户端/边界/存储43通过；最终只窄查文档状态与限定声明，不重复实现审查或全量CI。最终文档窄查发现P3旧context仍称身份OPEN，最小修复后窄复核关闭，无剩余P0–P3。显式5路径本地提交 `3b3be730eded59d97f4db56f1aa08600b9fa8978`，暂存集合/工作区/HEAD blob一致，7186路径保护检查通过，索引空、author lmh且无AI attribution。文档一致性门禁及协作记忆增量已完成，verification-result.json/protected-after-docs.json为本轮证据和下一保护基线。证据/tmp/miniprogram-identity-assessment-2026-10-30/，原计划及§318此前历史保留，四卷100/98/100/15共313记录。完成本轮门禁后下一MP-13知识地图/知识点详情，再MP-14考试、MP-15番茄钟、MP-16AI，之后Admin/OCR。既有改动/删除/诊断文本和任务未暂存边界保持；没有生产/真实微信/Redis/PostgreSQL/存储验收，无push/部署/用户数据操作，真实/生产验收仍最后进行。


## 三百二十、知识地图两消费链保留评估与契约补齐（2026-10-30）

MP-13（L2）精确覆盖科目地图/知识点详情两个GET消费者，不将overview或其他知识状态入口的历史归属当本轮真实调用。后端八模块职责已按查询/规则/投影/编排收敛，service195行、所有模块/函数满足既有300/50；客户端已有节点/统计/视图辅助、请求序号/缓存/在途复用/关系切换边界，保留已有职责，不按页面长度再拆。14运行时路径与HEAD/本轮基线逐字一致。

补4项隔离HTTP/schema契约，专用FastAPI app与tmp_path SQLite验证两个端点200/404/非法整数422和实际服务响应；现有36+新4共40passed17.62s。补9项实际Page契约覆盖请求最新序号/隐藏、首屏和后台错误、回执计数解析、缓存/去重/强刷/重试、子树显示/关系去重和卸载后的切换守卫。最后一例刻画普通loadDetail先挂起point1、实际关系切换point2完成后旧响应覆盖详情但页面ID仍2的原竞态，单列MP-19 DEFECT；未暗改语义。所有平台/API/timer/存储回执替身恢复，不访问真实微信/网络/用户数据。

Node9通过；当前reliability186命令是§319未变输入185条复用+本次新增命令，不冒称一次新完整shell。严格Ruff新Python测试、Node语法/appcompileall/diff通过。467文件固定静态CI8077passed64warnings（pytest626.06s/墙钟631.09s），2239后端/测试/CI冻结路径不变；Node强刷测试在CI启动后补在途断言并单独9项通过，不属于后端CI输入。一轮独立实现/测试/CI/文档审查发现P3强刷标题与覆盖不符，补未完成请求并发force断言后定向复验/窄复核关闭，无剩余P0-P3；审查者HTTP4/7.28s、Page9通过，修复后另窄复验force1项。MP-13 RETAIN；不提前开MP-14。兼容KNOWLEDGE_GRAPH_COMPATIBILITY.md§7，结果refactor-results/miniprogram-knowledge-map-retention-2026-10-30.json，证据/tmp/miniprogram-knowledge-map-assessment-2026-10-30/。原计划/此前历史保留，四卷100/98/100/16共314记录。显式6路径本地提交 `fb654637c4d38869acfd1f9313dc3abab2499e58`，暂存集合/工作区/HEAD blob一致，7189路径保护检查通过，索引空、author lmh且无AI attribution。最终文档检查与协作记忆增量已完成，verification-result.json/protected-after-docs.json为本轮门禁/新保护基线，才进入下一轮；身份/传输/诊断专项说明已核对，无需修改，未刷新旧验证日期；原改动/删除/诊断文本及任务未暂存边界保留，无push/部署/生产或用户数据操作，真实/生产验收仍最后进行。


## 三百二十一、考试完整消费链响应职责收敛（2026-10-30）

MP-14（L3）核对四页九契约，客户端既有pending/同步/恢复/交卷/结果控制器保留；后端列表、详情、题目/作答、历史与交卷结果投影迁至read/result两个模块，177/116行、最大函数35/39，满足300/50。服务1200→1045行，SQL、时钟、校验、行锁、开始幂等、保存、判题/模型写入/错题/诊断/outbox/commit与提交后prewarm仍原位，不按已有长事务继续拆分；相邻未被当前静态消费的paperdetail因投影改动也验证，未扩充九消费者计数。

原入口首轮32passed5.56s；扩展同组原实现34passed7.83s（1pytest预导入warning），当前加门禁49passed7.27s无warning。新服务四契约覆盖动态helper改绑/只读过时显示/错误次数与同次数出现次序的弱知识点/编码失败回滚；专用app+tmpSQLite HTTP生命周期覆盖九契约、相邻detail、重复交卷快照和两历史入口。原文lost_score排序描述按原Counter.most_common(8)事实修正，业务无改。新wrong投影测试用AsyncMock替代提交后prewarm入队并assert2calls，不做外部预热。只读AST核对12投影正文及实参、全24函数展开、原常量/异常/导入和32数据库调用均保持，禁止重跑extract_once.py。

客户端考试Node407通过，非完整mini shell/微信证据；当前readiness69/cloud30和冷原/现OpenAPI334路径相同。严格Ruff、appcompileall、diff通过。固定CI471文件8125passed64warnings（pytest694.04s/墙钟699.7s），2244后端/测试/CI冻结输入未变；一次独立实现/测试/CI/文档审查无剩余P0–P3，独立新服务/HTTP/门禁20passed6.50s并核对原稿/实参/源码哈希。MP-14 DONE；显式9路径本地提交 `9269e4cf557d38c0ec672d623fbd63f0b36c3ca7`，暂存集合/工作区/HEAD blob一致，7195路径保护检查通过，索引空、author lmh且无AI attribution。最终文档一致性检查与协作记忆增量已完成，verification-result.json/protected-after-docs.json为本轮门禁/新保护基线，不提前开始MP-15。身份/传输/知识地图/诊断专项说明已核对无需修改，不刷新旧验收日期。兼容EXAM_ATTEMPT_COMPATIBILITY.md§13，结果refactor-results/miniprogram-exam-request-2026-10-30.json，证据/tmp/miniprogram-exam-assessment-2026-10-30/。原计划/此前历史保留，四卷100/98/100/17共315记录。原有改动/删除/诊断文本与任务未暂存边界保持，无push/部署/生产或用户数据操作，真实/生产验收仍最后进行。


## 三百二十二、MP-15 番茄钟动作与统计消费链保留收口（2026-10-30）

按有限账本核对两页13消费契约，既有状态机、窗口/日归属、累计/响应/科目/历史投影与客户端同步/恢复/统计控制器职责已清晰，评估RETAIN。service2035行、87函数含方法、最大49行、snapshot40行；attribution既有64行规则保留，不为新增模块预算机械拆分。未改业务、API/schema、数据库、客户端或CI。

现有331后端通过（8历史弃用警告，29.09秒）、775Node通过；四脚本46/106/12/39通过。额外原CLI脚本在14检查后因旧_Result缺scalars失败，保留失败日志，仅修实体感知查询替身及Usage；当前23/23通过，原断言均保留。严格Ruff、app及脚本compileall、diff通过。§321固定CI471文件8125项、readiness69/cloud30/OpenAPI334复用，冻结2244后端/测试/CI输入中2243不变，唯一变化CLI不在固定命令内且已定向复验；不是本轮fresh完整CI。

一次独立只读保留审查无P0–P3，独立复跑23/23并核对13契约、哈希/预算和CI复用边界。兼容LEARNING_DATA_COMPATIBILITY.md新增§21（原§18–20保留），结果refactor-results/miniprogram-pomodoro-retention-2026-10-30.json，临时证据/tmp/miniprogram-pomodoro-assessment-2026-10-30/。本轮显式提交边界为CLI测试及新结果两路径，既有LEARNING_DATA/任务/库存文档未暂存边界保持。MP-15 RETAIN，nextMP16；真实微信/多端/PG锁/Redis/worker及生产仍最后验收。原计划/此前历史与无关改动保留，四卷100/98/100/18共316记录；最终文档/记忆与保护检查完成后才进入下一轮，无push/部署/用户数据操作。

本轮最终显式两路径已提交 `ca236a30aecd4e1c887cb504864e38c1791cf539`，暂存/工作区/HEAD blob匹配，7196路径提交前保护检查通过，index空、author lmh、无AI attribution。协作记忆增量2026-10-30T15-50-00-postgraduate-mp15-retention.md已写入，最终一致性/原文/哈希检查结果见本轮verification-result.json，protected-after-docs.json作为下轮保护基线。身份/传输/知识地图/考试专项已核对，无需修改，不刷新旧验证日期。


## 三百二十三、MP-16 小程序AI消费链保留收口（2026-10-30）

按有限账本核对错题分析/状态/恢复、408教师及反馈共五消费契约。现有分析执行/锁/持久化/发布、教师同域事实与查询/纯辅助函数、客户端请求/恢复/反馈职责保留；1234行教师service、213行入口不因长度继续拆分。1672运行时路径保持批前哈希，无业务/API/schema/DB/客户端改动。

新增教师入口14项及专属FastAPI/临时SQLite16项契约，验证固定版本自身历史（他人历史不放行）、四入口考试阻断、三入口错题归属、恢复revision/force/baseline、反馈提交及额度/用量先于解析/降级/取消。provider/分析生成/队列为本地替身，不是外部执行验收。原41文件667通过；首轮43文件695通过1失败，失败为新增meta-only缓存被错误期待未就绪。保留原宽松归一化，测试改为None/空dict后新增两文件30项通过，未重复43文件。一次独立审查P2测试假设已修并窄复核关闭，独立14+16通过，无剩余P0–P3。

Node当前相关65文件763通过，教师脚本按真实practice适配层/控制器和复盘卡片手势/更多动作默认收起修失效源码断言；visual脚本通过。feature-integration原版仍在storage studyStrategy位置失败，未触及该脚本/运行时，登记SHR-03，不能声称小程序所有脚本通过。两新测试各唯一注册CI，本次完整固定473文件8155项通过、64历史warning，readiness69/cloud30新跑通过；334路径OpenAPI复用§321且业务/schema未变，不冒称冷进程重跑。2246后端/测试/CI输入冻结未变。

兼容AI_ANALYSIS_COMPATIBILITY.md新增§16，结果refactor-results/miniprogram-ai-retention-2026-10-30.json，临时证据/tmp/miniprogram-ai-assessment-2026-10-30/。本轮显式六路径提交边界；原有任务/库存/其他脏文档及删除保持未暂存。MP-16 RETAIN；小程序20账本条目全部终态，25页面84消费契约归属已处置，MP-18/19缺陷不冒称修复。nextAdmin有界消费者映射ADM-01..07，再Admin治理/OCR/共享领域。真实与生产验收仍最后，原计划/此前历史保留，四卷100/98/100/19共317记录；最终文档/记忆/保护门禁后才下一轮，无push/部署/用户数据操作。

最终显式六路径已提交 `38f43a215c80d5f5229ee61dc3640eded14262f5`，暂存/工作区/HEAD blob一致，7199路径保护检查通过，index空、author lmh、无AI attribution。记忆增量2026-10-30T16-45-08-postgraduate-mp16-ai-retention.md已写入，最终文档/原文/哈希核验见verification-result.json，protected-after-docs.json为下轮保护基线。传输/身份/考试/番茄钟/知识地图专项已核对，无需修改，不刷新旧验证日期。


## 三百二十四、Admin有界消费者映射（2026-10-30）

按已确认工作流完成一次有限盘点：32页面、275非测试TS/TSX源文件、157静态消费契约、211有限action展开位置，全部对应216个已注册Admin operation中的157个；其余59个保留归属，不宣称外部无调用。18个注入请求位置、8个绑定、SSE/blob和uploaded字面参数已解析；孤立metadata声明单列保留。可能导入可达不是实际调用，查询/请求体与真实浏览器未完整验收。

代码图417模块分页耗尽，330路径分三次coverage耗尽；coverage页遗漏及部分TSX范围由有界AST补齐，0解析错误/0未解析本地导入。330文件哈希冻结，841backend/app输入与§321OpenAPI基线相同，复用334-path快照，非本轮冷生成。没有源码/测试/CI改动，不重复业务测试或完整CI。ADM-01..07转OPEN，映射不提前关闭结构域；下一ADM-01，随后Admin/OCR/共享，真实验收在结构之后、生产最后且另行授权。

说明ADMIN_CONSUMER_MAP.md，结果refactor-results/admin-consumer-map-2026-10-30.json，临时证据/tmp/admin-consumer-map-2026-10-30/。一次独立只读映射审查无P0–P3，独立无写入重算扫描/匹配结果一致、4287原源码/测试/CI路径不变；最终保护/文档门禁完成；原计划/此前历史及工作区改动保持，100/98/100/20共318记录。仅新映射/结果两路径为本地提交边界，既有任务/索引/库存仍未暂存，无push/部署/用户数据操作。

最终显式两路径本地提交 `9f4ba9ddc0362042ff917fee19346f16cb09ea43`，工作区/暂存/HEAD blob一致、author lmh且无AI attribution，index空。记忆增量2026-10-30T17-50-00-postgraduate-admin-consumer-map.md；原文/哈希/链接/容量/工作区保护核验见verification-result.json，protected-after-docs.json为下轮基线。小程序及其他专项兼容文档已核对无需修改，不刷新旧验收结论。


## 三百二十五、ADM-01题库与重审链路保留收口（2026-10-30）

按有界映射核查/questions与/review的17消费契约、4个无当前静态浏览器消费的注册端点。既有查询/筛选/URL/选择、草稿/patch、owner即时写入、历史版本、导出/下载、批量删除及展示组件各有职责，后端保留KP/不可变revision/审计和原事务顺序；不因页面或service长度继续拆分。1116后端/管理端运行时路径保持，ADM-01 RETAIN，其余页面领域不提前关闭。

新增review/page.test.ts直接调用真实页面，以隔离hook/query/request端口捕获三类mutation及四查询；覆盖预览匹配/异题读取、表格门禁、reason差异/有效选择、rollback目标、成功缓存和失败提示，共13项。首轮12通过1失败为新增表格夹具缺requires_review；修夹具后最终143管理端文件1769项通过（本域61文件508项），typecheck通过、lint0错误138警告。该测试不是DOM/effect/React调度或真实浏览器验收。

现有5份后端测试119项通过39.44秒；冻结2246backend/app/tests/.github输入未变，复用§323完整固定CI473文件8155项，非本轮完整重跑。§321OpenAPI334快照同理复用；构建/运行时配置不变未跑build。一次独立只读审查已关闭，具体证据见ADMIN_QUESTION_COMPATIBILITY.md§6与refactor-results/admin-question-retention-2026-10-30.json、/tmp/admin-question-assessment-2026-10-30/。

下一ADM-02导入审核/任务七页整链，再其余Admin/OCR/共享；全部真实环境最后，生产最后且另行授权。原计划/历史与用户工作区改动保留，四卷100/98/100/21共319记录。仅新页面测试/题库兼容文档/新结果三路径提交，任务/索引/库存已有未暂存边界保留；提交元信息与文档/协作记忆/保护门禁已回填，不提前开始下一轮，无push/部署/用户数据操作。

最终显式三路径提交 `8310ad8ae560fc6e4b8b71c4e6538f4926488e96`，暂存/工作区/HEAD blob匹配，author lmh且无AI attribution、index空。记忆增量2026-10-30T18-30-42-postgraduate-adm01-retention.md已写入；最终原文/哈希/链接/容量/保护门禁见verification-result.json，protected-after-docs.json为下轮基线。身份/AI/小程序映射及其他专项兼容文档已核对无需修改，不刷新旧验证结论。


## 三百二十六、ADM-02导入七页整链保留评估（2026-10-30）

按有界映射核查七页31消费契约及12无当前静态消费注册端点，现有审核hooks/reducers/展示、上传/状态/批处理/来源及风险纯规则、答案补录/发布/准入/管线owner保留。1116后端/管理端运行时路径不变，ADM-02 RETAIN；OCR-02/03、SHR-01/02剩余执行/恢复/共享worker结构不提前关闭。

新增19项真实六页面闭包/受控effect/SSE/假时钟契约，覆盖批次单次上传、watchdog/去重/终态/重置/卸载、CSV/PDF分流、有效文本、历史、维护dry-run和URL详情。首轮加载因AuthStore隔离不完整失败（0用例），补mock后19通过；最终管理端144文件1788项，本域46文件412项，typecheck通过、lint0错138警告，未跑build。条件迟响应刻画允许transport在abort后仍fulfill，未证明原生fetch/browser可达，补ENV-02场景，不当已确认线上缺陷。

后端首轮14文件168通过1失败9xfail；SSE live计数器被前组累加导致默认零值断言依赖顺序。仅将默认值检查改为独立runpy模块初始化，未清空或改写live counter。原顺序复跑169通过9xfail1既有warning（56.01秒）；随后新增低风险审核计数刻画，最终两改动文件24通过1.41秒，不冒称一次170项组合。低风险服务已有后项异常扣减此前成功计数的问题，首项published/qid31、后项pending却affected_count0，单列ADM-08 DEFECT，未修业务。

严格Ruff两测试/app及测试compileall/diff通过，一次独立只读审查关闭。固定后端CI§323473文件8155项按2244原输入不变+两份不在固定命令内的测试窄复验复用，非本轮重跑；OpenAPI334快照复用。相同大哈希集合引用已提交§325结果+selector/文件与集合摘要，两例外逐项列出，避免重复复制。旧batch-answer两个CLI import会改DATABASE_URL，未混入pytest或执行，不声明真实JWT/外部图片/生产端到端验收。

说明ADMIN_IMPORT_COMPATIBILITY.md，结果refactor-results/admin-import-retention-2026-10-30.json，证据/tmp/admin-import-assessment-2026-10-30/。下一ADM-03四页整链，再其余Admin/OCR/共享；所有真实环境与生产最后且单独授权。四卷100/98/100/22共320记录；原计划/历史与现有工作区改动保留，显式五提交路径为新页面测试/两后端测试/新说明/新结果，原任务/索引/库存保持未暂存。最终提交/文档/记忆/保护门禁后才下一轮，无push/部署/真实清理/用户数据操作。

最终显式五路径提交 `e3095f50f88cbffc83a388be1e33f132d945e9c4`，暂存/工作区/HEAD blob匹配，author lmh、无AI attribution、index空；7193无关路径保护检查通过。记忆增量2026-10-30T19-10-00-postgraduate-adm02-retention.md已写入；最终原文/哈希/链接/容量/保护门禁见verification-result.json，protected-after-docs.json为下轮基线。身份/AI/小程序映射和其他专项说明已核对无需修改，不刷新旧验证日期。


## 三百二十七、ADM-03知识治理四页保留收口（2026-10-30）

按有界映射核查/coverage、/knowledge-graph、/subjects、/syllabus四页16消费契约及8个无当前静态浏览器请求形状的注册端点。覆盖率保留active版本选择、草稿/已应用阈值、题库当前状态与不可变历史试卷快照双口径；图谱保留有界查询/画布及utils/geometry/layout分工；科目保留独立权限、祖先修复、乐观快照回滚和锁/路径/审计事务；考纲保留draft编辑、六读六写、切version锁、自动映射重建及手工映射保护。1116运行时路径不变，ADM-03 RETAIN，不因服务/页面长度继续拆。

新增15项四真实页面端口/闭包契约，覆盖coverage查询门禁和完整年份、graph总览24/聚焦搜索36预算、syllabus六读六写及依赖失效、subjects根科目确认与祖先乐观更新精确回滚。仅执行适用初始选择effect，不是DOM/React调度/原生fetch/画布指针或mutation库验收。管理端145文件1803项，本域7文件158项，typecheck通过、lint0错138警告；未跑build。后端subject API/service及coverage图像异常兼容3文件32项通过，不冒称图谱/考纲完整事务验收。

coverage/page.tsx被coverage目录规则漏索引，已读完整源码；新测试未入当前代码图。固定后端CI§323的473文件8155项在2246冻结输入仍为2244不变+原两例外时复用，非本轮重跑；OpenAPI334按后端运行时未变复用。严格Ruff/compileall/diff通过，一次独立审查指出两项P3：科目取消等待断言未建异步屏障、图谱空集合先返回与中心404的文档限定不全；只加强现有测试并补限定，业务未改，单文件15项窄复验，不冒称新全管理端重跑。审查内窄复核关闭后才提交。

说明ADMIN_KNOWLEDGE_GOVERNANCE_COMPATIBILITY.md，结果refactor-results/admin-knowledge-governance-retention-2026-10-30.json，证据/tmp/admin-knowledge-assessment-2026-10-30/。下一ADM-04登录/根入口/Admin与App用户/角色/审计六页，之后ADM-05..07、OCR/共享；真实环境全部最后，生产最后且另行授权。四卷100/98/100/23共321记录；原计划/历史/现有工作区改动及删除保留，显式三提交路径为新页面测试/新说明/新结果，任务/索引/库存保持未暂存。无push/部署/真实清理/用户数据操作。

最终显式三路径已提交 `04389a88aa687a8e2e79a5d87055ebbff7f07802`，暂存/工作区/HEAD blob一致，author lmh、无AI attribution、index空；7198无关路径保护检查通过。一次独立审查两项P3已修正并窄复核关闭，独立前端15项/后端32项通过。协作记忆增量2026-10-30T19-53-13-postgraduate-adm03-retention.md已写入；原计划/此前历史/哈希/链接/容量/保护检查见verification-result.json，protected-after-docs.json为下轮基线。身份/AI/小程序映射及其他专项说明已核对无需修改，不刷新旧验证日期。下一ADM-04，不提前生产验收。


## 三百二十八、ADM-04身份用户权限审计链保留收口（2026-10-30）

核查/admin-users、/app-users、/audit-logs、/roles、/login与/六入口18消费契约及7无当前静态浏览器请求形状注册端点。现有根/登录/壳、auth-store和共享client、Admin JWT/refresh安全原语、Admin与App用户服务、RBAC事务/版本缓存、审计净化/读取/展示owner保留；1116运行时路径不变，ADM-04 RETAIN。用户openid与Admin账号/JWT不合并，不因页面长度继续拆。

新增18项真实六页面及壳/详情端口契约：私有LoginForm经实际元素type执行，固定等待登录/安全next/通用错误/守卫、Admin新建与PATCH字段/强退/重置/停用、App5并发分组屏障及部分失败、角色失效等待与单角色覆盖层清理、审计别名与详情ID。重置只测字段，不复制legacy固定值；只执行适用守卫effect，不是DOM/React/TanStack调度、原生fetch/cookie或下载验收。管理端146文件1821项，本域7文件158项；typecheck/lint0错138警告通过，未跑build。

后端初始10文件99项通过（21.32秒）；发现原按分类权限测试实际请求平铺接口，仅将测试改为真正/by-category并补拒绝非super_admin、真实replace_role_permissions等待commit后bump/refresh、成功ID去重排序及403/422回滚不bump。最终改动RBAC单文件7项通过5.78秒，不声称一次103组合；身份矩阵/路由完整性/开发权限另3文件11项通过。严格Ruff改动Python、app项目CI忽略集Ruff、compileall/diff通过。

固定§323 CI473文件8155项与§321 OpenAPI334复用：2246原冻结输入2243保持，§326两例外未变，本轮新增RBAC测试例外不在固定命令且已窄复验7项；不冒称新完整CI。nbf/角色版本和DB提交仍为原副作用顺序，不声称跨Redis/PG原子性。代码图43+10+5+3路径coverage耗尽，改动RBAC元数据过期由实际源码/测试补足，新测试未索引；role trace的SQL select/delete误连按源码拒绝。

说明ADMIN_IDENTITY_COMPATIBILITY.md，结果refactor-results/admin-identity-retention-2026-10-30.json，证据/tmp/admin-identity-assessment-2026-10-30/。一次独立只读审查/显式四路径提交/文档记忆与保护门禁完成后才下一轮。四卷100/98/100/24共322记录；原计划/历史和既有改动及删除保持，任务/库存/索引保持原未暂存边界。下一ADM-05模型配置/推荐/系统任务六页，再其余Admin/OCR/共享；全部真实环境最后，生产最后且单独授权，无push/部署/用户数据操作。

本轮一次独立只读审查两项P3记录问题（冻结输入2243/三例外、Admin两类token共享aud/key而以type区分）已修正并窄复核关闭，无剩余P0–P3；独立前端18项/RBAC7项通过，未重跑全量CI。

最终显式四路径提交 `b71acd31078e8574fa62c31d7591a670b38617aa`，暂存/工作区/HEAD blob一致，author lmh、无AI attribution、index空；7200无关路径保护检查通过。记忆增量2026-10-30T20-33-09-postgraduate-adm04-retention.md已写入；最终原计划/历史/哈希/链接/容量/保护核验见verification-result.json，protected-after-docs.json为下轮基线。原身份/客户端/知识治理/AI/小程序映射专项已核对无需修改，不刷新旧验证日期。下一ADM-05，全部真实环境与生产仍最后。


## 三百二十九、ADM-05模型配置推荐与系统任务链保留收口（2026-10-30）

六页/ai-settings、recommendation的experiments/metrics/reports/strategies及/system/tasks，38归属消费契约与6注册保留端点评估RETAIN；1116运行时路径不变。配置注册/全局设置/向量、策略/实验/指标/质量/健康、任务诊断/调度/备份现有owner保留，不按长度继续拆分。模型稳定ID/软删除/加密掩码、连接测试能力分流、事务/审计/缓存和任务取消/重试语义保持；worker与恢复剩余结构仍由OCR/SHR承接。

新增operations-page-contracts.test.ts16项真实Client页面/VectorConfigSection端口契约；管理端初次147文件1837、本域5/134，typecheck通过、lint0错138既有警告。后端已有13文件138项通过7.37s；app Ruff/compileall/diff通过，未改Python/运行时/构建配置，未跑build。页面替身未证明React/TanStack完整调度、DOM/nativefetch/JWT；策略保存仅请求端口，纯表单规则由旧helper测试约束。

登记ADM-09 DEFECT：真实admin_tasks.cancel_task在获取pooled client后hgetall抛RuntimeError时，执行不到显式aclose；隔离探针观察await_count0，未证明真实Redis池耗尽，未修业务。固定CI§323473文件8155/OpenAPI§321334路径按逐项哈希核对复用，非本轮新跑；原2246冻结输入2243不变+既有3固定命令外例外，未新增例外。一次独立审查一项日期窗口P3已修正并窄复核关闭，独立最终16通过，无剩余P0–P3。

兼容说明ADMIN_OPERATIONS_COMPATIBILITY.md，结果refactor-results/admin-operations-retention-2026-10-30.json，证据/tmp/admin-operations-assessment-2026-10-30/。显式提交路径限新页面测试/新说明/新结果；任务/索引/库存保留原未暂存边界。四卷100/98/100/25共323记录，原计划和旧历史原文保留。审查/提交/文档/记忆/保护收尾后下一ADM-06公式/资源/考试六页，再ADM-07、OCR/SHR；ENV-01..06均WAITING-FINAL，生产最后且另行授权。

审查指出日期窗口仅格式断言的P3后，冻结合成时钟，精确检查对比/安全检查近30天区间；同16项最终窄验、typecheck与单文件ESLint通过。初次1837使用旧testSHA，最终新SHA的16项复验另列，未伪称新全套。

最终显式三路径提交 `930c4d279ee68e9bbeb7fa861bbffaeec667e38e`，暂存/工作区/HEAD blob一致、author lmh、无AI attribution、index空；7204无关路径保护通过。一次独立审查日期窗口P3已关闭、独立最终16通过；初次全套与补强后窄验SHA分开记录。记忆增量2026-10-30T21-09-30-postgraduate-adm05-retention.md已写入，最终原计划/旧历史/容量/链接/哈希/保护检查见verification-result.json，protected-after-docs.json为下一轮基线。原身份/导入/知识治理/AI/客户端兼容说明及映射已核对无需修改，不刷新旧日期。下一ADM-06，全部真实环境与生产仍最后。


## 三百三十、ADM-06公式审核规则与内容管理整链收口（2026-10-30）

六页/exams、/exams/[id]及/formulas、/formulas/[id]、/formulas/new、/formulas/categories，共32归属消费契约/19注册保留。共享公式审核状态/字段规则从admin_formulas迁入formula_review_rules，104行、最长函数30；旧_apply_formula_action签名和路由utcnow查找保持，两审核入口仍动态引用旧helper。其他39路由函数AST不变，快照/审计/flush/commit与逐项错误分类不改；其余CRUD/版本、图资源/spec/batch/storage及考试既有owner保留。ADM-06 DONE，真实环境尚未验收。

迁移前相关9文件218项，迁移后新17规则契约合10文件235项通过；有限126状态/动作/原因组合返回/错误/字段/写入序等价。新增真实六页/图组件端口19契约；管理端初次148文件1856、本域6文件152，后补精确题目错误断言后同19/typecheck/单文件ESLint窄验通过。全域lint0错138警告，未改前端运行时/构建配置，未跑build；初次全套旧SHA与最终新SHA窄验明确分开。

本轮实际修改后端运行时/CI：新测试登记固定清单，完整474文件8172项/64警告新跑通过860.59s（进程墙钟866.68s），2248冻结输入前后一致；原基线用5覆盖/2新增项重建，不复制同份哈希清单。全应用冷OpenAPI对照相等334路径，readiness69/cloud30通过，严格改动Python Ruff/app Ruff/compileall/diff通过。相邻真实PG/Redis/存储/浏览器仍未验收；前端旧不足40可发布提示不作为当前后端严格40题规则的验收依据，分支真实可达性未测。

内容兼容说明ADMIN_CONTENT_COMPATIBILITY.md，结果refactor-results/admin-content-refactor-2026-10-30.json，证据/tmp/admin-content-assessment-2026-10-30/。一次独立只读审查完成，无P0–P3发现，独立后端51/前端19通过；显式提交路径为变更路由/新规则/新规则测试/新页面测试/CI清单/新说明/新结果七项。任务/索引/库存保持原未暂存边界；四卷100/98/100/26共324记录，原计划/旧历史/现有工作区与删除保留。本轮审查/提交/文档/记忆/保护门禁后才下一ADM-07 dashboard单页五契约，再OCR-02/03、SHR-01..03；所有ENV仍WAITING-FINAL，生产最后且另行授权。

最终显式七路径提交 `adb538bdd1f367a9dcb353056b16bc49e3891adc`，暂存/工作区/HEAD blob一致、author lmh、无AI attribution、index空；7205无关路径保护通过。一次独立审查无P0–P3发现，独立后端51/前端19及126组合/39AST核对通过。记忆增量2026-10-30T22-02-08-postgraduate-adm06-review-rules.md已写入；最终原计划/旧历史/容量/链接/冻结重建/保护检查见verification-result.json，protected-after-docs.json为下一轮基线。原Public公式/考试、Admin身份/运行/导入/知识治理及映射说明已核对无需修改，范围差异由新Admin内容兼容说明承接，不刷新旧验证日期。下一ADM-07，全部真实环境/生产仍最后。


## 三百三十一、ADM-07仪表盘整链保留收口（2026-10-30）

§331 ADM-07仪表盘单页5归属契约及1条ADM-05共享任务诊断评估RETAIN，3注册端点保留；现有SQL/缓存/纯规则/图表owner不变，新增9页面契约。管理端149文件1865/本域2文件49、后端3文件34及静态检查通过；1117运行时/2248CI输入/330映射源哈希核对一致，固定CI8172/OpenAPI334/readiness69/cloud30复用§330，非本轮新跑。

页面请求的身份/bootstrap门禁、上海跨日7/30日区间、AI固定7日、query配置、刷新allSettled与busy结束屏障已刻画。Admin与学习统计口径、概览锁/缓存/回退、daily日期序列化/分桶、Admin ready与基础设施readiness区别保持，不因长度继续拆分。替身测试不证明真实React/TanStack/DOM、JWT、PG/Redis或多worker。

说明ADMIN_DASHBOARD_COMPATIBILITY.md，结果refactor-results/admin-dashboard-retention-2026-10-30.json，证据/tmp/admin-dashboard-assessment-2026-10-30/。一次独立审查无P0–P3，独立9项通过；显式提交限新页面测试/新说明/新结果三路径，任务/索引/库存保留既有未暂存边界。四卷100/98/100/27共325记录，原计划/旧历史保留。先完成审查/提交/文档/记忆/保护门禁，再OCR-02/03有界映射及SHR-01..03。Admin有界结构条目终态不等于全部行为验收，ADM-08/09仍DEFECT，所有ENV仍WAITING-FINAL，生产最后且另行授权。

最终显式三路径提交 `38a5474f4d898a0311c643bb846aef1fb8a665c9`，暂存/工作区/HEAD blob一致、author lmh、无AI attribution、index空；7212无关路径保护通过。一次独立审查无P0–P3，独立9项通过。记忆增量2026-10-30T22-28-30-postgraduate-adm07-dashboard-retention.md已写，最终原计划/历史/容量/链接/冻结重建/保护检查见verification-result.json，protected-after-docs.json为下一轮基线。原专项和映射文档已核对无需修改，不刷新旧验证日期；下一OCR-02/03有界映射，所有真实环境/生产仍最后。


## 三百三十二、OCR导入恢复与worker有界消费者映射（2026-10-30）

OCR-02/03完成有界映射：Admin导入、Public导入、内部OCR worker、v2任务、上传分流、Public/Admin恢复、OCRGateway执行后端与coordinator shadow模式分层归属。39源、376注册operation、Admin31/Public7/内部8路由、6类v2任务；小程序538源无直接静态导入消费。

新登记OCR-04 DEFECT：daemon artifact上传路径在当前APIRouter未注册，隔离ASGI404；未证明真实部署影响或外部服务承接。映射只读，未改运行时/测试/CI，未重跑全CI；真实OCR/PG/Redis/多worker仍最后验收。说明OCR_CONSUMER_MAP.md及结果清单；一次独立审查无P0–P3；审查后清理误放仓库根目录的11个证据快照文件，显式两路径提交/文档记忆收尾后再逐项处置OCR-02/03结构条目。

最终显式两路径提交 `25e40e47449175d0400c64ba686e095849979619`，暂存/工作区/HEAD blob一致、author lmh、无AI attribution、index空；7215无关路径保护通过。一次独立审查无P0–P3并支持提交。中断后发现的11个图检索/快照临时文件曾误放仓库根目录，提交前已移回证据目录，未影响业务/映射文件。记忆增量2026-10-31T00-26-55-postgraduate-ocr-consumer-map.md已写，最终原计划/历史/容量/链接/哈希/保护检查见verification-result.json，protected-after-docs.json为下一轮基线。下一步逐项处置OCR-02/03结构条目，OCR-04修复另行授权；真实环境/生产仍最后。


## 三百三十三、OCR-02诊断工件与后台编排保留收口（2026-10-31）

按§332映射逐项处置OCR-02：27阶段元数据、single-pass、chunked、resume、artifact schema v5、stage checkpoint、图片与通用后台、worker v2六类任务和coordinator现状均保留。19个相关源哈希与映射基线一致，`pipeline_orchestrator.py`仍4003行但已由独立模块、签名/AST边界和架构门禁约束，不因长度重拆。coordinator默认shadow，legacy仍是执行路径；coordinator模式Correction/Validation/Persistence未实现，只登记现状，不作为迁移目标。

定向运行`backend/tests/pipeline`及checkpoint/artifact/single/chunk/resume/background/image/worker-v2选择集合，1078项通过81.69秒；Ruff app、compileall和diff通过。无运行时/测试/CI改动，未重跑全量固定CI/OpenAPI/readiness，不冒称新全量结果。真实外部OCR/AI、Redis检查点恢复、多worker并发和大文件内存仍归ENV-03..06；OCR-04 artifact路径缺口独立保留DEFECT，未修复。

说明OCR_BACKGROUND_RETENTION.md，结果refactor-results/ocr-background-retention-2026-10-31.json，证据~/.cache/postgraduate-ai/refactor/2026-10-31-ocr02/。一次独立审查发现4项记录问题，修正后以相同选择集合复验1078项通过，窄复核确认P0–P3关闭且无新增发现。下一OCR-03专用上传、Public/Admin恢复和任务接口，再SHR-01..03。四卷100/98/100/29共326记录；原计划/旧历史/既有工作区改动和任务文件未暂存边界保留，无push/部署/用户数据操作。审查/显式提交/文档记忆/保护门禁完成后才下一轮。


## 三百三十四、OCR-03专用接口保留收口（2026-10-31）

按§332映射处置OCR-03：共享上传准入、Public chunk恢复、Admin stage恢复、批量图片、内部OCR worker协议、v2任务接口和真实环境缺口均给出终态。Admin/Public上传继续共用`start_import_pipeline`，Public恢复重放pending chunks，Admin恢复读取stage checkpoint/artifacts后重新上传并入队，两者不合并；批量图片与内部租约worker协议继续由现有owner持有。

20个相关源哈希与§332映射完全一致。定向16文件253项通过51.61秒，包含上传准入31项、Public/Admin等价与恢复、Admin接口、批量图片、OCR job状态机和worker v2接口；1个既有AsyncMock RuntimeWarning，不冒称环境验收。Ruff app、compileall和diff通过。无运行时/测试/CI改动，未重跑全量固定CI/OpenAPI/readiness。

说明OCR_INTERFACE_RETENTION.md，结果refactor-results/ocr-interface-retention-2026-10-31.json，证据~/.cache/postgraduate-ai/refactor/2026-10-31-ocr03/。OCR-03 RETAIN；OCR-04独立DEFECT未修复，真实浏览器/OCR/PG/Redis/多worker归ENV-02..05。下一SHR-01..03有限映射。四卷100/98/100/30共327记录；原计划/旧历史/既有工作区改动和任务文件未暂存边界保留，无push/部署/用户数据操作。审查/显式提交/文档记忆/保护门禁完成后才下一轮。

§334收尾：一次独立只读审查无P0–P2，两项P3（v2任务接口“6类”未枚举、结果JSON含本机绝对路径）已修复并复核关闭，结果JSON内联16个选择文件。两路径已提交`1c9892ca`；未暂存任务文件、既有删除与诊断文本保留，无push/部署/用户数据操作。


## 三百三十五、SHR-01..03 共享门禁与生命周期盘点（2026-10-31）

一次有界盘点把三条 `PENDING-MAP` 转为终态。SHR-01（L3）：dispatcher 共9类任务，`FENCING_TABLES` 仅注册7类，`answer_projection`/`error_diagnosis` 未围栏；是否有意待确认，新增静态刻画并入 CI 清单内的 `test_task_queue_protocol_boundaries.py`（20项通过），协议保留。SHR-02（L3）：`main.py` 在 `PROCESS_ROLE=scheduler/all` 经 HTTP 路径启动 scheduler，缺答案投影对账与调度健康监控，关停宽限固定30s，outbox 失败仅告警；生产 scheduler 服务运行 `python -m app.scheduler_main`，不经该路径，未改运行时，登记 DEFECT。SHR-03（L1）：`test-408-feature-integration.js` 7处过时源码位置断言改指向当前模块，脚本及另6个小程序 Node 脚本通过。

独立审查无P0–P2，4项P3（storage 断言偏弱、负向断言覆盖缩小、注册表子集断言、账本过时语句）已修复并复验。提交 `593349e6`。该 Node 脚本不在后端固定 CI，未重跑固定 CI/OpenAPI/readiness。真实租约/围栏竞态与多角色行为归 ENV-05。四卷100/98/100/31共328记录；未暂存任务文件与既有改动保留，无 push/部署/用户数据操作。

## 三百三十六、六项已登记缺陷修复（2026-10-31）

用户授权修复 MP-18、MP-19、ADM-08、ADM-09、OCR-04、SHR-02，每项先写失败测试（RED）再修复（GREEN），一次独立只读审查关闭 P0–P3，同步对应架构说明/结果清单与账本行，显式路径单独提交，无 push。

- ADM-09 `160f9afc`：`admin_tasks.cancel_task` 的 `hgetall` 移入 try/finally，异常时仍 `aclose`。
- ADM-08 `34442e61`：删除低风险批量审核中后项失败扣减此前成功计数的语句；新增与失败顺序无关的参数化计数测试。
- MP-18 `f3c1bdf6`：两处冻结名回退查询加 `select_from(KnowledgePoint)`，新增真实 SQLite 排序测试与 sqlite/postgresql 编译断言，测试入 CI 清单。
- MP-19 `1fbf683f`：`knowledge-detail.loadDetail` 记录请求 ID，成功与失败分支均在页面卸载或 ID 已变时丢弃迟到响应；17 项 Node 契约（含失败切换与重试）。
- OCR-04 `24766b08`：新增 `ocr_artifact_service` 与 `POST /api/internal/ocr-worker/artifacts/upload`，流式解码 daemon 的 hex-JSON，临时文件+SHA 校验+原子替换，租约/持有者/过期授权，发布前复核防 TOCTOU，存储错误 503；新增 `OCR_WORKER_ARTIFACT_DIR`/`OCR_WORKER_ARTIFACT_MAX_BYTES`，39 项测试入 CI。代理请求体上限与产物清理/配额未验证。
- SHR-02 `74825ae8`：HTTP scheduler/all 角色补启答案投影对账与调度健康监控（非致命），关停清单加入两者，`cancel_and_wait_runtime_tasks` 接受 `grace_seconds` 并由 `main.py` 传入 `WORKER_SHUTDOWN_GRACE_SEC`。审查无 P0/P1；P2 两项（启动后崩溃不可见、宽限与部署 stop grace 关系）入文档，P3 四项（日志改惰性参数、测试只替换 `asyncio.wait`、对等测试改集合比较、文档措辞与审计/指标失败策略差异）已修。`tests/core`+`tests/architecture` 2729 通过，仅两项既有 SHR-03 旧源码门禁失败。

真实 PG/Redis/微信/worker 行为仍归 ENV-01..06。下一步：完整 standard 安全审计。四卷100/98/100/32共329记录。


## 三百三十七、安全审计 11 项已确认发现修复（2026-10-31）

用户要求先修复审计发现、暂不开始 ENV-01..06。每项先写失败测试（RED）再修复（GREEN），显式路径单独提交，无 push；生产 nginx/镜像尚未同步。

- 头像解压炸弹（high）`633d1ee6`：`load()` 前按头部尺寸（单边4096/1600万像素）拒绝，损坏图片异常统一映射为 ValueError；审查指出 `catch_warnings` 非线程安全已移除。
- XFF 伪造 `4f5f3a03`：`deploy/nginx/nginx.conf` 与 `backend/docker/nginx.conf` 全部 location 改 `X-Forwarded-For $remote_addr`；`--forwarded-allow-ips=*` 保留，依赖 app 端口仅绑 127.0.0.1。**生产需 `--force-recreate nginx` 才生效，待授权。**
- 管理员锁定 `9eb2cfc9`：锁定期间校验口令前直接 429。
- 改密吊销 `81113442`：水印取变更时刻而非操作者 token iat。
- RAG `067bf6fe`：restricted 环境不挂载路由并加 404 守卫。
- 同步 `54e53b4d`：`review_status`/`is_active` 仅 `question:review` 持有者按 `_REVIEW_ALLOWED_TRANSITIONS` 生效，否则新题 re_pending/inactive、旧题不变；成功提交写 `sync.import` 审计。
- 水印 ReDoS `fa721b2d`：按正则语法树拒绝重复组内分支/变长重复，非 exact 类型一律校验，未知 rule_type 拒绝，匹配前截断单行。
- AI 额度 `87280779`：`analyze_error`/`generate_advice` 复用 `check_token_limit`，超限 `ai_quota_exceeded` 不可重试。
- 刷新/登出竞态 `d79e002b`：轮换后重读水印，被推进则吊销后继令牌返回 401。
- OCR 完成绑定 `70ed80e6`：HTTP complete 校验规范键、文件存在、大小、SHA、JSON 对象，不符 409。
- 账号注销 `5c33ffa4`：用户选择"匿名化+清除"并含 12 个月匿名化。注销即改写 openid；6 小时清理任务清除全部 `user_id` 表与导出文件；365 天不活跃仅匿名化登录标识。已封禁账号保留 openid 且不清除。

遗留/未决：后台 app-user 列表仍显示墓碑账号；注销后同 openid 可重新注册（非封禁用户）；不活跃判定仅看刷新令牌与练习记录；清理任务锁 TTL 300s 可能短于大批量；6 项 needs_validation 未处理（admin `question-options.tsx` innerHTML、PaddleOCR-VL SSRF、公式图整数幂、导出 WS `?token=`、OCR 产物保留、Dockerfile `--trusted-host`）。回归 2786 通过。四卷100/98/100/33共331记录。


## 三百三十八、安全审计 6 项 needs_validation 处理（2026-10-31）

用户要求"处理这六项中的全部"，仍不开始 ENV-01..06。每项 RED→GREEN，显式路径单独提交，无 push。

- admin 选项图片 innerHTML `e01a7a77`：失败提示改 React 状态渲染，源码禁 innerHTML 守卫。
- PaddleOCR-VL 结果 URL `644e960a`：拒绝内嵌凭据，仅允许全局可路由且非组播地址（`safe_remote_fetch` 同步）；DNS 重绑定连接钉住未做，残余风险。
- 公式图整数幂 `ae9e63a6`：sympify 前按子树对数规模估算，指数 >10^6 或估算结果 >1000 位拒绝。
- 导出 WS 令牌 `b511d111`：小程序改 `protocols: ['bearer', token]`，URL 不再带 token；此前生产默认拒绝 `?token=`，推送实际一直退化为轮询。
- OCR worker 产物 `1febc539`：发布前统计总量，超 `OCR_WORKER_ARTIFACT_TOTAL_MAX_BYTES`（2GiB）返回 507；`staging_cleanup` 清理超 `STAGING_RETENTION_SEC` 产物与超 1 小时临时文件。并发上传配额无锁。
- Dockerfile pip `bdccdabe`：移除 `--trusted-host`，测试防回退；依赖哈希锁定未做（需联网生成锁文件），残余风险。

生产 nginx/镜像仍未同步（待授权）。四卷100/98/100/34共332记录。

## 三百三十九、遗留项处理与生产部署（2026-10-31）

- DNS 重绑定 `71032186`：新增 `services/safe_httpx.py`（`PublicOnlyBackend` 连接时解析、校验并连接到同一公网 IP，TLS 仍校验原主机名），OCR-VL 结果下载改用该客户端（`trust_env=False`）。
- 依赖哈希 `3e3ec2c3`、`c0687b9d`：`backend/requirements.lock`（Python 3.11/linux，以生产 pip freeze 为约束、按阿里云镜像解析），`docker/Dockerfile` 用 `--require-hashes --no-deps` 安装。首次按 pypi.org 解析因镜像未同步 websockets 17.4 构建失败，已修正；早先"与生产一致"的判断只核对了部分包，后经全量 diff 修正。
- 并发上传 `3e85a368`：配额检查与原子替换放入 `.quota.lock` 的 `flock` 临界区。
- 生产部署（范围：仅安全修复文件，用户选择）：打 `pre-sec-20261031` 回滚标签；rsync 25 个文件（先逐文件比对服务器版本==修复前）；构建 app/scheduler/worker/admin；冒烟导入通过；替换容器；`--force-recreate nginx`（XFF 已生效）。**未部署**：`ai_service.py`/`analysis_responses.py` 的 AI 额度修复（服务器缺 `services/ai/` 重构，需随重构一并发布）。

## 三百四十、全量重构代码部署生产（2026-10-31）

用户要求把其余未发布重构文件一并部署。部署前：本地 compileall/ruff/tsc 通过，alembic head 与生产一致（`v19_pomodoro_subject_allocations`，无新迁移），`--delete` 干跑确认 backend/app 与 admin-frontend/src 无需删除文件。打 `pre-refactor-20261031` 回滚标签（`pre-sec-20261031` 仍在）；rsync 547 个文件（排除未跟踪的 `backend/service_compatibility.py`），复跑干跑差异为 0；构建 app/scheduler/worker/admin 通过；镜像内导入、`pip check`、alembic heads 冒烟通过；替换四个服务并 reload nginx。验证：`/health/ready` ok，公网 live 200，admin 307→/dashboard，未登录 API 返回应用 JSON 403；部署后约 5 分钟 nginx 无 5xx，app/scheduler/worker 无 ERROR。AI 额度修复 `87280779` 随本次上线。小程序与 ENV-01..06 仍未执行。

## 三百四十一、小程序运行错误修复与最终环境验收规划（2026-10-31）

用户授权修复小程序报错、操控微信开发者工具验收刷题/错题链路，然后执行ENV-01..06最终环境验收规划；生产参考明确指定 `docs/project/DEPLOY_PLAN.md`。

- 修复 `pomodoro-task-types.js` 九个重复函数声明；严格语法回归先失败再通过，保留原单份行为。实际模拟器又发现 `practice.js` 使用未定义的 `filterSubjectTree`；改为传入已导入的 `filter408SubjectTree`，真实Page加载回归先RED后GREEN。同步精确架构模板并增加拒绝错误简写的断言。
- 工具 `2.02.2607271` / SDK `3.10.3`：通过官方MCP连接，核对Windows镜像后仅同步两处业务修复。独立验收副本使用本地API与临时SQLite合成数据；原项目正式API配置已恢复。开发登录不当作真实微信登录。
- 实际交互与数据库：刷题4题、2对2错、50%；4条practice_records/1个practice_session/2条wrong_questions。错题列表、详情、掌握及取消掌握、手工计算错误标签、返回与重新编译持久化通过。将一条合成调度置到期后完成复习1题，结果100%，review_sessions/review_records各1，repetitions=1。4条outbox未验证消费者，不当作投影完成。
- 本地证据：533个运行时JS严格解析通过；相关89个Node脚本首次88过/1精确模板差异，模板更新后边界+科目加载13项窄复验通过；任务类型新回归及配置/渲染/多空题等通过。旧 `test-pomodoro-practice-stats.js` 仍29通过/12源码断言失败（退出1），保留限制，不声称全仓CI通过。
- 完成[六阶段规划与执行记录](../../../docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md)及[结构化结果](../../../docs/architecture/refactor-results/miniprogram-environment-acceptance-2026-10-31.json)。原始MCP、截图、测试、DB计数在 `~/.cache/postgraduate-ai/acceptance/2026-10-31/`。ENV-01 PARTIAL，其余WAITING-FINAL。
- 新跑生产只读预检：公网live200、首页跟随至dashboard200、匿名users/me403 JSON；没有生产登录、部署、迁移、备份/恢复或回滚。本机Docker/psql不可用，外部服务/多worker/真机未验。独立审查、本地提交与上传均未执行。当前HEAD `c0687b9d`，本地origin/main ahead0；既有未暂存/删除/未跟踪边界保留。

## 三百四十二、自由计时上限回调修复与番茄钟验收（2026-10-31）

用户补报番茄钟启动计时和恢复会话的 `options.maxMs is not a function`，要求修复后继续。控制器按回调读取上限，`buildFreeTimerLimitPageCapabilities` 原注入数字；仅将该属性改为 `() => FREE_TIMER_MAX_MS`。原恢复和轻同步的数字契约不变，未改后端/API/schema。

- 在现有适配器契约和恢复测试加入三个真实适配器/控制器连接回归，修复前三项均因同一TypeError失败（15项中12过/3失败）；修复后定向79项通过。番茄钟137个独立Node脚本全部退出0，540个已跟踪第一方运行时JS严格Babel解析通过。§341旧 `scripts/test-pomodoro-practice-stats.js` 的12项源码断言失败未治理、本次未重跑；不声称全仓CI通过。
- 核对两个Windows镜像适配器与HEAD一致后备份、只同步一处业务修复并比对SHA256；原项目 `LOCAL_DEBUG=false` 保持。实际操作继续使用独立验收项目、开发登录、本地API和SQLite合成数据。
- 自由计时启动/暂停/继续、跳转刷题再返回、结束确认/取消/在线结束通过。暂停会话与运行会话分别重新编译，从新运行时首页重进后恢复同一会话；编译期间旧页读数不作通过证据。
- 隔离API进程短时暂停超过30秒请求超时：页面空闲、本地1条complete保留、服务端paused；恢复API后队列清空、会话completed，重复排空未增加会话。最初wx.request模拟未产生预期失败回调，不计通过，模拟已撤销；故障只作用于本轮临时API，进程已恢复。
- 将第三个合成会话起始时间移到五小时上限前，经真实API读取/页面恢复，显示04:59:50后由真实计时器自动结束；服务端actual_duration18000秒、completed，页面空闲。三个合成番茄钟会话均已完成。不是五小时连续运行或真机证据。最新控制台未检出目标运行错误。
- 更新[规划](../../../docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md)，补建此前已引用但未落盘的[结构化结果](../../../docs/architecture/refactor-results/miniprogram-environment-acceptance-2026-10-31.json)。原始证据新增pomodoro前缀日志/JSON与截图，位于§341同一本地证据目录。ENV-01仍PARTIAL，其他阶段WAITING-FINAL；真实微信/HTTPS/真机与刷题请求恢复等仍待验。
- 继续补刷题未答/网络恢复：全部4题未答禁止交卷；答1题留3题确认与取消正常。隔离API暂停超过30秒请求超时，保存同一request_id和pending快照；恢复API重试后显示1对0错3跳过，仅新增1会话/1答题/1outbox。累计5答题/2会话/5outbox，错题仍2；任务消费未验。新增practice前缀证据与结果截图，关闭本地请求超时恢复子场景；响应丢失、多空题UI与真机仍待验，不扩大为PG幂等/并发证据。
- WSL与Windows均未找到Docker/psql，Windows无pg_ctl；WSL有redis-server但相关PG/Redis测试端口未监听。未提前执行生产验收；无提交、推送、上传、生产部署/迁移/回滚。自审已完成，独立审查未执行。本次未改API/数据/渲染架构，专项说明无需同步；未写系统记忆。四卷容量100/98/100/38，共336条记录。

## 三百四十三、隔离学习链续验、PG/Redis与进程恢复（2026-10-31）

延续用户“修复番茄钟链路报错后继续”的授权，保留§341/342三处小程序修复，不扩大到Admin审计业务修复或生产操作。生产仍参考指定DEPLOY_PLAN；本节为隔离技术验收，不将后序证据当作前序门禁已关闭。

- 多空题通过question_imports与人工审核发布：仅选空1完整作答计数0；完整选择A/B后1答1对，落库 `1:A;2:B`。探索中部分选择交卷曾有0作答完成会话，按未答统计，不能泛化单选全未答阻止规则。故障网关在上游200后丢响应，同request_id/同body哈希重试成功，最终只有一会话/一答题。SQLite最终8答题/6会话/3错题、1复习会话/记录、3个已完成番茄钟、8条pending outbox；不是6次全部成功用例，也没有这些outbox的消费证据。
- Chromium155.0.8059.12/Admin3000/API8000实际登录/RBAC：super_admin管理员/角色接口200，admin/user403，受限菜单隐藏入口。最终受控首轮两个读请求同时401，refresh仅一次200、重试均200；不是自然令牌到期。登录和人工审核未写audit_logs，只有system.init_super_admin，ENV-02记PARTIAL-AUDIT-FAIL；角色审计/导入SSE、轮询归属与fetch/body取消/迟响应仍未验。
- 从证据目录解包PG15.19/pgvector0.8.7，启动回环5433与Redis7.2.5/6380；不用Docker，不复用生产。空库迁移8、PG/Redis集成22项零失败零跳过，current=head=v19_pomodoro_subject_allocations；同request并发唯一胜出、payload冲突、事务/outbox回滚、番茄钟advisory/行锁、Redis严格缓存失败关闭与恢复均有真实证据。番茄钟PG测试夹具补pytest_asyncio.fixture、V19分摊表、合法408科目和UTC时间；未改后端业务。
- 未修改的用户/Admin刷新ASGI接口分别连接真实PG/Redis，各同token并发8次得到1个200/7个401，旧token重放401，后继token200；用户token共3枚、1枚有效。不是初始微信登录或HTTPS网关验收。
- ENV-05选定测试：队列/PG围栏29、Redis实际SIGKILL重启6、队列硬化23、worker进程恢复2项均通过。SIGTERM排空，SIGKILL后真实等待默认约600秒租约，替代worker接管，旧owner操作拒绝；两例648.94秒。两个原生worker_main与一个scheduler_main分别领取9001/9002任务，outbox均published/队列completed，学习行为、复习、掌握度和难度投影收敛，进程退出0。独立PG夹具不与模拟器8条outbox混算。
- PG合成源含2答题/2pending outbox，导出repeatable-read快照并pg_dump→新库pg_restore；81表逐表数据哈希、70序列、迁移/pgvector一致。323约束/385索引仅窄规范化varchar数组转text数组；12CHECK/1部分索引再逐项验证允许值/非法值/NULL，语义相同，原SQL哈希差异保留。信息模式735CHECK包含NOT NULL，pg_catalog显式CHECK51，禁止混淆。另真实enqueue_v2→Redis SAVE/RDB→新进程，全部key类型/值哈希、TTL/两任务pending状态一致。不是生产或跨存储原子时间点恢复。
- 六份XML共90项选定集成测试无失败/错误/跳过。PG客户端库路径、初始原SQL差异、备份报告打印异常及浏览器定位/观测/扩大故障注入的无效尝试均保留并排除；修正探针后才记录通过。原始MCP、日志、截图、JSON在本地持久证据目录；33份owned运行日志/证据和六份复现脚本已归档，PG/RDB/SQLite备份权限受限。未删除验收数据。
- [规划](../../../docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md)、[结果](../../../docs/architecture/refactor-results/miniprogram-environment-acceptance-2026-10-31.json)、context/任务入口/账本同步。ENV-01 PARTIAL，ENV-02 PARTIAL-AUDIT-FAIL，ENV-03/05 PASS-ISOLATED（限定技术检查通过，前序最终门禁未关闭），ENV-04/06 BLOCKED。下一步需要真实身份/HTTPS/真机、审计修复范围、导入迟响应与受控AI/OCR/存储/WS；生产窗口/授权/真实备份及回滚仍最后处理。

本次源码已自审，独立审查未执行；旧番茄钟脚本12项源码断言失败保留，不宣称全仓CI。三份Windows业务文件与WSL/验收副本最终SHA一致，原LOCAL_DEBUG=false保持。HEAD仍c0687b9d，无提交/推送/上传或生产部署/迁移/恢复/回滚；用户原有改动、删除、诊断文本保留，不写系统记忆。收尾15项番茄钟连接复验、后端夹具Ruff/编译与diff-check通过；7251个非本次文档路径哈希未变、65个文档链接通过。临时API/Admin/PG/Redis已优雅停止，3000/8000/8001/5433/6380均关闭，数据与脱敏日志保留，见runtime_cleanup。四卷容量100/98/100/39，共337条记录。

## 三百四十四、Admin角色审计与导入页新旧任务归属（2026-10-31）

继续ENV-02的隔离浏览器/API验收，不修改Admin业务代码、审计实现或外部服务。目标仍是查明最终门禁是否具备真实证据，而不是用测试网关替代真实OCR成功路径。

- 通过未修改的Admin API用合成账号创建管理员，从user角色改为admin后停用；`audit_logs`实际新增`admin_user.create`、`admin_user.update`、`admin_user.delete`，角色变更审计子场景通过。停用合成账号，凭据未写入证据或输出。登录和人工审核仍只更新业务字段、没有审计，既有失败项不因角色审计通过而关闭。
- 批量图片导入页在真实Admin UI验证：上传完成后挂起旧任务status和SSE，点击“停止并重置任务”，发起新批次，再释放旧响应。旧status/SSE均记录`net::ERR_ABORTED`；新批次显示new.png、成功4题和NEW_CURRENT_EVENT；晚到old.png、成功77题及OLD_STALE_EVENT均未出现。截图与结构化证据保留，证明轮询阶段取消和重置后新旧任务归属。
- 初查用Playwright挂起upload并在页面卸载后导航，未观察到upload `requestfailed`；保留为未证而不据此通过。随后增加8002本地原生HTTP网关：reset时网关从socket读取端分别观察到旧status/SSE EOF；upload响应挂起时导航离开，同样观察到upload EOF。原生取消通过，仅`queuePhase=uploading`无可见停止/重置按钮仍作为交互缺口。登录/人工审核审计仍使ENV-02总体`PARTIAL-AUDIT-FAIL`。
- 刷新失败场景将首个dashboard请求和refresh均注入401：页面跳至`/login?next=%2Fdashboard`，access token与refresh cookie均清除，未继续显示dashboard，通过。合成状态只作用于隔离API。
- 初次归属检查因失败请求URL含API前缀导致路径判定错误，另一次因在进入轮询后才读取停止按钮造成“上传阶段可见”语义误导；两者原件均保留并排除，修正判据后仅采用旧status/SSE实际`net::ERR_ABORTED`和新旧渲染结果。没有修改前端/后端代码。
- 更新验收规划、结构化结果、context、任务入口和账本；证据新增`env02-role-change-audit.json`、`env02-import-reset-ownership-summary.json`、原始导入探针JSON和截图。临时Admin/API在收尾时关闭（3000/8000均不监听），证据与合成数据库保留；未提交、推送、上传或执行生产操作。自审完成，独立审查未执行；四卷容量100/98/100/40，共338条记录。

## 三百四十五、专用身份、外部服务及生产只读就绪核查（2026-10-31）

用户继续要求完成剩余ENV验收。本节只核查能否安全进入真实环境场景；未把工具已登录、配置变量存在或公网入口存活当作阶段通过。

- 微信开发者工具桥接可用且登录未过期，但当前登录没有被文档/配置确认为专用测试身份，也没有已确认的测试AppID/账号映射。`.env.ci`虽存在WeChat变量名，不能据此认定可安全使用；未发起`wx.login`到后端的身份交换，未持久化账号资料。为避免真实用户openid进入测试，ENV-01继续PARTIAL；证据`env01-identity-readiness.json`。此外发现并用脱敏方式修正本地MCP证据中的登录资料字段，不写入仓库或最终输出。
- ENV-04只读检查隔离SQLite：`admin_ai_model_configs`没有启用项，OCR远程8080不可达，测试存储相关变量为空，未配置测试WS网关；故没有伪造AI/OCR/文件/WS成功路径，阶段继续BLOCKED。证据`env04-external-readiness.json`。
- ENV-06无凭据公网只读：`www.xzshub.top` DNS指向101.33.231.186，TLS1.3证书有效期约剩80天；匿名`/health/live` 200、首页200、受保护`/health/ready`由nginx 403。只证明公网入口存活，不证明镜像、迁移、worker、数据库、备份或回滚；阶段继续BLOCKED。证据`env06-production-public-readonly.json`。
- 同步验收规划、结构化结果、context/任务入口/账本。没有提交、推送、上传、生产登录/部署/迁移/备份/回滚或数据修改；临时本地验收服务此前已全部停止。自审完成，独立审查未执行；四卷容量100/98/100/41，共339条记录。

## 三百四十六、番茄钟修复续接收尾与Admin审计边界（2026-10-31）

- 续接核对 `options.maxMs is not a function` 修复已存在：适配器按控制器要求传入 `() => FREE_TIMER_MAX_MS`，其他读取数字上限的契约保持原样。四个相关Node测试文件26项通过、0失败/跳过，WSL、Windows原项目及隔离验收副本的三个业务文件SHA一致。
- 通过现有微信工具读取当前页面栈与缓存console，未命中maxMs、重复声明或全局错误标记。当前仍在刷题结果页；这不是新的番茄钟端到端验收，没有重启已关闭的隔离API或再次操作真实身份。
- 用代码图谱定位ENV-02已失败的具体边界：`admin_auth.py:122` 登录成功后只更新登录字段并提交；`admin_imports.py:591` 单题审核路由调用 `admin_import_service.py:899` 后提交，这两个函数没有写审计。现有 `admin_audit_service.py:36` 的 `write_admin_audit` 只添加实体，不自行提交；后续有界修复应验证业务/审计同事务提交与回滚，禁止记录密码或令牌。没有泛化为所有批量、拒绝或公式审核均缺审计，也没有修改Admin业务。
- 四个后端路径图谱metadata_match且无已记录覆盖缺口；修改过的适配器和两个测试为metadata_changed，使用直接源码/diff与执行证据，不依赖旧图谱证明修复。coverage为best effort。详细证据保存在本地 `pomodoro-followup-closeout/`。
- 六阶段仍为ENV-01 PARTIAL、ENV-02 PARTIAL-AUDIT-FAIL、ENV-03/05 PASS-ISOLATED、ENV-04/06 BLOCKED。继续需要专用微信身份/HTTPS/真机、Admin审计修复范围、受控AI/OCR/存储/WS以及最后的生产窗口/备份/授权。本次无新增提交、推送、上传或生产操作；自审完成，未新增独立审查或系统记忆。四卷容量100/98/100/42，共340条记录。

§346阻塞审计补记：前一目标轮次有新增Admin导入验收和审计边界证据，分类为progress；当前重新核对后，同一组身份/设备、修复范围、外部能力和生产前置阻塞已连续三个目标轮次未解除。隔离AI启用数为0，运行脚本测试微信/COS配置为空，3000/8000/8002/8080/5433/6380均无本地监听；不存在待观察的验收任务。当前没有新的可执行验收步骤，目标登记blocked，原始六阶段目标未完成且不缩减。未新跑业务测试或改业务代码，未提交/推送/生产操作；证据 `goal-blocked-audit/audit.json`。本补记不新增批次编号。

## 三百四十七、ENV-02审计与上传取消缺陷修复（2026-11-01）

用户授权“修复这些发现的问题”。登录成功新增system.login(low)，与登录字段同事务；单题导入审核通过新增import.approve(important)，与审核/发布同事务，仅记录batch_id/question_id/status及请求元信息。审计持久化失败业务回滚，登录不返回成功cookie；失败登录、发布失败、重复审核不写成功审计。复用现有审计服务，无迁移、权限或响应结构变更；补UI action标签及审计/审核文档。

上传阶段显示“取消上传”，复用原中止/清理；await后、SSE事件及watchdog创建前校验当前批次身份和signal。原有刻画测试允许中止后迟状态覆盖新队列，本次改为拒绝该行为，并验证迟upload不建stream、迟trace不污染新批次、迟状态不重建旧watchdog。取消是本页请求/跟踪的中止，不保证已接收的服务器OCR任务停止。

先RED后GREEN：后端新增6项中4项复现缺审计，前端21项中3项复现取消/迟响应缺陷。修复后API41、审计/鉴权/导入和幂等服务85、固定CI静态8336、mocked readiness69通过，后两者零失败/错误/跳过；静态集合65条warning保留。新后端测试入固定CI清单。管理端typecheck/lint、150文件1869项、build通过，lint为0错误/138警告；实时API OpenAPI生成TS和现有关键响应合约tsc通过，最初offline缓存探针失败保留，使用项目既定生成脚本后通过。

独立合成数据库副本+真实API登录/审核实际写system.login/import.approve，发布服务未mock，重复审核422、失败登录401且无额外成功审计；未写回原SQLite。Chromium1440/390px按钮可用且窄屏无横向溢出，取消观察原生EOF与ERR_ABORTED，新批次new.png/4题正常。任务响应受网关控制，不冒称真实OCR验收。结果env02-defect-fixes-2026-11-01.json，证据~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/。

ENV-02转PASS-ISOLATED；ENV-01 PARTIAL、ENV-03/05保留PASS-ISOLATED、ENV-04/06 BLOCKED，完整目标仍未完成。自审完成，独立审查未执行，无提交/推送/生产操作。未在本批重跑真实PG/Redis完整可靠性环境或生产HTTPS/Secure cookie，不宣称所有GitHub工作流通过。四卷容量100/98/100/43，共341条记录。

## 三百四十八、提交与继续验收准入修复（2026-11-01）

用户明确要求提交并在不满足继续验收标准时继续修复。旧统计脚本复现29通过/12失败后，用当前职责25个Node行为测试文件替代拆分前Page函数体的源码位置断言，保留统计格式化、WXML、趋势和结果恢复门禁。最终外层31项、内部206项全通过、0跳过，不相加为唯一用例总数。

新增真实提交适配器、控制器与构建器联通回归，验证持久化先于POST、批次/request_id绑定、后台扣时后冻结13秒，以及墙钟跳变/网络失败后的同体重试。仅在独立进程内变异接口路径或扣时逻辑，测试均失败；模拟子进程退出7时入口退出1，未修改业务源以通过门禁。原业务/CI哈希与前批8336静态/69readiness/1869管理端及OpenAPI成功证据一致，仅对新增/修改Node检查定向复验。

独立审查唯一候选回滚问题经真实get_db依赖、flush后提交故障和新会话查询验证关闭（1项通过/1警告），没有为误报修改业务源；零未解决发现。显式路径本地提交完成（小程序239dc7f9、Admin9087adf3、PG夹具432d9125、验收记录1315986c），结果以acceptance-commit-readiness-2026-11-01.json为准；任务交接分卷的既有未暂存边界保留。环境只读复核新合成SQLite启用AI仍为0，专用身份/HTTPS/真机、受控外部能力及生产窗口/备份条件未变，六阶段状态不变。无推送、上传小程序或生产修改。四卷容量100/98/100/44，共342条记录。

## 三百四十九、专用测试身份和角色续验与清理（2026-11-01）

用户授权自行创建验收测试身份/角色，并在验收结束后删除。新合成SQLite副本初始化3个专用管理账号、2个自定义角色、2个开发学习用户；角色/引导账号用隔离夹具，后续账号创建、权限变更和登录均走真实API。只读/空权限403、同会话授权200与撤权403、JWT跨域401、停用后旧令牌/新登录401通过；实际新增4登录/3权限/2创建/1停用审计。4登录包括脚本首次客户端上下文失败前已成功的引导登录，保留探索和计数修正，不冒称首次全部通过。

微信旧运行时原生请求200而封装失败，显式restore request mock并重新编译后恢复；仅计随后成功链路，没有改业务源。专用用户模拟器2题完整作答/交卷1对1错，数据库2答题/1会话/1错题，错题本1题、详情和掌握/取消确认通过；另一学习用户无记录，直接读/改该错题404。自由计时启动/暂停/继续/结束完成1会话，专注68秒、暂停14秒；直接调用实际endSession处理函数，不新增结束确认声明。两用户退出后旧访问/刷新令牌均401；新增2条pending outbox没有冒称消费完成。

停止本轮API后仅清理本轮新增主键：3管理账号、2学习用户、2角色及关联15表34行（含新副本测试审计）；79表逐行和计数与基线一致，无新增外键问题，旧合成源SHA不变。原11项模拟器存储恢复，临时凭据清单/存储备份删除，8000关闭；未删既有数据或生产数据。证据在~/.cache/postgraduate-ai/acceptance/2026-11-01-identities/，6份无凭据脚本归档，结果acceptance-owned-identities-2026-11-01.json。

记录提交`7f6cd4cb`，账号列表复核补充提交`b643465f`；本轮累计6个本地提交，未推送/上传/生产操作。无新业务源码改动，复用此前代码门禁/独立审查，不重复大集合；本批记录自审完成，未新增独立审查。合成身份创建权限已落实，DevTools测试号列表为0，真实微信交换/HTTPS/真机、受控外部能力及生产窗口/有效备份/回滚制品仍缺，六阶段状态不变、完整ENV目标未完成。专项接口/部署实现未变，已核对无需改专项说明。四卷容量100/98/100/45，共343条记录；既有任务分卷重组保持未暂存，无系统记忆写入。

## 三百五十、ENV-01前置与ENV-02/03/05证据复核（2026-11-01）

用户再次授权验收身份可自行创建。上一轮本地合成用户和角色已物理清理，本批不重复创建。WeChat MCP只读账号查询显示3个AppID，两个应用名称带测试标记；当前验收项目绑定其中一个未标记为测试用途的应用。测试号列表0；ticket本轮未查询/获取/设置/刷新；未对该项目调用 `wx.login`，未输出AppID、openid、app名或MCP令牌。真实微信身份映射、测试HTTPS、真机及真实移动网络仍不能验，ENV-01继续PARTIAL。当前应用未标记不等同于已经证明是生产，只说明没有足够证据安全用它作测试。

本轮按当前HEAD核验ENV-02修复源哈希与既有隔离API/浏览器证据一致。归档测试XML：ENV-03 fresh migration 8项、PG/Redis集成22项、Pomodoro PG concurrency 6项全零失败/错误/跳过；current=head=`v19_pomodoro_subject_allocations`，既有PG/Redis刷新轮换、缓存崩溃恢复和新库备份恢复报告PASS。ENV-05 fencing29、Redis故障恢复6、队列硬化23、worker进程恢复2项也全零失败/错误/跳过；双worker+scheduler投影和Redis RDB恢复报告PASS。上述阶段测试/运行证据日期为2026-10-31；此批只做hash/JSON/XML审计，没有重跑服务、浏览器或测试。

按当前规划，ENV-02/03/05各自的限定隔离技术验收已完成，状态仍为PASS-ISOLATED；ENV-01只有本地开发身份/模拟器部分通过。完整最终环境验收依赖按序先关闭ENV-01，且ENV-04/06仍缺受控外部能力、生产窗口和有效备份/回滚制品。未触及生产，无身份/角色待清理，本轮无源码变更。详细更新见`docs/project/ENV_ACCEPTANCE_PLAN_2026-10-31.md`§14及`docs/architecture/refactor-results/acceptance-owned-identities-2026-11-01.json`。专项接口/部署实现未变，无需改专项文档。四卷容量100/98/100/46，共344条记录；验收文档已显式路径提交`307a8df9`，本地共7个提交且未推送；既有重组仍未暂存、未写系统记忆。

## 三百五十一、生产空表只读盘点（2026-11-01）

用户要求提交任务文档，并清理生产空表且绝不删除非空表；随后补充若有后端/Admin新代码则同步服务器。先提交任务分卷文档`c3e95160`。按`docs/project/DEPLOY_PLAN.md`连接文档所指生产PostgreSQL，只读确认库`postgraduate`、迁移头`v19_pomodoro_subject_allocations`。以逐表`EXISTS(SELECT 1 ... LIMIT 1)`精确核验public表，发现17表在各自查询时为空；没有查询业务数据行。

逐一对照当前代码，17表均由现行SQLAlchemy ORM模型注册，并用于当前服务/路由/worker或其外键链路：Admin AI设置/用量、AI反馈、导出快照、公式预览/导入、可恢复导入流水线、OCR任务/worker凭据、推荐实验分桶、顺序刷题预约、大纲知识点映射、标签、用户推荐偏好及水印规则。空数据不代表schema废弃；手工DROP会造成生产schema漂移并让现行功能报错，故无安全可删除候选。可见PG dump最新为2026-10-16，Redis RDB最新为2026-10-22；没有当前回滚点，本轮未触发备份脚本或DDL，生产数据和schema均未改变。

检查当前工作区无`backend/app/`或`admin-frontend/`代码变更；`backend/service_compatibility.py`仍为排除的无关未跟踪诊断文本，不上传。未执行rsync。后续若确需删除空表，必须先退役所有代码消费者并通过Alembic迁移表达schema删除，核实当前完整备份/恢复路径与操作窗口，删除前在同一事务持锁并复查空值；本轮只做只读盘点，不代表生产环境验收完成。四卷容量100/98/100/47，共345条记录。

## 三百五十二、生产17张空表删除后按最新指令恢复（2026-11-01）

用户明确重申删除空表，并确认保留意外出现的HEAD `11332141`与`nul\r`后继续执行。先在生产生成23,185,496字节PG完整归档和schema快照，TOC、全量解码、SHA256通过；服务器证据目录`/data/backups/postgres/pre_drop_empty_20261101T051459Z_jondm9/`。单事务按白名单锁定17张普通表，逐表COUNT=0，以单条DROP TABLE RESTRICT删除，不使用CASCADE。2026-11-01 13:16:22提交后，17目标剩余0，其他64表名称/schema/OID保留，迁移头仍为`v19_pomodoro_subject_allocations`。

用户随即要求“算了，回滚那些表”。只提取本次备份内17表及附属对象，在单事务恢复17表、12序列及其last_value/is_called、12默认值、23主键/唯一约束、28独立索引、19外键和12序列归属；提交前逐表0行，其他64表身份和迁移标记未变，没有全库覆盖或回灌业务行。恢复校验于13:24:45完成，完整schema前后830对象段无缺失/新增，829段逐字相同；`ck_syllabus_kp_mapping_type`仅数组cast格式由解析器规范化，7允许值/非法值/空串/NULL共10项判定一致且约束validated。12序列值与备份完全一致，公网live/health/首页200，app/PG/Redis healthy，其他服务运行。

服务器源码仅做checksum dry-run：2个后端运行文件和2个Admin运行文件存在差异，另有测试/离线脚本及未部署材料。§351“本地无新改动”不代表服务器已同步。按用户最新回滚指令先完成恢复，没有执行rsync写入、构建、部署、重启、nginx reload或迁移；代码同步仍待处理。不重跑与本轮DDL无关的业务测试套件，不将有限恢复与健康检查宣称为完整ENV-06验收；六阶段状态不变。记录见`docs/project/PRODUCTION_TABLE_ROLLBACK_2026-11-01.md`，原始SQL/结果/归档保留在服务器，未加入Git。自审完成，未新增独立审查或系统记忆；四卷容量100/98/100/48，共346条记录。

## 三百五十三、保留工作区变化并同步后端与Admin源码（2026-11-01）

用户确认保留`.zcodeignore`删除、`error_log.txt`新增、`nul\r`消失；继续执行此前后端/Admin有新代码则同步服务器的授权。重新checksum dry-run明确4个运行文件差异：后端`admin_auth.py`/`admin_imports.py`，Admin `batch-image/page.tsx`/`action-labels.ts`。四文件当前SHA均匹配§347已通过验收的`env02-defect-fixes-2026-11-01.json`；无本轮业务代码改动，不重复其测试套件。

先逐文件备份服务器旧源码到`/data/backups/source_sync_20261101T053249Z_co6jr670/`并核验备份SHA；rsync仅使用4文件明确清单，不删除、不上传其他测试/脚本/环境材料。2026-11-01 13:33:43确认远程SHA逐项等于本地，再次checksum dry-run为0差异。前后哈希保留在服务器source-before/source-after JSON；详见生产操作记录的§353补记。

只更新服务器源码，未构建镜像、重启、替换容器、reload nginx或执行迁移，运行中的镜像尚未包含修复；不宣称源码已上线。17表恢复状态不变，ENV阶段状态不变，后续镜像部署仍按具体范围与授权处理。自审完成，无新增独立审查或系统记忆写入；四卷容量100/98/100/49，共347条记录。
