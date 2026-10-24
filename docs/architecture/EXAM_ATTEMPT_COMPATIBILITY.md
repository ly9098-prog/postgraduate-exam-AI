# 套卷考试兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限 Public 选择题套卷考试域（试卷列表、作答、终态、结果、历史）、`ExamAttempt`/`ExamAnswer` 状态机、revision 绑定与小程序考试消费者，不代表学习域、任务队列、OCR/AI 或全栈语义审查全部完成。

## 1. 入口与消费者

| 用例 | 实现入口 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| 试卷列表 | `GET /api/v1/exams/papers` | 小程序 `paper-list` | 只返回 `published` 且 `is_active` 的试卷；列表带最新作答状态与最佳成绩。 |
| 试卷详情 | `GET /exams/papers/{paper_id}` | 小程序 `paper-list` 启动确认 | 含科目分布、题数、总分；不返回答案。 |
| 开始作答 | `POST /exams/papers/{paper_id}/attempts` | 小程序 `paper-list` | `request_id` 8-128 字符，幂等重放返回同一 attempt；每用户每卷至多一个 `in_progress`。 |
| 作答视图 | `GET /exams/attempts/{attempt_id}` | 小程序 `exam-runner` | 只读；不为已过时 attempt 生成结果，保留 pending 答案供原子交卷。 |
| 保存答案 | `PATCH /exams/attempts/{attempt_id}/answers/{item_id}` | 小程序 `exam-runner` | 持久化草稿，非终态转换；过时后只允许幂等元数据/时间，拒绝改答案。 |
| 取消作答 | `POST /exams/attempts/{attempt_id}/abandon` | 小程序 `paper-list` | 条件 UPDATE；已到时不能取消，终态幂等返回 `abandoned`。 |
| 交卷 | `POST /exams/attempts/{attempt_id}/submit` | 小程序 `exam-runner` | 服务端幂等：终态直接返回不可变快照；可携带最终 pending 答案原子判题。 |
| 结果 | `GET /exams/attempts/{attempt_id}/result` | 小程序 `result` | 只读；非终态返回 409，不 lazy finalize。 |
| 历史概览 | `GET /exams/history/overview` | 小程序 `history` | 分页；summary 与 items 不加载 `result_snapshot`。 |
| 历史列表 | `GET /exams/history` | 旧版小程序 `history` | 兼容入口，委托 overview offset=0。 |

注册以 `backend/app/api/v1/router.py` 和当前小程序请求为准。

## 2. 数据职责与唯一性

- `ExamPaper` 发布后题面不可变：`paper_type` 只能 `past_exam_choice/mock_choice`，`status` 只能 `draft/published/archived`，`version >= 1`，`duration_sec` 为空或正数。软删除由 `deleted_at` 表示。
- `ExamPaperQuestion` 固定 `question_id` 和不可变 `question_version_id`，`(paper_id, position)` 与 `(paper_id, question_id)` 唯一；`score > 0`；`section_subject_id` 为分科统计口径。
- `ExamAttempt` 由 `(user_id, request_id)` 唯一支持开始幂等，部分唯一索引 `uq_exam_attempts_user_paper_in_progress` 保证每用户每卷至多一个进行中；`paper_version` 锁定开始时的试卷版本；`result_snapshot` 是终态后唯一结果事实。
- `ExamAnswer` 每题一行，`(attempt_id, exam_paper_question_id)` 唯一；`question_version_id` 固定到试卷快照，不随题库修正漂移；`answer_revision` 单调递增用于诊断重复/陈旧客户端写入；`practice_record_id` 唯一可空，交卷后绑定时才写入。
- 错题重审/回滚仍是设计预留，不在本域实现。

## 3. 开始、终态与幂等

- `start_attempt` 先按 `(user, request_id)` 查重放：同一 request 且同卷返回已有 attempt；不同卷返回 409。再查现有 `in_progress`：未过时则返回；过时则由 `_ensure_attempt_not_expired` 转终态。并发开始由部分唯一索引约束，`IntegrityError` 后 rollback 并确定 winner，不产生多条进行中。
- 开始时为每个 `ExamPaperQuestion` 创建空 `ExamAnswer`，固定 revision；随后提交。GET attempt 不副作用化过时 attempt，避免在客户端仍有 pending 答案时提前判题。
- `save_attempt_answer` 是持久化而非终态：过时后保留 8 秒 grace 允许最后一次 flush；超过 grace 只允许幂等元数据/时间，拒绝修改答案，强制走 `/submit`。
- `submit_attempt` 先锁 attempt 行；终态直接返回 `result_snapshot`。非终态时在同一事务内应用 `_apply_final_submit_answers`（校验 item 属于本次、选项有效、去重、时间上限），再判题。`abandoned` 不能交卷；过时映射为 `expired`，否则 `submitted`。
- `_finalize_attempt` 原子更新 `ExamAnswer` 对错/得分、写 `PracticeRecord`、`record_wrong`、`error_diagnosis_service.record_error_event`、answer projection outbox 和 `result_snapshot`；任何失败回滚全部判题。AI prewarm 在提交后 best-effort 入队，不影响终态。
- 小程序 `/submit` 可对模糊网络失败重试，因为服务端终态幂等；重试前用只读 GET 进行 reconciliation，不会把过时草稿误判成结果。

## 4. revision 与判题口径

- 试卷题目绑定不可变 revision；作答、结果和历史统计始终按该 revision，不回读当前 `questions`。GET attempt 校验 revision 与 `ExamPaperQuestion.question_version_id` 一致且为 `single_choice`，否则返回 409。
- 判题用 `is_answer_correct(selected, revision.answer, single_choice)`，选项校验来自 revision 投影；答案归一化为大写。选择题计分按 `item.score`，未答不计分但不报错。
- 错题写入复用 `wrong_question_service.record_wrong`，会重置 mastered 并调度；错因诊断 source_context=`exam`，`exam_answer_id` 唯一，`queue_ai=false`。
- 结果按 `EXAM408_CORE_CODES` 固定科目顺序排序；弱知识点来自错题 revision 知识点名，按丢失分数排序前 8。
- `result_snapshot` 通过 `jsonable_encoder` 归一化后存入 JSON 列，兼容嵌套 datetime/Decimal；GET result 直接返回该快照，不重建。

## 5. 历史与统计

- 历史只列 `submitted/expired` 且 `submitted_at` 和 `result_snapshot` 非空的终态 attempt；不加载大 JSON，题数/总分来自 `ExamPaperQuestion` 聚合。
- overview summary 全量聚合（completed_count、平均分、平均准确率、最佳分、最佳准确率），items 分页；`has_more` 由 offset+items<total 推导。
- `list_exam_history` 是兼容旧客户端入口，委托 overview limit/offset=0，返回 items；旧版小程序在 `/history/overview` 404 时回退到该接口本地聚合。
- 历史 `accuracy` 为 0-1 小数，结果页 `accuracy` 也为 0-1；小程序展示时按需转百分数，不能与 stats/study-report 其他口径直接合并。

## 6. 小程序兼容

- `paper-list` 用 `latest_attempt_status==='in_progress'` 判断可继续；取消/继续使用服务端 abandon，乐观更新后 force 刷新；取消失败/不确定时保留本地草稿。开始作答用 `api.createRequestId()` 作为 request_id。
- `exam-runner` 本地 pending 缓存 `exam_attempt_pending_v3:{attemptId}`，兼容 v2/v1；普通草稿 TTL 60 分钟，submit_pending TTL 7 天。到时后 pending 答案保留并走原子 submit，不先 PATCH。
- 正常作答期 eager PATCH 同步 pending；到时后只构建最终答案列表提交。PATCH 遇 409 调 `_reconcileAttemptState`：终态则清理 pending 并导航，非终态则保留 pending。网络恢复时按墙钟重判过时，必要时自动 submit。
- 终态导航锁 `_terminalNavigation`/`_attemptTerminal` 拒绝二次 submit，失败导航保持只读并允许 `retryResultNavigation`。只读覆盖层由 `timeExpired || submitting || resultRecoveryPending` 控制。
- `result` 页按 attempt GET/submit 返回的快照渲染；错题诊断按 question 内 `error_diagnosis` 和 `wrong_question_id` 收集，可异步刷新。`history` 支持 overview 分页与旧接口回退。

## 7. 旧数据与迁移兼容

- 选择题考试域迁移创建四张表和部分唯一索引；`answer_revision` 由后续迁移补齐，默认 0；`public_id` 由迁移回填并加唯一索引；软删除 `deleted_at` 与 coverage 索引后续补齐。
- 迁移不回填历史 attempt 的 `result_snapshot`；只有真正提交/过时的 attempt 才有快照，历史查询要求快照非空。
- `practice_record_id` 与 `exam_answer_id` 关系在错因诊断迁移中以 `SET NULL` 外键引入；历史考试答案可能没有 practice_record，判题时按需创建。

## 8. 可执行基线

后端：当前已有专项 Real-SQLite 服务语义回归：

```bash
cd backend
APP_ENV=test APP_SECRET=ci-refactor-test-secret-not-production \
DATABASE_URL=sqlite+aiosqlite:///:memory: REDIS_URL= SENTRY_DSN= \
STAGING_STORAGE_DIR=/tmp/exam-attempt-test \
.venv/bin/python -m pytest tests/test_services/test_exam_attempt_semantics.py \
-q --tb=short
```

结果（2026-10-24）：`1 passed`。覆盖已发布试卷开始作答、最终答案原子应用、固定 revision 判题、终态快照、同 request 重放、重复 submit 返回不可变快照，以及 `PracticeRecord`、错题、exam 错因事实和 answer projection outbox 同事务落库。

另有间接边界：`backend/tests/architecture/test_ai_prewarm_boundaries.py` 确认 `exam_service` 是 `prewarm_revision` 合法消费者，且不直接导入 worker；`backend/tests/test_services/test_phase5_2_vector_acceptance.py` 等涉及 `record_error_event` 的考试错因路径在练习/向量验收中覆盖。专项 API/OpenAPI、过时/取消并发、历史分页和真实 PostgreSQL/Redis/外部 AI/微信或生产集成仍未执行。

小程序本地重放（2026-10-24，Node 静态脚本）：

```bash
node miniprogram/tests/test-exam-terminal-navigation.js
node miniprogram/tests/test-storage-session-cleanup.js
```

结果：`Exam terminal navigation regression passed`；`Storage session cleanup regression passed`。

## 9. 未完成与未验证

- 考试专项测试当前仅覆盖服务层开始/提交主链；未覆盖完整 API 错误映射、过时 grace、取消并发、历史分页、PostgreSQL 行锁/部分唯一索引并发和真实外部环境。
- 未执行真实微信开发者工具/模拟器/真机、真实弱网/进程终止、生产 Admin 浏览器、真实 Redis 中断恢复、完整 worker、PostgreSQL 并发、外部 OCR/AI 或备份恢复演练。
- 考试域仍需后续按“开始 → 保存 → 过时 → 交卷 → 结果 → 历史”补专项测试与真实设备/生产验证。
- 已入库题目 `re_pending`、重审工作台与版本回滚已由 Admin 题库域实现；考试域仍只消费 `approved + is_active` 题目，不参与审核状态迁移。
- `practice_service.use_leitner` 的到期过滤与 fallback 已由 issuance 层 `candidate_schedule.filter_due_candidates` 统一执行，考试域不参与选题调度。
