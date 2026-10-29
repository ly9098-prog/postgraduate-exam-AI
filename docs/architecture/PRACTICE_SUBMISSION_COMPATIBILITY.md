# 刷题签发与提交语义兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限 Public 刷题批次签发、`batch-submit`、顺序刷题预留、答案投影 outbox 和小程序提交恢复链路，不代表学习域、任务队列、OCR/AI 或全栈语义审查全部完成。

## 1. 入口与消费者

| 用例 | 实现入口 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| 获取练习批次 | `GET /api/v1/practice/questions` | 小程序刷题页、结果恢复链路 | 响应强制 `Cache-Control: private, no-store, max-age=0` 与 `Pragma: no-cache`；题目投影来自不可变 revision，不暴露答案/解析。 |
| 顺序刷题重置 | `POST /api/v1/practice/sequential/reset` | 小程序顺序刷题重置入口 | 只写 `sequential_reset` marker，不删除历史答题记录，不改变统计事实。 |
| 批量交卷 | `POST /api/v1/practice/batch-submit` | 小程序刷题页、结果页恢复 | 必须携带服务器签发 `batch_token` 与完整 `session`；同一 `(user, request_id)` 只允许一份提交。 |
| 会话范围快照 | `GET /api/v1/practice/session/scope` | 知识练习复盘消费者 | 只读取已提交 session 的持久化语义范围，不重建或补写范围。 |
| 会话知识总结 | `GET /api/v1/practice/session/knowledge-summary` | 结果页知识影响展示 | 投影未完成时返回 `processing`，不得把旧掌握度伪装成最终结果。 |
| 练习统计/历史 | `GET /api/v1/practice/stats`、`/records` | 小程序统计/历史消费者 | 统计来自 `PracticeRecord`，会话时长类统计来自 `PracticeSession`，两类口径不能合并。 |

## 2. 批次签发契约

- `GET /practice/questions` 的 `count` 为 1-50，`mode` 仅允许 `random/smart/similar/sequential`；`smart_strategy` 默认 `scored`，`weakness_vector` 保留为显式 fallback/A-B 控制。
- 科目先经当前学生端可用科目规则解析；父级科目可聚合子科目，但 `sequential` 只允许单一叶子科目。知识点 `knowledge_point` 与 `knowledge_point_id` 互斥；`include_descendants` 仅支持 `knowledge_point_id` 且当前仅支持 random。
- `question_ids` 定向重练仅支持 random，数量 1-50、去重、正整数，且不可与来源题或知识点过滤混用。签发前若定向集合失效，返回 400；若候选集合在签发前变化，返回 409。
- 最终候选必须通过最新 revision 解析与科目/题型/active/approved 一致性防御；去重后按请求数量截断。smart/similar 的推荐日志只保留最终返回集合。
- `create_practice_batch_token` 签发 v2 HMAC token：绑定用户、科目、模式、下发顺序、`question_id -> QuestionVersion.id`、推荐 request_id、知识上下文、入口归因、顺序预留 request_id 和提交 request_id。TTL 为 24 小时，时钟偏移容忍 5 分钟。
- 响应中的 `batch_token` 与 `submission_request_id` 是交卷凭据；`request_id` 字段仍表示推荐/相似召回 request_id，不能与提交 request_id 混用。
- 顺序刷题在签发时创建数据库预留，签发/序列化/诊断成功后释放未下发预留并提交；失败由请求依赖回滚。预留 TTL 为 24 小时，唯一键按用户、叶子科目、知识点范围与题目隔离。

## 3. 提交请求与错误契约

`BatchSubmitRequest`：

- `answers` 最多 50 条；每题 `question_id > 0`、答案长度不超过 4096、`used_time` 为 0-21600 秒。
- `skipped_question_ids` 最多 50 条；答案题与跳过题不可重叠，总题数必须为 1-50。
- `session.request_id` 为 1-128 字符；`subject_id > 0`；`started_at/finished_at` 必须合法；`duration_sec` 为 0-21600 秒；`question_count` 为 1-50；`answered_count` 为 0-50；`status` 只能是 `completed`。
- `batch_token` 长度 16-16384，必须由当前 `APP_SECRET` 派生的 practice-batch v2 密钥签名。

服务层将答案按 `question_id` 排序、跳过题排序、session 关键字段归一化后连同 batch token 计算 SHA-256 `submission_payload_hash`。同一 `request_id` 的重放必须逐字段等价；答案、跳过集合、session 元数据或 token 任一变化都会得到不同指纹。

路由错误映射：

| 异常 | HTTP | 机器码 | 客户端行为 |
| --- | --- | --- | --- |
| `PracticeBatchTokenError` | 400 | `PRACTICE_BATCH_INVALID` | 不可重试，重新获取题目。 |
| `PracticeSubmissionConflictError` | 409 | `PRACTICE_SUBMISSION_CONFLICT` | 不可重试，避免结果串单。 |
| `ValueError` | 400 | `PRACTICE_PAYLOAD_INVALID` | 不可重试，修正后重新开始。 |

空答案、重复题、答案/跳过重叠、session 元数据不一致、revision 缺失或错绑、科目/模式与 token 不一致、时间越界均按上述确定性拒绝处理。小程序当前还识别 `PRACTICE_QUESTION_VERSION_CONFLICT` 作为不可重试版本错误；该码不在本路由映射中出现，属于客户端兼容分支，不能凭它宣称服务端存在该响应。

## 4. 幂等、事务与回滚

- `PracticeSession` 由 `(user_id, request_id)` 唯一索引约束。`submission_payload_hash` 与 `submission_response` 保存在 session 行上，因此全跳过批次和未来清理答题历史后仍可恢复。
- 快速重放先按 `(user, request_id)` 读取已提交 winner；命中时不再校验 token 过期或当前题目状态，只比较 payload hash 并重放 canonical response。hash 不同或 response 缺失时返回 409。
- 首次提交在写入前显式启动外层事务；SQLite 执行 `BEGIN`，避免 deferred 隐式事务下释放 savepoint 导致 session 行提前持久化。PostgreSQL 不需要额外 `BEGIN`。
- `(user, request_id)` 在 savepoint 内 claim。唯一冲突时只把该冲突视为幂等碰撞，重读已提交 winner 并按 payload hash 重放；非唯一冲突或其他异常回滚整个外层事务后传播。
- claim 成功后，同一外层事务依次写入 `PracticeRecord`、错题、错误诊断、answer projection outbox、canonical response 和顺序预留清理。任何 `BaseException` 都回滚全部写入后传播，不允许半会话/半记录/半 outbox 状态。
- 提交成功后，AI prewarm 仅 best-effort 入队；失败记录 warning，不影响已提交结果。路由随后失效练习统计、通用统计和复习相关缓存。

## 5. 数据与投影语义

- `PracticeSession` 是一次完整交卷的聚合事实：`duration_sec` 服务学习时长统计；`PracticeRecord` 是每题行为事件：`used_time` 服务单题行为分析。两者不能互相替代。
- `PracticeRecord.question_version_id` 是判题、错题、诊断和投影的不可变事实；提交时绝不回读当前 `questions` 行决定用户看到的内容。`mode` 保留在每题记录上，供行为分析使用。
- `projection_state` 只允许 `pending/completed/revision_only/archived`。异步投影只修复 `pending`；revision 范围内的行为、掌握度和推荐归因始终执行，Leitner/自适应等可变题目状态仅当记录的 revision 仍是当前 revision 时执行，否则落为 `revision_only`。
- answer projection outbox task id 为 `answer_projection:{practice_record_id}`，schema v2。outbox 与业务记录同事务提交；dispatcher 至少一次发布，业务投影通过行锁和 `projection_state` 条件更新实现 effectively-once。
- 对 SQLite ID 复用产生的孤儿非终态 outbox，只有当新 `PracticeRecord.created_at` 严格晚于旧 outbox `created_at` 时才重绑原 task id，并重置 pending/lease/retry 状态、写入 `recovered_from_orphan`；同源或更旧记录 fail-closed，保留原错误。

## 6. 小程序客户端兼容

- 刷题页从响应保存 `batchToken`、`batchMode`、推荐 `recommendationRequestId` 和 `submission_request_id`；题目数大于 0 时缺少任一交卷凭据即拒绝交卷，要求重新获取题目。
- 交卷前构建完整 submission 快照：答案、跳过/部分作答题、session、每题答案映射、恢复用题目投影、batch token、知识范围与推荐 request_id。快照先写入 `practice_pending_submission_v1:{userId}`，再发起网络请求；写入失败不阻止请求，但页面保留内存快照和 unload guard。
- pending 快照 TTL 为 24 小时，与 batch token TTL 对齐。确定性 4xx（排除 401/408/429）标记 blocked，不再自动重试；网络/5xx 保留 pending 并走既有 bounded retry。
- 成功后写 `lastPracticeResult`，并在结果缓存成功后清理 pending；结果缓存失败时保留 pending 直到结果页确认。结果页按 `_rid` 读取 pending，用同一 payload 重放 `batch-submit`，成功后重建本地结果并清理快照。
- 客户端不得自行生成新的提交 request_id 覆盖服务器签发的 `submission_request_id`；本地 fallback 只在历史会话缺失时存在，不能作为新链路依据。恢复失败时保留 pending，用户可稍后重试。

## 7. 旧数据与迁移兼容

- `practice_sessions` 基础迁移创建 `(user_id, request_id)` 部分唯一索引；`request_id` 为空的旧数据不受幂等约束影响。
- `submission_payload_hash` / `submission_response` 迁移到 session 行，覆盖全跳过批次；早期把指纹和响应临时放在 `PracticeRecord` 文本列的做法已废弃。
- `practice_records.question_version_id` 与 `projection_state` 由 revision 完整性迁移补齐；历史无法安全重建的记录落为 `archived`，不能被异步投影重新解释。
- `practice_records` 原批处理形状列已永久退役，投影 worker 在启动时校验必需列存在且退役列不存在，避免滚动部署读到旧 schema 后产生静默漂移。
- 顺序重置使用 marker session，不删除历史记录；历史 `sequential` 记录继续参与统计，重置后的进度查询只统计 marker 之后的新记录。

## 8. 可执行基线

- `backend/tests/test_api/test_practice.py`：签发响应不含答案、token 绑定 revision、三类提交错误映射。
- `backend/tests/test_api/test_practice_chain_regressions.py`：签发链路组装与知识上下文回归。
- `backend/tests/test_services/test_practice_service.py`：判题、多空题、revision 完整性、session 元数据与提交服务边界。
- `backend/tests/practice/`：请求解析、科目/知识点边界、候选选择、scored/smart 合同、最终候选防御、顺序预留、知识 session/scope、学生内容投影。
- `backend/tests/integration/test_practice_submit_postgres.py`：真实 PostgreSQL 下同 payload 并发重放、不同 payload 冲突、outbox 失败全回滚、孤儿 outbox 重绑/live source fail-closed。

本地重放结果（2026-10-24）：`tests/test_api/test_practice.py tests/test_api/test_practice_chain_regressions.py tests/test_services/test_practice_service.py tests/practice` 共 270 passed，10 warnings；warning 为既有 `utcfromtimestamp` 弃用和 mock SQLite 连接的 event-loop 清理提示，不是本批新增失败。

## 9. 未完成与未验证

- 本机没有 PostgreSQL 服务端；`test_practice_submit_postgres.py` 在未设置 `PRACTICE_TEST_POSTGRES_URL` 时按设计跳过。上述真实 PG 并发/回滚证据是历史服务器隔离库验收，不能扩大为当前生产验收或完整 worker 验收。
- 未执行真实微信开发者工具/模拟器/真机交卷恢复、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 中断恢复、完整 worker、多 dispatcher 或备份恢复演练。
- 已入库题目 `re_pending` 重审/回滚已由 Admin 题库域实现；刷题提交域仍只消费 `approved + is_active` 题目，本基线不参与审核状态迁移。
- `practice_service` 的 `get_similar_practice_questions` / `get_smart_practice_questions` 保留 `use_leitner` 形参，但实际到期过滤与 fallback 由 issuance 层 `candidate_schedule.filter_due_candidates` 统一执行（`question_issuance.issue_practice_questions` 调用），不再在各召回函数内重复实现。

## 10. 刷题 controller 职责边界（2026-10-26）

- `answer-feedback-controller.buildFeedback` 保留错误分支，正确连击的原档位、文案和动画参数由 `buildCorrectFeedback` 生成；计时器取消、反馈回调和页面状态更新顺序不变。
- `launch-return-controller.navigateBack` 分开处理无栈目标回退、每次尝试的重试闭包和成功复查。保留 44/96/180ms 重试、64ms 成功复查、nextTick 后 20ms 调度、重试去重和页面死亡解锁；知识页身份匹配及最近/最旧目标规则不变。
- `question-load-controller.loadQuestions` 将响应科目范围与批次校验交给 `acceptQuestionResponse`。仍按范围校验、应用范围、批次校验、交卷凭据、预热、渲染的顺序执行，保留请求序号和页面存活守卫、迟响应忽略、顺序重启与原异常恢复。
- 三个 controller 的 47 项刻画在 HEAD 原实现和拆分后实现均通过；独立只读审查的 261 组调用轨迹、返回值和异常对照一致。相关 practice/page-budget 回归 401 项通过，三个生产文件全部函数不超过 50 行。
- 本地精确重放 reliability 的 `Pomodoro module boundaries and lifecycle regressions` 步骤通过：TAP 汇总 1437 项、四个番茄钟独立脚本 46/106/12/39 项、渲染不变性 43 项和 5 个 fixture 的 31 项，另有存储清理与考试终态导航脚本通过。该步骤不包含分包体积门禁，也不构成微信开发者工具、模拟器或真机验收。
- 单独运行 `node miniprogram/tests/test-main-package-size.js` 时，study 分包源码累计体积仍超 1.2 MiB 预算。本批前按其他工作树文件不变、三个生产文件回算 HEAD 的基线为 1,395,945 字节，当前为 1,396,402 字节，净增 457 字节；未调整门禁。这是打包忽略规则下的源码体积统计，不能等同于微信工具编译或上传体积。

## 11. 客户端 controller 自动预算（2026-10-26）

- `learning-controller-budgets.js` 动态递归扫描番茄钟、番茄统计、刷题、复习、考试、刷题结果、错题详情对应的七个 controller 目录。当前发现 154 个 `*controller.js`、905 个有函数体的 function-like，固定函数上限 50 行、模块上限 300 行，均通过；后续新增同名模式文件自动纳入。
- 目录缺失、路径不是目录、目录内没有 controller 或 JavaScript 语法错误时失败。`node:vm` 的 `Script` 只编译校验源码，不执行；另外保留 TypeScript AST 扫描嵌套函数、对象/类方法、箭头函数和 getter。mutation 测试验证超限拒绝、50/300 边界及 JavaScript 中误写类型标注等非法语法。该命令和 21 项专属测试接入 reliability 同一步骤。
- 这层检查补充现有 11 页入口预算及番茄钟模块依赖门禁，不覆盖所有 state/helper、渲染组件或新目录，也不替代逐业务语义审查。study 分包体积债与真实微信验收仍按前节保留。

## 12. 顺序选题预留与查询（2026-10-26）

- `sequential_service` 保留 scope/reset/request 身份与日志；`sequential_selection` 承接 SQL 构造、原子 INSERT/SELECT、冲突补位、同请求预留重读、进度计数及结果装载。顺序模式仍与推荐/Leitner 独立，不因掌握度改变下一题。
- 保留 PostgreSQL 约束名与 SQLite 冲突列、24 小时 TTL、活动预留排除、失效预留清理顺序，以及读到竞争候选后重新尝试的循环。发题/预留不提交事务，显式 reset 仍写 marker 并提交，不删除答题历史。
- 原模块的 SQL/model/时间/UUID patch 端口继续生效；必要端口在 await 后重新读取。服务 354→285 行，两个原入口 132/97→37/49 行，选择模块 235 行，全部函数不超过 50 行。
- 新增 36 项刻画在原实现通过；核心 56 项与调用方/依赖 87 项通过。作者 720 组差分覆盖 2,805 条 SQL/参数；独立审查额外对照 1,500 个预留和 500 个发题场景，5,453 对预留 SQL/参数一致，无 P0–P3 发现。SQLite 与 SQL 编译证据不替代真实 PostgreSQL 并发竞争。

## 13. 答案投影阶段与修复轮询（2026-10-26）

- `answer_projection_service` 继续持有 schema 门禁、记录行锁、revision 校验、current-version 读取、终态迁移、一次 commit 和提交后缓存失效。`answer_projection_stages` 按原顺序执行 behavior、mastery、attribution，以及 current guard 放行时的 review/adaptive；不接管事务。
- 保留不可变 source dataclass 的 frozen/slots 与原服务导入别名。答题字段在副作用前捕获；旧 revision 仍投影不可变证据，跳过可变题目状态并落为 `revision_only`。缓存普通失败仅记录 debug，取消继续传播。
- 协调器只扫描超过 grace 的 pending 记录，不为扫描加记录行锁；原任务活跃或本小时修复已存在则跳过。每条 outbox 创建在 savepoint 内隔离，唯一冲突/普通失败分类计数，外部查询错误和取消传播；扫描非空时一次 commit，空扫描 rollback。
- `projection_reconciliation_runtime` 只负责参数解析和租约轮询，服务通过延迟绑定端口保留跨轮 reconcile、sleep、logger 与 settings patch 行为。四个业务文件均不超过 300 行，函数不超过 50 行；两个入口 140/111→45/33 行。
- 最终 85 项刻画在原实现通过，相关回归 158 项通过；作者 answer/reconcile 各 1,000 组差分一致。独立只读审查 88 项通过，四份行为测试在原实现重放 81 项通过，另核对动态端口、SQL/事务与 8 个保留函数 AST，无 P0–P3 发现。真实 PG 行锁竞争、Redis 租约和跨进程 worker 仍未验证。

## 14. 知识会话总结投影（2026-10-26）

- `knowledge_session_summary.py` 继续拥有数据库查询入口、事务边界和对外函数名；纯基线、点位统计与响应投影分别由 `knowledge_summary_baseline.py`、`knowledge_summary_points.py`、`knowledge_summary_projection.py` 承接。新模块不引入配置、模型、数据库或任务副作用。
- issue-time baseline 仍只对已签发 revision 实际代表的知识点建立逐点快照，最多保留 96 个逐点 baseline；完整 scope、served 顺序、截断前数量和根节点聚合字段仍进入签名上下文。持久化 scope 优先，旧数据继续使用 legacy fallback。
- session summary 仍先处理 `processing` 早返和 baseline 解码，再按原查询顺序投影；完整点位排序后才应用 24 个展示点上限，`touched_knowledge_point_count` 保留截断前计数。缺失 baseline 继续进入 `unavailable`，不以当前掌握度伪造历史结果。
- `_number_or_none`、`_delta`、状态分级、异常阶段、取消传播、动态 patch 入口和 SQL 参数均保持原语义；服务不接管事务。相关入口和四个业务文件均满足 300 行/50 行函数门禁。
- 证据：原实现重放 30 项刻画通过，当前相关回归 66 项通过；独立审查补充 5,000 组原/新差分与 13,700 组 SQLite/PostgreSQL 编译 SQL/参数对照，结果一致；架构门禁 7 项通过。SQL 对照未执行真实 PostgreSQL。

## 15. 提交会话归一化（2026-10-26）

- `normalization.py` 保留历史函数、UTC 解析、logger 与常量；`session_normalization.py` 按时间/时长、请求标识/科目/模式、答题与题数校验、最终 payload 装配分阶段执行。原入口 77→17 行，原文件 337→290 行，新增模块 110 行，全部函数不超过 50 行。
- 时间先于身份和题数校验；保留两个日期都解析后才拒绝无效日期、墙钟秒取整、时长负值/缺失回退、2 秒容差与 6 小时上限、answered_count 严格一致、question_count 转换失败回退等原规则。返回新字典，保留 ID、日期和计数对象引用及原错误文案/异常链。
- helper 在原表达式位置解析原模块和 builtin 端口，保持执行中替换解析器、阈值、转换函数时的生效顺序；naive 日期仍先记录原 warning 再转换，取消和 logger 异常继续传播。架构门禁检查两个模块的 300/50、依赖、IO 与 fresh import。
- 作者最终原版 148 项、新版相关 284 项通过，4,096 组结果/引用/异常/日志与 384 组动态端口/getter/取消轨迹一致。主流程合并旧 token 测试导入修复后专项 185 项通过；不包含真实 PostgreSQL、微信或生产提交验收。

## 16. 批量提交的准备边界（2026-10-26）

- `batch_submission_flow.py` 保留原 dataclass 和函数定义，以及历史模块中的可替换校验依赖；`batch_submission_preparation.py` 承接协议校验、revision 绑定校验、评分与 session/scope 准备、session 模型装配。新模块只导入标准库，不读取数据库、配置或 worker。
- 保留输入校验 → 已提交回放 → 签名与 revision 读取 → 评分和 session/scope 校验 → 请求认领 → 持久化提交 → 提交后预热顺序。准备模块不接管认领、事务、持久化或失败补偿。已提交回放继续先于 token 校验。
- 原模块和 builtin 依赖在原表达式执行位置解析，保留执行中替换校验器或阈值的时点、错误优先级、结果对象引用和取消传播。session 的墙钟容差仍是 2 秒；批次答案用时校验继续使用独立的 `PRACTICE_ANSWER_DURATION_TOLERANCE_SEC`。
- `test_batch_submission_preparation.py` 锁定评分/校验先后、首错中断、返回引用、动态阈值、revision 绑定与模型参数；`test_batch_preparation_boundaries.py` 检查两模块 300/50、准备模块依赖和 fresh import。两项与原 flow 契约接入静态 CI。此处不包含生产提交、真实 PostgreSQL 或完整跨进程 worker 验收。

## 17. Similar 候选召回与随机补齐装配（2026-10-27）

- `get_similar_practice_questions` 从 79 行收敛至 35 行，保留原签名、docstring、返回类型
  与科目范围解析；`similar_selection.py` 按原顺序组合向量召回与补齐条件，两个函数分别为
  43/36 行。实际向量查询、随机装载及 metadata 投影仍由 `similar_supplement.py` 承接。
  新模块不接管签发、到期过滤、事务、数据库执行、后台任务或鉴权。
- 显式 `subject_ids=[]` 保持空范围，只有 None 才调用原科目解析器。召回与补齐共用原
  scope 列表引用，召回期间对该列表的修改仍被后续条件读取。保留 provider 次序及重复候选；
  候选足够时只做原 Python 切片，metadata 不裁剪；不足时拼接补齐结果，不新增去重、
  数量截断或 50 题上限。Public 路由参数上限与内部候选池数量仍是不同边界。
- 补齐仍排除所有已召回 ID 及源题，保持 active、subject IN、revision scope 和可选历史
  作答排除；第二次历史排除查询按原参数重新构造，不复用召回请求中的表达式。随机装载
  仍先 COUNT 再按 need 调用采样，保留 subject_ref 预加载及 metadata 原地写入。
- 原 service 模块继续保留历史可替换端口；召回函数及请求构造器在参数求值前绑定，
  logger、向量 search 和 revision callback 在原参数位置读取。补齐条件与回调在召回
  await 后读取，随机回调在补齐 await 前绑定，metadata 回调在补齐 await 后读取。
  保留 `use_leitner` 参数；调度仍由 issuance 层执行，不在候选召回内增加到期查询。
- 新增 94 项行为契约在原实现与拆分后均通过，包括 SQLite/PostgreSQL 查询编译、实际
  召回/补齐 helper 装配、普通失败回退、端口替换、对象引用及真实 asyncio Task 取消。6 项架构
  检查约束 300/50 预算、依赖、入口绑定和独立导入；反向展开 helper 与端口替换后，业务
  AST、入口签名/docstring/返回类型及 service 其余定义与原实现一致。10 个故障变体均被
  契约拦截，对照 94 项通过，隔离守卫无违规尝试。
- 关联 practice 与依赖门禁纯端口回归 1074 项通过；1 项真实 SQLite 契约从零连接运行器
  中排除后，使用仅允许专属临时目录 `.db` 的守卫单独通过，放行 5 次连接。两类成功运行
  均无守卫违规；首次扩大运行时该 SQLite 契约因连接禁令失败的证据仍保留。新增 6 个
  Python 文件严格 Ruff、格式、Python 3.11 语法及 300/50 检查通过；原 service 的
  22 条 I001/F401 诊断与拆分前一致，全 app 按既有 ignore 配置检查通过。
- 上述查询编译与合成端口不代表真实向量 provider、PostgreSQL、微信或生产选题验收；
  学习域及 `practice_service` 其余超预算函数仍待治理。

## 18. 批次 token 签发与验收职责（2026-10-28）

- `batch_token.py` 保留公开入口、异常类型、常量和 HMAC v2 wire format；
  `_collect_practice_batch_revisions` 负责签发侧题目版本收集，`_encode_practice_batch_payload`
  负责签名编码，`_read_practice_batch_questions` 负责下发题目列表解析，
  `_validate_practice_batch_identity` 负责用户之外的提交身份匹配。模块仍不接触数据库、
  网络、文件 IO 或异步执行。
- 保留题目 `id` 的两次读取、重复题先于第二次 revision 查找、缺失 revision 的原 RuntimeError、
  签发顺序、`sort_keys` JSON 字节、动态 UUID/TTL/签名密钥端口，以及提交侧
  用户 → 题目列表 → 提交集合 → 科目/模式/request_id/推荐反馈 → 时间的校验顺序。
  50 题上限、5 分钟时钟偏移、异常链和 payload 引用返回均不变。
- 57 项新增契约在拆分前原实现重放通过；当前契约、既有 token 兼容测试和架构门禁共 86 项通过。
  14 个有效故障变体全部被拒绝，覆盖重复题、缺失版本、wire key/JSON、上限边界、
  下发顺序、异常链、用户/request 绑定和时钟偏移。另有 6,000 组新旧差分：
  签发 2,000 组中 405 组成功、1,595 组匹配原错误；验收 4,000 组中 403 组成功、
  3,597 组匹配原错误。反向展开四个 helper 后整个模块 AST 与原实现一致。
- 学习域相关回归 1,159 项通过；按当前 `ci.yml` 的静态架构与非 GPU 步骤本机精确重放，
  6,802 项通过、0 失败，包含 64 个既有 datetime/OCR 弃用警告。该重放不是远端 CI，
  也不包含真实 PostgreSQL、Redis、微信或生产提交验收。

## 19. 批次记录持久化与事务提交职责（2026-10-28）

- `batch_persistence.py` 保留 `PersistedPracticeBatch` 和公开入口；记录字段装配、
  批量 staging/flush、单条错题与诊断副作用分别交给 `_build_practice_record`、
  `_stage_practice_batch_records`、`_persist_practice_wrong_record`。原 61 行入口收敛为
  43 行，模块 145 行，最长函数 43 行；持久化模块仍不持有 commit/rollback。
- 保留逐条构造和 `db.add`、非空批次只 flush 一次、每条错题按
  `record_wrong → persist_wrong_answer → setattr(_error_diagnosis_payload) → create_outbox`
  执行、题号/revision 的 int 转换、预热门和错题 ID 映射，以及空批次不触发任何端口。
- `batch_commit.py` 保留原公开签名和函数定义；响应装配、提交后清理/提交、
  整个事务体分别由 `_build_claimed_practice_response`、`_finalize_claimed_practice_batch`、
  `_run_claimed_practice_batch` 承接。原 60 行入口收敛为 31 行，模块 168 行，
  最长函数 33 行。`submission_response` 仍在 cleanup 构建/执行前赋值，`cleanup is None`
  才跳过 execute，任何 `BaseException`（含取消和 KeyboardInterrupt）仍触发 rollback。
- 新增契约覆盖多记录顺序、动态端口、异常身份、空批次和清理 `None`/其他 falsy 语句、
  各阶段失败回滚、响应对象身份及请求参数。22 项在当前新契约的原实现重放中通过，
  当前入口、既有测试和 10 项模块边界共 36 项通过；12 个有效故障变体全部被拒绝，
  覆盖 `commit` 参数、projection 状态、正确分支、空 flush、错题映射、诊断字段、
  request_id、truthy cleanup、rollback、execute/commit 顺序、响应身份和 issued_order。
  学习域关联回归 1,169 项通过。反向展开四个持久化 helper 及三个提交 helper 后，
  两个模块的 AST 与原实现一致；仅 `dataclasses`/`datetime` 导入顺序按 Ruff 规范化。
- 上述事务顺序和异常契约使用内存 doubles，不代表真实 SQLAlchemy 会话、
  PostgreSQL 并发提交或生产 worker 验收。

## 20. 智能分支、入口装配与会话 scope 职责（2026-10-28）

- `smart_branches.py` 保留两个 dataclass 和 `create_smart_branches`；
  scored/path 两个闭包由 `_create_scored_branch`、`_create_path_branch` 构造。
  入口 72→11 行，两个工厂分别为 34/35 行，模块 134 行。scored/path supplement
  仍在闭包调用时延迟导入，weakness 仍直接委托 `providers.run_weakness(**kwargs)`。
- `smart_entry.py` 的 `run_smart_entry` 保留 subject scope 解析和
  `create_smart_branches` 组装，`_run_smart_practice_request` 承接 orchestrator
  `SmartPracticeRequest` 装配；入口 56→42 行，模块 122 行。provider 字段对象、
  显式 scope、回调对象身份、logger 和 subject_ids 传递顺序保持不变。
- `session_scope.py` 将身份门禁、resolved 集合、legacy served 回退分别交给
  `_scope_identity`、`_resolved_scope_ids`、`_served_scope_ids`。原 66 行入口收敛为
  45 行，模块 228 行，最长函数 45 行；默认 `knowledge_point`、scope_count 缺省 1、
  精确 scope 的 root 检查和 served 交集过滤保持原顺序。
- 新增契约覆盖分支 lazy import、请求对象先构造后 await、logger 动态查找、
  provider 身份、显式/默认 scope、root 缺失、未知 mode、正整数去重、
  legacy baseline 回退和 snapshot 字段顺序。18 项在当前实现改动前原版重放通过，
  当前行为与 9 项模块边界及既有 smart 架构检查共 31 项通过；13 个有效故障变体
  全部被拒绝。反向展开三个模块的职责 helper 后 AST 与原实现一致；
  `smart_entry` 仅按 Ruff 重排导入顺序。学习域关联回归 1,179 项通过。
- 按当前 `ci.yml` 的静态架构与非 GPU 步骤本机精确重放，6,865 项通过、0 失败，
  包含 64 个既有 datetime/OCR 弃用警告。该结果是本地重放，不是远端 CI，
  也不包含真实 PostgreSQL、Redis、外部 AI/OCR、微信或生产验收。

## 21. 学习分包答案归一化与跨分包同步（2026-10-28）

- `miniprogram/subpackages/study/utils/answer.js` 的 `normalizeBlankAnswer` 从 93 行
  收敛为 9 行分派，canonical 键值、圈号/括号/中文标记、可信 slotIds 位置答案分别由
  `parseCanonicalBlankAnswer`、`parseMarkedBlankAnswer`、`parsePositionalBlankAnswer`
  承接；模块 220→230 行，全部函数不超过 50 行，exports 的名称与顺序不变。
- 语义保持：解析优先级（canonical → 标记 → 位置）与提前返回不变；同一分段内后续无冒号
  片段归属上一槽位；`normalizeSlotValue` 仍按逗号/顿号拆分、去重、升序连接；重复槽位
  仍覆盖；非字符串对象仍原引用返回且不读取属性；`slotIds` 仍延迟读取并保留 `map`
  接收者、转换顺序与异常；`__proto__`/`constructor` 等特殊槽位仍走普通对象原型行为。
- 该实现与已评审的考试分包副本（`subpackages/exam/utils/answer.js`）现为逐字节一致，
  两分包仍互相不引用；本题只把学习分包补齐到同一已评审结构，源码净增 333 字节。
  `test-main-package-size.js` 报告 study 分包源码 1110.4 KiB / 196 个文件并继续通过
  1.2 MiB 源码预算；这是源码体积，不是微信编译或上传体积证据。
- 27 项契约（`tests/test-study-answer.js`，含 exports 名称/顺序、空值与对象短路、
  canonical/圈号/括号/中文/位置全部形状、原型与回调异常、导出替换不被判题读取）在
  HEAD 原模块与当前模块上均通过。改为提交前重放 HEAD 模块：27 通过。
- 差分刻画：以 5,284 组调用对照学习/考试两份实现，拆分前与拆分后均为 0 不一致；
  新门禁 `tests/test-study-answer-boundaries.js` 内置 3,376 组同样对照，另含模块 300
  行/函数 50 行预算、分派形状、exports 顺序与 source 同步断言，5 项全部通过。
- 10 个故障变体全部被拒绝（`/tmp/study-answer-mutants.log`）：分派重排、解析器改名、
  丢失分派返回、重复分派调用、解析器参数个数、exports 缺失、函数与模块超预算、语法错误。
- 按当前 `reliability.yml` 的小程序步骤（259 行命令）本机精确重放：退出码 0、
  0 个 `not ok`，含新增两项；本机重放不等于远端 CI。仍未执行真实微信开发者工具、
  模拟器或真机验收，也未做真机答案录入/判题对照。

## 22. 练习结果页复习视图纯规则拆分（2026-10-28）

- 2026-10-28，`subpackages/study/practice-result/index.js` 由 1,129 行收敛到 896 行；
  `scripts/architecture/page-budgets.js` 的该页 legacy ceiling 同步由 1130 收紧到 897（预算只降不升）。
- 12 个页面级纯函数迁到两个新模块：`utils/review-preview-format.js`（98 行）
  承接 `normalizeReviewStatus`、`pad2`、`formatMathPreviewText`、`formatAnswerPreview`、
  `getQuestionTitle`、`normalizeKpList`；`utils/review-analysis-view.js`（171 行）承接
  `looksLikeStructuredReviewAnalysis`、`containsRawAnalysisJson`、`formatReviewAnalysisText`、
  `buildReadableReviewParagraphs`、`extractGenericReviewAnalysis`、`buildReviewAnalysisView`。
  两模块均满足 300 行模块 / 50 行函数预算。
- 语义保持：预览文本仍先归一化 `<br>/标签/实体/换行`，再按
  `toPlainInlineMathText` → `formatInlineMathText` 两级渲染；`formatAnswerPreview` 的
  ①/数字/中文序号槽位判定与 `第N空：` 重写、`normalizeReviewStatus` 的
  partial/skipped/correct/wrong 优先级与 correctness 回退、`pad2` 的 `Number(n) || 0`
  负数归零、`getQuestionTitle` 的 `content.text → content.stem → stem → text → title` 顺序、
  `normalizeKpList` 的 `name/title/knowledge_point_name/label` 顺序与 `[,，、]` 切分全部逐字保留；
  分析视图保持 72/76 段落阈值、`extractGenericReviewAnalysis` 的 depth>4 上限与 11 个候选键顺序、
  `buildReviewAnalysisView` 的 structured/plain/generic/fallback 四段分支、section 顺序与 tone、
  `${key}-${index}` 段落键以及 `formatError` 判定。
- 页面同时删除已无引用的重复 `clamp`（职责早前已由 `utils/format-helpers.js` 承接，两者 NaN
  语义不同故未合并），并移除只服务被迁函数的 3 条 `require`。
- 差分刻画：14,985 组调用（含 1,200 组种子随机的 token 串与嵌套对象）对照 HEAD 页面原实现与
  拆分后模块，返回值、错误与 JSON 形状 0 不一致（`/tmp/practice_result_view_parity.js`、
  `/tmp/practice-result-view-parity.log`）。
- 18 项契约（`tests/test-practice-result-review-preview-format.js` 10 项、
  `tests/test-practice-result-review-analysis-view.js` 8 项）在 HEAD 原实现重放（
  `/tmp/practice-result-view-contracts-original.log`）与当前实现上均通过。
- 26 个故障变体全部被拒绝（`/tmp/practice-result-view-mutants.log`、
  `/tmp/practice-result-view-mutants-RpiOSD/report.json`），覆盖实体解码、渲染优先级、空位标签、
  分隔符、圈号上下界、pad2 NaN、标题/知识点顺序、知识点分隔符、status 优先级与 partial 识别、
  JSON 数组判定、已知键集合、换行 join、段落 72/76 阈值、depth 守卫、键顺序/缺失、tone 与标题文案、
  `formatError`、段落键、plain 段键与 fallback 守卫。
- 门禁强化：`scripts/architecture/learning-controller-budgets.js` 新增 `scanModules()`，把原 7 个
  治理目录从“只检查 `*controller.js`”扩展为检查其中全部 JS 模块（页入口
  `subpackages/productivity/pomodoro-stats/index.js` 仍由 page-budgets 的 legacy ceiling 管理），
  当前覆盖 282 个模块 / 1,818 个函数、0 违规；`tests/test-learning-controller-budgets.js`
  新增 5 项模块扫描用例（合计 26 项）。
- 定向回归：practice-result 相关 135 passed、practice 相关 423 passed、
  package-quality/component-paths/code-mode 3 passed。三项预存在失败
  （`scripts/test-error-diagnosis.js`、`scripts/test-408-ai-teacher.js` 与
  `scripts/test-pomodoro-practice-stats.js` 的 12 项）在 HEAD 树与本批前后逐项一致，非本批回归。
- 按当前 `reliability.yml` 的小程序步骤（264 行命令，含新增两项）本机精确重放：退出码 0、
  0 个 `not ok`、14,158 行输出、23.2 秒；本机重放不等于远端 CI。仍未执行真实微信开发者工具、
  模拟器或真机验收，也未验证结果页在真机上的排版与交互。


## 23. Practice 页面剩余职责收敛（2026-10-29）

本批以整个 practice 页面为交付范围，统一处理科目配置、返回与退出、题目交互、提交恢复四组 controller 能力装配，以及生命周期和启动预设编排。原 controller、纯规则与已有生命周期/计时/科目请求适配器继续复用；Page 保留声明、依赖注入和薄入口。未更改 WXML/WXSS、路由、存储键、API 或业务行为。

- 六个职责模块为 `practice-subject-page-adapter`、`practice-exit-page-adapter`、`practice-question-page-adapter`、`practice-submit-page-adapter`、`practice-lifecycle-flow` 和 `practice-launch-flow`。controller 惰性实例字段与跨调用身份保持，page/session/data 和平台方法继续在原调用时刻读取；导入的 helper、对象和构造器仍从原页面注入。
- 生命周期保留原序号/flag/会话重置、render guard 与 hook 顺序、timer 清理及同步失败后的部分状态。ready 保留等待恢复、快速启动后当前存活判断、科目静默补载非等待且捕获拒绝的原边界；未新增取消或回滚逻辑。
- 启动预设保留原对象修改、subjectCode 回填、科目不可用和定向题 mode 校验、override 写入、setData callback 后计算字段及最近科目记录顺序。手动配置清空的 override 字段集、请求参数字段顺序及默认科目存储回退不变。
- 退出/暂停/交卷/恢复仍由既有 controller 决策；平台 receiver、当前 helper、确认组件返回身份、timer/请求序号写回和恢复 await 后状态判定保持。题目加载 controller 保留首次装配时的平台对象捕获，后续返回缓存实例；其他原动态平台 callback 使用 getter 保留调用时读取。
- `practice-boundaries.js` 按实际 Page 直接属性逐项验证注册顺序、数量和 token 模板，拒绝未知/重复/spread/别名或委托漂移，字符串内部空白不会被忽略。模块/函数继续受现有预算门禁约束；六个页面 require 绑定按 const/路径/次数核对，职责模块拒绝新增导入、裸平台引用和动态执行。独立审查发现的两处门禁缺口已补检查及负例，业务实现未改变；CI 注册新门禁与契约，原 UI 测试夹具更新模块加载路径。

本轮剩余职责提取与入口登记完成。验收命令、数字、模块行数和证据限制统一见 `refactor-results/practice-page-2026-10-29.json`；临时原页及对照脚本位于该清单的 evidence_directory，不重跑 extract.js。对照包含原页契约、逆变换 AST token、全部原声明顺序及 controller 端口状态/轨迹；引擎 TypeError 的 this/page 名称归一化，未宣称错误诊断文本逐字一致。未执行真实微信开发者工具、模拟器或真机，也未验收真实网络/外部AI及完整学习闭环。

## 24. 小程序刷题提交请求生命周期（2026-10-30）

按“小程序接口 > 后台管理系统接口 > OCR 接口”继续处理真实消费链路。
刷题页 `practice-submit-page-adapter` 与结果页 `recoverSubmittedResult` 调用
`POST /api/v1/practice/batch-submit`，顺序重启适配器调用
`POST /api/v1/practice/sequential/reset`。本批只迁移仍在提交路由中的请求职责，
原小程序、已分离的发题与提交事务编排均保留；重置、会话 scope/knowledge-summary、
统计和其他查询路由的函数体保持原实现。记录和知识状态查询尚未确认小程序消费者，
不据负检索宣称不存在调用，也不因行数把它们纳入本批。

提交路由保留原鉴权、Header/Depends、请求 schema、路径、response_model 及签名，
单次委托 `services/practice/request_submission.py`。该模块承接诊断记录、
三类 service 错误映射、提交后缓存失效和响应投影；不导入路由、FastAPI、ORM、
配置或数据库模块。依赖仍在原使用位置从路由读取，包含 await 之后的当前
service 异常类、logger、cache、schema 和用户 ID，不将它们提前固化为请求快照。

- trace 仍先取日志上下文 truthy 值，否则 normalize header，再做 str 转换。
  debug 与 submit_before snapshot 在 service 调用及其 try 边界之前执行；
  answers 逐项 model_dump、session 转换、skipped IDs 原引用和 batch token 保持。
- 原 service 继续持有签发 token 校验、版本判题、幂等重放、事务、
  会话/outbox 持久化和顺序进度。路由及新模块均不增加 commit、rollback、
  flush、队列交接或重试。service 原抛出的 token/conflict/ValueError 分别映射为
  400 PRACTICE_BATCH_INVALID、409 PRACTICE_SUBMISSION_CONFLICT、
  400 PRACTICE_PAYLOAD_INVALID，retryable=False；日志及原异常上下文保留。
- service 成功之后依次失效 practice:stats、stats、review 三个原 pattern，
  再记录 submit_after，最后构造 AnswerResult 和 BatchSubmitResponse。
  cache/诊断/响应校验失败不进入 service 错误映射；保留前面已发生的提交和
  部分缓存失效，不添加回滚或吞错。其他异常和取消仍原样传播。
- total_skipped 缺失时仍为 0，knowledge_session 缺失时仍为 None。
  schema 继续按原规则投影；不改变外部响应 envelope，也不修复本批以外的业务行为。
  直接调用中已有的 session=None 分支保留，HTTP schema 仍要求合法 session。
- 重置路由继续先校验科目存在，再拒绝父科目或非单科范围，最后调用原重置 service。
  会话 scope 继续区分缺失会话与存在但无知识 scope；knowledge-summary 继续区分
  缺失、processing、ready、unavailable，不提前把异步投影标记为完成。

契约先在原路由上运行，再在当前入口验证。逆展开恢复原提交函数体，
其余原函数声明、函数体及顺序受结构检查约束；差分比较实际响应、异常、诊断、
service 参数、缓存顺序、取消和用户状态，并核对实际 FastAPI OpenAPI 对象。
新请求契约与架构门禁加入固定 CI 清单。命令、数量、结果与源码 hash 统一见
`refactor-results/miniprogram-practice-request-2026-10-30.json`；
临时证据在 `/tmp/miniprogram-practice-request-batch/`，不要重跑 extract.py。

本批是后端请求边界的兼容重构，未修改小程序源码；本地替身与差分不代表真实微信
编译/真机、生产鉴权、PostgreSQL/Redis、多 worker、外部模型或完整学习闭环验收。
