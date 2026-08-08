你现在直接在当前项目仓库中完成下面的功能改造。

不要只给设计方案，不要停留在分析/计划阶段，不要让我确认下一步。请先检查实际仓库、git 状态、现有 Alembic migration 体系和测试体系，然后直接修改代码、创建数据库 migration、补齐测试并执行测试。

不要覆盖或回滚仓库中与本任务无关的未提交修改。不要做无关重构。

# 任务目标

彻底解决番茄钟跨午夜、跨“统计日”时的时长归属问题，并直接采用长期可扩展方案。

产品仅面向中国大陆用户，因此：

- 产品时区固定为 `Asia/Shanghai / UTC+8`
- 不需要给用户选择 timezone
- 数据库存储仍保持当前项目约定：所有 DateTime 都是 **naive UTC**
- 不依赖服务器系统时区
- 不依赖用户手机当前 timezone
- 所有“今天 / 本周 / 某日”的番茄钟统计都按照中国时间计算

最终产品支持：

> 用户可以设置“我的一天从几点开始”。

默认：

```
00:00
```

例如用户设置：

```
06:00
```

则“2026-08-07 学习日”的统计区间定义为：

`2026-08-07 06:00:00 ~ 2026-08-08 06:00:00`（中国时间，左闭右开）

在凌晨 02:00 时，当前学习日仍然应该是前一天。

------

# 一、核心产品规则

以下规则必须统一，不允许不同 API 各自定义日期逻辑。

## 1. Session 是事实数据，不写死归属日期

`pomodoro_sessions` 继续保存真实事实：

- start_time
- end_time
- actual_duration
- total_paused_sec
- status
- subject
- preset
- etc.

不要增加并依赖：

- study_date
- belong_date
- statistics_date
- start_date

这类写死日期的字段。

原因：

用户以后改变“我的一天从几点开始”后，历史统计应该可以立即按照新规则重新计算。

所以：

**事实数据与统计视图必须分离。**

禁止为了方便统计，把一个 session 永久归属到某一天。

------

## 2. 专注时长跨统计日时必须拆分

例如用户设置：

```
day_start = 00:00
```

session：

```
2026-08-07 23:50 ~ 2026-08-08 00:20
```

实际专注 30 分钟。

统计：

- 2026-08-07：10 分钟
- 2026-08-08：20 分钟

不能全部算到 start_time 那一天，也不能全部算到 end_time 那一天。

------

如果用户设置：

```
day_start = 06:00
```

同一个 session：

```
2026-08-07 23:50 ~ 2026-08-08 00:20
```

全部属于：

```
2026-08-07 学习日
```

因为该学习日实际范围为：

```
2026-08-07 06:00 ~ 2026-08-08 06:00
```

统计：

- 2026-08-07：30 分钟
- 2026-08-08：0 分钟

------

再例如：

day_start = 06:00

session：

```
2026-08-08 05:00 ~ 07:00
```

应该拆成：

- 2026-08-07 学习日：1 小时
- 2026-08-08 学习日：1 小时

------

## 3. “专注次数”和“专注时长”采用不同语义

Session 是原子事件，因此不能因为跨统计日而制造两个番茄钟。

规则：

### 专注时长

按照实际专注时间拆分到各统计日。

### 专注次数

完整 session 只计算一次，归属于该 session **开始时所在的学习日**。

例如：

day_start = 00:00

23:50 ~ 00:20：

- 8 月 7 日：
  - 专注次数 +1
  - 专注时长 +10 分钟
- 8 月 8 日：
  - 专注次数 +0
  - 专注时长 +20 分钟

这样可以保证长期统计中：

```
sum(daily session count) == 实际完成 session 数
```

不会因为跨日造成 session 数重复。

------

## 4. History 也按“开始学习日”归属

```
GET /pomodoro/history?date=YYYY-MM-DD
```

日期过滤应按照：

**session.start_time 所属的学习日**

而不是 end_time。

原因：

session 是完整事件，只应该在历史记录中出现一次。

目前代码存在：

- history 使用 `end_time` 过滤日期
- UI 却显示 `start_time`

这会导致跨日 session 在 8 月 8 日列表出现，但显示时间却是 8 月 7 日，非常容易造成困惑。

修改后：

history 的日期归属 = session 开始时的 study day。

列表继续展示完整 session 的实际 duration，不做拆分。

------

# 二、当前代码中已经确认存在的问题

请以实际仓库代码为准再次确认，但目前代码至少存在以下问题。

后端：

```
app/services/pomodoro_service.py
```

当前：

### get_stats()

使用：

```
utcnow().replace(hour=0, ...)
```

然后：

```
PomodoroSession.end_time >= today_start
```

这里同时存在两个问题：

1. 00:00 是 UTC 00:00，不是中国 00:00
2. 使用 end_time 归属整个 actual_duration

必须替换。

------

### get_trends()

当前使用类似：

```
func.date(PomodoroSession.end_time)
```

并使用：

```
date.today()
```

这在 SQLite / PostgreSQL / UTC / 中国时间之间语义不稳定。

必须彻底移除这种日期聚合方式。

不要使用：

- func.date(timestamp)
- DATE(timestamp)
- server local date
- PostgreSQL timezone-specific SQL

实现核心统计逻辑。

采用统一的 UTC range + Python/application-side attribution，保证 SQLite 和 PostgreSQL 行为完全一致。

------

### get_subject_breakdown()

目前已经使用 China UTC range，这是正确方向，但仍然：

```
end_time >= start`
`end_time < end
```

然后把整个 `actual_duration` SUM 进去。

跨统计日仍然错误。

------

### get_history()

当前也是按照 end_time 过滤。

改成 start_time 所属学习日。

------

前端：

```
subpackages/productivity/pomodoro-stats/index.js
```

当前统计页为了计算某一天：

- 请求 `/pomodoro/history`
- 最多分页把当天所有 history 全部拉回前端
- 然后 `_buildSubjectBreakdownFromSessions()`
- 再在前端 SUM actual_duration

这会同时造成：

1. 跨日统计错误
2. 请求量随着历史记录增长
3. 前端承担本应属于后端的统计规则
4. 后端 `/subjects` 与前端统计可能产生两套口径

需要一起改掉。

**后端必须成为统计口径的唯一权威。**

------

# 三、统一中国时间 / Study Day 工具

将番茄钟日期逻辑集中到统一 helper。

优先放在：

```
app/core/time_utils.py
```

或一个语义明确的新模块，例如：

```
app/services/pomodoro_time_service.py
```

不要继续在 `pomodoro_service.py` 内复制 `_SHANGHAI_TZ`。

当前项目 DateTime 使用 naive UTC，请保持这个约定。

提供清晰、可单测的函数，至少包括：

1. 

```
study_day_utc_range(target_date, day_start_minute)
```

输入：

- date，例如 2026-08-07
- day_start_minute，例如 360

输出 naive UTC：

```
(start_utc, end_utc)
```

区间必须是左闭右开：

```
[start_utc, end_utc)
```

------

1. 

```
study_day_for_utc(datetime_utc, day_start_minute)
```

输入一个 naive UTC 时间。

返回其所属的中国学习日 date。

逻辑等价于：

- UTC -> 中国时间
- 减去 day_start_minute
- 取 date

------

1. 

```
current_study_day(day_start_minute)
```

必须根据当前中国时间计算。

例如：

当前中国时间：

```
2026-08-08 02:00
```

day_start = 06:00

返回：

```
2026-08-07
```

不要使用系统 `date.today()`。

------

1. 

需要的话增加：

```
study_week_utc_range(...)
```

本周仍定义为：

**中国语义下的周一到周日**

但每天的边界采用用户 day_start。

例如 day_start=06:00，则本周一实际上从：

周一 06:00

开始。

------

# 四、增加用户 Pomodoro 设置

不要把 timezone 做成用户可选项。

timezone 永远是中国时间。

建议新增独立表：

```
user_pomodoro_settings
```

而不是继续往 `users` 表堆番茄钟专属字段。

建议结构：

- user_id
  - PK 或 UNIQUE
  - FK -> users.id
  - ON DELETE CASCADE
- day_start_minute
  - INTEGER
  - NOT NULL
  - DEFAULT 0
  - 允许范围 0 ~ 1439
- created_at
- updated_at

`day_start_minute` 使用“当天 00:00 后多少分钟”的形式，而不是字符串。

示例：

- 00:00 = 0
- 03:00 = 180
- 06:00 = 360
- 06:30 = 390

这样以后支持分钟级设置不需要再迁移 schema。

如果用户没有 settings row：

默认：

```
day_start_minute = 0
```

不要要求给所有历史用户批量创建 row。

缺省读取即可。

------

增加 ORM model，并正确注册到当前项目 Base metadata。

增加 API：

### GET

```
GET /api/v1/pomodoro/settings
```

返回至少：

```text
{
  day_start_minute: 0,
  day_start_time: "00:00",
  timezone: "Asia/Shanghai"
}
```

### PUT

```
PUT /api/v1/pomodoro/settings
```

请求：

```text
{
  day_start_minute: 360
}
```

校验：

```
0 <= day_start_minute <= 1439
```

保存成功后返回完整 settings。

不要允许客户端传 timezone。

------

# 五、记录 Pause Interval，解决真正的跨日暂停问题

这是本次长期方案必须处理的地方。

当前 `pomodoro_sessions` 只有：

- paused_at
- total_paused_sec

这不足以精确拆分一个跨统计日 session。

例如：

23:50 开始

23:55 暂停

00:05 恢复

00:20 结束

total_paused_sec = 600

如果只知道总暂停 600 秒，并不知道 600 秒分别落在哪个统计日，就无法准确计算：

- 昨天到底专注多少
- 今天到底专注多少

因此增加：

```
pomodoro_pause_intervals
```

建议字段：

- id
- session_id
  - FK -> pomodoro_sessions.id
  - ON DELETE CASCADE
- started_at
  - naive UTC
- ended_at
  - nullable
- created_at

增加适当索引：

```
(session_id, started_at)
```

在 PomodoroSession 建 relationship。

------

## pause_session()

第一次真正进入 paused：

除了继续维护现有：

- paused_at
- total_paused_sec
- status

还要创建一个：

```
PomodoroPauseInterval(started_at=now, ended_at=NULL)
```

必须保证重复 pause 请求幂等，不要创建多个 open interval。

------

## resume_session()

如果当前处于 paused：

关闭对应 open interval：

```
ended_at = now
```

继续保留现有：

- total_paused_sec
- expected_end_time
- paused_at

兼容逻辑。

------

## complete_session() / interrupt_session()

如果结束时仍处于 paused：

除了现有暂停累计逻辑以外：

必须关闭 open pause interval。

------

## 老的 active session 兼容

部署新版本时，可能数据库中存在：

- status=paused
- paused_at != NULL
- 但是没有 pause_interval

resume / complete / interrupt 时必须兼容。

发现：

```
paused_at != NULL
```

但不存在 open pause interval 时：

根据旧的 `paused_at` 补建该 interval，然后关闭。

不要因为 migration 造成正在进行中的 session 丢失暂停信息。

------

# 六、历史 session 的兼容

不要修改或者重写已有 `pomodoro_sessions` 的：

- start_time
- end_time
- actual_duration
- total_paused_sec

旧 session 没有 pause interval 是正常情况。

统计逻辑必须兼容。

### 新 session

有 pause intervals：

按照真实 active intervals 拆分。

### 历史 session

如果不存在 pause interval：

因为无法知道暂停具体发生的位置：

若 session 没有跨 study-day boundary：

直接把整个 `actual_duration` 放入该 study day。

若跨 boundary：

按照 session 的 wall-clock overlap 比例分配 `actual_duration`。

例如：

wall time：

20 分钟 / 40 分钟

actual_duration：

30 分钟

则按 1:2 分配：

10 分钟 / 20 分钟。

这是历史数据唯一合理的 deterministic fallback。

不要伪造 pause interval。

------

# 七、统一的 Duration Attribution Engine

不要把拆分算法分别写在：

- stats
- trends
- subjects
- daily

里面。

实现一个统一的内部 attribution helper/service。

建议抽象类似：

```
split_session_duration_by_study_day(...)
```

或者批量版本。

目标：

给定：

- PomodoroSession
- pause intervals
- day_start_minute

返回：

```text
{
  2026-08-07: seconds,
  2026-08-08: seconds
}
```

------

## 对新 session 的算法

从：

```
[start_time, end_time)
```

中减去所有 pause intervals。

得到真正的 active intervals。

然后把 active intervals 与每个 study-day window 求 overlap。

------

## 必须保证 conservation

对于一个 completed session：

所有 study-day contribution 的总和必须严格等于：

```
session.actual_duration
```

不能因为：

- int()
- floor()
- round()
- timezone
- 边界

导致每天加总以后少几秒或多几秒。

由于当前 complete API 仍允许客户端提供 `actual_duration_sec`，它可能和根据 pause interval 算出的 wall active time 有少量差异。

因此：

1. 先计算每个 study day 的 raw active overlap
2. 使用 raw overlap 作为权重
3. 最终按照 `actual_duration` 做整数秒归一化分配
4. 使用 deterministic remainder / largest-remainder 方式处理余数
5. 保证：

```
sum(contribution_sec) == actual_duration
```

如果 raw overlap 异常为 0，但 actual_duration > 0：

采用 deterministic fallback，例如归属 session start study day，并记录必要日志；不要丢时长。

------

# 八、数据库查询方式

统计目标范围时，不要通过 end_time 所属日期筛 session。

例如计算某个 period：

```
[period_start, period_end)
```

应该找到所有与该 period 有 overlap 的 completed session：

```text
session.start_time < period_end
AND
session.end_time > period_start
AND
status = completed
```

然后使用 attribution engine 计算真正属于该 period 的 duration。

这非常重要。

一个前一天开始、今天结束的 session 必须能被今天的 duration query 找到。

------

建议新增复合索引：

```
pomodoro_sessions(user_id, status, start_time)
```

以及：

```
pomodoro_sessions(user_id, status, end_time)
```

不要依赖数据库特定的 DATE() / date_trunc()。

SQLite 和 PostgreSQL 使用相同应用层语义。

趋势统计一次读取总 range 内相关 sessions，然后在内存中拆到各 day。

禁止 N 天做 N 次数据库查询。

------

# 九、改造现有 Pomodoro API

保持现有 endpoint 兼容，不要删除旧字段。

## GET /pomodoro/stats

保留：

- today_sessions
- today_duration_sec
- week_sessions
- week_duration_sec

新增：

- today_date
- week_start_date
- day_start_minute
- day_start_time

规则：

### today_duration_sec

所有 completed sessions 在“当前 study day”中的 duration contribution。

### today_sessions

start_time 属于当前 study day 的 completed session 数量。

### week_duration_sec

所有 completed session 与当前 study week overlap 的 duration contribution。

### week_sessions

start_time 属于当前 study week 的 completed session 数。

------

## GET /pomodoro/trends?days=7

保持 response 结构兼容。

但：

```
date
```

代表 study-day label。

```
duration_sec
```

代表该 study day 的真实 contribution。

```
sessions
```

代表 start_time 属于该 study day 的 completed sessions 数。

不要再使用：

```
func.date(end_time)
```

或者：

`date.today()`。

------

## GET /pomodoro/subjects?date=YYYY-MM-DD

duration：

按照该 study day 的 contribution 计算。

sessions：

按照 start_time 属于该 study day 计算。

如果一个前一天开始的 session 在本日还有 duration contribution：

可能出现：

- duration_sec > 0
- sessions = 0

这是允许且语义正确的。

前端对应文案需要避免把这个字段错误叫做“本日完成次数”。

------

## GET /pomodoro/history

date 参数改为：

**session start_time 所属的 study day**

过滤条件使用统一 study-day UTC range。

history session 仍然只出现一次。

默认排序优先：

```
start_time DESC
```

而不是依赖 created_at。

保留 interrupted session 的现有 history 行为。

------

# 十、新增 Daily Summary API

为了彻底去掉前端“拉全部 history 再统计”的逻辑，增加一个后端权威接口。

建议：

```
GET /api/v1/pomodoro/daily-summary?date=YYYY-MM-DD
```

date 可选。

未提供时：

使用 current_study_day。

返回例如：

```text
{
  date: "2026-08-07",
  timezone: "Asia/Shanghai",
  day_start_minute: 360,
  day_start_time: "06:00",

  sessions: 4,
  duration_sec: 7200,

  subjects: [
    {
      subject_id: 1,
      subject_code: "...",
      subject_name: "...",
      sessions: 2,
      duration_sec: 3600
    }
  ]
}
```

这里：

- sessions = 当天开始的 completed session 数
- duration_sec = 当天 contribution
- subject.duration_sec = subject contribution
- subject.sessions = 当天开始且属于该 subject 的 completed sessions

保证：

```
sum(subject.duration_sec) == daily duration_sec
```

未分类 subject 也必须进入 breakdown，不能丢 duration。

------

# 十一、小程序统计页改造

重点文件目前是：

```
subpackages/productivity/pomodoro-stats/index.js
```

以及：

- index.wxml
- index.wxss

当前 `_fetchAllDateHistory()` 为了统计一天，会把当天全部 history 分页拉回客户端。

删除这种统计依赖。

不要再为了：

- selectedDurationSec
- pie subject breakdown
- selectedSessionCount

请求全部 history。

------

新的加载逻辑应类似：

1. 获取 Pomodoro settings
2. 根据 settings 计算当前中国 study date
3. 请求：
   - `/pomodoro/stats`
   - `/pomodoro/trends?days=7`
   - `/pomodoro/daily-summary?date=...`
   - `/pomodoro/history?page=1&page_size=20&date=...`
4. overview 使用 daily-summary
5. pie 使用 daily-summary.subjects
6. history 只用于“最近记录”

切换日期时只请求：

- daily-summary
- history 第一页

不再拉当天所有历史记录。

------

# 十二、小程序“今天”的计算必须修正

当前 stats 页面在 onLoad 中直接：

```
new Date()
```

然后：

```
getFullYear/getMonth/getDate
```

生成 `_todayDate`。

在支持自定义 day_start 后这是错误的。

例如：

中国时间：

8 月 8 日 02:00

day_start：

06:00

真正的 current study day：

8 月 7 日。

实现一个小程序端统一 helper。

建议：

```
utils/china-time.js
```

至少提供：

- minuteToTimeText()
- timeTextToMinute()
- getChinaStudyDate(dayStartMinute)

不要依赖手机当前 timezone。

可以基于 Unix timestamp：

- 转成 UTC+8
- 减 dayStartMinute
- 再取年月日

确保即使用户人在其他时区或系统 timezone 异常，产品仍按照中国时间统计。

后端仍然是最终权威。

------

# 十三、统计日设置 UI

在 Pomodoro 学习统计页加入一个低干扰的“统计日”设置入口。

不要破坏现有页面主要视觉结构。

建议放在 overview 下方或统计页较自然的位置。

显示：

```
统计日从 00:00 开始
```

或者：

```
统计周期 06:00 - 次日 06:00
```

点击后使用微信小程序适合的 time picker。

支持分钟级时间。

默认：

```
00:00
```

保存调用：

```
PUT /pomodoro/settings
```

保存成功后：

1. 更新本地 setting
2. 重新计算 current study date
3. 必要时修正 selectedDate
4. 重新加载：
   - stats
   - trends
   - daily summary
   - history
5. 重新绘制图表

不要要求用户重启页面。

------

在统计页适当位置加入一句简短说明：

```
专注时长按统计日边界拆分，专注次数按开始时间归属
```

如果 day_start != 00:00，可以显示：

```
当前统计日：06:00 - 次日 06:00
```

不要使用“昨天晚上算今天”这种容易混淆的文案。

------

# 十四、Date Picker 行为

```
_todayDate
```

必须代表：

**current study day**

而不是 calendar day。

Date Picker 的最大可选日期使用 current study day。

例如：

当前中国时间：

8 月 8 日 02:00

day_start = 06:00

最大日期：

```
2026-08-07
```

因为 8 月 8 日这个 study day 尚未开始。

------

如果用户修改 day_start 导致：

原 selectedDate > 新 currentStudyDate

则自动把 selectedDate 调整为新的 currentStudyDate。

如果用户修改设置前正在查看“今天”，则修改后继续定位新的“今天”。

如果用户明确正在查看历史日期，则尽量保持该日期，只要它仍是合法日期。

------

# 十五、History UI

history 仍展示：

- session start time
- 完整 session duration
- subject
- completed / interrupted

不要把一个跨日 session 拆成两条 history。

但是时间格式必须明确按照中国时间显示。

不要继续依赖手机 local timezone 的：

```
new Date(...).getHours()
```

来决定中国显示时间。

统一使用 China time helper。

------

# 十六、暂停逻辑兼容要求

现有：

- pause
- resume
- complete
- interrupt
- free timer
- countdown timer
- 本地暂停恢复
- total_paused_sec
- expected_end_time
- active session recovery

行为不能被破坏。

新增 pause interval 只能作为精确统计的数据能力。

不要删除：

- paused_at
- total_paused_sec

它们仍用于当前实时计时和兼容。

pause interval 与现有字段必须保持一致。

重复：

pause -> pause

resume -> 网络重试 resume

complete 重试

都不能制造重复 pause interval 或负 duration。

------

# 十七、数据库 Migration

项目代码已经明确：

生产 CLOUD_API 不允许 runtime schema repair，生产 schema 应由 Alembic 管理。

当前上传代码中虽然没有看到 Alembic 目录，但代码中已有：

```
alembic upgrade head
```

以及已有 migration revision 的引用。

因此：

1. 在实际仓库根目录定位真正的 Alembic 配置和 versions 目录
2. 基于当前 head 创建新的 migration
3. 不要猜 revision down_revision
4. migration 必须兼容：
   - SQLite 本地开发
   - PostgreSQL 生产
5. 不得通过给 production `init_db()` 增加 runtime ALTER TABLE 来绕开 Alembic

migration 至少包含：

- user_pomodoro_settings
- pomodoro_pause_intervals
- 必要 foreign keys
- indexes
- pomodoro_sessions 新复合 indexes

migration 必须可 downgrade。

不要做 destructive migration。

不要改写已有 session 数据。

------

本地开发模式如果依赖 `Base.metadata.create_all()`：

确保新 model 被正确注册，使一个全新的 SQLite 数据库也能直接创建这些新表。

但：

**已有生产数据库的 schema 升级仍必须由 Alembic migration 完成。**

------

# 十八、测试要求

必须补自动化测试。

不要只手工验证。

至少覆盖以下案例。

## Time helper

### case 1

day_start = 00:00

2026-08-07 study day：

中国：

08-07 00:00 ~ 08-08 00:00

UTC 应正确转换成：

08-06 16:00 ~ 08-07 16:00

------

### case 2

day_start = 06:00

2026-08-07 study day：

中国：

08-07 06:00 ~ 08-08 06:00

UTC：

08-06 22:00 ~ 08-07 22:00

------

### case 3

当前中国时间：

08-08 02:00

day_start = 06:00

current study day：

08-07

------

## Duration attribution

### case 4：自然日跨日

day_start = 00:00

23:50 ~ 00:20

actual_duration = 1800

结果：

08-07 = 600
08-08 = 1200

------

### case 5：06:00 边界

同一 session：

23:50 ~ 00:20

day_start = 06:00

结果：

08-07 = 1800

------

### case 6：跨日暂停

day_start = 00:00

session：

23:50 ~ 00:20

pause：

23:55 ~ 00:05

真实 active：

- 前一天 5 分钟
- 后一天 15 分钟

结果：

08-07 = 300
08-08 = 900

总计：

1200

------

### case 7：旧数据 fallback

同样是跨日 session，但：

没有 pause_interval

只有：

actual_duration
total_paused_sec

验证 fallback：

- deterministic
- 各天非负
- sum == actual_duration

------

### case 8：session count

23:50 开始、00:20 完成：

即使 duration 被拆成两天：

session count 只能属于 start study day。

两天 sessions 相加仍为 1。

------

### case 9：history

验证 date filter 使用 start study day，而不是 end_time。

------

### case 10：settings

- 无 row -> default 0
- PUT 360
- GET -> 360
- 非法 <0 / >1439 被拒绝

------

### case 11：study week

验证：

- 周一起点
- 自定义 day_start
- 周边界跨午夜

------

### case 12：pause interval 幂等

- pause
- 重复 pause
- resume
- 重复/重试行为

不能创建重复开放 pause。

------

### case 13：旧 paused active session

DB 中：

- paused_at 有值
- pause_interval 不存在

resume / complete 后：

自动兼容，并产生正确 interval / duration。

------

# 十九、小程序回归测试

保留并运行已有：

```
scripts/test-pomodoro-duration.js
```

并补新的 JS regression tests，至少覆盖：

- China study date
- day_start = 06:00 时凌晨属于前一 study day
- minute <-> HH:mm
- daily-summary 驱动 overview
- selectedDate 在 setting 改变后的调整
- history 时间按 UTC+8 格式化

不要破坏现有：

- 主题切换
- 图表动画
- 日期切换
- duration 格式
- free timer
- active session restore

------

# 二十、性能要求

不要对 trends 的每一天分别 query。

对于 N 天 trends：

1. 算出总 UTC range
2. 一次读取所有 overlapping sessions
3. 一次加载相关 pause intervals
4. application-side 拆分
5. 聚合到 N 个 study day

避免 N+1。

pause interval 使用 eager/selectin loading 或批量查询。

daily summary 也不要查询全用户历史，只查询与目标 study day overlap 的 session。

history 查询按照 start_time range，可直接使用 index。

------

# 二十一、禁止事项

不要：

1. 把整个 session duration 全部算给 start_time
2. 把整个 duration 全部算给 end_time
3. 固定每天 06:00 开始
4. 新增 study_date 并永久写死
5. 使用服务器本地 timezone
6. 使用客户端设备 timezone 作为产品统计 timezone
7. 使用 `func.date(end_time)` 实现日期统计
8. 为每个 trend day 单独做 SQL query
9. 继续让前端拉全部 history 再 SUM
10. 为生产数据库增加 runtime ALTER TABLE
11. 修改无关功能
12. 删除 paused_at / total_paused_sec
13. 把跨日 session 拆成多个 PomodoroSession
14. 因为 migration 而重写历史数据

------

# 二十二、兼容原则

现有接口尽可能 backward compatible。

现有 Pomodoro start/complete/pause/resume/interrupt 请求格式不要无必要修改。

允许 response 增加字段。

现有 session 数据必须继续可读。

新统计逻辑必须同时支持：

- legacy session
- new session
- SQLite
- PostgreSQL

用户修改 day_start 后：

历史统计应立即按新规则变化。

这正是预期行为，因为 day_start 是“统计视角”，不是 session 事实。

------

# 二十三、建议代码组织

不要机械照抄，但优先形成类似结构：

Backend：

```text
app/models/pomodoro.py
    PomodoroSession
    PomodoroPauseInterval
    UserPomodoroSettings

app/core/time_utils.py
    China / study-day helpers

app/services/pomodoro_service.py
    lifecycle
    stats orchestration

app/services/pomodoro_attribution.py
    active interval + duration splitting
```

如果项目现有结构更适合其他位置，以已有规范为准。

Schemas：

```text
PomodoroSettingsUpdate
PomodoroSettingsResponse
PomodoroDailySummaryResponse
```

Mini Program：

```text
utils/china-time.js

subpackages/productivity/pomodoro-stats/
    index.js
    index.wxml
    index.wxss
```

------

# 二十四、完成标准

代码完成后必须实际执行：

1. 后端相关测试
2. Pomodoro 新测试
3. 小程序已有 Pomodoro regression tests
4. 新增的小程序统计日测试
5. 如果仓库存在 lint/typecheck，执行相关检查
6. 检查 migration upgrade/downgrade 或至少验证 migration SQL/SQLite upgrade
7. 检查 git diff，确保没有无关修改

如果本地环境具备 PostgreSQL 测试配置，同时验证 PostgreSQL migration。

如果没有 PostgreSQL runtime，不要阻塞任务，但必须确保 migration 使用 SQLAlchemy/Alembic 跨 dialect 写法，并明确说明未实际连接 PostgreSQL 的部分。

------

# 二十五、最终回复格式

完成代码以后，不要再给我一篇设计方案。

只报告：

## 已完成

简要说明最终行为。

## 修改文件

列出核心文件。

## 数据库迁移

说明：

- migration revision
- 新表
- 新索引
- 是否需要执行 `alembic upgrade head`

## 统计规则

用这两个例子确认结果：

### 默认 00:00

23:50 ~ 00:20

=> 10min / 20min

### day_start=06:00

23:50 ~ 00:20

=> 全部属于前一个 study day

并说明：

session count 按开始 study day。

## 测试

列出实际执行的命令和结果。

## 兼容性

说明：

- legacy session 如何处理
- SQLite
- PostgreSQL
- existing paused session

如果仍有未解决的问题，明确列出，但不要把可以直接解决的问题留给我做。

现在开始检查仓库并直接实施。
