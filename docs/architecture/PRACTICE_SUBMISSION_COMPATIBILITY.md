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

## 拆分内容索引（2026-11-08）

原 §6 起的编号批记（重构批次登记）已迁至 [[docs/architecture/PRACTICE_SUBMISSION_HISTORY.md|PRACTICE_SUBMISSION_HISTORY]]，编号沿用；新批记继续登记在该历史文件，本文件只维护稳定契约。

| 原章节 | 内容 | 现位置 |
|--------|------|--------|
| §6 | 小程序客户端兼容（原编号沿用） |
| §7 | 旧数据与迁移兼容（原编号沿用） |
| §8 | 可执行基线（原编号沿用） |
| §9 | 未完成与未验证（原编号沿用） |
| §10 | 刷题 controller 职责边界（2026-10-26）（原编号沿用） |
| §11 | 客户端 controller 自动预算（2026-10-26）（原编号沿用） |
| §12 | 顺序选题预留与查询（2026-10-26）（原编号沿用） |
| §13 | 答案投影阶段与修复轮询（2026-10-26）（原编号沿用） |
| §14 | 知识会话总结投影（2026-10-26）（原编号沿用） |
| §15 | 提交会话归一化（2026-10-26）（原编号沿用） |
| §16 | 批量提交的准备边界（2026-10-26）（原编号沿用） |
| §17 | Similar 候选召回与随机补齐装配（2026-10-27）（原编号沿用） |
| §18 | 批次 token 签发与验收职责（2026-10-28）（原编号沿用） |
| §19 | 批次记录持久化与事务提交职责（2026-10-28）（原编号沿用） |
| §20 | 智能分支、入口装配与会话 scope 职责（2026-10-28）（原编号沿用） |
| §21 | 学习分包答案归一化与跨分包同步（2026-10-28）（原编号沿用） |
| §22 | 练习结果页复习视图纯规则拆分（2026-10-28）（原编号沿用） |
| §23 | Practice 页面剩余职责收敛（2026-10-29）（原编号沿用） |
| §24 | 小程序刷题提交请求生命周期（2026-10-30）（原编号沿用） |

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/REVIEW_SYSTEM_DESIGN.md|REVIEW_SYSTEM_DESIGN]] — 复习系统设计
- [[docs/architecture/PRACTICE_SUBMISSION_HISTORY.md|PRACTICE_SUBMISSION_HISTORY]] — 编号批记历史（§6 起）
