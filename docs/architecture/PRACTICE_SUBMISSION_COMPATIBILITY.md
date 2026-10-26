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
