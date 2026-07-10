你是一个微信小程序 + FastAPI 全栈工程师。请基于当前项目代码直接修复以下问题，重点修改前端 `miniprogram`，必要时可补充后端 `app` 接口。不要只做表面样式调整，要定位真实原因并保证交互稳定。

## 一、项目关键路径

前端小程序重点文件：

- `components/quiz-runner/quiz-runner.js`
- `components/quiz-runner/quiz-runner.wxml`
- `components/quiz-runner/quiz-runner.wxss`
- `pages/wrong-detail/wrong-detail.js`
- `pages/wrong-detail/wrong-detail.wxml`
- `pages/wrong-detail/wrong-detail.wxss`
- `pages/review-today/review-today.js`
- `pages/review-today/review-today.wxml`
- `pages/review-today/review-today.wxss`
- `pages/practice/practice.js`
- `pages/practice/practice.wxml`
- `pages/practice/practice.json`
- `pages/practice-result/practice-result.js`
- `pages/practice-result/practice-result.wxml`
- `pages/practice-result/practice-result.wxss`
- `components/AnimatedView/AnimatedView.*`
- `subpackages/animation/lottie-loader.js`
- `subpackages/animation/lottie/success/success-check.js`
- `subpackages/animation/lottie/reward/celebration.js`

后端可用接口重点文件：

- `app/api/v1/review.py`
- `app/schemas/review_scheduler.py`
- `app/services/review_scheduler.py`
- `app/api/v1/ai.py`
- `app/services/ai_service.py`
- `app/schemas/ai.py`

保持现有题目渲染体系不被破坏，包括 `SEGMENTS / RICH_TEXT / CODE / LATEX / MIXED`、`mp-html`、`math-question`、多空选择题、safe mode、自愈逻辑、答题记录提交逻辑。

------

# 二、wrong-detail 页面修复

## 1. 去掉“答案行”

当前 `pages/wrong-detail/wrong-detail.wxml` 中存在 `<!-- 答案行 -->` 区域：

- `detail-card answer-card`
- 我的答案
- 正确答案
- 题目解析

请整体移除该区域，不再展示这块独立答案卡。

同时清理 `wrong-detail.wxss` 中仅服务于该答案卡的样式，例如：

- `.q-answer-line`
- `.q-answer-label`
- `.q-answer-value`
- `.q-answer-analysis`
- `.q-analysis-text`
- `.answer-card`
- 其他仅该区域使用的样式

注意：题目本身仍通过 `quiz-runner` readonly 高亮正确/错误选项，不要破坏 readonly 答案高亮。

------

## 2. 修复 wrong-detail 复用 quiz-runner 时多余提交按钮问题

当前 `quiz-runner` 的底部提交按钮始终渲染，即使 `submitDisabled="{{true}}"` 也会出现“继续复盘”等无用按钮。

请在 `components/quiz-runner` 增加显式属性：

```js
showSubmitButton: { type: Boolean, value: true }
```

修改：

- `quiz-runner.wxml` 底部主提交按钮加 `wx:if="{{showSubmitButton}}"`
- 答题卡弹窗底部提交按钮也加 `wx:if="{{showSubmitButton}}"`
- 默认保持 `true`，避免影响 practice / review-today
- `pages/wrong-detail/wrong-detail.wxml` 使用 quiz-runner 时传入：

```xml
showSubmitButton="{{false}}"
```

wrong-detail 页面不应再出现任何提交/交卷/复盘提交按钮。

------

## 3. 修复 wrong-detail 无法左右滑动切换题目

当前 `quiz-runner.js` 的触摸逻辑在 `readonly || submitted` 时直接 return，导致 wrong-detail 是 readonly 状态时无法左右滑动。

请增加独立控制属性，例如：

```js
swipeEnabled: { type: Boolean, value: true },
allowSwipeInReadonly: { type: Boolean, value: false }
```

修改逻辑：

- 选项点击仍然必须受 `readonly/submitted` 限制，不能在 wrong-detail 选答案。
- 左右滑动导航不应被 `readonly` 阻止。
- `onTouchStart/onTouchEnd` 判断应改成：
  - `swipeEnabled === false` 时禁止滑动
  - `submitted === true` 可按现有逻辑禁止滑动
  - `readonly === true` 时，只有 `allowSwipeInReadonly === true` 才允许滑动
- `wrong-detail` 传入：

```xml
swipeEnabled="{{true}}"
allowSwipeInReadonly="{{true}}"
```

验收：wrong-detail 中左右滑动可以切换错题，但选项仍不可点击修改。

------

## 4. 修复 wrong-detail 点击上一题/下一题切换时页面跳动

当前 `pages/wrong-detail/wrong-detail.js` 的 `_navigateTo` 会：

```js
this.setData({ switching: true })
```

而 wxml 中：

```xml
<view wx:if="{{switching}}" class="switch-loading">...</view>
<quiz-runner wx:if="{{!switching}}" ... />
```

这会在切题时销毁/重建 quiz-runner，造成页面高度变化和视觉跳动。

请改为：

- 切题时不要卸载 `quiz-runner`
- 不要用 `wx:if="{{!switching}}"` 包裹 quiz-runner
- 可以保留轻量的半透明 loading overlay，但必须 `position: fixed` 或 `position: absolute`，不能影响页面布局流
- `_navigateTo` 中使用 `navigating` 或 `switching` 仅做按钮节流，不要用它控制主内容销毁
- 切题失败时保持当前题不丢失
- 切题成功后只更新：
  - `wq`
  - `currentIdx`
  - `currentWqId`
  - `currentQuestion`
  - `wrongQuestions`
  - `runnerProgressPercent`
  - `subjectLabelText`
  - `errorTypeLabelText`
  - AI 状态

验收：

- 点击上一题/下一题时题号变化稳定
- 页面顶部/内容区不闪烁、不突然跳高/跳低
- 题目切换动画可保留，但不能破坏布局稳定性

------

## 5. 修复 AI 解析区域重新生成容易失败的问题

当前 wrong-detail 的 AI 解析调用：

```js
api.post('/ai/error-analysis', { wrong_question_id })
api.post('/ai/error-analysis', { wrong_question_id, force_regenerate: true })
```

后端已有：

- `app/api/v1/ai.py`
- `app/services/ai_service.py`
- `ErrorAnalysisRequest.force_regenerate`
- `AiResponse.cache_preserved`
- `AiResponse.from_fallback`

请做前后端协同增强。

前端要求：

- 点击“重新生成”时保留旧的 `aiCards`，不要先清空旧解析。
- 生成失败时旧解析仍展示，只在按钮附近展示轻量错误文案，例如“重新生成失败，已保留历史解析”。
- `aiRegenerating` 必须在所有路径下正确复位，使用 `try/catch/finally` 或等价逻辑。
- 区分以下状态：
  - 正在生成：展示 loading，不清空旧内容
  - 后端返回 `from_fallback && cache_preserved`：保留旧解析，提示失败
  - 后端返回 `model === 'generating'` 或内容提示正在生成：不要视为永久失败，可提示“正在生成中，请稍后重试”
  - 后端成功返回新内容：更新 `aiResult/aiCards`
- 加按钮级防抖，避免连续点击触发并发生成。
- 切换题目时通过 token 或 wqId 防止旧请求覆盖新题数据，保留现有 stale response guard。

后端要求：

- `app/services/ai_service.py::analyze_error` 在 `force_regenerate=True` 且生成失败、超时、无模型配置、解析失败时：
  - 如果原本有可用旧缓存，应返回旧缓存内容，并设置：
    - `from_cache: true`
    - `from_fallback: false` 或按实际情况
    - `force_regenerated: false`
    - `cache_preserved: true`
  - 不要直接把 fallback 当成新解析覆盖前端展示
- 不要把 fallback 内容持久化为正式 `wrong_questions.ai_analysis`
- JSON 解析失败时至少保证返回结构字段完整：
  - `mistake_diagnosis`
  - `knowledge_patch`
  - `review_task`
- 如果已经有分布式锁或进程内锁，前端收到“正在生成中”不应进入失败空白态。

验收：

- 有历史 AI 解析时，重新生成失败不会导致内容消失。
- 无历史解析时失败才展示空状态/重试态。
- 连续点击不会触发多个并发请求。
- 切换题目过程中旧请求不会污染新题解析。

------

# 三、review-today 页面修复

## 1. 修复最后一题选项选择后顶部进度条不同步

当前 `review-today.js` 中：

- `_showQuestion()` 会调用 `_updateRunnerFields()`
- 但 `selectOption()` / `selectBlankOption()` 只更新了 `answers/currentQuestion/_answeredCount` 和 `_syncAnsweredFlags()`
- 没有立即更新 `runnerProgressPercent`
- 因此最后一题选择后顶部进度条不会立刻到 100%，需要页面滑动/刷新后才更新

请重构为一个统一的状态提交方法，例如：

```js
_applyAnswerState({ answers, currentQuestion })
```

该方法一次性更新：

- `answers`
- `currentQuestion`
- `_answeredCount`
- `runnerProgressPercent`
- `groupQuestions` 的 `_answered` 标记

避免多个 setData 互相覆盖或延迟。

最低要求：

- 在 `selectOption()` setData 后立即调用 `_updateRunnerFields()`
- 在 `selectBlankOption()` setData 后立即调用 `_updateRunnerFields()`
- `_syncAnsweredFlags()` 不应覆盖掉新的 `_answeredCount`
- 选择最后一题答案后，`progressPercent` 立即显示 `100%`

顺手修复字段命名不一致问题：

- review-today 中多空题应统一使用 `_hasBlankOptionGroups`
- 不要一处用 `_hasBlankGroups`，另一处用 `_hasBlankOptionGroups`
- 确保 quiz-runner 能正确识别多空选择题

验收：

- 最后一题一点击选项，顶部进度条和百分比立即变成 100%
- 答题卡中的已答状态同步更新
- 多选题取消选择导致未答时，进度也能即时回退

------

## 2. 优化“组结果页”：去掉无用装饰，增加有价值数据

当前 `review-today.wxml` 的 `phase === 'group-result'` 页面存在：

- `result-medal`
- 大标题 hero 感文案
- `group-reward-strip`
- 装饰性强但信息价值低的内容

请重做该页面，要求：

- 不要标题 hero
- 不要大勋章/大装饰/过多渐变
- 使用小程序主风格：蓝白、干净、卡片化
- 页面首屏应直接展示有价值数据
- 保留底部“进入下一组 / 查看总体结果”按钮
- 可保留轻微动效，但不能喧宾夺主

建议结构：

1. 顶部紧凑摘要卡
   - 第 X / N 组
   - 本组正确率
   - 本组题数
   - 正确数
   - 需巩固数
   - 跳过数，如有
2. 复习调度反馈卡
   - 已更新记忆曲线 X 题
   - 下次复习时间分布，例如“明天 / 3天后 / 7天后”
   - 可基于 `groupResults.next_review_at` 或 `interval_after` 客户端计算
3. 本组答题详情
   - 题目简要内容
   - 我的答案
   - 正确答案
   - 正确/错误/跳过状态
   - 错题优先展示可以保留，但要清晰标明原题号
4. 可选：按科目/知识点统计
   - 如果当前题目含 `subject` / `subject_name` / `_subjectLabel`，客户端即可聚合
   - 如果数据不足，可后端补接口

允许新增后端字段：

- 可以扩展 `POST /api/v1/review/grade-batch` 的响应，新增可选 `summary` 字段，不要破坏旧字段：
  - `submitted_count`
  - `skipped_count`
  - `accuracy`
  - `next_review_buckets`
  - `subject_stats`
- 修改 `app/schemas/review_scheduler.py::BatchGradeResponse`
- 修改 `app/api/v1/review.py::grade_batch`

验收：

- 组结果页视觉不再像游戏结算大海报
- 首屏至少有 4 个有价值指标
- 页面留白减少
- 答题详情阅读清晰
- 不影响下一组流程

------

## 3. 优化“最终结果页”蓝白主风格

当前最终结果页 `phase === 'final-result'` 风格与主小程序蓝白风格不完全一致，且仍有装饰性标题区。

请重做：

- 使用 `#EEF5FF / #F8FAFF / #FFFFFF / #4F7FFF` 为主
- 卡片圆角、轻阴影、弱边框
- 不使用大面积深色、强烈渐变、hero 标题区
- 不需要“今日复习完成”大标题 hero
- 页面开头直接放结果摘要卡

建议结构：

1. 总览摘要卡
   - 今日复习正确率
   - 已完成题数
   - 答对
   - 错题
   - 跳过
   - 已掌握
2. 完成度卡
   - 完成组数 / 总组数
   - 完成率
   - 若全部完成，显示“今日复习已完成”
   - 若仍有跳过/未完成，显示“仍有 X 题待处理”
3. 薄弱点卡
   - 错题数
   - 错题占比
   - 错题较多时提示先复盘
   - 如果能聚合科目，展示“主要薄弱科目”
4. 下一步建议卡
   - 根据正确率和错题数生成建议
   - 保留底部操作按钮：复盘错题 / 继续练习 / 完成

重要：修复最终结果 VM 统计口径。

当前 `_buildReviewResultViewModel()` 中：

```js
var total = this.data.totalCorrect + this.data.totalWrong
var answered = this.data.totalCompleted || total
var skipped = Math.max(0, total - answered)
```

这会导致 skipped 基本无法正确统计。请改为更合理口径：

- `sessionTotal = allGroupResults.length`，表示本轮出现过的题目数
- `submittedTotal = totalCompleted`
- `correct = totalCorrect`
- `wrong = totalWrong`
- `skipped = max(0, sessionTotal - submittedTotal)`
- `accuracy = submittedTotal > 0 ? Math.round(correct / submittedTotal * 100) : 0`
- `completionRate = sessionTotal > 0 ? Math.round(submittedTotal / sessionTotal * 100) : 0`

返回 VM 时增加：

- `sessionTotal`
- `submittedTotal`
- `completionRate`
- `subjectStats`
- `wrongRate`
- `hasSkipped`
- `hasWrong`
- `isPerfect`

------

## 4. 去掉最终结果页无用区域

删除 `review-today.wxml` 中最终结果页的：

```xml
<view class="wrong-inline-tip ...">
  今日新增 x 道错题，建议立即复盘
</view>
```

同时删除 `review-today.wxss` 中对应样式：

- `.wrong-inline-tip`
- `.wrong-marker`
- `.wrong-body`
- `.wrong-tip-text`
- `.wrong-count`
- `.wrong-tip-action`
- 以及相关 active/reduced-motion 样式

错题提醒可以整合进“薄弱点卡”或“下一步建议卡”，不要单独占一块无用区域。

------

## 5. 优化最终结果页信息密度，减少留白

最终结果页不能只显示大标题 + 少量数字 + 大量留白。请通过以下方式增加信息密度：

- 结果摘要使用 2x3 或 3x2 网格
- 增加完成度条
- 增加本轮复习分布：
  - 正确
  - 错误
  - 跳过
  - 已掌握
- 增加科目分布或错题科目分布
- 增加下一步建议
- 底部按钮固定，但内容区要留出安全距离

如果客户端数据不足，可以新增一个后端接口，例如：

```http
GET /api/v1/review/today-result-summary
```

返回今日真实复习统计：

```json
{
  "reviewed_today": 12,
  "correct_today": 9,
  "wrong_today": 3,
  "accuracy_today": 0.75,
  "remaining_today": 0,
  "overdue": 0,
  "by_subject": {
    "math2": {
      "reviewed": 6,
      "correct": 4,
      "wrong": 2,
      "remaining": 0
    }
  }
}
```

如果新增接口，请：

- 放在 `app/api/v1/review.py`
- 统计逻辑放在 `app/services/review_scheduler.py`
- schema 放在 `app/schemas/review_scheduler.py`
- 保持原有 `/review/schedule-stats` 不破坏

------

# 四、practice 页面修复

## 1. 全对时显示 subpackage 中的 success 或 celebration Lottie 动画

当前 practice 提交成功后直接：

```js
wx.redirectTo({ url: '/pages/practice-result/practice-result?...' })
```

要求：如果本次答题全对，即：

```js
result.total_wrong === 0 && result.total_correct > 0 && answeredCount === total
```

则在 `pages/practice/practice` 页面先显示一次成功/庆祝 Lottie 动画，再跳转到结果页。

可复用现有：

- `components/AnimatedView/AnimatedView`
- `subpackages/animation/lottie-loader.js`
- `success-check.js`
- `celebration.js`

实现建议：

1. `practice.json` 增加：

```json
{
  "usingComponents": {
    "animated-view": "/components/AnimatedView/AnimatedView",
    "quiz-runner": "/components/quiz-runner/quiz-runner",
    "loading-lottie": "/components/loading-lottie/loading-lottie"
  }
}
```

注意保留原有 usingComponents，不要覆盖丢失。

1. `practice.js` data 增加：

```js
showPerfectCelebration: false,
perfectCelebrationType: 'practice',
perfectCelebrationTitle: '全对完成',
perfectCelebrationDetail: '',
perfectCelebrationMotto: '这组掌握很稳，继续保持',
perfectCelebrationRewardText: ''
```

1. 在 `doSubmit()` 成功拿到 result 并写入 `lastPracticeResult` 后：

- 先拼好 resultUrl
- 如果全对：
  - `setData({ showPerfectCelebration: true, ...copy })`
  - 等 AnimatedView `done` 事件后跳转
- 如果不是全对：
  - 直接跳转

1. `practice.wxml` 顶部加入：

```xml
<animated-view
  wx:if="{{showPerfectCelebration}}"
  show="{{showPerfectCelebration}}"
  type="{{perfectCelebrationType}}"
  title="{{perfectCelebrationTitle}}"
  detail="{{perfectCelebrationDetail}}"
  motto="{{perfectCelebrationMotto}}"
  reward-text="{{perfectCelebrationRewardText}}"
  duration="{{2600}}"
  gif-src="/assets/animation/celebration.gif"
  png-src="/assets/animation/celebration-static.png"
  bind:done="goPracticeResultAfterCelebration"
/>
```

1. 增加方法：

```js
goPracticeResultAfterCelebration() {
  const url = this._pendingResultUrl
  this._pendingResultUrl = ''
  this.setData({ showPerfectCelebration: false, submitting: false })
  if (url) wx.redirectTo({ url })
}
```

1. 非全对路径仍应正确 `submitting=false` 或跳转，不要卡住 loading。

验收：

- 全对时，practice 页面先展示 success/celebration Lottie，再进入 practice-result
- 非全对时原流程不受影响
- 动画组件失败时有 gif/png/static fallback，不影响跳转
- 不重复跳转

------

# 五、practice-result 页面修复

## 1. 默认展开答题详情

当前 `pages/practice-result/practice-result.js`：

```js
showDetail: false
```

请改为默认展开：

```js
showDetail: true
```

并确保 `onLoad` 也不会把它重置为 false。

WXML 中按钮文案仍可保留“收起 / 展开”。

验收：进入 practice-result 后，答题详情默认可见。

------

## 2. 优化答题详情内容可读性

当前详情问题：

- 题干单行省略，阅读性差
- 对错状态用 `✓ / ✗` 信息量不足
- 我的答案/正确答案挤在同一行
- 字号偏小
- 长答案换行体验一般
- 正确题与错误题虽然有底色，但层级不够清晰

请优化 `practice-result.wxml` 和 `practice-result.wxss`。

建议改造：

1. 每题卡片结构：

- 顶部行：
  - 原题号
  - 状态 pill：正确 / 错误 / 跳过
- 题干：
  - 至少显示 2~4 行
  - 不要默认单行 `white-space: nowrap`
  - 支持长文本换行
- 答案区：
  - 分成两行或两块
  - “我的答案”
  - “正确答案”
  - 正确题可以显示“答案：X”
- 错题样式：
  - 左边红色细条
  - 错误 pill
  - 我的答案红色
  - 正确答案绿色
- 正确题样式：
  - 左边绿色细条
  - 正确 pill
  - 整体浅绿或白底弱绿边框

1. JS 数据处理：

当前 `compactResults` 将错题放前面，可以保留，但必须显示 `_displayIndex` 原始题号。

请补充字段：

```js
_statusText: r.is_correct ? '正确' : '错误'
_userAnswerText: r.user_answer || '未作答'
_correctAnswerText: formatInlineMathText(r.correct_answer || '')
```

如果有跳过题，也要支持：

```js
_cls: 'skipped'
_statusText: '跳过'
```

1. CSS 调整：

- `.detail-stem` 改为多行自然换行：
  - `white-space: normal`
  - `line-height: 1.65`
  - `font-size: 25rpx` 左右
  - 不要强制单行省略
- `.detail-answer-line` 改为纵向布局或卡片内 grid
- 答案文本支持 `word-break: break-word`
- 增加块间距，提升阅读性
- 避免过多红绿大面积背景，保持蓝白主风格

验收：

- 默认展开后能清楚阅读每道题题干和答案
- 长题干不会被截成一行
- 长答案不溢出
- 正确/错误/跳过状态一眼可识别
- 底部固定按钮不遮挡最后几道详情

------

# 六、统一设计要求

所有结果页统一主风格：

- 背景：`#EEF5FF` 或 `#F8FAFF`
- 卡片：白底、浅边框、轻阴影
- 主色：`#4F7FFF`
- 成功：`#22C55E`
- 错误：`#EF4444`
- 警告：`#F59E0B`
- 不要大面积深色卡片
- 不要无意义大图标、大勋章、大 hero
- 数据优先，装饰弱化

------

# 七、回归验证清单

请完成后逐项验证：

## wrong-detail

- 错题详情页不再出现独立“答案行”卡片。
- 不再出现多余提交按钮。
- 左右滑动可以切换错题。
- 上一题/下一题点击切换不跳页、不闪烁、不销毁主组件。
- 题目 readonly 高亮仍正常。
- AI 重新生成失败时不会清空旧解析。
- 连续点击重新生成不会并发请求。
- 切题过程中旧 AI 请求不会覆盖新题。

## review-today

- 选择最后一题答案后，顶部进度条立即到 100%。
- 取消最后一题答案后，进度能即时回退。
- 答题卡已答状态同步。
- 多空选择题仍可正常答题和统计。
- 组结果页没有大 hero / 大勋章 / 无用装饰。
- 组结果页首屏展示足够数据。
- 最终结果页是蓝白主风格。
- 最终结果页不再有“今日新增 x 道错题，建议立即复盘”独立区域。
- 最终结果页信息密度提升，留白减少。
- 最终统计口径正确：总题数、已提交、跳过、正确率、完成率不互相矛盾。

## practice

- 全对时显示 success 或 celebration Lottie 动画。
- 动画结束后进入 practice-result。
- 非全对时原提交结果流程正常。
- loading / submitting 状态不会卡死。

## practice-result

- 答题详情默认展开。
- 题干多行可读。
- 我的答案/正确答案分区清晰。
- 长文本不溢出。
- 底部按钮不遮挡详情最后内容。

------

# 八、代码质量要求

- 不要删除现有核心功能。
- 不要破坏 practice / review-today / wrong-detail 共用 quiz-runner 的现有使用方式。
- 新增 quiz-runner 属性必须有默认值，保证旧页面不传也能正常运行。
- 所有新增接口必须向后兼容。
- WXML 中避免重复无效节点。
- WXSS 清理废弃样式，避免长期残留。
- 异步请求必须有错误处理。
- setData 尽量合并，避免进度不同步。
- 提交前检查语法错误。
- 如果项目没有自动测试，至少执行：
  - 小程序开发者工具编译
  - 后端 Python 语法检查或 `python -m compileall app`
  - 手动跑通以上验收清单
