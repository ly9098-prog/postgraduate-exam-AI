# SM-2 复习调度系统设计

> 基于代码真实状态的架构设计文档。描述当前系统边界、数据职责、同步策略与技术债。
> 最后更新：2026-06-26（P0、P1 已修复）

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
│                  API 层 (review.py)                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ 旧接口   │  │ 新接口   │  │ 错题本接口         │  │
│  │ /due     │  │ /today   │  │ /wrong_questions   │  │
│  │ /submit  │  │ /schedule│  │ /{id}/quality      │  │
│  │ /stats   │  │ -submit  │  │ (旧 SM-2 评分)     │  │
│  │          │  │ /grade-  │  │                    │  │
│  │          │  │ submit   │  │                    │  │
│  │          │  │ /grade-  │  │                    │  │
│  │          │  │ batch    │  │                    │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
└───────┼──────────────┼─────────────────┼────────────┘
        │              │                 │
        ▼              ▼                 ▼
┌─────────────────────────────────────────────────────┐
│                Service 层                            │
│                                                      │
│  ┌──────────────────┐   ┌────────────────────────┐  │
│  │ review_service   │   │ review_scheduler       │  │
│  │ (旧: WQ 直操作)  │   │ (新: RS 主调度)        │  │
│  │                  │   │                        │  │
│  │ get_due_reviews() │   │ get_today_review()    │  │
│  │ submit_review()  │   │ submit_review()        │  │
│  │ get_review_stats()│  │ batch_submit_review()  │  │
│  └────────┬─────────┘   │ get_review_stats()     │  │
│           │             │ get_review_history()   │  │
│           │             │ auto_schedule_wq()     │  │
│           │             │ mark/unmark_mastered()  │  │
│           │             └───────────┬────────────┘  │
│           │                         │               │
│           ▼                         ▼               │
│  ┌──────────────────────────────────────────┐       │
│  │          SM-2 Engine (唯一计算来源)       │       │
│  │          calc_sm2(quality, efactor,       │       │
│  │          interval, repetitions, date)     │       │
│  └──────────────────────────────────────────┘       │
│                                                      │
│  ┌──────────────────────────────┐                   │
│  │ wrong_question_service       │                   │
│  │ (错题 CRUD + 历史 SM-2 路径) │                   │
│  │ record_wrong()               │                   │
│  │ update_quality() ← 遗留风险   │                   │
│  └──────────────────────────────┘                   │
└─────────────────────────────────────────────────────┘
        │              │
        ▼              ▼
┌─────────────────────────────────────────────────────┐
│               数据层 (ORM Model)                     │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │         ReviewSchedule (主系统)               │   │
│  │  id | user_id | question_id | subject         │   │
│  │  interval | ease_factor | repetitions         │   │
│  │  next_review_at | last_reviewed_at            │   │
│  │  mastered                                     │   │
│  │  created_at | updated_at                      │   │
│  └────────────────────┬─────────────────────────┘   │
│                       │ 单向同步                      │
│                       ▼                              │
│  ┌──────────────────────────────────────────────┐   │
│  │         WrongQuestion (历史兼容层)             │   │
│  │  id | user_id | question_id                   │   │
│  │  wrong_answer | error_type | ai_analysis      │   │
│  │  review_count | last_review_at                │   │
│  │  ═══════════════════════════════════════════  │   │
│  │  efactor ← RS.ease_factor (兼容字段)          │   │
│  │  interval ← RS.interval (兼容字段)            │   │
│  │  repetitions ← RS.repetitions (兼容字段)      │   │
│  │  next_review_date ← RS.next_review_at.date()  │   │
│  │  mastered ← RS.mastered (兼容字段)            │   │
│  │  quality (独立字段，旧路径使用)                │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │         ReviewRecord (历史记录层)              │   │
│  │  id | user_id | question_id | schedule_id     │   │
│  │  rating | interval_before | interval_after    │   │
│  │  ease_factor_before | ease_factor_after       │   │
│  │  reviewed_at                                  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 层级角色

| 层 | 角色 | 职责 |
|----|------|------|
| **ReviewSchedule** | 主系统 | 所有复习调度状态（interval / ease_factor / repetitions / next_review_at / mastered）的唯一主数据源 |
| **SM-2 Engine** | 唯一计算来源 | `calc_sm2()` 是系统中唯一的 SM-2 算法实现，所有路径共享同一个函数 |
| **WrongQuestion** | 历史兼容层 | 错题分析、AI 分析缓存、review_count 统计；SM-2 字段为同步副本，不参与调度决策 |
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
subject         str?          科目缓存（冗余，来自 Question；避免高频 join）
interval        int           当前复习间隔（天），SM-2 计算结果
ease_factor     float         难度因子（E-Factor），SM-2 计算结果，下限 1.3
repetitions     int           连续正确次数，SM-2 计算结果
next_review_at  datetime?     下次复习时间（UTC naive datetime）
last_reviewed_at datetime?    最近一次复习时间
mastered        bool          是否标记为已掌握
created_at      datetime      创建时间
updated_at      datetime      最后更新时间
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
review_count    int           总复习次数（含旧路径）
last_review_at  datetime?     最近一次复习时间
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
efactor         float         ← 兼容：ReviewSchedule.ease_factor
interval        int           ← 兼容：ReviewSchedule.interval
repetitions     int           ← 兼容：ReviewSchedule.repetitions
next_review_date date?        ← 兼容：ReviewSchedule.next_review_at.date()
mastered        bool          ← 兼容：ReviewSchedule.mastered
quality         int?          （独立字段，旧路径 `update_quality()` 写入）
```

### 职责分离原则

- **SM-2 参数**（interval / efactor / repetitions）→ 调度核心，仅由 ReviewSchedule 持有权威值
- **错题分析**（wrong_answer / error_type / ai_analysis）→ 错题分析，仅由 WrongQuestion 持有
- **复习历史**（rating / interval_before/after / ease_factor_before/after）→ 历史审计，仅由 ReviewRecord 持有
- **复习计数** → ReviewSchedule 无此字段，WrongQuestion.review_count 独立统计（含新旧路径）

---

## 3. 单向同步原则

### 同步策略

```
ReviewSchedule 更新
       │
       ▼
_sync_schedule_to_wq(db, schedule)
       │
       ├─ wq.efactor          = schedule.ease_factor
       ├─ wq.interval         = schedule.interval
       ├─ wq.repetitions      = schedule.repetitions
       ├─ wq.next_review_date = schedule.next_review_at.date()
       ├─ wq.mastered         = schedule.mastered
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
- **绝不直接修改 WrongQuestion SM-2 字段**：业务代码不应直接赋值 `wq.efactor` 等字段，应通过 ReviewSchedule 修改后由 `_sync_schedule_to_wq()` 回写
- **同步是最终一致性的**：短窗口内（同一请求处理过程中）可能存在 RS 已更新但 WQ 未同步的状态，但在请求结束（`db.commit()`）后应一致

### 例外：`record_wrong()` 中的初始化

`wrong_question_service.record_wrong()` 在创建新 `WrongQuestion` 记录时会初始化 SM-2 字段（efactor=2.5, interval=1, repetitions=0, next_review_date=today+1）。这是合理的——此时 ReviewSchedule 尚未创建，`auto_schedule_wrong_question()` 随后会覆盖这些值。

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

当用户未提供自评 rating 时（`/review/grade-submit` 和 `/review/grade-batch`）：

```
答对 (correct) → rating=4（正确但稍有犹豫）
答错 (wrong)  → rating=1（错误但能回想）
```

故意不使用极端值 5/0，避免 SM-2 评分过于激进。

### 时区策略

- **内部存储**：统一使用 naive UTC datetime（`utcnow()` 返回 `datetime.now(timezone.utc).replace(tzinfo=None)`）
- **日期提取**：统一使用 `utcnow().date()`，不使用 `date.today()`
- **计算输入**：`calc_sm2()` 的 `review_date` 参数由调用方传入 UTC date

---

## 5. 双接口体系说明

### 当前状态

```
┌────────────────────────────────────────────────────┐
│                  双接口并存                          │
│                                                     │
│  旧接口（WrongQuestion 基座）  新接口（RS 基座）    │
│  ───────────────────────────  ───────────────────  │
│  GET  /review/due             GET  /review/today    │
│  POST /review/submit          POST /review/schedule-│
│  GET  /review/stats             submit              │
│  PUT  /wrong_q/{id}/quality   POST /review/batch-   │
│                                  submit             │
│                                POST /review/grade-  │
│                                  submit              │
│                                POST /review/grade-  │
│                                  batch               │
│                                GET  /review/schedule-│
│                                  stats               │
│                                GET  /review/history  │
│                                POST /review/{id}/   │
│                                  master/unmaster     │
└────────────────────────────────────────────────────┘
```

### 共存原因

1. **渐进迁移**：新接口（Stage 12）开发时，旧接口（早期 Stage）已被小程序使用，无法一次性切换
2. **功能差异**：旧接口返回 `wrong_answer`/`error_type`/`answer` 等分析字段；新接口设计为纯复习用途，不暴露答案
3. **统计维度不同**：旧 `/review/stats` 基于 WQ 的 `total_wrong`/`due_today`/`reviewed_today`；新 `/review/schedule-stats` 基于 RS 的 `total_scheduled`/`remaining_today`/`accuracy_last_7d`

### 已知风险

| 风险 | 影响 |
|------|------|
| 旧路径 `update_quality()` 在 WQ 上独立执行 SM-2 计算 | RS 与 WQ 的 SM-2 参数在此路径下不会同步，产生数据不一致 |
| 旧路径使用 `date.today()`（本地时区） | 新路径使用 `utcnow().date()`，时区偏移可能导致同一天判定不一致 |
| WQ.quality 字段仅由旧路径写入 | 新路径不写入此字段，前端若展示 `quality` 可能看到过时值 |
| 小程序未直接调用旧接口 | `grep` 确认 miniprogram 未引用旧端点，风险主要来自 API 直接调用或第三方集成 |

### 迁移计划

> **P1（后续优化）**：旧接口切换为 RS 数据源
> **P2（长期重构）**：废弃旧接口，前端统一切换到新接口

---

## 6. 系统一致性审计

### 审计方法

基于 2026-06-26 代码快照，逐条检查以下风险点。**只分析，不改代码。**

### 6.1 ReviewSchedule → WrongQuestion 未同步字段

| RS 字段 | 是否有 WQ 对应 | 是否被同步 | 风险 |
|---------|---------------|-----------|------|
| id | 无对应 | N/A | 无风险（各自独立） |
| user_id | user_id | 否（但两表同值） | **低**：创建时相同，不会偏 |
| question_id | question_id | 否（但两表同值） | **低**：创建时相同，不会偏 |
| subject | 无对应 | N/A | **无**：WQ 无此字段，无需同步 |
| interval | interval | 是 | 无风险 |
| ease_factor | efactor | 是 | 无风险 |
| repetitions | repetitions | 是 | 无风险 |
| next_review_at | next_review_date | 是（`date()` 截断） | **低**：datetime→date 精度损失不影响日级别调度 |
| last_reviewed_at | last_review_at | **否** | **中**：新路径提交后 WQ.last_review_at 可能过时 |
| mastered | mastered | 是 | 无风险 |

**结论**：`last_reviewed_at` 未同步，但影响有限（WQ.last_review_at 主要用于旧 `/review/stats` 的 `reviewed_today` 计数）。

### 6.2 WrongQuestion 被用于计算 SM-2 的路径

**确认存在**：`wrong_question_service.update_quality()` (wrong_question_service.py:158-187)

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
| `review_scheduler.submit_review()` | `utcnow().date()` | UTC ✅ |
| `review_scheduler.get_today_review()` | `utcnow()` | UTC ✅ |
| `review_scheduler.auto_schedule_wq()` | `utcnow()` | UTC ✅ |
| `review_scheduler.get_review_stats()` | `utcnow()` | UTC ✅ |
| ~~`_sync_schedule_to_wq()` fallback~~ | `utcnow().date()` | P1-3 已修复 ✅ |
| ~~`wrong_question_service.record_wrong()`~~ | `utcnow().date()` | P1-4 已修复 ✅ |
| ~~`wrong_question_service.update_quality()`~~ | 已废弃（走 RS 路径） | P0-1 已修复 ✅ |
| ~~`review_service.get_due_reviews()`~~ | RS 路径（`utcnow()`） | P1-1 已修复 ✅ |
| ~~`review_service.get_review_stats()`~~ | RS/ReviewRecord 路径（`utcnow()`） | P1-1 已修复 ✅ |

**结论**：全部路径已统一为 UTC ✅。无 `date.today()` 残留。

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
| P1-5 | **`quality` 字段废弃计划** | `wrong_question.py` | WQ.quality 仅由旧路径写入；待 P2 废弃 | 📋 待处理 |

### P2 — 长期重构

| ID | 问题 | 说明 |
|----|------|------|
| P2-1 | **废弃旧接口端点** | 前端全量切换到新接口后，移除 `GET /review/due`、`POST /review/submit`、`GET /review/stats`。 |
| P2-2 | **废弃 WrongQuestion SM-2 兼容字段** | 前端无依赖后，移除 WQ 的 efactor/interval/repetitions/next_review_date/mastered 字段，仅保留错题分析字段。 |
| P2-3 | **统一复习视图** | 将 `/review/today` 与 `/review/due` 合并为单一复习列表端点，消除双接口的数据源歧义。 |
| P2-4 | **复习统计接口合并** | `/review/stats` 和 `/review/schedule-stats` 合并为统一统计端点，前端按需选择维度。 |
| P2-5 | **ReviewSchedule.subject 去冗余** | subject 在 ReviewSchedule 中冗余存储（来自 Question.subject），可通过 join 消除。当前为性能优化（避免高频 join），长期可评估是否需要。 |

---

> 本文档基于代码真实状态，不包含未实现的设计。相关代码路径：
> - 调度服务：`backend/app/services/review_scheduler.py`
> - SM-2 算法：`backend/app/services/sm2_service.py`
> - 旧接口服务：`backend/app/services/review_service.py`
> - 错题服务：`backend/app/services/wrong_question_service.py`
> - ORM 模型：`backend/app/models/review_scheduler.py`, `wrong_question.py`
> - API 路由：`backend/app/api/v1/review.py`, `wrong_questions.py`
