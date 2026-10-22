# SM-2 复习调度系统设计

> 基于代码真实状态的架构设计文档。描述当前系统边界、数据职责、同步策略与技术债。
> 最后更新：2026-10-23（按当前代码复核：接口清单、ORM 字段表与时区策略修正；ReviewSchedule 仍为唯一数据源）

---

## 目录

1. [系统分层结构](#1-系统分层结构)
2. [数据职责边界](#2-数据职责边界)
3. [单向同步原则](#3-单向同步原则)
4. [SM-2 规则冻结](#4-sm-2-规则冻结)
5. [双接口体系说明](#5-双接口体系说明)
6. [系统一致性审计](#6-系统一致性审计)
7. [技术债清单](#7-技术债清单)

---

## 1. 系统分层结构

```
┌─────────────────────────────────────────────────────┐
│               API 层 (review.py + wrong_q.py)        │
│  ┌─────────────────────┐  ┌───────────────────────┐ │
│  │ 复习接口 (RS 基座)   │  │ 错题本接口            │ │
│  │  /today              │  │  /wrong-questions      │ │
│  │  /today/overview     │  │  /stats                │ │
│  │  /today/next-batch   │  │  /task-flow            │ │
│  │  /today/result       │  │  /diagnosis/*          │ │
│  │  /schedule-stats     │  │  /{wq_id} GET/PUT      │ │
│  │  /history            │  │  /batch POST           │ │
│  │  /grade-batch        │  │                        │ │
│  │  /{id}/master        │  │                        │ │
│  │  /{id}/unmaster      │  │                        │ │
│  └──────────┬──────────┘  └───────────┬───────────┘ │
└─────────────┼──────────────────────────┼────────────┘
              │                          │
              ▼                          ▼
┌─────────────────────────────────────────────────────┐
│                Service 层                            │
│                                                      │
│  ┌────────────────────────────────────────────┐     │
│  │         review_scheduler                   │     │
│  │  (RS 主调度，唯一 SM-2 计算入口)            │     │
│  │                                            │     │
│  │  get_today_review()                         │     │
│  │  get_today_review_overview()                │     │
│  │  get_next_today_review_batch()              │     │
│  │  get_today_review_result()                  │     │
│  │  submit_review() / grade_batch_review()     │     │
│  │  get_review_stats() / get_review_history()  │     │
│  │  auto_schedule_wrong_question()             │     │
│  │  mark_mastered() / unmark_mastered()        │     │
│  └───────────────────┬────────────────────────┘     │
│                      │                              │
│                      ▼                              │
│  ┌──────────────────────────────────────────┐       │
│  │          SM-2 Engine (唯一计算来源)       │       │
│  │          calc_sm2(quality, efactor,       │       │
│  │          interval, repetitions, date)     │       │
│  └──────────────────────────────────────────┘       │
│                                                      │
│  ┌──────────────────────────────────────┐           │
│  │  wrong_question_service               │           │
│  │  (错题 CRUD，不含 SM-2 逻辑)                 │           │
│  │  record_wrong()                       │           │
│  └──────────────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│               数据层 (ORM Model)                     │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │         ReviewSchedule (主系统)               │   │
│  │  id | user_id | question_id                   │   │
│  │  question_version_id | subject_id(FK)         │   │
│  │  interval | ease_factor | repetitions         │   │
│  │  next_review_at | last_reviewed_at            │   │
│  │  occurrence_seq | is_active | mastered        │   │
│  │  created_at | updated_at                      │   │
│  └────────────────────┬─────────────────────────┘   │
│                       │ 单向同步 (仅 last_review_at) │
│                       ▼                              │
│  ┌──────────────────────────────────────────────┐   │
│  │         WrongQuestion (错题分析层)             │   │
│  │  id | user_id | question_id                   │   │
│  │  wrong_answer | error_type | ai_analysis      │   │
│  │  review_count | last_review_at                │   │
│  │  mastered (状态位)                            │   │
│  │  created_at | updated_at                      │   │
│  │                                               │   │
│  │  ⚠ SM-2 兼容字段已于 P2-2 移除               │   │
│  │  (efactor/interval/repetitions/               │   │
│  │   next_review_date/quality)                   │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │         ReviewRecord (历史记录层)              │   │
│  │  id | user_id | question_id                   │   │
│  │  question_version_id | schedule_id            │   │
│  │  occurrence_seq | request_id                  │   │
│  │  rating | interval_before/after               │   │
│  │  ease_factor_before/after                     │   │
│  │  mastery_percent | reviewed_at                │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 层级角色

| 层 | 角色 | 职责 |
|----|------|------|
| **ReviewSchedule** | 主系统 | 所有复习调度状态（interval / ease_factor / repetitions / next_review_at / mastered）的唯一主数据源 |
| **SM-2 Engine** | 唯一计算来源 | `calc_sm2()` 是系统中唯一的 SM-2 算法实现，所有路径共享同一个函数 |
| **WrongQuestion** | 错题分析层 | 错题答案、错误类型、AI 分析、复习次数统计；不含 SM-2 调度参数（P2-2 已移除） |
| **ReviewRecord** | 历史记录层 | 每次复习提交的完整快照（评分、间隔变化、难度变化），仅追加不修改 |

---

## 2. 数据职责边界

### ReviewSchedule 负责（调度核心）

```
字段            类型          说明
─────────────────────────────────────────────────────
id              int           PK
user_id         int           用户 FK
question_id     int           题目 FK
question_version_id int       题目版本 FK（question_versions.id）；提交时校验版本一致
subject_id      int?          科目 FK（subjects.id，ondelete SET NULL，可空）
interval        int           当前复习间隔（天），SM-2 计算结果
ease_factor     float         难度因子（E-Factor），SM-2 计算结果，下限 1.3
repetitions     int           连续正确次数，SM-2 计算结果
next_review_at  datetime?     下次复习时间（UTC naive datetime）
last_reviewed_at datetime?    最近一次复习时间
mastered        bool          是否标记为已掌握
is_active       bool          是否有效（默认 true；失效调度不进入待复习列表）
occurrence_seq  int           服务端持有的下一次复习序号；每次成功提交 +1，提交时校验防重
created_at      datetime      创建时间
updated_at      datetime      最后更新时间
```

### ReviewRecord 负责（历史记录）

```
字段            类型          说明
─────────────────────────────────────────────────────
id              int           PK
user_id         int           用户 FK
question_id     int           题目 FK
question_version_id int       题目版本 FK
schedule_id     int?          关联 ReviewSchedule（可空）
occurrence_seq  int           本次复习对应的调度序号（schedule_id + occurrence_seq 唯一）
request_id      str           请求幂等键（user_id + request_id 唯一）
rating          int           0-5 评分（自评或自动批改映射值）
interval_before/interval_after int?  提交前后复习间隔（天）
ease_factor_before/ease_factor_after float? 提交前后难度因子
mastery_percent int?          掌握度百分比（0-100，可空）
reviewed_at     datetime      提交时间（仅追加，不修改）
```

### WrongQuestion 负责（错题分析）

```
字段            类型          说明
─────────────────────────────────────────────────────
id              int           PK
user_id         int           用户 FK
question_id     int           题目 FK
wrong_answer    str?          错误答案
error_type      str           错题类型：concept / calculation / careless / other
ai_analysis     dict?         AI 分析结果缓存
review_count    int           总复习次数
last_review_at  datetime?     最近一次复习时间（从 RS.last_reviewed_at 同步）
mastered        bool          是否已掌握（状态位，与 RS.mastered 保持最终一致）
created_at      datetime      创建时间
updated_at      datetime      最后更新时间

移除于 P2-2：efactor / interval / repetitions / next_review_date / quality
```

### 职责分离原则

- **SM-2 参数**（interval / efactor / repetitions）→ 调度核心，仅由 ReviewSchedule 持有（P2-2 已从 WQ 移除）
- **错题分析**（wrong_answer / error_type / ai_analysis）→ 错题分析，仅由 WrongQuestion 持有
- **复习历史**（rating / interval_before/after / ease_factor_before/after）→ 历史审计，仅由 ReviewRecord 持有
- **复习计数** → ReviewSchedule 无此字段，WrongQuestion.review_count 独立统计

---

## 3. 单向同步原则

### 同步策略

```
ReviewSchedule 更新
       │
       ▼
_sync_schedule_to_wq(db, schedule)
       │
       ├─ wq.last_review_at = schedule.last_reviewed_at
       └─ db.commit()
```

### 同步触发点

| 操作 | 函数 | 同步时机 |
|------|------|----------|
| 做错题自动排期 | `auto_schedule_wrong_question()` | 创建/更新 ReviewSchedule 后立即同步 |
| 提交复习评分 | `submit_review()` | SM-2 计算并更新 RS 后立即同步 |
| 标记已掌握 | `mark_mastered()` | RS.mastered=True 后立即同步 |
| 取消已掌握 | `unmark_mastered()` | RS.mastered=False 后立即同步 |

### 核心约束

- **绝不反向同步**：WrongQuestion → ReviewSchedule 的路径不存在且不应存在
- **同步范围已缩减**：P2-2 后 `_sync_schedule_to_wq()` 仅同步 `last_review_at`（原 SM-2 字段已从 WQ 模型移除）
- **同步是最终一致性的**：短窗口内可能存在 RS 已更新但 WQ 未同步的状态，但在请求结束（`db.commit()`）后应一致

---

## 4. SM-2 规则冻结

### 算法来源

唯一实现在 `app/services/sm2_service.py:calc_sm2()`，所有路径共享。

### rating 范围

```
rating  含义                    对 SM-2 影响
────────────────────────────────────────────────────────
5       完全正确，毫不犹豫        efactor 上调最大
4       正确，稍有犹豫            efactor 小幅上调
3       正确，但较困难            efactor 轻微下调
2       错误，能回想正确答案       efactor 下调，repetitions=0
1       错误，回想困难            efactor 下调，repetitions=0
0       完全错误，毫无印象        efactor 下调最大，repetitions=0
```

**关键规则**：

- **0 是合法评分**：不应抛出 `ValueError`；SM-2 算法会重置 `repetitions=0` 并将间隔重置为 1 天
- **quality < 3 → 失败**：`repetitions=0`, `interval=1`（当天或明天重现）
- **quality >= 3 → 成功**：`repetitions += 1`

### interval 计算规则

```
if quality < 3:
    interval = 1
else:
    if repetitions == 0:    # 首次正确
        interval = 1
    elif repetitions == 1:  # 第二次正确
        interval = 6
    else:                   # 第三次及以上
        interval = max(1, floor(interval * efactor + 0.5))
```

### efactor 更新公式

```
efactor' = efactor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
efactor' = max(1.3, efactor')
```

### 最小值约束

| 参数 | 最小值 | 说明 |
|------|--------|------|
| efactor | 1.3 | SuperMemo 标准下限；低于此值强制回升 |
| interval | 1 | 禁止 0 间隔（当天必须重现意味着 interval=1） |
| repetitions | 0 | quality < 3 时归零 |

### 自动批改默认映射

批量自动批改提交时（`POST /review/grade-batch`，按作答对错映射 rating）：

```
答对 (correct) → rating=4（正确但稍有犹豫）
答错 (wrong)  → rating=1（错误但能回想）
```

故意不使用极端值 5/0，避免 SM-2 评分过于激进。

### 时区策略

- **复习日期**：按 Asia/Shanghai 日历日计算。`calc_sm2()` 的 `review_date` 缺省为 `shanghai_today()`（`sm2_service.py`），`review_scheduler.submit_review()` 显式传入 `shanghai_today()`（`review_scheduler.py:665`）
- **next_review_at 存储**：上海日历日起点的 naive UTC 瞬时——`shanghai_date_utc_range(next_review_date)[0]`（`review_scheduler.py:674`）
- **内部存储**：其余时间戳统一使用 naive UTC datetime（`utcnow()` 返回 `datetime.now(timezone.utc).replace(tzinfo=None)`）
- **禁止**：产品口径的「今天」不得从 `utcnow().date()` 或服务器本地时间推导（`time_utils.shanghai_today` docstring 明确要求）

---

## 5. 接口体系（单一路径）

### 当前接口清单

```
┌────────────────────────────────────────────────────┐
│                  复习接口（RS 基座）                 │
│                                                     │
│  GET    /review/today            今日待复习列表      │
│  GET    /review/today/overview   今日复习总览        │
│  POST   /review/today/next-batch 获取下一批待复习     │
│  GET    /review/today/result     本次复习结果        │
│  GET    /review/schedule-stats   复习统计            │
│  GET    /review/history          复习历史            │
│  POST   /review/grade-batch      批量自动批改 + 提交 │
│  POST   /review/{schedule_id}/master    标记已掌握   │
│  POST   /review/{schedule_id}/unmaster  取消已掌握   │
│                                                     │
│  错题本接口（WQ 基座，不含 SM-2 参数）              │
│  GET    /wrong-questions          错题列表           │
│  GET    /wrong-questions/stats    错题统计           │
│  GET    /wrong-questions/task-flow     任务流        │
│  GET    /wrong-questions/diagnosis/taxonomy  错误分类│
│  GET    /wrong-questions/diagnosis/stats    诊断统计│
│  GET    /wrong-questions/{wq_id}            单题详情│
│  GET    /wrong-questions/{wq_id}/diagnosis   单题诊断│
│  PUT    /wrong-questions/{wq_id}/diagnosis   更新诊断│
│  POST   /wrong-questions/{wq_id}/diagnosis/suggest  建议│
│  PUT    /wrong-questions/{wq_id}             更新错题│
│  POST   /wrong-questions/batch               批量操作│
└────────────────────────────────────────────────────┘
```

### 设计说明

- 旧接口（`/review/due`、`/review/submit`、`/review/stats`）已于 P2-1 移除
- 所有复习操作统一使用 ReviewSchedule 作为数据源；评分提交唯一入口是 `POST /review/grade-batch`（`grade_batch_review()` 逐条调用 `submit_review()`，按作答对错映射 rating=4/1）
- 错题本侧无任何 SM-2 参数写入端点（原 `PUT /wrong-questions/{id}/quality` 已不存在）
- WrongQuestion 响应中不含 SM-2 参数（P2-2 移除）

---

## 6. 系统一致性审计

### 审计方法

基于 2026-06-26 的历史审计快照，结合 2026-09-02 与 2026-10-23 两次当前代码复核，逐条检查以下风险点。标注为“已修复”的代码块仅用于说明历史风险，不能作为当前实现示例。

### 6.1 ReviewSchedule → WrongQuestion 已移除字段

P2-2 后 WQ 不持有 SM-2 字段（efactor/interval/repetitions/next_review_date/quality），同步范围缩减为仅 `last_review_at`：

| RS 字段 | WQ 对应字段 | 同步状态 | 说明 |
|---------|------------|---------|------|
| last_reviewed_at | last_review_at | ✅ P1-2 已修复 | `_sync_schedule_to_wq()` 唯一保留的同步 |
| mastered | mastered | WQ 独立维护 | P2-2 保留 mastered 状态位，由业务代码主动同步 |
| ease_factor | 无 | P2-2 已移除 | WQ 不再持有 SM-2 参数 |
| interval | 无 | P2-2 已移除 | WQ 不再持有 SM-2 参数 |
| repetitions | 无 | P2-2 已移除 | WQ 不再持有 SM-2 参数 |
| next_review_at | 无 | P2-2 已移除 | WQ 不再持有 SM-2 参数 |

**结论**：无残留风险。

### 6.2 WrongQuestion 被用于计算 SM-2 的路径

**确认不存在**：`wrong_question_service.update_quality()` 已不存在——当前 `wrong_question_service.py` 无任何 SM-2 计算或 quality 写入；错题本侧也无 `PUT /wrong-questions/{id}/quality` 路由。所有 SM-2 计算统一经 `review_scheduler.submit_review()` → `calc_sm2()`。

> 以下调用链是 P0-1 修复前的历史示例，当前代码不再执行；保留它仅为审计追溯。

> **状态：P0-1 已修复** ✅ — `update_quality()` 已改为通过 ReviewSchedule 路径执行 SM-2 计算，不再绕开 RS。

**调用链路**：

```python
async def update_quality(db, user_id, wq_id, quality):
    wq = await get_by_id(db, user_id, wq_id)
    sm2_result = calc_sm2(
        quality=quality,
        efactor=wq.efactor or 2.5,
        interval=wq.interval or 0,
        repetitions=wq.repetitions or 0,
        review_date=date.today(),
    )
    wq.efactor = sm2_result["efactor"]
    wq.interval = sm2_result["interval"]
    wq.repetitions = sm2_result["repetitions"]
    wq.next_review_date = sm2_result["next_review_date"]
    ...
```

**调用链路**：
1. `PUT /api/v1/wrong_questions/{wq_id}/quality` → `wrong_question_service.update_quality()` → WQ 上独立 SM-2
2. `POST /api/v1/review/submit` → `review_service.submit_review()` → `wrong_question_service.update_quality()` → WQ 上独立 SM-2

**风险等级：P0** — 双路径独立计算 SM-2，WQ 的 SM-2 参数被直接修改后，RS 无法感知。后续新路径读取 RS 时得到的是旧值。

### 6.3 双接口返回同一题的 interval 不一致

**可能发生**：当用户通过旧路径（`/review/submit` 或 `/wrong_questions/{id}/quality`）提交评分时：
- 旧路径现通过 `update_quality()` → RS 路径执行，SM-2 参数一致
- RS/WQ 同步由 `_sync_schedule_to_wq()` 保证

**结论**：P0 + P1 已消除此风险 ✅。

### 6.4 timezone / utcnow 混用残留

| 位置 | 使用 | 时区 |
|------|------|------|
| `review_scheduler.submit_review()` | `shanghai_today()` 作 review_date；`shanghai_date_utc_range()` 定 next_review_at；存储戳 `utcnow()` | Asia/Shanghai 日历日 ✅ |
| `review_scheduler.get_today_review()` | `shanghai_today_boundaries()` 定今日窗口 | Asia/Shanghai 日历日 ✅ |
| `review_scheduler.auto_schedule_wrong_question()` | 首次复习 = `shanghai_today() + 1 天`（错题首次复习从北京时间次日开始，e3389c59） | Asia/Shanghai 日历日 ✅ |
| `review_scheduler.get_review_stats()` | `shanghai_today()` / `shanghai_date_utc_range()` | Asia/Shanghai 日历日 ✅ |
| ~~`_sync_schedule_to_wq()` fallback~~ | `utcnow().date()` | P1-3 已修复 ✅ |
| ~~`wrong_question_service.record_wrong()`~~ | `utcnow().date()` | P1-4 已修复 ✅ |
| ~~`wrong_question_service.update_quality()`~~ | 已废弃（走 RS 路径） | P0-1 已修复 ✅ |
| ~~`review_service.get_due_reviews()`~~ | RS 路径（`utcnow()`） | P1-1 已修复 ✅ |
| ~~`review_service.get_review_stats()`~~ | RS/ReviewRecord 路径（`utcnow()`） | P1-1 已修复 ✅ |

**结论**：产品日期口径全部为 Asia/Shanghai 日历日 ✅，存储统一 naive UTC；无 `date.today()` 残留。

---

## 7. 技术债清单

### P0 — 必须立即修复

| ID | 问题 | 文件 | 说明 | 状态 |
|----|------|------|------|------|
| P0-1 | **旧路径直接修改 WQ SM-2 字段** | `wrong_question_service.py` `update_quality()` | 改为通过 ReviewSchedule 执行 SM-2 计算，再同步回 WQ | ✅ 已修复 |
| P0-2 | **旧 `/review/submit` 未同步 RS** | `review_service.py` `submit_review()` | 继承 P0-1 修复，`update_quality()` 现路由到 RS | ✅ 已修复（无代码改动） |
| P0-3 | **PUT `/wrong_questions/{id}/quality` 暴露旧 SM-2 路径** | `wrong_questions.py` | 底层继承 `update_quality()` 修复，自动走 RS 路径 | ✅ 已修复（无代码改动） |

### P1 — 后续优化

| ID | 问题 | 文件 | 说明 | 状态 |
|----|------|------|------|------|
| P1-1 | **旧接口数据源未切换** | `review_service.py` | `GET /review/due`、`GET /review/stats` 切换为 ReviewSchedule 数据源 | ✅ 已修复 |
| P1-2 | **WQ.last_review_at 未同步** | `_sync_schedule_to_wq()` | 新增 `wq.last_review_at = schedule.last_reviewed_at` 同步 | ✅ 已修复 |
| P1-3 | **`_sync_schedule_to_wq()` 中 `date.today()`** | `review_scheduler.py:35` | fallback 替换为 `utcnow().date()` | ✅ 已修复 |
| P1-4 | **`record_wrong()` 中 `date.today()`** | `wrong_question_service.py:23,47` | 替换为 `utcnow().date()` | ✅ 已修复 |
| P1-5 | **`quality` 字段废弃计划** | `wrong_question.py` | WQ.quality 已随 P2-2 移除 | ✅ 已完成 |

### P2 — 已完成

| ID | 问题 | 处理 | 状态 |
|----|------|------|------|
| P2-1 | **废弃旧接口端点** | 移除 `GET /review/due`、`POST /review/submit`、`GET /review/stats` | ✅ 已移除 |
| P2-2 | **废弃 WrongQuestion SM-2 兼容字段** | 移除 efactor/interval/repetitions/next_review_date/quality；保留 mastered 状态位 | ✅ 已移除 |
| P2-3 | **统一复习视图** | 旧接口已移除，`/review/today` 为唯一复习列表端点 | ✅ 已完成 |
| P2-4 | **复习统计接口合并** | 旧接口已移除，`/review/schedule-stats` 为唯一统计端点 | ✅ 已完成 |
| P2-5 | **ReviewSchedule.subject 去冗余** | 科目缓存字段已改为 `subject_id` 外键（subjects.id，可空） | ✅ 已实施 |

---

> 本文档基于代码真实状态，不包含未实现的设计。相关代码路径：
> - 调度服务：`backend/app/services/review_scheduler.py`（submit_review / grade_batch_review / get_today_review* 等）
> - SM-2 算法：`backend/app/services/sm2_service.py`
> - 错题服务：`backend/app/services/wrong_question_service.py`
> - 时区工具：`backend/app/core/time_utils.py`（shanghai_today / shanghai_today_boundaries / shanghai_date_utc_range）
> - ORM 模型：`backend/app/models/review_scheduler.py`, `wrong_question.py`
> - API 路由：`backend/app/api/v1/review.py`, `wrong_questions.py`
