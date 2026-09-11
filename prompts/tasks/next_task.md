/goal

全面审查并修复“小程序刷题从开始到结束”的完整后端链路。

这是一个执行任务，不是只做 code review。
你需要先理解小程序当前真实调用方式，再沿后端调用链检查实现、数据一致性、异常恢复、幂等、并发、性能和测试。
发现能够确认的问题后直接修改代码并验证，持续执行“审查 → 修复 → 测试 → 再审查”，直到完成条件满足。

==================================================
一、先理解真实客户端契约
==================================================

不要根据后端函数名猜业务流程。

首先阅读小程序中与刷题直接相关的代码，重点包括但不限于：

- subpackages/study/practice/practice.js
- subpackages/study/components/quiz-runner/**
- subpackages/study/utils/question-runner-adapter.js
- subpackages/study/utils/answer.js
- subpackages/study/practice-result/**
- review / wrong-question / study-plan 等刷题入口相关代码
- utils/api.js
- config.js

以小程序实际发送的 request 和实际消费的 response 作为 API contract。

先整理出完整流程和状态机，再开始修改后端。

当前已知核心链路包括：

1. 获取可刷科目
   GET /practice/subjects

2. 开始刷题 / 获取题目
   GET /practice/questions

3. 顺序刷题完成一轮后可能调用
   POST /practice/sequential/reset

4. 用户本地完成答题

5. 交卷
   POST /practice/batch-submit

6. 后端交卷后产生的所有业务副作用

7. 小程序进入 practice-result，继续访问错题、复习、统计等数据

但不要只检查以上几个 endpoint。
必须继续追踪它们内部调用的 service / repository / model / task / scheduler。

==================================================
二、重点检查 GET /practice/questions
==================================================

完整追踪请求参数的处理：

- subject_id
- include_children
- count
- mode
- exclude_answered
- no_repeat_days
- use_leitner
- question_ids
- plan_token
- knowledge_point_id
- include_descendants
- knowledge_point
- trace_id

覆盖至少这些模式：

- random
- smart
- sequential
- 指定题目重练
- 知识点专项
- 包含子知识点
- Study Plan 启动
- 允许重复刷题
- 禁止近期重复
- Leitner / spaced repetition

检查：

1. 实际取题范围是否正确。
2. subject / knowledge point scope 是否可能串范围。
3. include_children / include_descendants 是否语义一致。
4. question_ids 是否可能被推荐算法重新过滤。
5. count 是否可能返回超量、少量或重复题。
6. 是否可能返回无效 question id。
7. 是否会返回小程序不能作答的 question_type。
8. 是否存在已删除、禁用、审核未通过或版本异常的题目。
9. 是否有 N+1 SQL。
10. smart/random/sequential 是否存在重复数据库查询。
11. no-repeat / Leitner / recommendation 策略是否可能互相覆盖。
12. 顺序刷题游标是否正确推进。
13. 多并发请求下顺序进度是否会重复或跳题。

特别验证 response 中客户端依赖的：

- questions
- request_id
- submission_request_id
- batch_token
- mode
- trace_id
- sequential_progress
- knowledge_scope

这些字段必须具有一致且明确的语义。

==================================================
三、重点审查 batch_token
==================================================

完整追踪 batch_token：

生成
→ 保存/签名
→ 返回小程序
→ batch-submit 校验
→ 失效

检查：

- 是否绑定 user
- 是否绑定 question ids
- 是否绑定 question versions
- 是否绑定 subject
- 是否绑定 mode
- 是否有合理 expiration
- 是否能够篡改
- 是否可能跨用户使用
- 是否可能拿旧 batch 提交新答案
- 是否可能少提交/多提交题目绕过校验
- skipped_question_ids 是否必须属于 batch
- answers.question_id 是否必须属于 batch

不要只验证 token 存在，要验证整个 batch integrity。

==================================================
四、重点审查题目版本
==================================================

小程序获取题目后，到用户交卷可能经过较长时间。

检查：

- question_version_id
- question_version
- current question
- historical question version

交卷判题必须对应用户实际看到的题目版本。

确认以下情况不会错误判题：

1. 用户获取题目后管理员修改答案。
2. 用户获取题目后修改选项。
3. 用户获取题目后删除/禁用题目。
4. 用户刷题期间 question version 更新。
5. 历史版本缺失。

重点检查：

PRACTICE_QUESTION_VERSION_CONFLICT

是否真的只在无法安全恢复用户所见版本时产生。

绝不能偷偷使用最新答案给旧题判分。

==================================================
五、完整审查 POST /practice/batch-submit
==================================================

客户端真实 payload 包括类似：

answers: [
  {
    question_id,
    user_answer,
    used_time,
    request_id
  }
]

skipped_question_ids

session: {
  request_id,
  subject_id,
  mode,
  started_at,
  finished_at,
  duration_sec,
  question_count,
  answered_count,
  status
}

batch_token

注意：

answers[].request_id 是推荐链路 attribution request id。

session.request_id 是一次交卷的 idempotency request id。

不要把这两个 request_id 混为一个概念。

检查从 request validation 一直到 transaction commit 的整个链路。

==================================================
六、重点检查交卷幂等
==================================================

这是最高优先级。

客户端网络失败后会使用完全相同的 submission snapshot 重试。

因此：

同一个：

session.request_id
+
相同 payload

重复提交必须安全返回相同业务结果，不产生重复副作用。

但：

相同 request_id
+
不同 payload

必须确定性拒绝。

重点检查：

PRACTICE_SUBMISSION_CONFLICT

以及数据库层是否有真正的唯一约束或事务保护。

验证至少：

- 双击交卷
- 网络 timeout 后重试
- server 已 commit 但 response 丢失
- 两个并发相同 request
- 两个并发不同 payload 但 request_id 相同
- 服务重启后重试

不能只依赖内存锁。

==================================================
七、检查 batch-submit 原子性
==================================================

追踪一次提交会产生的所有写操作。

包括但不限于：

- practice/session record
- question answer record
- correct/wrong result
- wrong question
- wrong question quality / metadata
- review schedule
- Leitner state
- mastery / knowledge mastery
- knowledge point statistics
- subject statistics
- study duration/statistics
- recommendation feedback/log
- sequential progress
- user practice progress
- daily statistics
- dashboard aggregates
- study plan progress

搜索相关代码，例如：

review_scheduler
wrong_question_service
practice service
recommendation service
mastery service
study statistics
Leitner / review scheduling

确认：

一次 batch-submit 是一个业务事务。

不能出现：

答案写成功
但错题没写成功

或者：

错题写成功
但 review scheduler 失败

或者：

session 已标记 completed
但题目结果只写了一半

如果业务设计允许 eventual consistency，必须确认：

- 有可靠 job/outbox
- 可重试
- 幂等
- 不会静默丢数据

否则应该修复为适当的 transaction boundary。

==================================================
八、错题链路
==================================================

答错题目后完整检查：

batch-submit
→ 判错
→ wrong_question_service
→ wrong_question record
→ wrong book
→ wrong detail
→ 后续再次答题

重点检查：

1. 同一道题重复答错是否创建重复错误记录。
2. 应该 update 还是 insert。
3. wrong_count 是否正确。
4. 连续答错次数是否正确。
5. 最近答错时间是否正确。
6. 正确后错题状态怎么变化。
7. question version 是否记录正确。
8. subject / knowledge point 是否正确。
9. user_answer 是否标准化。
10. multiple_choice 顺序是否影响判题。
11. true_false normalization。
12. multi_blank_choice normalization。
13. skipped / partial 是否错误进入错题本。

==================================================
九、复习调度链路
==================================================

检查：

batch-submit
→ answer correctness
→ review_scheduler
→ next review

尤其检查：

- 首次答错
- 再次答错
- 答对
- 连续答对
- repeated submissions
- retry
- duplicate request

同一份 batch-submit 被重试时：

review schedule 不能被推进两次。

检查时间计算：

- timezone
- UTC / China time
- naive datetime / aware datetime
- date rollover

==================================================
十、答题正确性
==================================================

与小程序：

subpackages/study/utils/answer.js
subpackages/study/utils/question-runner-adapter.js

进行契约对照。

覆盖：

- single_choice
- multiple_choice
- true_false
- multi_blank_choice

检查 frontend 与 backend normalization 是否一致。

例如：

"A"
"a"
" A "
"AB"
"A,B"
["A","B"]

在合理情况下应该得到一致结果。

multi_blank_choice 重点检查：

- blank id
- answer order
- serialization
- 部分作答
- 空字符串
- 非法选项

绝不能出现：

前端认为已经作答，
后端认为未作答；

或者：

前端显示答案正确，
后端记错题。

==================================================
十一、skipped / partial
==================================================

小程序明确区分：

answered
partial
skipped

检查 batch-submit 是否正确处理：

- skipped_question_ids
- partially answered multi_blank_choice
- unanswered

不要把：

skipped

错误记录成：

wrong

也不要让 partial 产生不符合产品语义的 wrong-question / review side effect。

==================================================
十二、答题时间
==================================================

客户端上传：

used_time
duration_sec
started_at
finished_at

检查：

- 是否可信
- 是否需要限制最大值
- 是否允许负值
- duration 与 question time 是否异常
- 后台切换时间是否可能导致错误统计
- 极端值是否污染统计
- 用户篡改是否影响推荐系统

不要求重新设计反作弊系统，
但明显的数据完整性问题需要修复。

==================================================
十三、并发和竞态
==================================================

重点主动寻找：

check-then-write race
read-modify-write race

特别是：

- sequential cursor
- wrong question upsert
- mastery update
- Leitner update
- review schedule
- daily stats
- recommendation feedback
- idempotency record

如果数据库支持：

unique constraint
upsert
select for update
atomic update

优先使用数据库保证一致性，而不是进程级 Python lock。

==================================================
十四、异常和失败恢复
==================================================

模拟：

- DB timeout
- transient DB error
- deadlock
- network interruption
- duplicated request
- malformed payload
- expired token
- stale question version
- unauthorized user
- deleted question
- invalid subject
- partial batch
- duplicated question ids

检查异常是否：

返回正确 HTTP status
+
稳定 error code
+
不会留下半写数据

小程序目前至少会针对这些确定性错误停止重试：

- PRACTICE_SUBMISSION_CONFLICT
- PRACTICE_QUESTION_VERSION_CONFLICT
- PRACTICE_BATCH_INVALID
- PRACTICE_PAYLOAD_INVALID

检查后端是否与此契约一致。

==================================================
十五、性能
==================================================

重点检查一组 5 / 10 / 20 / 50 道题时：

GET /practice/questions

和：

POST /practice/batch-submit

数据库 query 数是否随题目数量出现明显 N+1。

特别检查：

- knowledge points
- question versions
- wrong-question lookup
- review state
- mastery
- recommendation logs

可以合理 batch query / bulk insert / upsert 的地方进行优化。

但是：

不要为了微小性能收益做大规模重构。

==================================================
十六、安全
==================================================

确认：

用户只能提交自己的 batch。

客户端不能通过修改：

question_id
subject_id
correct answer
question version
batch_token
request_id

影响其他用户或伪造成绩。

不要信任客户端上传的：

is_correct
correct_answer
subject ownership
question ownership

判题必须以服务端受信数据为准。

==================================================
十七、代码质量
==================================================

重点寻找影响该链路可靠性的：

- duplicated business rules
- 新旧两套刷题实现并存
- API / service validation 重复但规则不一致
- transaction boundary 混乱
- helper 语义不一致
- exception 被吞
- broad except
- commit 出现在 service 中间
- flush / commit 使用不一致
- hidden side effects
- dead code

只修改和本次刷题链直接相关的问题。

不要顺手重构整个项目。

==================================================
十八、测试
==================================================

先阅读现有相关 tests。

发现 bug 时优先增加 regression test。

至少覆盖：

A. 获取题目

- random
- smart
- sequential
- knowledge point
- child subjects
- targeted question ids
- no repeat
- invalid scope

B. 提交

- all correct
- wrong
- skipped
- partial
- mixed result

C. 幂等

- same request_id + same payload
- same request_id + different payload
- concurrent identical submit

D. version

- question modified after fetching
- valid historical version
- missing historical version

E. side effects

- wrong question
- review scheduler
- mastery
- Leitner
- sequential progress
- statistics

特别增加一个端到端 service/integration test：

获取一批题
→ 作答
→ batch-submit
→ 验证 session
→ 验证 answers
→ 验证 wrong questions
→ 验证 review schedule
→ 验证 progress/statistics

==================================================
十九、修复原则
==================================================

发现明确问题直接修复，不要只告诉我。

优先修根因。

不要：

- 为了测试通过删除功能
- catch Exception 后静默忽略
- 降低 validation
- 跳过测试
- 用 sleep 修 race condition
- 用前端 workaround 掩盖后端问题
- 大范围格式化无关文件

尽量：

- 保持现有 API contract
- 保持现有数据库 schema

但如果数据库 schema 缺少保证数据一致性所必需的：
unique constraint / index / relation

可以修改 migration。

如果涉及 migration：
先确认确实必要，并保证向前兼容。

不要新增第三方依赖，除非现有技术栈无法合理解决。

==================================================
二十、保护工作树
==================================================

开始前执行：

git status
git diff

保护当前已有未提交修改。

禁止：

git reset --hard
git checkout .
git clean
git stash

除非我明确要求。

不要覆盖与当前 goal 无关的用户修改。

==================================================
二十一、执行方式
==================================================

开始时先输出一个简短链路图，例如：

MiniProgram
  ↓
GET /practice/questions
  ↓
Practice API
  ↓
selection/recommendation
  ↓
batch token
  ↓
answer
  ↓
POST /practice/batch-submit
  ↓
validation
  ↓
grading
  ↓
transaction
  ├─ answer records
  ├─ wrong questions
  ├─ review schedule
  ├─ mastery
  ├─ recommendation feedback
  └─ statistics
  ↓
practice result

然后开始真正检查代码。

不要输出几十条可能存在的问题之后停止。

对于每一个问题：

确认代码证据
→ 判断真实影响
→ 修复
→ regression test
→ 验证

如果一个假设经过检查不存在问题，就不要为了“有产出”而修改代码。

==================================================
二十二、验证
==================================================

每修复一批问题执行最相关 tests。

最终至少尝试：

- 后端相关 unit tests
- practice API tests
- service tests
- integration tests
- lint / formatter check
- type/static check（如果项目已有）
- affected backend test suite

测试失败时：

判断是已有问题还是本次修改导致。

如果属于本链路真实 bug，继续处理。

==================================================
完成条件
==================================================

只有同时满足以下条件才能结束 goal：

1. 已从小程序真实 request contract 出发完整追踪刷题链路。
2. GET /practice/questions 已审查。
3. POST /practice/batch-submit 已审查。
4. batch token / question version 已审查。
5. idempotency / concurrent submit 已审查。
6. grading correctness 已审查。
7. wrong-question side effects 已审查。
8. review scheduling 已审查。
9. mastery / Leitner / statistics 等直接副作用已审查。
10. random / smart / sequential 三种核心模式已覆盖。
11. 所有确认的高/中优先级问题已经实际修复。
12. 对重要修复已有 regression tests。
13. 相关测试通过。
14. 最后重新检查 git diff 和 git status。
15. 没有误改无关模块。

在达到上述条件之前，不要仅因为完成一轮检查就宣布 goal complete。

最终报告只包含：

1. 实际确认的问题，按 Critical / High / Medium / Low 分类；
2. 每个问题的根因；
3. 已完成的修复；
4. 新增或修改的测试；
5. 实际运行的验证命令和结果；
6. 修改文件列表；
7. 仍存在的风险或无法验证项；
8. 如果没有遗留问题，明确写“未发现仍需处理的已知高/中优先级问题”。
