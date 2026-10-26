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
