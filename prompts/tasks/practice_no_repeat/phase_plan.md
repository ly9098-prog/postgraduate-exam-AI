# 刷题系统「周期不重复 + 自适应复习 + 智能推荐」阶段规划文档

## 1. 项目目标

当前刷题页面 `pages/practice` 已包含三种刷题模式：

- 随机刷题
- 顺序刷题
- 智能推荐

本次优化目标不是简单实现“刷过的题一段时间内不出现”，而是逐步升级为：

> 基于个人刷题数据的无感知学习调度系统。

系统最终应具备以下能力：

1. 刚刷过的题不会马上重复出现。
2. 做错题可以在合理时间内再次复习。
3. 连续答对的题逐渐降低出现频率。
4. 系统自动分析知识点掌握度，不要求用户主观填写。
5. 智能推荐根据题目复习状态和知识点薄弱程度综合选题。
6. 题库不足时有合理降级策略，避免无题可刷。

------

# 2. 总体技术路线

采用分阶段开发方式，不一开始上复杂模型。

推荐路线：

```text
V0：现有取题逻辑梳理
V1：周期内不重复基础版
V2：Leitner 题目盒子
V3：知识点掌握度无感知分析
V4：智能推荐综合打分
V5：统计分析与可视化
V6：长期个性化调度优化
```

核心原则：

```text
先可用，再智能；
先规则，再优化；
先题目级，再知识点级；
先个人数据闭环，再考虑复杂模型。
```

------

# 3. 阶段总览

| 阶段 | 名称               | 主要目标                           | 开发优先级 |
| ---- | ------------------ | ---------------------------------- | ---------- |
| V0   | 现有逻辑梳理       | 明确当前取题、答题、记录流程       | 必做       |
| V1   | 周期内不重复基础版 | 最近 N 天做过的题不重复出现        | 必做       |
| V2   | Leitner 题目盒子   | 每道题根据答题表现生成下次复习时间 | 强烈建议   |
| V3   | 知识点掌握度       | 根据刷题数据自动分析薄弱知识点     | 强烈建议   |
| V4   | 智能推荐打分       | 结合题目到期、错题、知识点薄弱推荐 | 建议       |
| V5   | 学习统计面板       | 展示题目状态、知识点掌握、复习任务 | 建议       |
| V6   | 长期优化           | 个性化间隔、题目难度校准、类 FSRS  | 后期       |

------

# 4. V0 阶段：现有逻辑梳理

## 4.1 阶段目标

先不要急着改算法，先明确当前系统的数据流：

```text
用户进入 pages/practice
        ↓
选择刷题模式
        ↓
前端请求后端取题接口
        ↓
后端根据模式返回题目
        ↓
用户提交答案
        ↓
后端写入 practice_records
```

## 4.2 需要确认的模块

### 前端

重点检查：

```text
pages/practice/practice.js
pages/practice/practice.wxml
pages/practice/practice.wxss
```

需要确认：

- 三种模式的参数如何传给后端。
- 当前是否传递 `exclude_answered`。
- 是否有 `count`、`subject_id`、`knowledge_point_id` 等参数。
- 提交答案后是否刷新题目。
- 用户未提交答案时是否算作刷过。

### 后端

重点检查：

```text
api/v1/practice.py
services/practice_service.py
models/practice_record.py
models/question.py
```

需要确认：

- 取题接口在哪里。
- 随机模式如何取题。
- 顺序模式如何取题。
- 智能推荐如何取题。
- 提交答案后是否记录 `answered_at`。
- 是否已有 `practice_records` 表。

## 4.3 阶段产出

- 整理当前取题接口参数。
- 整理当前答题记录表结构。
- 确认三种模式是否共用同一个取题入口。
- 明确最小改动点。

## 4.4 验收标准

完成后应能回答：

```text
1. 当前题目是从哪里取出来的？
2. 当前刷题记录保存在哪里？
3. 当前是否能判断用户做过哪些题？
4. 当前随机、顺序、智能推荐是否能统一加过滤条件？
```

------

# 5. V1 阶段：周期内不重复基础版

## 5.1 阶段目标

实现最基础的功能：

> 用户最近 N 天做过的题，不再出现在刷题列表中。

例如：

```text
no_repeat_days = 30
```

表示 30 天内刷过的题不重复出现。

## 5.2 功能范围

本阶段只做“周期过滤”，不做复杂复习算法。

支持模式：

- 随机刷题
- 顺序刷题
- 智能推荐中的普通补题逻辑

## 5.3 前端改造

在 `pages/practice/practice.js` 的取题参数中增加：

```js
exclude_answered: true,
no_repeat_days: 30
```

示例：

```js
const params = {
  subject_id: subjectId,
  include_children: true,
  count: this.data.count || 5,
  mode: this.data.selectedMode || 'random',
  exclude_answered: true,
  no_repeat_days: 30,
  _traceId: this.data.traceId,
}
```

## 5.4 后端接口改造

取题接口新增参数：

```python
exclude_answered: bool = Query(False)
no_repeat_days: int | None = Query(None, ge=1, le=365)
```

## 5.5 后端过滤逻辑

如果传入 `exclude_answered = true` 且 `no_repeat_days = 30`，则排除：

```text
当前用户在最近 30 天内提交过答案的题目
```

伪代码：

```python
answered_sub = (
    select(PracticeRecord.question_id)
    .where(PracticeRecord.user_id == user_id)
)

if no_repeat_days:
    cutoff = now - timedelta(days=no_repeat_days)
    answered_sub = answered_sub.where(PracticeRecord.answered_at >= cutoff)

answered_sub = answered_sub.distinct()

conditions.append(Question.id.notin_(answered_sub))
```

## 5.6 数据库优化

建议增加索引：

```sql
CREATE INDEX IF NOT EXISTS idx_practice_records_user_answered_question
ON practice_records (user_id, answered_at DESC, question_id);
```

## 5.7 降级策略

如果过滤后题目不足，不能直接返回空。

建议：

```text
第一层：最近 N 天未做过的题
第二层：从未做过的题
第三层：最久没有做过的题
第四层：允许少量重复，但优先间隔最久的题
```

## 5.8 阶段验收标准

### 随机刷题

```text
最近 30 天做过的题，不会再次随机出现。
```

### 顺序刷题

```text
按题目顺序取题，但跳过最近 30 天做过的题。
```

### 智能推荐

```text
智能推荐补题时，也尽量不返回最近 30 天做过的题。
```

------

# 6. V2 阶段：Leitner 题目盒子

## 6.1 阶段目标

把“统一 30 天不重复”升级为：

> 每道题根据个人答题表现，拥有自己的复习间隔。

核心字段：

```text
box_level
next_review_at
```

## 6.2 为什么要做 Leitner

固定周期的问题：

```text
答错题 30 天不出现，太晚；
熟练题 7 天后又出现，太浪费；
所有题统一周期，不符合真实学习。
```

Leitner 的优势：

```text
答错题快速复现；
答对题逐渐拉长间隔；
数据少也能用；
不需要机器学习；
容易调试。
```

## 6.3 新增表：user_question_state

建议新增用户题目状态表：

```sql
CREATE TABLE user_question_state (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    question_id BIGINT NOT NULL,

    box_level INT DEFAULT 0,

    last_answered_at TIMESTAMP,
    next_review_at TIMESTAMP,

    correct_streak INT DEFAULT 0,
    wrong_streak INT DEFAULT 0,

    answer_count INT DEFAULT 0,
    correct_count INT DEFAULT 0,
    wrong_count INT DEFAULT 0,

    last_is_correct BOOLEAN,
    last_answer_time_seconds INT,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id, question_id)
);
```

## 6.4 Leitner 盒子设计

| box_level | 状态            | 下次复习间隔 |
| --------- | --------------- | ------------ |
| 0         | 很不熟 / 刚做错 | 1 天         |
| 1         | 初步接触        | 3 天         |
| 2         | 有点熟          | 7 天         |
| 3         | 较熟            | 14 天        |
| 4         | 熟练            | 30 天        |
| 5         | 稳定掌握        | 60 天        |

## 6.5 答题后更新规则

### 答对

```python
box_level = min(box_level + 1, 5)
correct_streak += 1
wrong_streak = 0
```

### 答错

```python
box_level = max(box_level - 2, 0)
correct_streak = 0
wrong_streak += 1
```

### 复习时间

```python
interval_map = {
    0: 1,
    1: 3,
    2: 7,
    3: 14,
    4: 30,
    5: 60,
}

next_review_at = now + timedelta(days=interval_map[box_level])
```

## 6.6 耗时修正

如果答对但耗时过长，不应该升级太快。

示例：

```python
if is_correct and answer_time_seconds > expected_time_seconds * 1.5:
    box_level = max(box_level - 1, 0)
```

或者：

```python
if is_correct and answer_time_seconds > expected_time_seconds * 1.5:
    next_review_at = now + timedelta(days=max(2, interval_days * 0.6))
```

## 6.7 取题规则

刷题时只取：

```text
从未做过的题
+
next_review_at <= 当前时间的题
```

SQL 逻辑：

```sql
WHERE user_question_state.next_review_at IS NULL
   OR user_question_state.next_review_at <= NOW()
```

## 6.8 阶段验收标准

完成后应满足：

```text
1. 答错题第二天或较短时间后再次出现。
2. 连续答对题出现频率逐渐降低。
3. 每道题都有自己的 next_review_at。
4. 刷题页面不会出现刚刷完又立刻刷到同一道题的问题。
```

------

# 7. V3 阶段：知识点掌握度无感知分析

## 7.1 阶段目标

让系统自动判断用户在哪些知识点上薄弱。

不要求用户填写：

```text
我掌握了
我没掌握
我觉得这个知识点一般
```

而是完全通过刷题数据分析。

## 7.2 核心思想

Leitner 管的是：

```text
这道题什么时候再出现
```

知识点掌握度管的是：

```text
接下来应该多练哪个知识点
```

二者结合：

```text
题目级：控制复习周期
知识点级：控制练习方向
```

## 7.3 新增表：user_knowledge_state

```sql
CREATE TABLE user_knowledge_state (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    knowledge_point_id BIGINT NOT NULL,

    mastery_score FLOAT DEFAULT 50,
    confidence FLOAT DEFAULT 0,

    answer_count INT DEFAULT 0,
    correct_count INT DEFAULT 0,
    wrong_count INT DEFAULT 0,

    recent_answer_count INT DEFAULT 0,
    recent_correct_count INT DEFAULT 0,
    recent_wrong_count INT DEFAULT 0,

    last_practiced_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id, knowledge_point_id)
);
```

## 7.4 掌握度分数设计

`mastery_score` 范围：

```text
0 到 100
```

初始值：

```text
50
```

含义：

```text
50 代表未知状态，不代表会，也不代表不会。
```

## 7.5 掌握度更新规则

### 基础规则

```python
if is_correct:
    delta = 6
else:
    delta = -12
```

答错扣更多，是因为错题更能暴露薄弱点。

### 耗时修正

```python
if is_correct and answer_time_seconds > expected_time_seconds * 1.5:
    delta *= 0.4
```

表示：

```text
虽然答对，但耗时过长，说明不熟，掌握度少涨。
```

### 难度修正

如果题目有难度字段：

```python
if is_correct and difficulty == "hard":
    delta += 3

if not is_correct and difficulty == "easy":
    delta -= 4
```

### 多次错误修正

```python
if not is_correct and recent_wrong_count >= 2:
    delta -= 3
```

### 最终更新

```python
mastery_score = max(0, min(100, mastery_score + delta))
```

## 7.6 置信度设计

小数据情况下，不能只看掌握度，还要看置信度。

```python
confidence = min(1.0, answer_count / 10)
```

含义：

| answer_count | confidence |
| ------------ | ---------- |
| 0            | 0          |
| 1            | 0.1        |
| 3            | 0.3        |
| 5            | 0.5        |
| 10           | 1.0        |

## 7.7 知识点状态划分

| mastery_score | 状态 |
| ------------- | ---- |
| 0 - 40        | 薄弱 |
| 40 - 70       | 一般 |
| 70 - 85       | 较熟 |
| 85 - 100      | 掌握 |

结合置信度后：

```text
低分 + 高置信 = 明确薄弱
低分 + 低置信 = 需要继续观察
高分 + 高置信 = 基本掌握
高分 + 低置信 = 暂不确定
```

## 7.8 阶段验收标准

完成后系统应能做到：

```text
1. 用户不用手动填写掌握度。
2. 每个知识点都有 mastery_score。
3. 每个知识点都有 confidence。
4. 智能推荐可以优先选择薄弱知识点。
5. 系统能区分“真的薄弱”和“数据太少暂不确定”。
```

------

# 8. V4 阶段：智能推荐综合打分

## 8.1 阶段目标

将智能推荐从简单推荐升级为综合推荐：

```text
题目是否到期
+
知识点是否薄弱
+
是否错过
+
是否新题
+
是否长期未练
```

## 8.2 推荐候选池

候选题来源：

```text
1. 从未做过的新题
2. 已到 next_review_at 的复习题
3. 薄弱知识点下的新题
4. 薄弱知识点下的错题
5. 题库不足时，最久未做的旧题
```

## 8.3 推荐分设计

示例：

```python
score = 0

score += due_score
score += weakness_score
score += wrong_history_score
score += new_question_score
score += overdue_score
score += diversity_score
```

## 8.4 各项分数建议

### due_score：复习到期分

```python
if next_review_at and next_review_at <= now:
    score += 40
```

如果逾期很久：

```python
overdue_days = (now - next_review_at).days
score += min(overdue_days * 2, 20)
```

### weakness_score：知识点薄弱分

```python
weakness_score = (100 - mastery_score) * confidence * 0.4
score += weakness_score
```

### wrong_history_score：错题历史分

```python
score += min(wrong_count * 8, 30)
```

### new_question_score：新题分

```python
if never_answered:
    score += 20
```

### diversity_score：多样性分

避免连续推荐同一个知识点：

```python
if knowledge_point_id not in recent_practiced_kp_ids:
    score += 10
```

## 8.5 智能推荐优先级

推荐顺序：

```text
第一优先级：薄弱知识点下的到期错题
第二优先级：薄弱知识点下的新题
第三优先级：普通知识点下的到期题
第四优先级：普通知识点下的新题
第五优先级：最久未做的旧题
```

## 8.6 三种刷题模式的最终设计

### 随机刷题

```text
从可练习题池中随机抽题。
可练习题池 = 新题 + 到期复习题。
```

可以加入轻微权重：

```text
70% 新题 / 到期题
30% 薄弱知识点题
```

### 顺序刷题

```text
按题目 ID 顺序取题，但跳过未到复习时间的题。
```

如果题库不足：

```text
释放最久未做的题。
```

### 智能推荐

```text
根据综合推荐分排序。
优先照顾薄弱知识点和到期错题。
```

## 8.7 阶段验收标准

完成后应满足：

```text
1. 智能推荐不再只是随机补题。
2. 错题会被合理复现。
3. 薄弱知识点会被更多覆盖。
4. 已掌握题出现频率明显下降。
5. 题库不足时仍有题可刷。
```

------

# 9. V5 阶段：统计分析与可视化

## 9.1 阶段目标

让用户能看到自己的学习状态。

可视化不是第一优先级，但长期使用很重要。

## 9.2 建议页面

可以新增：

```text
pages/study-dashboard
pages/knowledge-report
pages/wrong-questions
pages/review-plan
```

## 9.3 统计内容

### 题目统计

展示：

```text
总做题数
正确题数
错误题数
正确率
今日刷题数
本周刷题数
待复习题数
```

### Leitner 盒子统计

展示：

| 盒子  | 状态     | 数量 |
| ----- | -------- | ---- |
| box 0 | 很不熟   | n    |
| box 1 | 初步接触 | n    |
| box 2 | 有点熟   | n    |
| box 3 | 较熟     | n    |
| box 4 | 熟练     | n    |
| box 5 | 稳定掌握 | n    |

### 知识点掌握度

展示：

```text
薄弱知识点
一般知识点
较熟知识点
已掌握知识点
```

### 今日复习计划

展示：

```text
今天到期复习题数量
今天建议练习知识点
今天建议新题数量
今天建议错题数量
```

## 9.4 阶段验收标准

完成后用户应能看到：

```text
1. 今天该复习多少题。
2. 哪些知识点最薄弱。
3. 哪些题反复做错。
4. 哪些题已经长期掌握。
5. 自己近期学习趋势是否变好。
```

------

# 10. V6 阶段：长期个性化优化

## 10.1 阶段目标

当个人数据积累足够多以后，再进行更细致的个性化优化。

此阶段不是前期必须做。

## 10.2 可优化方向

### 1. 个人遗忘速度

不同用户遗忘速度不同。

后期可以根据历史数据调整间隔：

```text
某类题经常到期后答错 → 缩短间隔
某类题到期后仍稳定答对 → 拉长间隔
```

### 2. 题目难度自动校准

如果没有人工难度标签，可以根据个人表现动态判断：

```text
经常错 + 耗时长 = 对该用户较难
经常对 + 耗时短 = 对该用户较简单
```

### 3. 知识点关联推荐

如果题目有知识点树，可以做：

```text
前置知识点薄弱 → 暂缓推荐高级知识点
基础知识点掌握 → 推进到关联知识点
```

### 4. 类 FSRS 调度

后期数据多后，可以从 Leitner 升级到更个性化的间隔调度。

但不建议前期直接做。

## 10.3 阶段验收标准

完成后系统应具备：

```text
1. 能根据个人遗忘情况自动调整间隔。
2. 能识别个人维度的题目难度。
3. 能根据知识点关系推荐学习路径。
4. 智能推荐更加个性化。
```

------

# 11. 推荐开发顺序

建议严格按照以下顺序开发：

```text
第一步：V1 周期内不重复
第二步：V2 Leitner 题目盒子
第三步：V3 知识点掌握度
第四步：V4 智能推荐综合打分
第五步：V5 统计分析页面
第六步：V6 个性化优化
```

不要一开始就开发 V4 或 V6。

原因：

```text
没有 V2，智能推荐不知道题目是否该复习；
没有 V3，智能推荐不知道哪个知识点薄弱；
没有足够数据，复杂模型效果不稳定。
```

------

# 12. 最小可用版本建议

如果想尽快上线，建议先做 MVP：

## MVP 功能

```text
1. 最近 N 天不重复
2. user_question_state 表
3. box_level
4. next_review_at
5. 答对升级盒子
6. 答错降级盒子
7. 取题时过滤未到期题
```

## MVP 暂不做

```text
1. 复杂智能推荐
2. 知识点置信度
3. 可视化统计页面
4. 题目难度自动校准
5. FSRS
6. 机器学习模型
```

------

# 13. 数据表最终建议

长期建议至少保留三类表：

## 13.1 原始答题记录表

用于记录每一次答题历史。

```text
practice_records
```

作用：

```text
保留原始行为数据，不要被覆盖。
```

## 13.2 用户题目状态表

用于快速判断某道题什么时候再出现。

```text
user_question_state
```

作用：

```text
支持 Leitner 盒子和 next_review_at。
```

## 13.3 用户知识点状态表

用于分析知识点掌握度。

```text
user_knowledge_state
```

作用：

```text
支持智能推荐和学习报告。
```

------

# 14. 核心业务规则总结

## 14.1 提交答案时

每次提交答案后，系统同时做三件事：

```text
1. 写入 practice_records
2. 更新 user_question_state
3. 更新 user_knowledge_state
```

## 14.2 取题时

系统根据模式取题：

```text
随机刷题：从可练习题池中随机
顺序刷题：从可练习题池中按顺序
智能推荐：从可练习题池中按推荐分排序
```

## 14.3 可练习题池

```text
从未做过的题
+
next_review_at 已到期的题
+
题库不足时释放最久未做的题
```

## 14.4 不推荐出现的题

```text
刚刷过的题
next_review_at 未到期的题
已稳定掌握且没有复习必要的题
```

------

# 15. 风险点与注意事项

## 15.1 题库数量不足

如果题库太小，严格过滤会导致无题可刷。

解决：

```text
允许 fallback：
1. 先取到期题
2. 再取新题
3. 再取快到期题
4. 最后取最久未做题
```

## 15.2 用户未提交答案

如果用户只是打开题目但未提交，不应算作已刷。

建议：

```text
只有提交答案后才写入 practice_records。
```

## 15.3 答对不等于掌握

答对可能是蒙对，也可能耗时很长。

解决：

```text
结合耗时、连续正确次数、题目难度修正掌握度。
```

## 15.4 做题次数少时不要过度判断

一个知识点只做 1 道题，不能直接判断掌握或薄弱。

解决：

```text
引入 confidence 置信度。
```

## 15.5 智能推荐不要过度集中

如果一直推荐同一知识点，用户体验会差。

解决：

```text
加入 diversity_score，控制知识点多样性。
```

------

# 16. 最终推荐方案

长期来看，最适合当前项目的方案是：

```text
Leitner 题目盒子
+
知识点掌握度无感知分析
+
next_review_at 复习调度
+
智能推荐综合打分
```

其中：

```text
Leitner 负责：这道题什么时候再出现
知识点掌握度负责：接下来应该多练哪个方向
智能推荐负责：在可练习题池中选择最合适的题
```

最终系统不需要用户手动填写掌握度，而是通过刷题数据自动分析。

这是个人刷题、小数据场景下最稳、最容易开发、最适合长期使用的方案。