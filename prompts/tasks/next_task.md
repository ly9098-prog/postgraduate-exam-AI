现在进入这个功能的 **最终上线前验收阶段**。

前一轮你已经完成：

- PracticeSession
- 刷题时长进入番茄钟学习统计
- `/pomodoro/history` 合并刷题记录
- Pomodoro / Practice 时间重叠去重
- 跨统计日分摊
- request_id 幂等
- 前端最近记录展示
- 测试补充
- 第一轮 code review finding 修复

这一次 **不要新增需求，不要重构无关模块**。

你的任务是：

> 不依赖上一轮的自我总结，直接以当前仓库的实际 git diff、数据库模型、SQL、API、前端调用和测试为准，做一次独立的 production-readiness review。发现真实问题就直接修；没有问题就提供证据说明为什么正确。

------

# 1. 先查看实际改动

先执行并检查：

```bash
git status
git diff --stat
git diff
```

如果改动已经 staged：

```bash
git diff --cached
```

逐文件 review 本次功能涉及的所有变化。

重点文件至少包括：

```text
backend/app/models/practice_session.py
backend/alembic/versions/f1a2b3c4d5e6_add_practice_sessions.py

backend/app/models/__init__.py
backend/app/models/admin.py
backend/app/core/database.py

backend/app/schemas/practice.py
backend/app/api/v1/practice.py
backend/app/services/practice_service.py

backend/app/services/pomodoro_attribution.py
backend/app/services/pomodoro_service.py
backend/app/schemas/pomodoro.py
backend/app/api/v1/pomodoro.py

miniprogram/subpackages/study/practice/practice.js

miniprogram/subpackages/productivity/pomodoro-stats/index.js
miniprogram/subpackages/productivity/pomodoro-stats/index.wxml

backend/tests/test_services/test_practice_session_stats.py
backend/tests/test_services/test_pomodoro_study_day_stats.py

miniprogram/scripts/test-pomodoro-practice-stats.js
```

不要根据之前写的总结判断实现已经正确。

------

# 2. 第一优先级：检查学习时长数学是否绝对正确

本功能最危险的是：

```text
Pomodoro duration
+
Practice duration
-
overlap
```

请逐行检查 attribution / interval 算法。

必须证明以下恒等式成立。

## Case A：完全不重叠

```text
Pomodoro: 10:00-10:25 = 1500s
Practice: 11:00-11:20 = 1200s

学习总时长 = 2700s
```

------

## Case B：部分重叠

```text
Pomodoro active: 10:00-10:25
Practice:        10:15-10:35

Pomodoro = 1500
Practice 净增 = 600

total = 2100
```

不能：

```text
2700
```

也不能：

```text
1500
```

------

## Case C：Practice 完全位于 Pomodoro active 内

```text
Pomodoro: 10:00-10:25
Practice: 10:05-10:20

total = 1500
```

但 `/history` 仍应存在两条行为记录。

------

## Case D：番茄暂停时刷题

例如：

```text
Pomodoro:
10:00-10:25

pause:
10:05-10:15

Practice:
10:08-10:13
```

如果 Pomodoro 实际 active：

```text
10:00-10:05
10:15-10:25
```

则：

```text
Practice 10:08-10:13
```

必须完整贡献 5 分钟。

不要因为 Pomodoro session 的：

```text
start_time -> end_time
```

覆盖 Practice 就错误减掉。

------

# 3. 重新审查 Finding 6，不允许只引用上一轮理由

上一轮明确写了：

> Finding 6（pomodoro actual_duration < active wall 时的过度排除）有意不改，因为 V2 规范化后 actual_duration == active wall。

这一次请重新从实际代码证明这个假设。

检查所有可能产生 PomodoroSession 的路径：

- 固定番茄
- free timer
- 暂停 / 恢复
- 中断
- stop
- complete
- 历史旧数据
- migration 前数据
- API 直接写入路径
- 测试 fixture

确认数据库是否真的存在强约束保证：

```text
actual_duration
==
所有 active interval 的墙钟长度
```

如果这个等式：

- 只是业务通常成立
- 但数据库没有强约束
- 或历史数据可能不成立

那么：

**Practice overlap 去重不能直接用完整 active wall interval 去排除 Practice。**

例如：

```text
Pomodoro active wall = 25min
actual_duration = 20min
Practice 与这个 wall interval 重叠 10min
```

如果直接排掉 Practice 10min：

```text
20 + Practice剩余
```

可能造成真实学习时长欠计。

如果这是一个真实可达的数据状态，请修算法。

目标：

> overlap exclusion 的总量不能超过 Pomodoro 实际已经贡献到统计中的时长。

要求增加回归测试。

如果确认绝对不可达，也要给出具体代码/constraint 证据，不接受一句“V2 已保证”。

------

# 4. 重新审查 Finding 8

上一轮写了：

> 全被番茄覆盖的刷题会话不生成科目切片，有意不改。

请重新判断产品语义是否正确。

场景：

```text
10:00-10:25
番茄钟：无科目 / 英语

10:05-10:20
实际在刷：高等数学
```

虽然 wall-clock 总时长不能重复：

```text
总学习时间仍然只有 25min
```

但「科目学习时长分布」应该是什么？

当前需求中有：

> 用户刷高等数学 18 分钟，则这 18 分钟应进入高等数学的科目学习时长。

这里存在一个独立问题：

**总学习时长去重 ≠ 科目归因一定要把 Practice 完全删除。**

请检查目前算法是否会导致：

```text
总学习时长 = 25min
但高等数学 = 0min
```

如果会，重新判断是否符合业务。

需要明确设计以下情况：

### 情况 1

Pomodoro 本身 subject_id 与 Practice 相同：

```text
Pomodoro 数学 + Practice 数学
```

应该只计一次数学时长。

### 情况 2

Pomodoro 没有科目，但 Practice 有数学：

需要判断这段 wall-clock 应如何归因。

### 情况 3

Pomodoro 英语 + Practice 数学同时存在：

总时间不能重复。

但 subject distribution 不能简单变成：

```text
英语 25min
数学 15min
总科目 = 40min
总学习 = 25min
```

除非 UI 明确允许科目时长是行为维度、可以超过总学习时长。

当前 UI 看起来是：

```text
各科目学习时长占比
```

因此正常情况下：

```text
sum(subject.duration_sec)
```

应该等于：

```text
daily_summary.duration_sec
```

请明确检查并增加 invariant：

```python
sum(subject duration) == daily total duration
```

允许整数拆分产生极小 rounding 误差时再处理。

如果目前实现会破坏这个 invariant，请修复。

不要为了修复引入复杂的任意分摊。

应根据已有产品语义选择确定性规则，并在代码注释中写清楚：

```text
当 Pomodoro 与 Practice 重叠且科目不同，重叠墙钟时间归属于谁？
```

推荐优先考虑：

```text
更具体的学习行为 Practice 覆盖无科目 Pomodoro 的科目归因；
已有明确 subject 的 Pomodoro 与 Practice 冲突时保持单一确定规则。
```

但先基于项目现状判断。

------

# 5. 检查跨统计日 + overlap 同时发生

不要只分别测试：

- 跨日
- overlap

必须测试二者组合。

例如：

```text
day_start = 06:00

Pomodoro:
05:45 -> 06:15

Practice:
05:55 -> 06:05
```

要求：

- 两个统计日贡献正确
- overlap 只扣对应统计日内真正重叠部分
- 所有统计日总贡献守恒
- 不出现负值
- 不因为切日顺序不同产生结果差异

增加 property/invariant 风格测试：

```text
daily contribution >= 0
```

并且：

```text
sum(all study-day contribution)
==
union(active Pomodoro + Practice wall-clock contribution)
```

在现有 duration normalization 语义允许的范围内成立。

------

# 6. 检查多个 Pomodoro interval 对一个 Practice 的 overlap

例如：

```text
Practice:
10:00-11:00

Pomodoro A:
10:05-10:25

Pomodoro B:
10:20-10:40
```

Pomodoro A/B 本身 overlap。

不能从 Practice 里减：

```text
20 + 20 = 40min
```

因为：

```text
10:20-10:25
```

被重复覆盖。

必须先：

```text
union Pomodoro active intervals
```

再从 Practice 排除。

增加测试。

------

# 7. 检查多个 Practice Session

上一轮为了避免顺序依赖，明确：

> Practice 不再互相去重。

请验证这是否符合真实产品行为。

如果 UI 可以由于：

- 双击
- 页面恢复
- request_id 不同
- bug
- 多设备

生成两个相互重叠的 PracticeSession：

```text
Practice A 10:00-10:30
Practice B 10:15-10:45
```

当前总时长是否变成：

```text
60min
```

而真实墙钟只有：

```text
45min
```

首先检查业务是否真的保证 PracticeSession 互斥。

如果只是“正常 UI 不会这样”，不代表生产数据不可能发生。

但不要未经需求就大幅修改行为。

请做以下决策：

### 如果存在强业务/代码保证互斥

提供证据并保持现状。

### 如果没有强保证

评估是否应该把所有学习 activity interval 统一做 union。

如果修改，必须保证：

- subject attribution 仍正确
- history 不去重
- request_id 幂等仍独立存在

------

# 8. Practice session duration normalization 深度检查

检查：

```text
started_at
finished_at
duration_sec
```

三者关系。

必须防止：

```text
duration_sec > wall-clock duration
duration_sec < 0
finished_at < started_at
极端未来时间
极端历史时间
NaN / float / bool
```

尤其要检查：

```text
duration_sec 被 clamp 后，
跨日 attribution 是否仍按正确比例守恒
```

例如：

```text
wall = 1200 sec
client duration = 5000 sec
server clamp → 1200
```

最终统计不能继续使用旧的 5000。

------

# 9. 检查客户端 duration 是否可能包含后台挂起时间

检查：

```text
practice.js
```

当前：

```js
Date.now() - startTime
```

是否会把：

- 微信切后台 1 小时
- 锁屏
- 去其他页面
- onHide
- onUnload
- app suspend

全部算成刷题时长。

检查页面已有生命周期代码。

如果现有 `elapsedSec` timer 已经只统计有效前台学习时间，而最终：

```js
duration = Date.now() - startTime
```

却重新使用墙钟时间，就可能造成：

用户刷题 5 分钟
切后台 50 分钟
回来提交

记录成：

```text
55分钟
```

请明确检查。

如果当前产品已经有：

```text
elapsedSec
questionTimeMap
onHide/onShow
```

优先让 PracticeSession duration 使用现有“有效刷题计时器”的最终值，而不是简单墙钟差。

但仍要保留：

```text
started_at
finished_at
```

用于统计日归属和 overlap。

如果：

```text
duration_sec < finished_at - started_at
```

则 attribution 算法必须正确处理这种“有效学习时长小于墙钟跨度”的情况。

这是与 Finding 6 同类的核心数学问题。

不要为了满足 overlap 简单假设 duration 永远等于 wall time。

------

# 10. 检查 history 的 SQL / pagination

检查 `/pomodoro/history`。

必须验证：

```text
total
page
page_size
items
```

对 UNION 后结果严格正确。

测试：

### 数据

Pomodoro：

```text
10:00
10:20
10:40
```

Practice：

```text
10:10
10:30
10:50
```

page_size = 2。

必须：

```text
page 1:
10:50 P
10:40 Pomodoro

page 2:
10:30 P
10:20 Pomodoro

page 3:
10:10 P
10:00 Pomodoro
```

不能丢项、重复或者顺序错。

------

# 11. history 同秒排序必须稳定

如果：

```text
Pomodoro.start_time == Practice.started_at
```

只按：

```sql
ORDER BY start_time DESC
```

数据库分页可能不稳定。

增加 deterministic secondary sort，例如：

```text
start_time DESC
record_type
id DESC
```

或等价稳定顺序。

保证翻页时不会：

- 同一记录出现两页
- 某记录消失

增加测试。

------

# 12. 检查 UNION 类型兼容性

重点考虑 PostgreSQL。

确认：

```text
Pomodoro id
Practice id
record_key
record_type
subject_id
subject_name
start_time
end_time
actual_duration
status
```

UNION 两侧 SQL 类型兼容。

特别关注：

```text
NULL
enum
varchar
datetime timezone
integer/bigint
```

SQLite 测试通过不代表 PostgreSQL UNION 一定能执行。

如果使用 SQLAlchemy：

- 显式 label
- 必要时 cast

避免 PostgreSQL 上出现：

```text
UNION types X and Y cannot be matched
```

------

# 13. Alembic migration 做真正的 upgrade / downgrade review

检查：

```text
f1a2b3c4d5e6_add_practice_sessions.py
```

确认：

```python
down_revision
```

真的指向当前 Alembic head。

不要仅因为文件名看起来像 head 就认为正确。

执行：

```bash
alembic heads
alembic history
```

确保没有意外产生多个 head。

如果项目测试环境允许：

1. 空数据库 upgrade head
2. 确认 practice_sessions 表/索引/约束
3. downgrade 一版
4. 再 upgrade head

至少检查 migration 可逆。

------

# 14. 检查 PostgreSQL partial unique index

确认：

```text
(user_id, request_id)
```

所谓“部分唯一索引”在：

- PostgreSQL
- SQLite 测试

语义一致。

如果条件类似：

```text
request_id IS NOT NULL
```

但现在：

```text
PracticeSessionMeta.request_id 必填
```

请确认 model 与 migration 没有出现不必要的不一致。

同时检查 request_id：

```text
VARCHAR(64)
```

和代码：

```python
request_id[:64]
```

是否存在幂等碰撞问题：

两个不同的 >64 字符 request_id：

```text
前 64 位完全一样
```

会被截断成同一个 key。

这是潜在 correctness bug。

不要简单继续截断。

更合理的选项可能是：

- schema max_length=64，客户端超长 session meta 视为 malformed 并只跳过 session
- 或对超长 request_id 做稳定 hash
- 或扩大 DB column

要求选择不会把两个不同 request_id 错误合并的方案。

旧答案提交仍不能因为 malformed session 丢失。

增加回归测试：

```text
两个不同超长 request_id，前64位相同
```

绝不能被当成同一次会话。

------

# 15. malformed session 的事务行为

上一轮已经改成：

> session metadata 异常时保留 answers，只跳过 PracticeSession。

重新检查 transaction。

保证：

```text
answers insert
PracticeSession normalization failure
```

不会：

- rollback answers
- 留 session 半成品
- 导致 mastery / wrong book / recommendation 阶段读取错误数据

同时确认 API response 是否需要让客户端知道：

```text
答案提交成功
但学习 session 未被记录
```

当前如果完全静默，只写日志，用户学习统计可能无声丢数据。

这里不要擅自修改协议。

但请评估是否至少可以在 response 中兼容地增加：

```text
session_recorded: true/false
```

如果会扩大本轮范围，则只记录为后续建议，不强行实现。

------

# 16. subject_id 防伪

目前逻辑似乎：

> 客户端传不存在 subject_id 时，回退到题目真实 subject。

还需要检查：

如果客户端传的是：

```text
一个存在、但与题目完全无关的 subject_id
```

是否会被直接接受。

比如：

实际刷：

```text
数学题
```

客户端伪造：

```text
英语 subject_id
```

最终科目统计会被污染。

PracticeSession.subject_id 应优先来源于：

- 实际题目 subject
- 或本次练习系统已经确定的 subject

而不是无条件相信客户端。

检查：

- 同批题是否保证同一 subject
- mixed subject practice 是否允许

如果当前模式允许 mixed subjects，则要有明确规则。

至少不要让客户端任意写一个存在的 subject_id 就污染统计。

------

# 17. request_id 是否真的“一次刷题共享”

检查：

```text
practice.js
```

确认：

```text
answers[].request_id
session.request_id
```

是否确实使用同一个本次练习 request ID。

并检查：

- 第一次 submit 失败
- retry
- 回到页面
- 二次点击
- success 后按钮重复触发

是否仍使用相同 request ID。

不能每次 retry：

```js
_generateRequestId()
```

否则 DB 唯一索引无法提供幂等。

------

# 18. 双击提交 / 并发提交

检查前端是否有：

```text
submitting
loading
disabled
```

保护。

同时后端必须能够承受两个完全并发的：

```text
POST /practice/batch-submit
same request_id
```

重点验证：

- 两份 PracticeRecord 会不会重复
- PracticeSession 是否一条
- transaction IntegrityError 后是否影响答案提交

如果 answers 本身已有 request_id 幂等，也确认它的唯一约束。

增加并发等价逻辑测试（不一定真正启动线程，只要覆盖重复调用结果）。

------

# 19. API 向后兼容

重新检查：

```text
BatchSubmitRequest.session = Optional
```

旧 payload：

```json
{
  "answers": [...]
}
```

必须完全正常。

同时 `/pomodoro/history` response schema 已改变。

检查是否还有其他前端/管理端/脚本调用：

```text
/pomodoro/history
```

全仓搜索：

```bash
rg "pomodoro/history"
rg "get_history"
rg "PomodoroSessionResponse"
```

确认没有其它调用方依赖旧字段。

如果旧字段仍然存在于新 `LearningHistoryItem` 中通常最好。

不要为了当前页面破坏其他客户端。

------

# 20. record_key

确认：

```text
pomodoro:{id}
practice:{id}
```

始终存在。

不能返回：

```text
null
```

检查：

```xml
wx:key="record_key"
```

以及 formatter 是否保留它。

不要在：

```js
.map(_formatSession)
```

过程中不小心把 `record_key` 丢掉。

------

# 21. 前端 duration 展示

检查：

```text
actual_duration
duration_sec
```

新 history API 对 Practice 和 Pomodoro 是否统一成同一字段。

前端 formatter 不能出现：

```text
Practice 实际18分钟 → 显示0分钟
```

也不能有：

```text
NaN分钟
```

测试：

```text
0 sec
59 sec
60 sec
119 sec
3600 sec
```

跟当前 Pomodoro 页面既有格式保持一致。

------

# 22. 时区彻底检查

项目统计时区：

```text
Asia/Shanghai
```

客户端：

```js
new Date(timestamp).toISOString()
```

是 UTC ISO。

后端必须正确解析。

测试至少包括：

```text
2026-08-08T23:50:00+08:00
2026-08-09T00:20:00+08:00
```

以及：

```text
day_start = 06:00
```

确认统计日正确。

另外检查 naive datetime。

上一轮选择：

> naive 按 UTC + warning

确认这个决定是否与项目其它 API 一致。

如果项目其它代码明确将 naive 看作 China local，则这里单独按 UTC 会产生行为不一致。

应该遵守项目统一时间处理工具，而不是自定义约定。

------

# 23. statistics snapshot query 数量

现在增加 PracticeSession 后：

```text
stats
trends
daily-summary
statistics-overview
```

是否出现 N+1 查询？

尤其：

```text
subjects
practice sessions
pomodoro sessions
pause intervals
```

确认 query count 仍然稳定。

不要针对每个 PracticeSession 单独：

```sql
SELECT subject ...
```

也不要针对每一天循环查数据库。

统计 snapshot 应继续一次性加载所需数据，然后内存 attribution。

------

# 24. 统计 invariant

给统计逻辑增加/确认以下 invariant 测试：

```text
duration_sec >= 0
subject.duration_sec >= 0
sum(subject.duration_sec) == daily_summary.duration_sec
```

如果产品语义确实要求科目总和等于总学习时长。

以及：

```text
week_duration_sec
==
对应统计周每天贡献之和
```

最近 7 天：

```text
trend duration
```

应与同日期 daily summary 一致。

------

# 25. 今日 / 本周边界

测试：

```text
study day start = 06:00
```

现在时间假设：

```text
Monday 05:59
Monday 06:01
```

确认 week boundary 与 study-day boundary 一致。

PracticeSession 纳入以后不能出现：

```text
today 正确
week 错误
```

------

# 26. 零时长 PracticeSession

用户可能：

- 打开
- 立即提交

得到：

```text
duration_sec = 0
```

明确行为：

- 是否保存 PracticeSession
- history 是否显示
- 显示 0 分钟是否合理
- total duration 不增加

遵守现有产品规则即可，但测试行为必须确定。

------

# 27. test-china-time.js

上一轮说明：

> test-china-time.js 因 stale mock 已经在 HEAD 上失败，与本改动无关。

这一次目标是：

> merge-ready / CI-ready

所以请检查这个 stale test。

如果确实只是因为产品代码早已从：

```text
/pomodoro/daily-summary
```

切到：

```text
/pomodoro/statistics-overview
```

而测试 mock 没更新：

**可以修测试。**

要求：

- 只修改 stale mock / assertion
- 不改变生产代码行为
- 确认测试意图仍然是验证中国统计日
- 修完跑通过

这不是扩大产品需求，而是让测试套件反映当前真实 API。

------

# 28. Redis integration tests

之前：

```text
test_export_redis_integration.py
```

有 3 个因本地 Redis 不可用失败。

不要为了让测试全绿而：

- 删除测试
- catch 所有异常
- 修改业务代码绕过 Redis

只确认：

```text
这些失败与本次改动无关
```

如果项目本身已经有：

```text
integration marker / env skip
```

则按照现有测试规范运行。

否则保持现状并报告。

------

# 29. 运行完整验证

修复真实问题后执行：

## 后端

至少：

```bash
pytest backend/tests/test_services/test_practice_session_stats.py -q
pytest backend/tests/test_services/test_pomodoro_study_day_stats.py -q
```

以及相关 practice API tests。

然后：

```bash
ruff check backend
```

如果环境允许：

```bash
pytest backend -q
```

------

## 小程序

运行：

```bash
node miniprogram/scripts/test-pomodoro-practice-stats.js
node miniprogram/scripts/test-pomodoro-duration.js
node miniprogram/scripts/test-pomodoro-free-timer-limit.js
node miniprogram/scripts/test-china-time.js
```

如果实际 package script 不同，根据仓库调整。

------

# 30. 再做一次 git diff review

测试完成后再次：

```bash
git diff --check
git diff
```

检查：

- debug console
- 临时日志
- TODO
- dead code
- unused imports
- 魔法数字
- 测试专用逻辑泄露到生产
- accidentally modified files
- formatting

------

# 31. 不要做这些事情

不要：

- 再新增新功能
- 重写整个统计模块
- 为了理论完美做巨大架构改造
- 为了让测试通过删除断言
- 忽略 PostgreSQL，只因为 SQLite 测试过
- 把前一次 review 的结论当成事实
- 用“应该没问题”代替代码证据
- 因为问题复杂就停下来问我

发现问题直接修，并补对应 regression test。

------

# 32. 最终输出格式

最后给我一个严格的最终报告：

## A. 最终结论

只允许：

```text
READY FOR MERGE
```

或者：

```text
NOT READY FOR MERGE
```

------

## B. 本轮发现的问题

按严重度：

```text
P0
P1
P2
P3
```

逐项说明：

```text
文件
原因
实际影响
修复方式
对应测试
```

如果没有问题：

明确写：

```text
No new correctness issues found.
```

------

## C. 两个重点 finding 的最终结论

单独回答：

```text
Finding 6:
是否仍决定不改？
证据是什么？

Finding 8:
总学习时长与科目时长 invariant 是否成立？
重叠且不同科目时最终规则是什么？
```

------

## D. 核心 invariants

给出实际测试确认结果：

```text
1. 非重叠：Pomodoro + Practice 正确求和
2. 部分重叠：不 double count
3. 完全覆盖：不 double count
4. pause 内 Practice 正确计入
5. 多 Pomodoro overlap 先 union
6. 跨统计日 + overlap 正确
7. history 总数正确
8. history 分页稳定
9. request_id 幂等
10. 超长 request_id 无碰撞
11. 旧客户端兼容
12. subject duration 与 total duration invariant
13. UTC / Asia-Shanghai / day_start 正确
```

------

## E. Migration

输出：

```text
Alembic current head:
...

new revision:
...

upgrade:
PASS/FAIL

downgrade:
PASS/FAIL

multiple heads:
YES/NO
```

------

## F. 测试结果

精确输出：

```text
backend focused:
X passed

backend full:
X passed / X failed / X skipped

ruff:
PASS

miniprogram:
...

test-china-time:
PASS/FAIL

Redis integration:
...
```

------

## G. 最终修改文件

只列本轮实际改动的文件。

------

## H. 上线操作

如果 READY：

给出最小上线步骤，例如：

```bash
alembic upgrade head
```

以及是否需要：

```text
restart backend
rebuild/release miniprogram
```

不要编造项目里不存在的部署命令。

目标：

> 这一轮结束后，我应该能够放心提交 git、执行数据库 migration、部署后端并发布小程序，而不是再进行一轮泛泛的 review。
