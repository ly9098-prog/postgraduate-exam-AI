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
- 结果按 `EXAM408_CORE_CODES` 固定科目顺序排序；弱知识点来自错题 revision 知识点名，按 `Counter.most_common(8)` 的错误次数和同次数出现顺序取前 8，`lost_score` 为累计展示字段，不参与排序（§321 按原实现核实并修正文档）。
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

## 10. 考试答案与讲解归一化（2026-10-26）

- `answer.normalizeBlankAnswer` 从 93 行收敛为 9 行分派，canonical 键值、圈号/括号/中文标记、可信 slotIds 位置答案各自解析。保留解析优先级、同分段多选续写、重复槽位处理、对象原引用返回和 slotIds 延迟读取。
- `ai-teacher-408.normalizeResult` 从 57 行降至 45 行，练习题建议结构由 `normalizePracticeQuestion` 处理；字段别名、truthy/nullish 区别、options 枚举顺序、getter 读取顺序、异常及中文文案不变。
- 两模块的 exports 名称与顺序不变，均未增加跨分包依赖；当前文件 230/232 行，全部函数不超过 50 行。生产源码净增 397 字节，仅属于 exam 分包；这不是微信编译/上传体积证据。
- 新增答案 27 项、讲解 10 项契约；独立复审在 HEAD 原模块和当前模块上重放相同 37 项均通过，无 P0–P3 发现。测试接入 reliability，仍未执行微信开发者工具、模拟器或真机验收。

## 11. 考试题干渲染职责（2026-10-26）

- `stem-render.js` 保留原公开 exports 的名称、顺序和形参；题干准备、模式路由与 payload 构造由 `stem-render-model.js` 负责，文本、选项、segments、代码块、诊断与依赖捕获分为同分包模块。原 `buildRenderModel` 137 行降为公开入口，核心 `renderModel` 为 29 行；八个业务文件均不超过 300 行，全部函数不超过 50 行。
- 保留依赖加载顺序、`RENDER_MODE` 每次入口加载的独立身份、render guard/诊断状态、五种模式互斥 payload、对象引用、getter/异常顺序及图像 URL 解析。study 分包继续保留自身实现，未增加跨分包依赖；原逐字同源检查改为导出和行为对照，并用 payload 篡改、导出缺失和 helper 行为变异验证断言能拒绝差异。
- 新增 32 项刻画在原版和新版均通过，作者 6,500 组新旧差分一致；相邻考试 60 项、考试版 CODE 197 项、render invariant 43 项、5 个历史 fixture 的 31 项及表格测试通过。门禁复用 Admin 的 TypeScript AST，并以 `vm.Script` 仅编译校验 JavaScript；不依赖 CI 未安装的小程序 node_modules。
- 八个业务源码合计 36,085→41,875 字节，净增 5,790 字节；按现有打包忽略规则，exam 分包累计 780,351 字节。study 仍为 1,396,402 字节，超出原 1.2 MiB 源码预算；未提高阈值。源码体积与 Node 回归不等于微信工具编译或设备验收。
- 独立审查补充 750 组结果/引用/异常/日志差分一致，原版与新版 32 项契约均通过。发现的 parity P3 已补有效 URL、选项图像 URL、跨页 guard 告警和 reset 状态对照，四种保留名称/arity 的 mutation 均由行为断言拒绝；最终两份契约与门禁 59 项通过，阻断 mini node_modules 解析仍通过，复审无 P0–P3 余项。

## 12. 考试结果页雷达/指标纯规则拆分（2026-10-28）

- 2026-10-28，`subpackages/exam/result/index.js` 由 526 行收敛到 301 行；`page-budgets.js` 的该页
  legacy ceiling 由 527 收紧到 302（预算只降不升）。
- 页面顶部 21 个纯声明（2 个常量 + 19 个函数）迁入新模块
  `subpackages/exam/utils/exam-result-view.js`（255 行，函数最长 45 行，均满足 300/50 预算）：
  `RADAR_SIZE`、`RADAR_ANGLES`、`clamp`、`percentNumber`、`compactDuration`、`compactScore`、
  `normalizeName`、`shortName`、`masteryTag`、`encouragement`、`encouragementTail`、
  `firstWrongIdByQuestion`、`buildKnowledgeMetrics`、`buildKnowledgeStats`、`sortAndSliceMetrics`、
  `fillSubjectBreakdown`、`fillOverallAndFallback`、`buildRadar`、`buildScoreRing`、`buildTopItems`、
  `collectWrongIds`；页面只 require 其中 12 个对外使用项，其余 9 个作为模块内部实现保留。
- 语义保持：时长 `Math.round` 后再分时/补零、分数整数值去尾零、`percentNumber` 的
  `<=1` 视为比例、`clamp` 非有限值返回下界、知识点名空白折叠与 `未命名知识点` 兜底、
  `shortName` 的 `maxLength-1` 截断加省略号、掌握度 85/70 分档、激励文案 90/80/60 分档、
  尾部文案“错题优先于未作答”、`firstWrongIdByQuestion` 仅接受正数、知识点统计按
  `status` 计数并保留首个 wrong id、`sortAndSliceMetrics` 的题量→正确率→名称排序与 5 条上限、
  综合表现与 `能力维度N` 兜底、雷达坐标/边/多边形样式、`buildScoreRing` 的 0/100 边界、
  `buildTopItems` 的 fallback 过滤与题量/正确率/名称排序、`collectWrongIds` 去重均逐字保留。
- 页面 `_examResultLoadController()` 的 25 项 capability 端口名称与顺序未变
  （`tests/test-exam-result-page-wiring.js` 原样通过），只是端口指向迁出的纯函数。
- 差分刻画：6,797 组调用（含 600 组种子随机的题目/结果形状）对照 HEAD 页面原实现与拆分后
  模块，返回值、错误与 JSON 形状 0 不一致（`/tmp/exam_result_view_parity.js`、
  `/tmp/exam-result-view-parity.log`）。
- 15 项契约（`tests/test-exam-result-view.js`）在 HEAD 原实现重放
  （`/tmp/exam-result-view-contracts-original.log`）与当前实现上均通过；其中补上
  `compactDuration(65.6)`、`percentNumber(1)`、同分同名项排序与负数 wrong id 等边界，
  使 30 个故障变体全部被拒绝（`/tmp/exam-result-view-mutants.log`、报告目录
  `/tmp/exam-result-view-mutants-2CiSEx`），覆盖时长阈值/取整、分数小数与非有限值、
  clamp 兜底、比例边界、名称折叠与兜底、截断长度、掌握度分档、激励取值与分档、尾部优先级、
  wrong id 分支、统计字段与 wrong 守卫、排序键与两种切片上限、兜底标签、雷达圆心/半径、
  环形边界与半径、Top 过滤/上限/同分排序、wrong id 去重与取值。
- 定向回归：`tests/test-exam-*.js` 392 passed；`scripts/test-408-ai-teacher.js` 与
  `scripts/test-408-feature-integration.js` 在 HEAD 树与本批前后失败集合完全一致
  （预存在失败，非本批回归）。
- 按当前 `reliability.yml` 的小程序步骤（265 行命令，含新增一项）本机精确重放：退出码 0、
  0 个 `not ok`、14,258 行输出、22.9 秒；本机重放不等于远端 CI。仍未执行真实微信开发者
  工具、模拟器或真机验收，也未验证结果页雷达图在真机上的渲染与点击。

## 13. MP-14 完整考试消费链响应投影（2026-10-30，§321）

当前消费者映射精确覆盖四个页面的九条静态契约：试卷列表、开始、作答视图、PATCH 草稿、取消、提交、结果、历史概览及旧历史回退。旧文档中试卷详情的客户端归属不作为当前静态消费证据；该路由保留，并因本轮投影迁移而纳入相邻 HTTP 契约。客户端已有恢复、pending、答案同步、交卷、终态导航和结果控制器，维持原实现。

`exam_service` 从 1200→1045 行：列表/详情/题目/保存响应/历史行与汇总归 `exam_read_projection`（177 行，8 函数，最长 35）；结果题目、科目汇总、弱知识点和快照 envelope 归 `exam_result_projection`（116 行，4 函数，最长 39）。两个模块均满足 300/50，无 import/异步/数据库操作；原服务仍拥有 SQL、时钟、状态检查、行锁、答案判定、模型写入和事务。原有较长的查询与事务函数不按长度继续拆分。

保留原入口及错误类型、每行动态 `_money`/内容/选项处理与常量读取；服务命名空间作为有界端口传入投影，避免提前冻结 helper。原始 24 个服务函数的签名与展开后的完整 AST 一致，12 个投影函数正文及每个实参绑定与原代码核对，32 处按源序数据库调用 AST 不变。开始幂等、8 秒 grace、revision 绑定、PATCH 元数据、最终答案/判题/错题/诊断/outbox 原子提交、JSON 编码及提交后 prewarm 顺序均保持。

原入口首轮 32 项通过；扩展后的同一组契约在原实现上 34 项通过，当前加 15 项门禁共 49 项通过。新服务契约覆盖读取时 helper 改绑顺序、列表仅显示过时但不改状态、弱知识点按次数而非丢分排序及错题/诊断链接、快照编码失败后关闭会话回滚；专用 FastAPI app/临时 SQLite 的一次生命周期覆盖九个消费者与相邻试卷详情、结果读取/重复交卷及两种历史响应。新增错题投影用例只把提交后的 prewarm 入队替换为 `AsyncMock` 并核对两次调用，不执行外部预热；不能由此声称真实外部服务已验收。

当前客户端考试 Node 测试 407 项通过；不是新一次完整 reliability shell，也不是微信编译/设备证据。本轮 readiness/cloud 门禁、冷进程全 OpenAPI、固定静态 CI、源码哈希及一次独立审查/提交状态集中在 [结果清单](refactor-results/miniprogram-exam-request-2026-10-30.json)。此前第 8–9 节的历史“尚未覆盖”描述以本次新增局部证据为补充，真实 PostgreSQL 行锁/部分唯一索引并发、Redis、微信、外部 AI 与生产环境仍未验收。

本条完成消费者所需的响应职责治理后停止继续按文件长度拆分。完整真实环境及生产验收仍是全部结构重构之后的最后阶段；本轮不授权部署、迁移、生产重启或用户数据操作。临时 `extract_once.py` 是源代码写入器，禁止作为验证命令重跑。
