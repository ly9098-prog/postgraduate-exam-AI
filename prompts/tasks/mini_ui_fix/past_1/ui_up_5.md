你是一个微信小程序 + FastAPI 全栈工程师。请将当前 `pages/review-today` 页面从“刷题式选择复习题数”改造成“不背单词式今日复习任务流”。

核心目标：用户进入 review-today 后，不再选择“今天复习几道题”，而是由系统根据记忆曲线 / 复习计划自动计算“今日应复习 X 道题”。用户只需要点击“开始复习”或“继续复习”，按系统分组完成今日复习任务。

------

# 一、当前问题

当前 `review-today` 更像刷题页：

- 用户需要选择复习题数。
- 页面逻辑类似“我要刷几道题”。
- 今日复习任务感不强。
- 没有明确告诉用户“今天系统安排你应该复习几道题”。
- review 逻辑没有形成“今日任务池 → 分组复习 → 组结果 → 继续下一组 → 今日完成”的闭环。
- 这不符合类似不背单词的 Review 心智：系统告诉用户今天该复习多少，用户按计划完成即可。

------

# 二、目标交互逻辑

参考“不背单词式”Review 体验，但不要照抄 UI。要借鉴其任务流：

## 新 review-today 逻辑

用户进入页面后：

1. 系统自动请求今日复习任务概览。
2. 页面显示：
   - 今日待复习 X 道
   - 已完成 Y 道
   - 剩余 Z 道
   - 逾期复习 A 道，如有
   - 预计用时
3. 用户点击“开始复习”或“继续复习”。
4. 系统自动取今日到期题中的下一组，例如每组 10 道或 20 道。
5. 用户完成一组后进入组结果页。
6. 点击“继续下一组”继续从剩余今日待复习题中取下一组。
7. 全部完成后进入最终结果页，显示“今日复习完成”。

用户不再看到“选择复习几道题”的入口。

------

# 三、前端重点文件

主要修改：

- `pages/review-today/review-today.js`
- `pages/review-today/review-today.wxml`
- `pages/review-today/review-today.wxss`
- `components/quiz-runner/quiz-runner.*`，仅在必要时改
- `utils/api.js` 或现有 API 封装文件

后端相关：

- `app/api/v1/review.py`
- `app/services/review_scheduler.py`
- `app/schemas/review_scheduler.py`
- 相关 model，例如 wrong question / review schedule / review record

------

# 四、前端页面状态重构

## 1. review-today 阶段状态

请将当前 review-today 的 phase 明确整理为：

```js
phase: 'loading' 
  | 'overview' 
  | 'reviewing' 
  | 'group-result' 
  | 'final-result'
  | 'empty'
  | 'error'
```

含义：

- `loading`：正在加载今日复习概览。
- `overview`：展示今日复习任务首页。
- `reviewing`：正在复习当前组。
- `group-result`：当前组完成后的结果页。
- `final-result`：今日所有待复习题完成后的最终结果页。
- `empty`：今天没有待复习题。
- `error`：加载失败。

------

## 2. review-today data 新增字段

请在 `review-today.js` 的 data 中增加或规范以下字段：

```js
reviewOverview: null,

todayDueCount: 0,
todayCompletedCount: 0,
todayRemainingCount: 0,
todayOverdueCount: 0,
todayNewDueCount: 0,

estimatedMinutes: 0,
reviewBatchSize: 10,

currentBatchNo: 0,
totalBatchCount: 0,

sessionId: '',
currentGroupId: '',
currentGroupQuestions: [],

allTodayQuestionIds: [],
completedQuestionIds: [],
remainingQuestionIds: [],

todayProgressPercent: 0,

isContinuing: false,
isStarting: false,
overviewLoading: false,
batchLoading: false,
```

说明：

- `todayDueCount`：今天系统安排需要复习的总题数。
- `todayCompletedCount`：今天已经完成复习的题数。
- `todayRemainingCount`：今天还剩多少题。
- `todayOverdueCount`：今天待复习中已经逾期的题。
- `reviewBatchSize`：每组复习题数，来自后端用户设置或默认值，不由用户在入口页选择。
- `allTodayQuestionIds`：今日任务池题目 ID。
- `remainingQuestionIds`：当前还未复习的今日任务题目 ID。
- `todayProgressPercent`：今日复习完成进度。

------

# 五、前端 overview 页面改造

## 1. 移除“选择复习题数”

请删除或隐藏所有类似功能：

- 选择复习数量
- 选择 5 / 10 / 20 道
- 手动输入复习题数
- “开始刷题”
- 与临时题量选择相关的卡片、按钮、样式、字段

注意：可以保留“每组复习数量”的概念，但它应该是设置项或后端配置，不应该是用户每次进入 review-today 时必须选择的东西。

------

## 2. overview 页面新结构

`phase === 'overview'` 时，页面应展示今日复习任务首页。

建议 WXML 结构：

```xml
<view wx:if="{{phase === 'overview'}}" class="review-overview page-blue-white">
  <view class="today-review-card">
    <view class="today-review-main">
      <text class="today-review-label">今日待复习</text>
      <view class="today-review-count-row">
        <text class="today-review-count">{{todayRemainingCount}}</text>
        <text class="today-review-unit">道</text>
      </view>
      <text class="today-review-sub">
        共 {{todayDueCount}} 道，已完成 {{todayCompletedCount}} 道
      </text>
    </view>

    <view class="today-progress-box">
      <view class="today-progress-track">
        <view 
          class="today-progress-fill" 
          style="width: {{todayProgressPercent}}%;"
        ></view>
      </view>
      <text class="today-progress-text">{{todayProgressPercent}}%</text>
    </view>
  </view>

  <view class="review-stat-grid">
    <view class="review-stat-item">
      <text class="review-stat-value">{{todayOverdueCount}}</text>
      <text class="review-stat-label">逾期复习</text>
    </view>
    <view class="review-stat-item">
      <text class="review-stat-value">{{estimatedMinutes}}</text>
      <text class="review-stat-label">预计分钟</text>
    </view>
    <view class="review-stat-item">
      <text class="review-stat-value">{{reviewBatchSize}}</text>
      <text class="review-stat-label">每组题数</text>
    </view>
  </view>

  <view class="review-plan-card">
    <text class="review-plan-title">今日复习安排</text>
    <text class="review-plan-desc">
      系统已根据记忆曲线为你安排今日复习内容，完成后会自动更新下次复习时间。
    </text>
  </view>

  <button 
    class="primary-review-btn"
    loading="{{isStarting || isContinuing}}"
    disabled="{{todayRemainingCount <= 0 || isStarting || isContinuing}}"
    bindtap="startTodayReview"
  >
    {{todayCompletedCount > 0 ? '继续复习' : '开始复习'}}
  </button>
</view>
```

视觉要求：

- 蓝白主风格。
- 不要大 hero。
- 首页重点突出“今日待复习 X 道”。
- 不要像刷题页。
- 不要展示题量选择器。
- 页面信息密度适中。

------

## 3. empty 状态

如果 `todayRemainingCount === 0` 且 `todayDueCount === 0`：

```xml
<view wx:if="{{phase === 'empty'}}" class="review-empty">
  <text class="empty-title">今天没有待复习题</text>
  <text class="empty-desc">记忆曲线暂时没有安排新的复习任务，可以去练习新题或查看错题本。</text>
  <button bindtap="goPractice">去练习</button>
  <button bindtap="goWrongBook">查看错题本</button>
</view>
```

如果 `todayDueCount > 0` 但 `todayRemainingCount === 0`：

显示：

```text
今日复习已完成
```

并进入 `final-result` 或完成态 overview。

------

# 六、前端复习启动逻辑

## 1. onLoad / onShow 加载今日概览

在 `onLoad` 或 `onShow` 中调用：

```js
loadTodayReviewOverview()
```

实现：

```js
async loadTodayReviewOverview() {
  this.setData({ phase: 'loading', overviewLoading: true })

  try {
    const overview = await api.get('/review/today/overview')
    const vm = this.buildReviewOverviewVM(overview)

    this.setData({
      ...vm,
      reviewOverview: overview,
      phase: vm.todayRemainingCount > 0 ? 'overview' : 'empty',
      overviewLoading: false,
    })
  } catch (e) {
    this.setData({
      phase: 'error',
      overviewLoading: false,
      errorText: '今日复习计划加载失败，请稍后重试',
    })
  }
}
```

------

## 2. 视图模型转换

新增：

```js
buildReviewOverviewVM(overview) {
  const due = Number(overview.today_due_count || 0)
  const completed = Number(overview.today_completed_count || 0)
  const remaining = Number(overview.today_remaining_count || Math.max(0, due - completed))
  const progress = due > 0 ? Math.round((completed / due) * 100) : 0

  return {
    todayDueCount: due,
    todayCompletedCount: completed,
    todayRemainingCount: remaining,
    todayOverdueCount: Number(overview.today_overdue_count || 0),
    todayNewDueCount: Number(overview.today_new_due_count || 0),
    estimatedMinutes: Number(overview.estimated_minutes || Math.ceil(remaining * 0.5)),
    reviewBatchSize: Number(overview.batch_size || 10),
    currentBatchNo: Number(overview.current_batch_no || 0),
    totalBatchCount: Number(overview.total_batch_count || Math.ceil(remaining / 10)),
    allTodayQuestionIds: overview.all_question_ids || [],
    completedQuestionIds: overview.completed_question_ids || [],
    remainingQuestionIds: overview.remaining_question_ids || [],
    todayProgressPercent: Math.min(100, Math.max(0, progress)),
  }
}
```

------

## 3. startTodayReview 自动取下一组

新增或改造：

```js
async startTodayReview() {
  if (this.data.todayRemainingCount <= 0) return
  if (this.data.isStarting || this.data.isContinuing) return

  this.setData({
    isStarting: true,
    batchLoading: true,
  })

  try {
    const batch = await api.post('/review/today/next-batch', {
      batch_size: this.data.reviewBatchSize,
    })

    if (!batch.questions || !batch.questions.length) {
      await this.loadTodayReviewOverview()
      return
    }

    const questions = this.normalizeReviewQuestions(batch.questions)

    this.setData({
      phase: 'reviewing',
      sessionId: batch.session_id || '',
      currentGroupId: batch.group_id || '',
      currentBatchNo: batch.batch_no || this.data.currentBatchNo + 1,
      totalBatchCount: batch.total_batch_count || this.data.totalBatchCount,
      groupQuestions: questions,
      currentQuestion: questions[0],
      currentIndex: 0,
      answers: {},
      runnerProgressPercent: 0,
      isStarting: false,
      isContinuing: false,
      batchLoading: false,
    })
  } catch (e) {
    this.setData({
      isStarting: false,
      isContinuing: false,
      batchLoading: false,
    })
    wx.showToast({
      title: '获取复习题失败，请重试',
      icon: 'none',
    })
  }
}
```

要求：

- 不允许用户传入“我要复习多少题”作为任务池总数。
- 前端只允许传 `batch_size`，它是每组上限。
- 后端必须保证只返回今日到期且尚未完成的题。
- 如果没有题了，刷新 overview 并进入完成态。

------

# 七、reviewing 页面逻辑

`phase === 'reviewing'` 仍可复用当前 `quiz-runner`。

但顶部文案要从“第几题 / 刷题进度”改为“今日复习进度”。

建议传给 quiz-runner 的标题：

```text
今日复习 · 第 X 组
```

进度：

```text
本组 a / b，今日已完成 y / total
```

如果 quiz-runner 不支持该文案，可在 review-today 外层增加顶部信息条：

```xml
<view class="reviewing-progress-strip">
  <text>第 {{currentBatchNo}} / {{totalBatchCount}} 组</text>
  <text>今日已完成 {{todayCompletedCount}} / {{todayDueCount}}</text>
</view>
```

要求：

- 本组答题进度仍正常。
- 今日总进度也要可见。
- 完成一组后提交到后端，后端更新每道题的下次复习时间。

------

# 八、组结果页逻辑

用户完成当前组后，调用现有或新接口提交批量复习结果：

```http
POST /api/v1/review/grade-batch
```

提交数据需要带：

```json
{
  "session_id": "...",
  "group_id": "...",
  "answers": [...]
}
```

后端返回：

```json
{
  "group_id": "...",
  "batch_no": 1,
  "submitted_count": 10,
  "correct_count": 8,
  "wrong_count": 2,
  "skipped_count": 0,
  "accuracy": 0.8,
  "today_due_count": 30,
  "today_completed_count": 10,
  "today_remaining_count": 20,
  "has_next_batch": true,
  "next_batch_size": 10,
  "results": [...]
}
```

组结果页按钮逻辑：

- 如果 `has_next_batch === true`：
  - 主按钮：“继续下一组”
  - 点击后调用 `startTodayReview()` 或 `loadNextBatch()`
- 如果 `has_next_batch === false`：
  - 主按钮：“查看今日结果”
  - 点击进入 `final-result`

组结果页不要出现“选择再复习几道”的逻辑。

------

# 九、最终结果页逻辑

当今日待复习全部完成后，显示最终结果页。

最终结果页数据来源：

- 当前 session 累积结果
- 或后端 `/review/today/result`
- 或 `/review/today/overview` 中 completed/remaining 数据

最终结果页应展示：

- 今日应复习：X 道
- 已完成：X 道
- 正确：X 道
- 错误：X 道
- 跳过：X 道
- 正确率：X%
- 今日完成率：100%
- 下次复习已更新：X 道
- 明天预计复习：X 道，如后端能提供

按钮：

- “查看错题”
- “继续练习”
- “返回首页”

不再出现：

- 选择题量
- 再刷几道
- 今日新增 x 道错题这种无价值提示
- 过度装饰 hero

------

# 十、后端接口设计

请新增或改造以下接口。

------

## 1. GET /api/v1/review/today/overview

用途：进入 review-today 时获取今日复习任务概览。

返回示例：

```json
{
  "date": "2026-07-09",
  "today_due_count": 28,
  "today_completed_count": 8,
  "today_remaining_count": 20,
  "today_overdue_count": 6,
  "today_new_due_count": 22,
  "estimated_minutes": 10,
  "batch_size": 10,
  "current_batch_no": 1,
  "total_batch_count": 3,
  "all_question_ids": [101, 102, 103],
  "completed_question_ids": [101],
  "remaining_question_ids": [102, 103],
  "has_due_review": true,
  "is_completed": false
}
```

字段说明：

- `today_due_count`：今天应该复习的总题数。包括今天到期和以前逾期未复习的题。
- `today_completed_count`：今天已经完成复习的题数。
- `today_remaining_count`：今天还剩未完成复习的题数。
- `today_overdue_count`：`next_review_at < today_start` 且未完成的题数。
- `today_new_due_count`：`today_start <= next_review_at <= today_end` 的题数。
- `batch_size`：每组复习数量，默认 10，可来自用户设置。
- `total_batch_count`：按今日待复习总量和 batch_size 计算。
- `is_completed`：今天任务是否已完成。

------

## 2. POST /api/v1/review/today/next-batch

用途：获取今日下一组待复习题。

请求：

```json
{
  "batch_size": 10
}
```

注意：

- 这个 `batch_size` 是每组大小，不是用户选择今日复习总题数。
- 如果后端有用户设置，则优先用后端设置，可以忽略前端传入值。
- 最大值建议限制为 40。
- 默认 10。

返回：

```json
{
  "session_id": "review_20260709_user50",
  "group_id": "review_20260709_user50_batch_2",
  "batch_no": 2,
  "total_batch_count": 3,
  "batch_size": 10,
  "today_due_count": 28,
  "today_completed_count": 8,
  "today_remaining_count": 20,
  "questions": [
    {
      "wrong_question_id": 102,
      "question_id": 88,
      "stem": "...",
      "options": [],
      "answer": "...",
      "subject": "...",
      "next_review_at": "2026-07-09T00:00:00",
      "review_level": 2
    }
  ]
}
```

取题规则：

- 只取当前用户的题。
- 只取 `next_review_at <= now` 或 `next_review_date <= today_end` 的题。
- 排除今天已经完成复习的题。
- 排除已删除、已归档、不需要复习的题。
- 排序优先级：
  1. 逾期更久的题优先。
  2. 复习失败次数更多的题优先。
  3. 最近做错的题优先。
  4. ID 稳定排序，避免抖动。
- 返回数量不超过 batch_size。

------

## 3. GET /api/v1/review/today/result

用途：今日复习完成后获取最终结果。

返回：

```json
{
  "date": "2026-07-09",
  "today_due_count": 28,
  "today_completed_count": 28,
  "correct_count": 22,
  "wrong_count": 5,
  "skipped_count": 1,
  "accuracy": 0.79,
  "completion_rate": 1.0,
  "updated_schedule_count": 28,
  "tomorrow_due_count": 12,
  "subject_stats": [
    {
      "subject": "数学",
      "reviewed": 10,
      "correct": 7,
      "wrong": 3
    }
  ],
  "is_completed": true
}
```

------

# 十一、后端服务层逻辑

在 `app/services/review_scheduler.py` 中增加或整理以下函数：

```python
async def get_today_review_overview(db, user_id, today, timezone):
    ...
async def get_next_today_review_batch(db, user_id, batch_size, today, timezone):
    ...
async def get_today_review_result(db, user_id, today, timezone):
    ...
```

核心规则：

## 1. 今日待复习定义

今日待复习题 = 满足以下条件的题：

```text
next_review_at <= today_end
AND user_id = 当前用户
AND 未归档
AND 未删除
AND 仍需要复习
```

其中包括：

- 以前到期但没复习的逾期题。
- 今天刚到期的题。

不包括：

- 明天及以后才到期的题。
- 今天已经完成过复习的题。
- 已掌握且不再需要复习的题，如项目已有该状态。
- 被删除/归档的题。

------

## 2. 今日已完成定义

今日已完成题 = 今天已经提交过 review 结果的题。

如果项目已有 review record 表，请用 record 判断：

```text
review_records.created_at between today_start and today_end
AND mode = 'review_today'
```

如果项目暂时没有 record 表，则需要基于现有批量提交结果存储逻辑判断。

------

## 3. 复习完成后更新调度

每道题提交后，应根据答题结果更新复习计划：

- 答对：
  - 提升熟练度。
  - 下次复习间隔变长。
- 答错：
  - 降低熟练度或保持低等级。
  - 下次复习时间缩短。
  - 进入错题强化。
- 跳过：
  - 视为未掌握或低置信度。
  - 下次复习时间不应过长。

保持现有算法即可，但要保证今日完成状态能够正确计算。

------

# 十二、数据库与兼容性

如果现有数据表已经能表达以下字段，不要新增表：

- `next_review_at`
- `review_count`
- `mastery_level`
- `last_reviewed_at`
- `wrong_question_id`
- `user_id`

如果缺少“今日是否完成复习”的记录能力，请优先使用已有 review record / answer record 表。

只有在确实缺失时，才新增轻量表，例如：

```sql
review_today_records
- id
- user_id
- wrong_question_id
- review_date
- session_id
- group_id
- is_correct
- user_answer
- correct_answer
- created_at
```

要求：

- 同一用户、同一题、同一 review_date 不应重复计入今日完成数。
- 可以重复提交更新结果，但统计时只能算一次。
- 建议唯一索引：
  - `user_id`
  - `wrong_question_id`
  - `review_date`

------

# 十三、前端删除/废弃字段

请检查并删除或停止使用以下“刷题式”字段：

```js
selectedReviewCount
reviewCountOptions
customReviewCount
showCountSelector
questionLimit
targetCount
```

如果这些字段仍被其他页面使用，不要全局删除，只在 `review-today` 页面停止使用。

------

# 十四、前端按钮文案统一

将 review-today 页面中的按钮文案统一为任务式：

使用：

- 今日待复习
- 开始复习
- 继续复习
- 继续下一组
- 查看今日结果
- 今日复习完成
- 去练习新题
- 查看错题本

避免：

- 开始刷题
- 选择题数
- 再刷几道
- 随机练习
- 生成一组题
- 做 X 道

------

# 十五、UI 风格要求

保持小程序主风格：

- 蓝白色系。
- 卡片化。
- 数据清晰。
- 不要大面积深色背景。
- 不要大 hero。
- 不要大勋章。
- 不要过多装饰图标。
- 页面首屏必须看到“今日待复习 X 道”。

推荐颜色：

```css
--review-primary: #4F7FFF;
--review-bg: #EEF5FF;
--review-card: #FFFFFF;
--review-text-main: #1F2937;
--review-text-sub: #6B7280;
--review-success: #22C55E;
--review-warning: #F59E0B;
--review-danger: #EF4444;
```

------

# 十六、异常状态

需要处理以下情况：

## 1. 今日没有待复习

显示：

```text
今天没有待复习题
```

按钮：

- 去练习
- 查看错题本

## 2. 今日任务已完成

显示：

```text
今日复习已完成
```

展示今日完成数据。

## 3. 加载失败

显示：

```text
复习计划加载失败
```

按钮：

- 重新加载

## 4. 获取下一组失败

toast：

```text
获取复习题失败，请重试
```

保留 overview，不要进入空白页。

## 5. 提交组结果失败

toast：

```text
提交失败，请检查网络后重试
```

保留当前答题结果，不要丢答案。

------

# 十七、验收清单

## 入口页

- 进入 `pages/review-today` 后，不再出现“选择复习几道题”。
- 首屏直接显示“今日待复习 X 道”。
- 显示已完成、剩余、逾期、预计用时。
- 今日没有复习任务时显示 empty 页面。
- 今日已完成时显示完成态。

## 开始复习

- 点击“开始复习”后，系统自动拉取下一组。
- 用户不能选择本次总题数。
- 每组题数由后端配置或默认值决定。
- 题目来自今日到期任务池，不是随机刷题池。

## 分组复习

- 每组完成后进入组结果页。
- 组结果页显示当前组正确率、正确数、错误数、跳过数。
- 如果还有剩余题，按钮为“继续下一组”。
- 如果今日任务完成，按钮为“查看今日结果”。

## 今日进度

- 完成一组后，overview / group-result / final-result 中的今日已完成数量同步更新。
- 今日进度百分比正确。
- 不重复统计同一道题。
- 逾期题优先出现。

## 最终结果

- 完成全部今日复习题后，进入最终结果页。
- 最终结果页显示今日应复习、已完成、正确、错误、跳过、正确率。
- 不再显示选择题数。
- 不再显示刷题式文案。
- 页面风格保持蓝白主风格。

## 后端

- `/review/today/overview` 正确返回今日任务概览。
- `/review/today/next-batch` 只返回今日到期且未完成题。
- `/review/today/result` 正确返回今日完成结果。
- `grade-batch` 提交后会更新复习调度和今日完成记录。
- 同一题今天重复提交不会重复计入完成数。

------

# 十八、实现优先级

请按以下顺序实施：

1. 后端增加 `/review/today/overview`，先让页面能显示今日待复习数。
2. 后端增加 `/review/today/next-batch`，替代前端选择题量取题。
3. 前端重构 overview 页面，删除选择题量。
4. 前端接入 next-batch，开始复习自动取下一组。
5. 调整组结果页按钮逻辑。
6. 增加 `/review/today/result` 或复用 overview 生成最终结果。
7. 完成 UI 风格统一和异常态处理。
8. 回归测试整个 review-today 流程。

------

# 十九、不要做的事情

- 不要继续保留“选择复习几道题”的主入口。
- 不要把 review-today 做成随机刷题。
- 不要让用户手动决定今天总共复习几道。
- 不要破坏现有答题组件的题目渲染能力。
- 不要破坏错题调度算法。
- 不要把未来才到期的题提前塞进今日复习任务。
- 不要重复统计同一道题的今日完成次数。