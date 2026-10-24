# 错题本与复习调度兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限 Public 错题本、今日复习、SM-2 当前状态、错因诊断事实表和小程序对应消费者，不代表学习域、任务队列、OCR/AI 或全栈语义审查全部完成。

## 1. 入口与消费者

| 用例 | 实现入口 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| 今日复习旧列表 | `GET /api/v1/review/today` | 兼容保留入口；当前主要页面走任务流 | 响应不缓存；签发时重绑最新 revision 并持久化 `occurrence_seq`。 |
| 今日复习概览 | `GET /review/today/overview` | 小程序 `review-today` | `today_due_count` 是稳定今日任务集合，不只是当前 due。 |
| 获取下一组 | `POST /review/today/next-batch` | 小程序 `review-today` | `batch_size` 1-40；返回任务携带 `(schedule_id, revision, occurrence)`。 |
| 今日结果 | `GET /review/today/result` | 小程序 `review-today` 结果页 | 只统计属于今日任务集合的记录，同题同日取最新一次。 |
| 调度统计 | `GET /review/schedule-stats` | 复习统计消费者 | `days` 1-90；字段名 `accuracy_last_7d` 是兼容命名，实际窗口跟随 `days`。 |
| 复习历史 | `GET /review/history` | 复习历史消费者 | 分页读取追加型 `ReviewRecord`，不做当前状态反推。 |
| 批量自动批改 | `POST /review/grade-batch` | 小程序 `review-today` | 每批 1-40 题、每题独立 `request_id`；业务失败逐题返回。 |
| 手动掌握/撤销 | `POST /review/{schedule_id}/master`、`/unmaster` | 小程序今日复习页 | 只作用于当前用户任务；`changed` 表示真实语义迁移。 |
| 错题列表 | `GET /api/v1/wrong-questions` | 小程序错题本 | 展示当前 `questions` 投影；历史统计仍绑定 `WrongQuestion.question_version_id`。 |
| 错题统计 | `GET /wrong-questions/stats` | 小程序错题本 | `today_due_count` 表示当前仍 due 的任务，不是稳定今日集合。 |
| 错题任务流 | `GET /wrong-questions/task-flow` | 小程序错题本任务视图 | 分组优先去重；summary 的 `today_due_count` 是非独占标题计数。 |
| 错题详情 | `GET /wrong-questions/{wq_id}` | 小程序错题详情 | 当前投影修正立即反映；缺失题目时保留行但题面为空。 |
| 错题分类编辑 | `PUT /wrong-questions/{wq_id}` | 错题详情编辑入口 | 仅编辑 `error_type`；成功后失效错题/统计缓存。 |
| 批量错题操作 | `POST /wrong-questions/batch` | 错题本、错题详情、结果页相关操作 | 1-100 个 ID，去重保序；非本人或已失效项跳过。 |
| 错因 taxonomy | `GET /wrong-questions/diagnosis/taxonomy` | 错因 UI | 静态分类清单，不触发数据写入。 |
| 错因统计 | `GET /wrong-questions/diagnosis/stats` | 小程序 dashboard | `window_days` 7-365；用户确认优先于 AI 建议。 |
| 单题错因 | `GET/PUT /wrong-questions/{wq_id}/diagnosis` | 错题详情、练习结果页 | GET 缺失时为 legacy 错题补一条 occurrence 行。 |
| AI 错因建议 | `POST /wrong-questions/{wq_id}/diagnosis/suggest` | 当前小程序不再主动调用 | 后端入口保留；手动请求递增 classification_version 并入队。 |

注册以 `backend/app/api/v1/router.py` 与当前小程序请求为准。小程序静态回归确认“我的错因”不再发起 `/diagnosis/suggest`，因此该入口不能被描述为当前默认用户路径。

## 2. 数据职责与唯一性

- `WrongQuestion` 是每用户每题一条错题聚合行，`(user_id, question_id)` 唯一。`question_version_id` 表示产生最新错误尝试的不可变 revision；`wrong_answer/review_count/error_type/ai_analysis/mastered/is_active` 是错题本展示与操作状态。管理员修正题目后，列表/详情题面读取当前 `questions` 投影，历史复习次数、next review 和掌握度子查询仍按该 revision 绑定。
- `ReviewSchedule` 是唯一 SM-2 当前状态，`(user_id, question_id)` 唯一。`interval/ease_factor/repetitions/next_review_at/mastered/is_active` 描述下一任务；`occurrence_seq` 是服务器拥有的任务代数，非客户端请求次数。
- `ReviewRecord` 是追加型复习历史，`(user_id, request_id)` 支持网络重放，`(schedule_id, occurrence_seq)` 保证一个任务代数只消费一次；保存 rating 前后快照、答案、对错、掌握度与 revision。
- `ReviewSession` 是一组今日复习的学习时长事实，`(user_id, request_id)` 唯一；一组跨科目时按成功题数拆分时长，`request_id` 形如 `<segment>:<subject_id|none>`。它不参与判题。
- `WrongQuestionErrorDiagnosis` 是一次错误尝试的 occurrence 级事实；`practice_record_id` 与 `exam_answer_id` 各自唯一，`source_context` 只能是 `practice/exam/legacy`。用户确认与 AI 建议分开存储，读取时用户确认优先。

## 3. revision、occurrence 与幂等

- 复习发题时通过 `_prepare_latest_review_revisions` 将任务重绑到最新 `QuestionVersion`。revision 真正变化时在行锁内更新 schedule revision/subject，并递增 `occurrence_seq`，随后提交；因此客户端拿到并判题的是精确的 `(schedule, revision, occurrence)`。
- `submit_review` 先获取 request 锁与题目状态锁，再按 `(user, request_id)` 精确重放。重放必须匹配 schedule、题目、revision、occurrence、rating 和答案；不匹配返回确定性错误。重放不重新推进 SM-2。
- 首次提交按 schedule 归属、active、mastered、revision 和 occurrence 依次防御。SM-2 更新、错题同步、`ReviewRecord` 插入和 `occurrence_seq + 1` 在同一事务中提交。
- `grade-batch` 每题独立 `request_id`，按题目稳定排序处理，整体一次提交；确定性 `ValueError` 映射为逐题 `error_code/retryable/refresh_required`。网络/5xx 不会进入该逐题结果，仍按 HTTP 失败处理。
- PostgreSQL 使用 `(user, request_id)` 与 `(user, question_id)` advisory lock 串行化；SQLite 依赖写序列化和数据库唯一约束。锁只保护状态推进，不替代唯一约束。

## 4. SM-2 与掌握状态

- 算法唯一入口是 `sm2_service.calc_sm2`：错题 rating=1、正确 rating=4；错误归零连续正确并重置 1 天，正确按 1/6/interval×EF 推进，EF 下限 1.3。日期按上海日历日并保存为 naive UTC 起点瞬时。
- 复习掌握度按连续正确次数映射为 20/45/65/80/90/100%，第 3 次连续正确自动 mastered。该掌握度是 scheduled revision 语义，不读取 `UserQuestionState` 的当前题自适应状态。
- 手动 `master/unmaster` 通过 `set_mastered_state` 同步 `WrongQuestion` 与 `ReviewSchedule`。只有 canonical mastery 布尔真实变化才返回 `changed=true` 并递增 occurrence；修复 `mastered_at` 元数据不授予 undo 权利。手动掌握会消耗今日可见任务但不写 `ReviewRecord`。
- 再次答错会重置错题和 schedule 的 mastered 状态，更新最新答案/revision，清除 revision 相关 AI 分析，并重新调度。发题时的 revision 重绑也同步错题行并清除旧 AI 分析。

## 5. 今日任务、统计与缓存

- 今日复习 overview 的稳定任务集合是“当前 due + 今日已产生 ReviewRecord + 今日手动掌握”的并集，任务按 `next_review_at/id` 排序；`today_due_count` 表示该集合总数，`remaining` 排除已复习/已掌握题。跨入口同日复习不会污染该集合的准确率。
- `wrong-questions/stats` 与 task-flow 的 `today_due_count` 只统计当前仍 due 的任务；字段同名但语义不同。小程序错题本标题计数可随提交下降，今日复习入口的“今日总任务”在完成后保持稳定，这是有意兼容差异，不能合并或顺手修正。
- `review/schedule-stats` 的响应键保留 `accuracy_last_7d`，但服务端按请求 `days` 计算 1-90 天窗口；schema 不能在等价重构中改名。
- 错题任务流 summary 中 `high_frequency_count`/`today_due_count` 是非独占标题计数；groups 内桶按“今日应复习 → 高频 → 最近新增 → 待巩固 → 已掌握”优先去重。
- `GET /review/today` 和 next-batch 不缓存 actionable payload。overview TTL 60 秒、schedule-stats TTL 300 秒；批改、手动掌握/撤销、错题批量操作和练习提交都会失效 `review:*:{uid}*` 与 `stats:*:{uid}*`。错题诊断确认还失效 dashboard 专用 pattern。缓存删除失败会回退本地缓存，属于既有可用性语义。

## 6. 批量操作与删除边界

- 批量请求最多 100 个错题行 ID，schema 与服务层均去重保序。非本人 ID 进入 `skipped_ids`；动作按 `question_id` 稳定排序加锁，避免重叠批次死锁。
- `add_to_review` 每项使用 savepoint：恢复 active、取消 mastered、缺失或版本变化时重建/重绑 schedule，并把未来任务拉到当前时间；单项异常只跳过该行，不回滚整批。
- `mark_mastered/unmark_mastered` 只作用于仍在错题本中的 active 行；陈旧页面请求不会获得 undo。`changed=false` 时跳过。
- `remove_from_book` 是软移除：错题行 inactive 并递增 schedule occurrence；`add_to_review` 是显式恢复路径。
- `delete` 是应用提供的硬删除路径，会删除该用户该题的 `ReviewRecord`、`ReviewSchedule` 和 `WrongQuestion`；仅测试可使用临时 SQLite 数据，禁止对用户或生产数据执行。前端提供二次确认。

## 7. 错题列表、日期与文本投影

- 列表与详情对题面/options 做学生端 sanitize：归一换行、移除 admin-only 字段；普通文本可做 OCR 去重和 roman 子题拆分，代码内容只合并尾随运算符，不做普通 OCR 去重。task-flow preview 与普通列表保持同一投影契约。
- `date_from/date_to` 是北京时间自然日，服务端映射为半开 naive UTC 区间并校验开始不得晚于结束；过滤的是错题加入时间 `WrongQuestion.created_at`，不是最近复习时间。
- 小程序日期筛选支持 today/week/month/custom、跨零点重置相对区间、分页重新从第 1 页开始、请求序号防乱序响应；自定义日期在零点后保持固定，直到用户重新选择。
- 列表稳定排序为 `updated_at DESC, id DESC`，`id` tie-breaker 防止相同时间戳分页重复/漏行。

## 8. 错因诊断与 AI 边界

- practice/exam 错误事实在答题主事务内通过 `record_error_event` 建立；practice_record/exam_answer 唯一键与 savepoint 处理并发重试。当前默认 `queue_ai=false`，答题主事务不因可选 AI 富化失败而回滚。
- 手动 `/diagnosis/suggest` 会锁定诊断行、递增 `classification_version`、生成确定性 outbox task id `error_diagnosis:{id}:{version}:{suffix}` 并提交。重复非终态 task 不重复入队；入队失败置 `ai_status=failed`，不吞成永久 pending。
- worker 生成建议前校验 classification version，AI 返回后重新锁行再应用，防止旧 worker 覆盖新手动重试；失败也只在同版本上写 failed。建议始终不能覆盖用户确认。
- 用户确认 `PUT /diagnosis` 写入 user_primary/user_secondary 和确认时间，同时维护 legacy `WrongQuestion.error_type` 投影；它不递增 classification_version，已排队建议仍可完成但展示仍以用户确认为准。
- dashboard 错因统计以 occurrence 表为事实源，按有效错因（用户确认 > AI suggested > unknown）统计；知识点按 revision 关系计数，一个 occurrence 对多个知识点时每个知识点计一次，不重复计同一 relation/ordinal。

## 9. 小程序兼容

- 今日复习页按 `(schedule_id, question_version_id, occurrence_seq)` 生成并缓存每题 request_id，同一 immutable occurrence 重试复用；草稿按 revision/occurrence 匹配恢复，提交成功后清理对应草稿。
- 批量提交前校验全部作答和三联版本信息；计时快照在 HTTP 请求前冻结，网络时间不计入学习时长。服务端按 `(user, request_id)` 幂等记录 ReviewSession，同一分段重试不重复计时。
- 逐题失败按 `refresh_required/retryable` 分流：需刷新的任务重新获取，可重试任务保留本地组继续重试；批改结果用 schedule + revision + occurrence 精确匹配，防止同题旧结果误投影。
- 手动掌握/撤销由今日复习页调用 review master 端点，错题详情和错题本调用 wrong-questions batch；undo 仅在真实 changed 后出现，5 秒窗口过期后要求刷新，不提供跨设备盲撤销。
- 错题详情/练习结果页确认错因时优先显示本地确认结果，再异步刷新专属 diagnosis；迟到的空/旧 aggregate 不能覆盖已确认事实。练习结果页批量错因逐题 PUT，部分失败保留失败选择供重试。
- 错题本日期筛选、任务流、批量操作、AI 洞察和导出能力检查均有本地请求序号/生命周期守卫；页面卸载后迟到响应不写 UI。

## 10. 旧数据与迁移兼容

- revision 完整性迁移为 wrong/review 行补齐 `question_version_id`、`request_id` 和 `occurrence_seq`；历史重复 WrongQuestion/ReviewSchedule 归并为 canonical 行，并重映射历史 ReviewRecord。历史 request_id 缺失时生成 `migration-review:{record_id}` 确定值。
- 历史 ReviewRecord 绑定当时的 canonical revision，并按 schedule 顺序分配 occurrence；schedule 的下一次 occurrence 为历史消费数。无法安全重建的 practice 记录落为 `archived`，不能被重新解释。
- `review_sessions` 迁移只建表，不回填历史时长；历史复习无时长事实，番茄钟/统计不能虚构。
- 错因迁移把 legacy `WrongQuestion.error_type` 中有意义的值转换为一条 `source_context=legacy` 的用户确认事实；无法识别的值保留为 unknown，不自动继承到新错误尝试。

## 11. 可执行基线

后端本地重放（2026-10-24，SQLite/in-memory，无 Redis/Sentry）：

```bash
APP_ENV=test APP_SECRET=ci-refactor-test-secret-not-production \
DATABASE_URL=sqlite+aiosqlite:///:memory: REDIS_URL= SENTRY_DSN= \
STAGING_STORAGE_DIR=/tmp/review-compat-staging \
.venv/bin/python -m pytest tests/test_api/test_review_api.py \
tests/test_api/test_review_master_api.py \
tests/test_api/test_wrong_question_update_cache.py \
tests/test_features/test_wrong_question_batch.py \
tests/test_features/test_wrong_question_date_filter.py \
tests/test_services/test_wrong_question_service.py \
tests/test_services/test_review_scheduler.py \
tests/test_services/test_review_scheduler_service.py \
tests/test_services/test_review_session_stats.py \
tests/test_services/test_e2e_review_flow.py \
tests/test_services/test_review_overview_dirty_schedule.py \
-q --tb=short
```

结果：`127 passed in 85.53s`。

小程序本地重放（2026-10-24，Node 静态/单元脚本）：

```bash
node --test miniprogram/tests/test-review-group-submission.js \
  miniprogram/tests/test-review-submit-confirm-controller.js \
  miniprogram/tests/test-review-submit-request-controller.js \
  miniprogram/tests/test-review-submit-result-controller.js \
  miniprogram/tests/test-review-submit-entry-controller.js \
  miniprogram/tests/test-review-next-retry-group-controller.js \
  miniprogram/tests/test-review-next-remote-batch-controller.js \
  miniprogram/tests/test-review-next-group-controller.js \
  miniprogram/tests/test-review-result-dock-controller.js \
  miniprogram/tests/test-review-timer-controller.js \
  miniprogram/tests/test-review-master-controller.js \
  miniprogram/tests/test-review-start-batch-controller.js \
  miniprogram/tests/test-review-draft-controller.js \
  miniprogram/tests/test-review-answer-interaction-controller.js \
  miniprogram/tests/test-review-question-display-controller.js \
  miniprogram/tests/test-review-overview-vm-controller.js \
  miniprogram/tests/test-review-render-safety-controller.js \
  miniprogram/tests/test-review-batch-size-sheet-controller.js \
  miniprogram/tests/test-review-question-enrichment-controller.js \
  miniprogram/tests/test-review-session-controller.js \
  miniprogram/tests/test-review-nav-back-controller.js \
  miniprogram/tests/test-review-self-heal-controller.js \
  miniprogram/tests/test-review-overview-sync-controller.js

node miniprogram/tests/test-review-submit-completion.js
node miniprogram/scripts/test-error-diagnosis.js
node miniprogram/tests/test-wrong-book-date-filter.js
```

结果：CI 清单 `node --test` 为 `124 passed`；`test-review-submit-completion.js` 通过；`test-error-diagnosis.js` 通过；`test-wrong-book-date-filter.js` 输出 `PASS`。

另执行 `miniprogram/scripts/test-review-today-interactions.js`：34 项通过、26 项失败。失败原因是该历史页面级脚本仍假定控制器工厂方法/旧内联代码形状，而当前实现已拆分到控制器模块；同一脚本源码字符串检查也落后于 `start-batch-controller`、`group-submission` 和 `submit-request-controller`。该脚本不在当前 `.github/workflows/reliability.yml` review 清单中，不能把本次失败扩大为小程序功能失败，也不能把已接入的控制器回归视为页面级/真机验收。

## 12. 未完成与未验证

- 未执行真实微信开发者工具/模拟器/真机、真实弱网或进程终止、生产 Admin 浏览器、真实 Redis 中断恢复、完整 worker/scheduler、PostgreSQL 并发、外部 OCR/AI 或备份恢复演练。上述 SQLite 与 Node 证据均不能升级为生产或设备验收。
- 错题本 `delete` 是硬删除路径，测试仅允许临时 SQLite；尚未对生产或用户数据做任何删除操作。
- AI 错因建议的完整外部模型调用与 worker 循环未在本次验证；只完成代码语义和静态/单元边界盘点。
- `questions.review_status = re_pending`、重审工作台、已入库题目重审/版本回滚仍是设计预留；本基线不改变审核状态机。
- `practice_service.use_leitner` 仍有 TODO(V3)。实现向量/path 结果后的到期过滤和 Leitner fallback 会改变选题行为，必须单独立项，不能混入本批等价审查。
