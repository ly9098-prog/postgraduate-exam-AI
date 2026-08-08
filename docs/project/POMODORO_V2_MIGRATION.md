# Pomodoro V2 数据迁移 Runbook

> 目标：把历史 Pomodoro session 一次性规范化到 V2 canonical 模型，然后**删除全部 legacy
> compatibility**。迁移完成后，所有历史与未来 session 都遵循同一套
> `Session + PauseIntervals → active timeline → attribution engine` 数据模型。
>
> 适用范围：生产 PostgreSQL（`101.33.231.186` / `xzshub.top`）。
> 配套代码：`backend/scripts/audit_pomodoro_v2_migration.py`、
> `backend/scripts/migrate_pomodoro_sessions_v2.py`、
> `backend/scripts/verify_pomodoro_v2_migration.py`、Alembic `48e17ed2a3f3` + `f6e7a8b9c0d1`。

---

## 0. 产品决策（已确定，不再讨论）

- **不长期维护 legacy Pomodoro compatibility。**
- 对生产数据库完整备份后，**一次性迁移/规范化**历史 Pomodoro 数据，然后**删除 legacy 统计分支**。
- 历史 pause 位置无法真实恢复，允许 **deterministic normalization**（centered / proportional）。
  - 历史 pause intervals 是**规范化重建结果**，不代表用户过去真实点击暂停的精确时刻。
  - 这是产品明确接受的一次性历史误差。
- **`actual_duration` 是迁移时必须优先保留的历史事实**，不被改变（除非 ≤2s rounding 或显式 `--repair-invalid`）。

最终接受的 trade-off（写入代码与文档）：

> Exact historical pause positions were unavailable. Historical sessions were
> deterministically normalized while preserving actual_duration. Post-migration
> sessions contain precise server-recorded pause intervals.

迁移完成以后，runtime 不再区分 legacy / new session —— 只有 canonical session。

---

## 1. 背景与当前状态

### 1.1 历史数据长什么样

旧 session 只有：

```text
start_time
end_time
actual_duration
total_paused_sec
paused_at
```

**没有 pause interval。** 因此不能声称能真实恢复历史 pause timestamp。

### 1.2 迁移后的 canonical 模型

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
Session + PauseIntervals → active timeline → attribution engine → daily/weekly/trends/subjects
```

### 1.3 当前部署状态（重要）

- 生产当前运行的是 **旧 Pomodoro 代码**（尚无 pause intervals / 学习日统计）。
- 本仓库的 Study Day / Pause Interval / Attribution Engine 改造（Alembic `48e17ed2a3f3`）与
  本迁移（`f6e7a8b9c0d1` + 三个 scripts + legacy 删除）尚未上线。
- 生产 app 启动自检（`production_config_validator`）校验 **alembic 必须在 head**，否则拒绝启动。
  因此 schema 迁移必须先于新 app 上线。

---

## 2. 历史数据 normalization 规则

### 2.1 completed session

要求：`start_time != NULL`、`end_time != NULL`、`actual_duration >= 0`。

```text
wall_sec = end_time - start_time
pause_sec_required = wall_sec - actual_duration
```

**`actual_duration` 是优先保留的历史事实。** 旧 `total_paused_sec` 只作为 consistency check，
不决定最终 pause duration。最终 canonical invariant 必须是：

```text
wall_sec - sum(pause_intervals) == actual_duration
```

### 2.2 无暂停（pause_sec_required <= 0）

- 不创建 pause interval。
- 若 `actual_duration` 比 `wall` 大 1~2 秒：视为历史 rounding，`actual_duration = wall`（零暂停），记录 audit。

### 2.3 有暂停（pause_sec_required > 0）

采用 **CENTERED / PROPORTIONAL NORMALIZATION**，一个历史 session **最多创建一个**重建 pause interval：

```text
pause_start = start_time + (wall_sec - pause_sec) / 2   # 取整数秒 floor
pause_end   = pause_start + pause_sec
```

即把未知的历史 pause **居中**放在 wall-clock timeline 上，避免系统性偏置跨日统计。
**最多一个 interval**，不制造大量数据库行。

> 这不是声称历史真的在中间暂停，而是一种 deterministic normalization。

### 2.4 异常数据策略

| 异常 | 默认 | `--repair-invalid` |
|------|------|--------------------|
| `actual_duration > wall + 2s` | skip + 报告 | `actual_duration = wall`（零暂停） |
| `actual_duration` 为负 | skip + 报告 | `actual_duration = 0` + 整个 wall 作为一个 pause interval |
| `end_time IS NULL`（completed） | skip + 报告 | skip + 报告（无法归一） |
| `end_time < start_time` | skip + 报告 | skip + 报告（无法归一） |

`actual_duration` 比 wall 大但 ≤2s：自动 clamp（rounding），不需要 `--repair-invalid`。

### 2.5 active session（running / paused）

规范规定 `end_time IS NULL` 的 active session **不当 historical completed 回填**，让 V2 lifecycle
自然处理。但为了 canonical invariant 与 §13 的 `status == paused → 恰好一个 open interval`，backfill
对 active session 做两件事：

- `running/paused` 且有 `total_paused_sec > 0` 但无 closed interval → 在 elapsed 窗口内
  居中重建一个 closed interval（时长 = `total_paused_sec`）。
- `paused` 且 `paused_at` 有值但无 open interval → 在 `paused_at` 处补建 open interval。

这样迁移完成后，生产不存在 §13 说的 `paused_at != NULL but no open interval` 数据。

---

## 3. 生产迁移顺序（Runbook）

> 所有 `docker compose` 命令都需要 `--env-file backend/.env -f deploy/docker-compose.prod.yml`。
> 以下以 `compose()` 简写指代该前缀（同 `deploy/scripts/deploy.sh` 内）。

### Step 0 — 低峰窗口 + 告知

选择低流量时段。番茄钟在迁移窗口内（Step 4→Step 8）可能产生极少量“迁移后无 interval”的 in-flight
session，Step 8 之后的二次 backfill 会收尾。此窗口越短越好。

### Step 1 — 备份 PostgreSQL（强制）

```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh backup
```

`backup` 走 compose 的 `backup` 服务（custom-format `pg_dump` 到持久卷）。确认备份产物存在后再继续。
Redis 不影响 Pomodoro 持久数据，可选 `redis-cli SAVE`。

> ⚠️ 历史数据迁移的最终 rollback 来源是**这份备份**。schema 可 downgrade，但**历史数据不做自动
> downgrade** —— 数据回滚 = 用备份恢复。

### Step 2 — 构建新镜像（不重启 app）

```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh build        # 等价 docker compose build app scheduler
```

只构建、不 `up`，运行中的旧 app 继续服务。

### Step 3 — 应用 schema 迁移

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app alembic upgrade head
```

- 应用 `48e17ed2a3f3`（创建 `user_pomodoro_settings`、`pomodoro_pause_intervals`、复合索引）
  与 `f6e7a8b9c0d1`（V2 constraints）。
- `f6e7a8b9c0d1` 是 **data-tolerant**：pause CHECK + partial unique index 空表/新表直接应用；
  completed session 的 `actual_duration >= 0 AND end_time >= start_time` CHECK 只在无违规行时应用，
  有违规行则打印 WARNING 跳过（Step 6 修完数据后 Step 7 重跑即可补上）。

> 不用 `deploy.sh migrate`：它跑在**旧 app 容器**里，旧镜像没有新 migration 文件。

### Step 4 — Dry-run 审计

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.audit_pomodoro_v2_migration
```

只读，输出各分类计数 + 少量 sample session id：

- total / completed / running / paused / interrupted
- already canonical / requiring reconstruction / invalid
- actual>wall / negative / missing end_time / end<start / total_paused mismatch

**审核结果**：确认 `invalid` 数量可接受（若为 0 最好）。若有 invalid 且不想跳过，先在 Step 6 用
`--repair-invalid`。

### Step 5 — Backfill dry-run

```bash
# 记录 cutoff（UTC ISO，建议取 Step 8 cutover 时刻）
CUTOFF=$(date -u +%Y-%m-%dT%H:%M:%S)

docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.migrate_pomodoro_sessions_v2 --dry-run --cutoff "$CUTOFF"

# 抽样灰度：只迁某用户
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.migrate_pomodoro_sessions_v2 --dry-run --cutoff "$CUTOFF" --user-id 12

# 抽样灰度：只迁前 N 条
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.migrate_pomodoro_sessions_v2 --dry-run --cutoff "$CUTOFF" --limit 50
```

`--dry-run` 默认，**不写库**。输出各分类写入数。

### Step 6 — Backfill apply

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.migrate_pomodoro_sessions_v2 --apply --cutoff "$CUTOFF"

# 有 invalid 且已审核 → 显式修复
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.migrate_pomodoro_sessions_v2 --apply --cutoff "$CUTOFF" --repair-invalid --report /tmp/pomo_migration.json
```

- 默认 `--batch-size 200`，每批独立事务，失败 rollback 当前批并中止，不留半完成批。
- **idempotent**：已存在 canonical pause data 的 session 不重复创建；重复运行 0 rows changed。
- 可重复执行。`--report` 可选，写 JSON 汇总。

### Step 7 — 重跑 alembic head（补齐被跳过的 completed CHECK）

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app alembic upgrade head
```

若 Step 6 修掉了违规行，此步会补上 `ck_pomodoro_sessions_completed_duration`。

### Step 8 — Post-migration verifier（必须 100% 通过）

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.verify_pomodoro_v2_migration
```

校验所有 completed session 的 6 个 invariant：

1. `start_time <= end_time`
2. 每个 pause：`started_at < ended_at`（completed 不允许 open interval）
3. pause 位于 `[start_time, end_time]`
4. 同 session 的 pause 不 overlap
5. `abs(wall_duration - pause_duration - actual_duration) <= 1s`
6. 不存在需要 legacy fallback 的 completed session

外加 §13：`status == paused → 恰好一个 open interval`。

**失败 exit non-zero**。任何失败 → 回到 Step 6/7 修复后重跑，**禁止带失败进入 Step 9**。

### Step 9 — Cutover：部署 legacy-removal runtime

```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh update
```

DB 已到 head，validator 通过；新 runtime 是 canonical（无 legacy fallback）。

### Step 10 — 二次 backfill + 二次 verify（收尾窗口内旧 app 产生的 session）

Step 4→Step 8 期间旧 app 仍可能产生 legacy 风格 session。cutover 后收尾：

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.migrate_pomodoro_sessions_v2 --apply
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml \
  run --rm app python -m scripts.verify_pomodoro_v2_migration
```

二次 backfill 只处理“无 interval”的 session（新 runtime 创建的 session 自带 interval，会被跳过），
idempotent，安全。

---

## 4. 迁移完成以后：Legacy 删除清单

| 删除内容 | 位置 |
|----------|------|
| attribution legacy fallback 语义（无 interval = wall-clock 比例拆分的历史含义） | `app/services/pomodoro_attribution.py`（docstring 已改为“零暂停 = 整个 wall 为 active”） |
| `_close_open_pause_interval` 的 `paused_at`-backfill | `app/services/pomodoro_service.py`（改为只关闭已有 open interval，违反 §13 时记录 warning，不偷偷补） |
| 客户端 `actual_duration_sec` 覆盖 DB | `app/services/pomodoro_service.py` complete/interrupt 改为纯 server 计算；`PomodoroCompleteRequest` 清空 |
| 客户端 `total_paused_ms`/`total_paused_sec` 合并 | complete/interrupt/resume 请求体清空（`PomodoroResumeRequest` 清空） |
| `_cancel_running` 死代码 | `app/services/pomodoro_service.py`（scheduler 已移除） |
| legacy fallback 期望测试 | `test_pomodoro_study_day_stats.py`（case7/case7b 改为“零暂停”语义；case13/13b 改为“data anomaly 不修复”） |
| legacy test 断言客户端传 `actual_duration_sec` | `miniprogram/scripts/test-pomodoro-free-timer-limit.js` |

**保留（derived cache, not authoritative）：** `total_paused_sec` 字段仍是响应字段，供 active timer UI
恢复用；注释标注 `derived cache, not authoritative`，唯一权威是 `pomodoro_pause_intervals`。

**保留：** `paused_at` 字段（“当前是否暂停”的恢复标志 + API 字段），但暂停时长一律从 interval 计算。

---

## 5. Canonical Invariants（迁移后强制）

- completed：`end_time >= start_time` 且 `actual_duration >= 0`（DB CHECK `ck_pomodoro_sessions_completed_duration`）
- pause：`ended_at IS NULL OR ended_at > started_at`（DB CHECK `ck_pomodoro_pause_intervals_ended_at`）
- 每个 session 至多一个 open interval（DB partial unique index `ux_pomodoro_pause_intervals_one_open`）
- 统计恒等式：`sum(contribution_sec) == actual_duration`（largest-remainder，attribution engine）
- `status == paused` → 恰好一个 open interval（runtime 不再修复违规）

---

## 6. Rollback

| 层面 | 操作 | 说明 |
|------|------|------|
| 代码 | 回滚 git 状态 → 重新 `deploy.sh update` | 不 `down`、不删 volume |
| Schema | `docker compose run --rm app alembic downgrade -1`（`f6e7a8b9c0d1`→`48e17ed2a3f3`） | constraints 可降；仅 schema |
| **数据** | **用 Step 1 备份恢复** | 历史数据迁移不做自动 downgrade；`schema rollback != historical data rollback` |

---

## 7. 工具与参数速查

### audit（只读）

```bash
python -m scripts.audit_pomodoro_v2_migration [--sample-size N]
```

### migrate（backfill）

```bash
python -m scripts.migrate_pomodoro_sessions_v2 [--apply] [--batch-size 200]
    [--user-id UID] [--session-id SID] [--cutoff YYYY-MM-DDTHH:MM:SS]
    [--repair-invalid] [--limit N] [--report PATH]
```

### verify

```bash
python -m scripts.verify_pomodoro_v2_migration [--sample-size N]
# exit 0 = pass, 1 = fail
```

---

## 8. PostgreSQL 验证状态

- 本地（WSL，无 Docker）已做：SQLite 全链路 `alembic upgrade head → backfill --dry-run →
  --apply → verify` + 反复 upgrade/downgrade/upgrade；PG dialect 编译验证（partial unique index
  `WHERE ended_at IS NULL`、两个 CHECK constraint 均生成合法 PG DDL）。
- **未在本机跑真实 PostgreSQL**（无 Docker/PG 环境）。生产执行前建议在临时 PG 实例（或灰度库）
  跑一遍 §3 全流程，命令见上。

### 8.1 生产执行记录（2026-08-08）

已在生产 PostgreSQL（`101.33.231.186`）执行完整 §3 流程：

| 步骤 | 结果 |
|------|------|
| Step 1 备份 | `postgraduate_postgres_20260808_023925.dump`（12.7 MB，pg_restore --list 699 TOC，SHA-256 校验通过） |
| Step 3 schema | `c5d6e7f8a9b0 → 48e17ed2a3f3 → f6e7a8b9c0d1`，无 WARNING |
| Step 4 审计 | 144 总 / 129 completed / 15 interrupted / 0 running+paused；invalid=0；3 条 actual>wall（≤2s rounding）；21 条 total_paused 缓存不一致 |
| Step 6 backfill | 129 processed，81 pause intervals，3 clamp，0 repair，0 invalid |
| Step 8 verify | 100% 通过 |
| Step 9 cutover | `deploy.sh update`，新 runtime healthy，Restarts=0 |
| Step 10 二次 backfill | 0 changes（幂等），final verify 100% 通过 |

> **生产方言坑（已修复）**：backfill 首轮 apply 在 asyncpg 报 `invalid input for query argument ... got 'str'`。
> `_sql_dt()` 把 datetime 序列化为字符串绑定，SQLite 接受但 PostgreSQL/asyncpg 拒绝（timestamp 列期望 datetime
> 对象）。修复：`_process_completed` 改为直接绑定 datetime 对象（SQLite/PG 通用），本地 25 个迁移测试复验通过后
> 重跑 apply 成功。历史 schema 迁移（alembic）与回滚不受影响。
