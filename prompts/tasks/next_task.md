继续在当前已完成 Study Day / Pause Interval / Attribution Engine 改造的生产项目上工作。

本项目已经上线生产。

这一次我们的明确决策是：

> 不长期维护 legacy Pomodoro compatibility。
> 对生产数据库做好完整备份后，一次性迁移/规范化历史 Pomodoro 数据，然后删除 legacy 统计分支，让所有历史和未来 session 都遵循同一套 V2 数据模型。

不要只给设计建议。

直接检查当前仓库、Alembic、Pomodoro models/services/tests/deploy scripts，然后实施代码、migration、backfill 工具和测试。

禁止自动连接真实生产数据库执行 destructive operation。

需要为生产准备明确、可审核、可手工执行的迁移命令。

------

# 一、最终目标

迁移完成后：

所有 Pomodoro session，包括历史 session，都必须使用统一模型：

```text
PomodoroSession
    start_time
    end_time
    actual_duration

PomodoroPauseInterval[]
    started_at
    ended_at
```

统计只允许：

```text
Session
+ PauseIntervals
→ active timeline
→ attribution engine
→ daily / weekly / trends / subjects
```

迁移完成后删除：

- legacy attribution fallback
- “没有 pause interval 时按 wall-clock 比例拆分”的运行时逻辑
- old paused-session compatibility repair
- 为旧数据存在而保留的特殊统计 branch

最终 production runtime 不再区分：

```text
legacy session
new session
```

只存在：

```text
canonical session
```

------

# 二、重要事实：历史暂停位置无法真实恢复

旧 session 只有：

- start_time
- end_time
- actual_duration
- total_paused_sec

并没有 pause interval。

因此不能声称能够真实恢复历史 pause timestamp。

本次迁移允许：

> 对旧 Pomodoro 数据进行 deterministic normalization。

即：

历史 pause intervals 是规范化重建结果，不代表用户过去真实点击暂停的精确时刻。

这是产品明确接受的一次性历史误差。

但是必须保证：

```text
historical actual_duration
```

不被改变。

这是历史记录中我们优先保留的事实。

------

# 三、历史数据 normalization 规则

首先按照 session 分类。

## A. completed session

要求：

```text
start_time != NULL
end_time != NULL
actual_duration >= 0
```

计算：

```text
wall_sec = end_time - start_time
pause_sec_required = wall_sec - actual_duration
```

这里：

```text
actual_duration
```

是迁移时必须优先保留的历史事实。

不要直接相信旧：

```text
total_paused_sec
```

决定最终 pause duration。

它只能作为 consistency check。

因为最终 canonical invariant 必须是：

```text
wall_sec
- sum(pause_intervals)
== actual_duration
```

------

## B. 无暂停

如果：

```text
pause_sec_required <= 0
```

则：

- 不创建 pause interval
- 如果存在轻微异常，例如 actual_duration 比 wall duration 大 1~2 秒，按照下文的数据异常策略处理

------

## C. 有暂停

如果：

```text
pause_sec_required > 0
```

必须创建 deterministic reconstructed pause interval(s)。

不要简单全部放在：

- session 开头
- session 尾部

因为这会系统性偏置跨日统计。

采用：

## CENTERED / PROPORTIONAL NORMALIZATION

目标是让暂停时间在整个 session wall-clock timeline 上尽量中性分布。

优先实现一个 deterministic 算法。

例如：

如果只有一个重建 pause interval：

```text
pause_start =
start_time
+ (wall_duration - pause_duration) / 2

pause_end =
pause_start + pause_duration
```

即把历史未知 pause 居中。

如果当前 attribution engine 或统计准确性更适合多个 interval：

可以将 pause duration 均匀拆成有限数量的 interval。

但不要制造大量数据库行。

优先保持：

**一个历史 session 最多创建一个 reconstructed pause interval。**

这不是声称历史真的在中间暂停，而是一种 deterministic normalization。

必须通过代码注释和 migration/backfill 文档说明。

------

# 四、为什么 canonical invariant 优先于 total_paused_sec

迁移后唯一要求：

```text
actual_duration
==
wall_duration - canonical_pause_duration
```

旧：

```text
total_paused_sec
```

可能存在：

- 客户端计时漂移
- 网络延迟
- round/floor 差异
- 老版本 bug

因此：

如果：

```text
total_paused_sec
```

和：

```text
wall_duration - actual_duration
```

不一致，

以：

```text
actual_duration
```

为优先。

记录 migration audit 数据。

------

# 五、Migration Audit

不要静默修改。

提供一个生产迁移审计工具，例如：

```text
scripts/audit_pomodoro_v2_migration.py
```

或者项目更合适的位置。

必须支持：

```text
--dry-run
```

默认 dry-run，不修改数据库。

至少统计：

```text
total sessions
completed sessions
already canonical sessions
legacy sessions requiring reconstruction
sessions requiring zero pause
sessions requiring reconstructed pause
invalid sessions
actual_duration > wall_duration
negative duration
missing end_time
total_paused mismatch
currently running sessions
currently paused sessions
```

对于异常类别输出：

- count
- 少量 sample session ids

不要 dump 用户隐私信息。

------

# 六、生产 Backfill 工具

实现明确的 production backfill command。

例如：

```text
python scripts/migrate_pomodoro_sessions_v2.py --dry-run
```

真正执行必须要求显式：

```text
--apply
```

禁止默认修改数据库。

建议支持：

```text
--batch-size
--user-id
--session-id
```

方便灰度验证。

每批独立 transaction。

出现异常：

- rollback 当前 batch
- 清晰报错
- 不留下半完成 batch

整个操作必须可重复运行。

即：

**idempotent。**

已经存在 canonical pause intervals 的 session：

不得重复创建。

------

# 七、不要让 Alembic 负责大规模 Python backfill

Schema migration 与 data migration 分开。

Alembic revision 只负责：

- schema
- constraint
- indexes
- 必要字段

生产历史 Pomodoro normalization 使用专门 Python backfill command。

不要在：

```text
alembic upgrade head
```

里面循环扫描所有 Pomodoro session。

原因：

避免：

- migration lock 时间过长
- production deployment 超时
- rollback 困难
- 无法 dry-run
- 无法 batch

------

# 八、生产迁移顺序

在仓库中补充清晰的 runbook。

建议：

## Step 1

备份 PostgreSQL。

例如项目实际环境对应的：

```text
pg_dump
```

命令模板。

不要硬编码密码。

------

## Step 2

部署仍兼容当前数据的过渡版本。

如果当前版本已经支持：

```text
pause intervals + legacy fallback
```

则当前版本本身可以作为 migration bridge。

------

## Step 3

执行：

```text
alembic upgrade head
```

------

## Step 4

运行：

```text
python ...pomodoro migration... --dry-run
```

审核统计结果。

------

## Step 5

先抽样迁移。

例如：

```text
--user-id
```

或：

```text
--limit
```

验证。

------

## Step 6

完整：

```text
--apply
```

------

## Step 7

执行 post-migration verifier。

要求：

所有 completed historical sessions 满足 canonical invariant。

------

## Step 8

只有 verification 100% 通过以后：

才能部署删除 legacy compatibility 的代码版本。

------

# 九、Post Migration Verifier

增加：

```text
scripts/verify_pomodoro_v2_migration.py
```

必须验证所有 completed sessions：

### invariant 1

```text
start_time <= end_time
```

### invariant 2

所有 pause：

```text
started_at < ended_at
```

### invariant 3

pause 位于：

```text
[start_time, end_time]
```

### invariant 4

同 session pause intervals 不 overlap。

### invariant 5

```text
abs(
    wall_duration
    - pause_duration
    - actual_duration
) <= 1 second
```

理想情况下：

```text
== 0
```

### invariant 6

不存在：

```text
completed session
```

需要 legacy fallback。

Verifier 失败：

必须 exit non-zero。

这样生产发布 pipeline 可以阻止继续部署。

------

# 十、对异常历史数据的策略

不要让 migration 因为极少量脏数据完全无法运行。

分类处理。

## actual_duration > wall_duration

如果差异 <= 2 秒：

认为是历史 rounding。

canonical：

```text
actual_duration = wall_duration
```

记录 audit。

如果 > 2 秒：

不要自动猜。

放入：

```text
invalid/manual-review
```

默认 backfill 跳过并报告。

支持明确：

```text
--repair-invalid
```

才自动处理。

------

## actual_duration < 0

invalid。

不要静默迁移。

------

## end_time NULL

running / paused active session：

不要当 historical completed session 回填。

让当前 V2 lifecycle 自然处理。

------

## interrupted session

检查当前产品是否把 interrupted session 计入统计。

保持现有语义。

如果 interrupted session 有 actual_duration 且需要 canonical timing：

使用同样 normalization。

------

# 十一、处理生产迁移期间的新 session

迁移过程中生产仍可能有人使用番茄钟。

因此：

backfill 必须是：

```text
WHERE canonical pause data missing
AND session created before migration cutoff
```

在开始 migration 时记录：

```text
migration_cutoff UTC
```

之后的新 session：

V2 已经天然生成 pause intervals。

不要碰。

推荐 backfill command 接受：

```text
--cutoff
```

或者自动创建 migration run metadata。

------

# 十二、迁移完成以后删除 Legacy Runtime

只有 verifier 成功以后，修改代码。

删除 attribution engine 中：

```text
if no pause intervals:
    legacy fallback
```

改成统一：

```text
calculate_active_intervals(session, pause_intervals)
```

无 pause interval 表示：

```text
整个 session 无暂停
```

不再表示：

```text
legacy unknown
```

这是本次迁移最关键的语义变化。

------

# 十三、删除 old paused compatibility repair

上一轮为了历史 active session 存在：

```text
paused_at != NULL
but no open pause interval
```

的 repair。

migration/deployment 完成以后：

验证生产中不存在此类数据。

然后删除 runtime repair。

新的 invariant：

```text
status == paused
→ exactly one open pause interval
```

如果违反：

当作数据异常。

不要运行时偷偷补。

------

# 十四、actual_duration Server Authoritative

这轮同时完成 V2 收敛。

新 session：

complete / interrupt 时：

```text
actual_duration
```

必须完全由：

```text
server start_time
server end_time
pause intervals
```

计算。

客户端传：

```text
actual_duration_sec
```

不允许覆盖 DB。

如果现有 API 仍需要兼容字段：

暂时接受但 ignore。

如果确认当前小程序和后端同步发布：

直接删除客户端提交 actual_duration_sec。

同时删除 backend schema 中无必要的兼容字段。

这是一次明确的 breaking internal API cleanup。

小程序和后端必须一起修改。

------

# 十五、total_paused_sec

现在已经有 canonical pause interval 后：

检查：

```text
total_paused_sec
```

是否还真正需要。

如果只是统计用途：

直接删除。

如果 active timer UI / recovery 仍需要：

保留为 cache。

但：

```text
PauseInterval
```

必须是唯一 source of truth。

建议长期可以通过 API response 动态计算 pause total。

如果性能完全足够：

优先删除 total_paused_sec，减少重复事实。

但是：

删除前必须完整搜索：

- backend
- mini program
- scheduler
- tests

确认不会破坏 active recovery。

如果保留：

清晰注释：

```text
derived cache, not authoritative
```

------

# 十六、数据库约束强化

历史数据规范化后，可以比上一阶段增加更严格 invariant。

评估并实现安全约束：

## pause interval

```text
ended_at IS NULL
OR ended_at > started_at
```

## completed session

应用层保证：

```text
end_time >= start_time
actual_duration >= 0
```

## open pause

一个 session 最多一个：

```text
ended_at IS NULL
```

PostgreSQL：

优先 partial unique index。

SQLite：

确认当前版本支持 partial indexes。

如果两个 dialect 都支持，使用 Alembic 创建：

```text
UNIQUE(session_id)
WHERE ended_at IS NULL
```

如果 migration portability 有问题：

使用 dialect-aware Alembic。

不要放弃 PostgreSQL 数据完整性只是为了迁就理论上的 SQLite。

------

# 十七、删除 legacy tests，改成 canonical tests

迁移代码本身可以测试 legacy input。

但是 runtime attribution tests：

删除：

```text
legacy fallback expected behavior
```

替换为：

```text
all persisted canonical sessions use precise path
```

增加测试：

### backfill

旧：

```text
start=23:00
end=01:00
actual_duration=5400
```

迁移后 pause total 必须：

```text
1800
```

且：

```text
wall - pause == actual
```

------

### idempotent

运行 migration 两次：

第二次：

```text
0 rows changed
```

------

### verification

canonical DB：

100% pass。

人为制造 broken interval：

verifier fail。

------

### runtime

无 pause intervals：

解释为：

```text
zero pause
```

而不是 legacy。

------

# 十八、PostgreSQL 实际验证

这次必须尽最大可能实际验证 PostgreSQL。

检查：

- docker
- docker compose
- CI
- testcontainers

如果可用：

启动临时 PostgreSQL。

执行完整流程：

```text
old-ish schema/data fixture
↓
alembic upgrade head
↓
backfill --dry-run
↓
backfill --apply
↓
verify
↓
runtime tests
```

再测试：

```text
downgrade/upgrade
```

注意：

data normalization 本身不要求自动 downgrade。

数据库 backup 才是生产 data migration rollback 方案。

这是可以接受的。

在 runbook 中明确：

**schema rollback != historical data rollback**

historical data rollback 使用生产 backup。

------

# 十九、生产安全

即使 Pomodoro 数据业务敏感度较低，也必须按照生产数据库迁移标准执行。

不要：

- 自动连接 production
- 自动 drop 数据
- truncate
- 覆盖 backup
- 将数据库凭据写入脚本
- 在一个无限 transaction 中更新全表
- migration 执行期间锁住整张 pomodoro_sessions

使用 batch。

必要时：

```text
ORDER BY id
LIMIT batch_size
```

逐批 commit。

------

# 二十、最终我们明确接受的 trade-off

在代码文档中写清楚：

对于 migration 之前缺失 PauseInterval 的历史 session：

> Exact historical pause positions were unavailable.
> Historical sessions were deterministically normalized while preserving actual_duration.
> Post-migration sessions contain precise server-recorded pause intervals.

这是历史事实。

不要把 reconstructed pause 描述为：

```text
actual user pause
```

它只是 normalization。

但是 migration 完成以后：

runtime 不需要知道这件事。

------

# 二十一、最终代码必须达到

```text
PRODUCTION HISTORY
       ↓
one-time normalization
       ↓
canonical sessions
       ↓
────────────────────
       ↓
NEW SESSIONS
       ↓
server timestamps
       ↓
canonical sessions
────────────────────
       ↓
ONE attribution engine
       ↓
statistics
```

禁止最终仍然：

```text
if legacy:
    ...
else:
    ...
```

------

# 二十二、最终报告

完成以后只报告：

## Production Migration

- 新 backfill command
- dry-run 用法
- apply 用法
- verifier
- batch/idempotency

## Historical Normalization

说明如何从：

```text
start/end/actual_duration
```

重建 pause intervals。

明确承认历史 pause timestamp 是 deterministic approximation。

## Legacy Removed

列出具体删除的：

- fallback
- compatibility repair
- old API fields
- old tests

## Canonical Invariants

列出 migration 后强制成立的 invariant。

## PostgreSQL

说明是否实际跑过。

## Deployment Runbook

给出实际生产执行顺序。

## Rollback

明确：

- code rollback
- schema rollback
- data rollback

其中历史数据 migration 的最终 rollback 来源必须是 migration 前数据库 backup。

## Tests

列出实际运行命令和结果。

不要再次给我讨论是否应该迁移。

我们的产品决策已经确定：

**备份生产数据库，然后一次性规范化历史 Pomodoro 数据并删除长期 legacy compatibility。**

现在直接实施。
