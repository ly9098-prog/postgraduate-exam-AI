# `pages/review-today` 页面重点审查报告与详细修复任务

审查对象：pages/目录中的：

```text
pages/review-today/review-today.js
pages/review-today/review-today.wxml
pages/review-today/review-today.wxss
components/AnimatedView/AnimatedView.*
utils/answer.js
```

审查方式：静态代码审查 + 页面逻辑链路分析。
已执行 `node --check pages/review-today/review-today.js`，JS 语法检查通过。
本报告未包含真机截图校验，UI 结论基于当前 WXSS/WXML 结构判断，仍建议修复后用微信开发者工具和真机复测。

------

# 一、总体现状结论

`pages/review-today` 页面仍然存在明显问题，尤其是：

1. **UI 字体/按钮/标签在容器中垂直居中不稳定，问题真实存在。**
2. **提交复习题后，再点击“查看总体结果/查看复习详情”会再次触发完成动画，问题真实存在。**
3. **跳过题目重新入队后，会导致最终统计重复计算，这是当前页面更严重的隐藏逻辑问题。**
4. **开始新一轮复习时，部分统计字段没有完整重置，可能导致二次进入页面后数据污染。**
5. **提交结果匹配使用 `question_id`，如果同一题多次出现在复习计划中，存在匹配错位风险。**
6. **接口异常容错不足，`res.results` 异常时可能导致页面报错。**

建议本轮优先修复 UI 垂直居中、动画重复触发、跳过题统计重复这 3 个问题。

------

# 二、问题 1：UI 字体在容器中没有垂直居中

## 问题等级

```text
P1 高优先级 UI 问题
```

## 问题位置

主要文件：

```text
pages/review-today/review-today.wxss
```

涉及选择器包括但不限于：

```css
.gradient-btn
.finish-btn
.nav-btn
.submit-group-btn
.master-btn-cancel
.master-btn-confirm
.size-chip
.mission-badge
.section-chip
.group-meta
.subject-badge
.blank-group-title
.final-growth-kicker
.eyebrow
```

## 当前问题表现

页面中多个按钮、胶囊标签、统计标签、题号标签依赖：

```css
line-height: 固定高度;
```

或者只设置了：

```css
padding
font-size
line-height: 1.35;
```

但没有使用稳定的 flex 垂直居中。

在微信小程序里，尤其是 `button`、`text`、中文字体、不同 Android 机型、系统字体缩放环境下，仅依靠 `line-height` 很容易出现文字偏上或偏下的问题。

当前典型代码如下：

```css
.gradient-btn {
  display: block;
  min-height: 92rpx;
  line-height: 92rpx;
}

.finish-btn {
  height: 92rpx;
  line-height: 92rpx;
}

.nav-btn {
  height: 78rpx;
  line-height: 78rpx;
}

.master-btn-cancel,
.master-btn-confirm {
  height: 80rpx;
  line-height: 80rpx;
}

.size-chip {
  min-height: 76rpx;
  line-height: 76rpx;
}

.mission-badge {
  padding: 12rpx 16rpx;
  font-size: 22rpx;
  font-weight: 800;
}
```

这些写法在视觉上很容易造成“文字没有在容器正中间”的问题。

------

## 修复原则

本页面所有“按钮 / 胶囊 / 圆角标签 / 小徽章 / 题号块”统一改为 flex 居中。

不要继续依赖固定 `line-height` 来实现垂直居中。

核心原则：

```css
display: flex;
align-items: center;
justify-content: center;
line-height: normal;
box-sizing: border-box;
```

对于 `text` 类型胶囊，使用：

```css
display: inline-flex;
align-items: center;
justify-content: center;
line-height: 1;
box-sizing: border-box;
```

------

## 详细修复任务 1.1：统一修复按钮垂直居中

修改文件：

```text
pages/review-today/review-today.wxss
```

建议新增一组统一样式，放在“通用”区域后面：

```css
/* ==================== 垂直居中修复：按钮类 ==================== */
.gradient-btn,
.finish-btn,
.nav-btn,
.submit-group-btn,
.master-btn-cancel,
.master-btn-confirm {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  line-height: normal;
  padding-top: 0;
  padding-bottom: 0;
}
```

然后修改原有按钮样式。

### 修改 `.gradient-btn`

当前：

```css
.gradient-btn {
  display: block;
  margin: 30rpx 24rpx 0;
  background: linear-gradient(135deg, #4F7FFF 0%, #6EC1FF 100%);
  color: #FFFFFF;
  font-size: 30rpx;
  font-weight: 900;
  min-height: 92rpx;
  padding: 0;
  border-radius: 999rpx;
  border: none;
  line-height: 92rpx;
  text-align: center;
  box-shadow: 0 14rpx 30rpx rgba(79, 127, 255, 0.24);
}
```

建议改为：

```css
.gradient-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  margin: 30rpx 24rpx 0;
  min-height: 92rpx;
  padding: 0 28rpx;
  border-radius: 999rpx;
  border: none;
  background: linear-gradient(135deg, #4F7FFF 0%, #6EC1FF 100%);
  color: #FFFFFF;
  font-size: 30rpx;
  font-weight: 900;
  line-height: normal;
  text-align: center;
  box-shadow: 0 14rpx 30rpx rgba(79, 127, 255, 0.24);
}
```

### 修改 `.finish-btn`

当前：

```css
.finish-btn {
  width: 100%;
  height: 92rpx;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #4F7FFF 0%, #6EC1FF 100%);
  color: #FFFFFF;
  font-size: 30rpx;
  font-weight: 900;
  line-height: 92rpx;
  border: none;
  box-shadow: 0 14rpx 30rpx rgba(79, 127, 255, 0.24);
}
```

建议改为：

```css
.finish-btn {
  width: 100%;
  height: 92rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: 0 28rpx;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #4F7FFF 0%, #6EC1FF 100%);
  color: #FFFFFF;
  font-size: 30rpx;
  font-weight: 900;
  line-height: normal;
  border: none;
  box-shadow: 0 14rpx 30rpx rgba(79, 127, 255, 0.24);
}
```

### 修改 `.nav-btn`

当前：

```css
.nav-btn {
  flex: 1;
  height: 78rpx;
  border-radius: 999rpx;
  background: #E8F0FF;
  border: none;
  font-size: 26rpx;
  color: #4F7FFF;
  font-weight: 800;
  line-height: 78rpx;
}
```

建议改为：

```css
.nav-btn {
  flex: 1;
  height: 78rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: 0 20rpx;
  border-radius: 999rpx;
  background: #E8F0FF;
  border: none;
  font-size: 26rpx;
  color: #4F7FFF;
  font-weight: 800;
  line-height: normal;
}
```

### 修改 `.submit-group-btn`

当前已经使用 flex，但没有显式清掉 `button` 默认行高。建议补充：

```css
.submit-group-btn {
  line-height: normal;
  padding: 0 24rpx;
  box-sizing: border-box;
}
```

### 修改弹窗按钮

当前：

```css
.master-btn-cancel,
.master-btn-confirm {
  flex: 1;
  height: 80rpx;
  border-radius: 999rpx;
  border: none;
  font-size: 28rpx;
  font-weight: 800;
  line-height: 80rpx;
}
```

建议改为：

```css
.master-btn-cancel,
.master-btn-confirm {
  flex: 1;
  height: 80rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: 0 20rpx;
  border-radius: 999rpx;
  border: none;
  font-size: 28rpx;
  font-weight: 800;
  line-height: normal;
}
```

------

## 详细修复任务 1.2：统一修复胶囊标签垂直居中

修改文件：

```text
pages/review-today/review-today.wxss
```

建议新增：

```css
/* ==================== 垂直居中修复：胶囊 / 标签类 ==================== */
.eyebrow,
.mission-badge,
.section-chip,
.size-chip,
.group-meta,
.subject-badge,
.blank-group-title,
.final-growth-kicker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  line-height: 1;
}
```

然后局部修正。

### 修改 `.size-chip`

当前：

```css
.size-chip {
  flex: 1;
  text-align: center;
  min-height: 76rpx;
  line-height: 76rpx;
  background: #F7FAFF;
  border-radius: 999rpx;
  font-size: 27rpx;
  color: #617089;
  font-weight: 800;
  border: 2rpx solid transparent;
}
```

建议改为：

```css
.size-chip {
  flex: 1;
  min-height: 76rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  text-align: center;
  line-height: normal;
  background: #F7FAFF;
  border-radius: 999rpx;
  font-size: 27rpx;
  color: #617089;
  font-weight: 800;
  border: 2rpx solid transparent;
}
```

### 修改 `.mission-badge`

建议补充：

```css
.mission-badge {
  min-height: 48rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
```

### 修改 `.group-meta`

当前没有 line-height，也没有 flex。建议改为：

```css
.group-meta {
  flex-shrink: 0;
  min-height: 48rpx;
  padding: 0 16rpx;
  border-radius: 999rpx;
  background: #FFF7E8;
  color: #B87509;
  font-size: 22rpx;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  box-sizing: border-box;
}
```

### 修改 `.subject-badge`

建议：

```css
.subject-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42rpx;
  padding: 0 15rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 900;
  background: #E8F0FF;
  color: #4F7FFF;
  line-height: 1;
  box-sizing: border-box;
}
```

### 修改 `.section-chip`

建议：

```css
.section-chip {
  flex-shrink: 0;
  min-height: 42rpx;
  padding: 0 16rpx;
  border-radius: 999rpx;
  background: #E8F0FF;
  color: #4F7FFF;
  font-size: 20rpx;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  box-sizing: border-box;
}
```

------

## 详细修复任务 1.3：修复选项区域视觉垂直对齐问题

当前：

```css
.option-item {
  display: flex;
  align-items: flex-start;
}
```

这会导致单行选项时圆点/文字整体看起来偏上。
但多行选项时，`flex-start` 又是合理的。

建议采用折中方案：保留多行可读性，但让圆点和首行文字视觉基线更稳定。

修改：

```css
.option-item {
  display: flex;
  align-items: flex-start;
}
```

保留，但调整 indicator 的偏移：

```css
.option-indicator {
  margin-top: 5rpx;
}
```

并统一文字行高：

```css
.opt-key,
.option-key,
.opt-val,
.option-text {
  line-height: 1.55;
}
```

如果真机表现仍然偏上，可以改成：

```css
.option-item {
  align-items: center;
}
```

但需要重点测试多行选项，避免多行文字时圆点跑到整个块中间导致阅读不自然。

------

## UI 修复验收标准

修复后需要在微信开发者工具和真机上检查：

```text
1. “开始今日复习”按钮文字垂直居中。
2. “上一题 / 下一题 / 提交本组复盘”文字垂直居中。
3. “查看总体结果 / 进入下一组”按钮文字垂直居中。
4. “完成”按钮文字垂直居中。
5. “5题 / 10题 / 20题”节奏标签文字垂直居中。
6. “记忆加固 / 全部完成”胶囊标签文字垂直居中。
7. “题数”标签、科目标签、成长结算标签文字垂直居中。
8. Android 真机、iOS 真机、开发者工具均无明显偏上/偏下。
```

------

# 三、问题 2：点击查看复习详情/总体结果后异常再次触发完成动画

## 问题等级

```text
P1 高优先级逻辑 / 体验问题
```

## 问题位置

文件：

```text
pages/review-today/review-today.js
pages/review-today/review-today.wxml
```

相关代码链路：

```js
submitGroup()
  -> setData({ phase: 'group-result' })
  -> this._showGroupCelebration(...)

nextGroup()
  -> 如果已经是最后一组
  -> setData({ phase: 'final-result' })
  -> this._showFinalCelebration()
```

当前代码：

```js
// submitGroup 末尾
this.setData({
  phase: 'group-result',
  ...
})
this._showGroupCelebration(groupCorrect, groupQuestions.length)
// nextGroup
if (nextGroupIdx >= this.data.groups.length) {
  this.setData({
    phase: 'final-result',
    ...
  })
  this._showFinalCelebration()
  return
}
```

## 问题原因

用户提交最后一组后，页面已经触发了一次“本组完成”动画。
然后用户点击“查看总体结果”或产品文案中的“查看复习详情”时，`nextGroup()` 又进入最终结果页，并主动调用：

```js
this._showFinalCelebration()
```

所以用户看到的是：

```text
提交后播放一次动画
点击查看结果后又播放一次完成动画
```

这就是重复动画的根因。

------

## 推荐修复方案

建议改成：

```text
最后一组提交成功后，只播放一次最终完成动画。
之后点击“查看总体结果 / 查看复习详情”只切换页面，不再播放动画。
```

也就是说：

1. 如果当前组不是最后一组：提交后播放“本组完成”动画。
2. 如果当前组是最后一组：提交后播放“今日复习完成”动画。
3. 用户点击查看结果页时，只进入 final-result，不再触发任何动画。

------

## 详细修复任务 2.1：增加动画一次性防重标记

修改文件：

```text
pages/review-today/review-today.js
```

在 `Page` 对象中增加实例级标记，不建议放在 `data` 里，因为不需要渲染：

```js
onLoad() {
  this._finalCelebrationShown = false
  this._groupCelebrationKey = ''
  setRenderGuardPage('review-today')
  this._setDateStr()
  this._loadEntry()
},
```

同时在 `startReview()` 开始新一轮复习时重置：

```js
async startReview() {
  this._finalCelebrationShown = false
  this._groupCelebrationKey = ''
  this.setData({ practiceLoading: true, phase: 'practice' })
  ...
}
```

新增方法：

```js
_showFinalCelebrationOnce() {
  if (this._finalCelebrationShown) return
  this._finalCelebrationShown = true
  return this._showFinalCelebration()
}
```

------

## 详细修复任务 2.2：修改 submitGroup 的动画触发逻辑

当前 `submitGroup()` 末尾是：

```js
this.setData({
  phase: 'group-result',
  groups,
  groupResults,
  groupCorrect,
  groupWrong,
  groupSkipped,
  submittingGroup: false,
  allGroupResults,
  totalCorrect,
  totalWrong,
  totalCompleted,
  unansweredCount: groupSkipped,
  _groupProgressStyle: this._calcGroupProgressStyle(this.data.currentGroupIdx + 1, groups.length),
})
this._showGroupCelebration(groupCorrect, groupQuestions.length)
```

建议改为：

```js
const isLastGroup = this.data.currentGroupIdx + 1 >= groups.length

this.setData({
  phase: 'group-result',
  groups,
  groupResults,
  groupCorrect,
  groupWrong,
  groupSkipped,
  submittingGroup: false,
  allGroupResults,
  totalCorrect,
  totalWrong,
  totalCompleted,
  unansweredCount: groupSkipped,
  _groupProgressStyle: this._calcGroupProgressStyle(this.data.currentGroupIdx + 1, groups.length),
})

if (isLastGroup) {
  this._showFinalCelebrationOnce()
} else {
  this._showGroupCelebration(groupCorrect, groupQuestions.length)
}
```

注意：如果当前组有跳过题，并且跳过题被重新加入 `groups`，则当前未必是最后一组。`isLastGroup` 必须基于重新计算后的 `groups.length` 判断。

------

## 详细修复任务 2.3：修改 nextGroup，禁止查看结果时再次播放动画

当前：

```js
if (nextGroupIdx >= this.data.groups.length) {
  const { totalCorrect, totalCompleted, allGroupResults } = this.data
  const denom = totalCompleted || allGroupResults.length
  this.setData({
    phase: 'final-result',
    _accuracyStyle: this._calcAccuracyStyle(totalCorrect, denom),
    _accuracyText: denom > 0 ? `${Math.round(totalCorrect / denom * 100)}%` : '0%',
  })
  this._showFinalCelebration()
  return
}
```

建议改为：

```js
if (nextGroupIdx >= this.data.groups.length) {
  const { totalCorrect, totalCompleted, allGroupResults } = this.data
  const denom = totalCompleted || allGroupResults.length
  this.setData({
    phase: 'final-result',
    _accuracyStyle: this._calcAccuracyStyle(totalCorrect, denom),
    _accuracyText: denom > 0 ? `${Math.round(totalCorrect / denom * 100)}%` : '0%',
  })

  // 这里不要再调用 _showFinalCelebration()
  // 用户点击“查看总体结果/查看复习详情”只做页面切换，不播放完成动画
  return
}
```

------

## 详细修复任务 2.4：修复“已掌握”路径中的重复 final 动画

当前 `confirmMaster()` 中有两处：

```js
this._showFinalCelebration()
```

建议全部替换为：

```js
this._showFinalCelebrationOnce()
```

避免连续标记已掌握、重复进入 final-result 时重复弹动画。

------

## 动画修复验收标准

```text
1. 提交普通组后，只播放“本组完成”动画一次。
2. 提交最后一组后，只播放“今日复习完成”动画一次。
3. 点击“查看总体结果 / 查看复习详情”不再播放任何完成动画。
4. 快速重复点击结果按钮，不会重复弹动画。
5. 标记已掌握导致全部完成时，最终动画最多只出现一次。
6. 动画自动消失、点击消失后，不会重新弹出。
```

------

# 四、问题 3：跳过题重新入队会导致最终统计重复

## 问题等级

```text
P0 严重逻辑问题
```

## 问题位置

文件：

```text
pages/review-today/review-today.js
```

相关代码：

```js
const groupResults = groupQuestions.map(q => {
  const r = res.results.find(rr => rr.question_id === q.question_id)
  const isAnswered = _isQuestionAnswered(q, answers)
  const wasSubmitted = !!r
  return {
    ...q,
    isCorrect: r ? r.is_correct : false,
    correctAnswer: r ? r.correct_answer : '',
    userAnswer: answers[q.schedule_id] || '',
    wasAnswered: isAnswered,
    wasSubmitted,
    wasSkipped: !isAnswered && !wasSubmitted,
  }
})

const allGroupResults = [...this.data.allGroupResults, ...groupResults]
```

以及：

```js
const skippedQuestions = groupQuestions.filter(q => !_isQuestionAnswered(q, answers) && !treatUnansweredAsWrong)
const groups = skippedQuestions.length > 0
  ? [...this.data.groups, skippedQuestions]
  : this.data.groups
```

## 问题原因

当用户选择“仅提交已答”时，未答题会被标记为：

```js
wasSkipped: true
```

但这些 skipped 题又会被重新加入一个新的 group：

```js
skippedQuestions
```

后续用户再次作答这些题时，`allGroupResults` 会出现同一个 `schedule_id` 的两条记录：

```text
第一次：wasSkipped = true
第二次：wasSubmitted = true
```

最终页面使用：

```js
allGroupResults.length
```

展示复习题数，并用于部分统计。

这会导致：

```text
1. 复习题数虚高。
2. 跳过题数量虚高。
3. 最终“已答 X 题 · 跳过 Y 题”可能错误。
4. “复习经验 +N”可能重复计算。
5. 最终正确率分母逻辑不稳定。
```

这是比动画问题更严重的隐藏逻辑问题。

------

## 修复原则

`allGroupResults` 必须按 `schedule_id` 去重。
同一个 `schedule_id` 后一次结果应该覆盖前一次 skipped 结果。

------

## 详细修复任务 3.1：增加结果合并函数

修改文件：

```text
pages/review-today/review-today.js
```

在工具函数区域新增：

```js
function _mergeResultsByScheduleId(oldResults, newResults) {
  const order = []
  const map = {}

  ;(oldResults || []).forEach(function(item) {
    const sid = String(item && item.schedule_id || '')
    if (!sid) return
    if (!map[sid]) order.push(sid)
    map[sid] = item
  })

  ;(newResults || []).forEach(function(item) {
    const sid = String(item && item.schedule_id || '')
    if (!sid) return
    if (!map[sid]) order.push(sid)
    map[sid] = item
  })

  return order.map(function(sid) {
    return map[sid]
  })
}
```

------

## 详细修复任务 3.2：submitGroup 中使用去重合并

把当前：

```js
const allGroupResults = [...this.data.allGroupResults, ...groupResults]
const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasAnswered).length
const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length
```

改为：

```js
const allGroupResults = _mergeResultsByScheduleId(this.data.allGroupResults, groupResults)
const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasSubmitted).length
const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length
```

注意这里建议将：

```js
r.isCorrect && r.wasAnswered
```

改为：

```js
r.isCorrect && r.wasSubmitted
```

因为统计正确数应该基于已提交结果，而不是仅基于本地“是否有答案”。最终以后端批改结果为准。

------

## 详细修复任务 3.3：最终页展示使用唯一题目数

当前 WXML：

```xml
<text class="result-stat-val">{{allGroupResults.length}}</text>
```

如果 `allGroupResults` 已经按 `schedule_id` 去重，这里可以保留。

但如果不做去重，则必须新增字段：

```js
totalUniqueQuestions
```

推荐还是做去重，不增加额外字段。

------

## 跳过题修复验收标准

测试用例：

```text
假设一组 5 题：
- 用户只答 3 题
- 选择“仅提交已答”
- 剩余 2 题重新进入后续组
- 用户之后完成这 2 题
```

修复后应满足：

```text
1. 最终复习题数仍为 5，不是 7。
2. 最终跳过题数为 0。
3. totalCompleted 为 5。
4. totalCorrect + totalWrong = 5。
5. “复习经验 +5”，不是 +7。
6. 正确率分母为 5。
```

------

# 五、问题 4：开始新一轮复习时状态重置不完整

## 问题等级

```text
P2 中优先级逻辑问题
```

## 问题位置

文件：

```text
pages/review-today/review-today.js
```

当前 `startReview()` 中重置了：

```js
allGroupResults: [],
totalCorrect: 0,
totalWrong: 0,
safeModeActive: false,
renderTraces: [],
```

但没有明确重置：

```js
totalCompleted
groupResults
groupCorrect
groupWrong
groupSkipped
unansweredCount
currentQuestion
masterConfirmId
showCelebration
```

## 风险

如果用户在同一次页面生命周期中重新开始复习，可能出现：

```text
1. 上一轮 totalCompleted 残留。
2. 最终页正确率分母错误。
3. 上一组结果数据短暂残留。
4. master 弹窗状态残留。
5. 动画状态残留。
```

------

## 详细修复任务 4.1：补全 startReview 状态重置

修改 `startReview()` 中的 `setData`。

建议改为：

```js
this.setData({
  allQuestions,
  groups,
  currentGroupIdx: 0,
  groupQuestions: groups[0] || [],
  answers: {},
  currentIndex: 0,
  currentQuestion: null,
  optionKeys: [],
  _answeredCount: 0,

  groupResults: [],
  groupCorrect: 0,
  groupWrong: 0,
  groupSkipped: 0,
  unansweredCount: 0,

  allGroupResults: [],
  totalCorrect: 0,
  totalWrong: 0,
  totalCompleted: 0,

  masterConfirmId: null,
  submittingGroup: false,
  animClass: '',
  showCelebration: false,

  safeModeActive: false,
  renderTraces: [],
  practiceLoading: false,
})
```

并在 `startReview()` 开头加：

```js
this._clearCelebrationTimer()
this._finalCelebrationShown = false
this._groupCelebrationKey = ''
```

------

# 六、问题 5：提交结果匹配使用 question_id，存在错位风险

## 问题等级

```text
P2 中优先级逻辑问题
```

## 问题位置

文件：

```text
pages/review-today/review-today.js
```

当前：

```js
const r = res.results.find(rr => rr.question_id === q.question_id)
```

## 问题原因

复习任务的主标识其实是：

```text
schedule_id
```

如果同一道题因为不同复习计划、不同轮次、重复进入复习队列，单纯用 `question_id` 匹配可能错位。

## 修复建议

优先按 `schedule_id` 匹配，如果后端结果暂时没有 `schedule_id`，再 fallback 到 `question_id`。

修改为：

```js
const results = Array.isArray(res && res.results) ? res.results : []

const groupResults = groupQuestions.map(q => {
  const r = results.find(rr => {
    if (rr.schedule_id !== undefined && rr.schedule_id !== null) {
      return String(rr.schedule_id) === String(q.schedule_id)
    }
    return String(rr.question_id) === String(q.question_id)
  })

  const isAnswered = _isQuestionAnswered(q, answers)
  const wasSubmitted = !!r

  return {
    ...q,
    isCorrect: r ? !!r.is_correct : false,
    correctAnswer: r ? (r.correct_answer || '') : '',
    userAnswer: answers[q.schedule_id] || '',
    wasAnswered: isAnswered,
    wasSubmitted,
    wasSkipped: !isAnswered && !wasSubmitted,
  }
})
```

同时建议后端 `/review/grade-batch` 返回结果里增加 `schedule_id`，这样前端可以完全避免错配。

------

# 七、问题 6：res.results 缺少容错，接口异常时可能导致页面报错

## 问题等级

```text
P2 中优先级稳定性问题
```

## 问题位置

文件：

```text
pages/review-today/review-today.js
```

当前：

```js
const res = await api.post('/review/grade-batch', { reviews })
const groupResults = groupQuestions.map(q => {
  const r = res.results.find(rr => rr.question_id === q.question_id)
  ...
})
```

如果接口异常返回：

```js
res = null
```

或：

```js
res.results = undefined
```

页面会直接报错：

```text
Cannot read property 'find' of undefined
```

## 修复任务

增加安全兜底：

```js
const res = await api.post('/review/grade-batch', { reviews })
const results = Array.isArray(res && res.results) ? res.results : []

if (!results.length) {
  wx.showToast({
    title: '批改结果为空，请重试',
    icon: 'none'
  })
  this.setData({ submittingGroup: false })
  return
}
```

如果允许部分结果返回，则不要直接 return，而是按已有结果构造，但要提示：

```js
if (results.length < reviews.length) {
  wx.showToast({
    title: '部分题目批改失败',
    icon: 'none'
  })
}
```

建议使用“允许部分结果”的方案，因为当前页面已经支持 skipped/wasSubmitted 逻辑。

------

# 八、问题 7：结果按钮可被快速重复点击，存在重复状态切换风险

## 问题等级

```text
P3 低到中优先级体验问题
```

## 问题位置

文件：

```text
pages/review-today/review-today.wxml
pages/review-today/review-today.js
```

当前按钮：

```xml
<button class="gradient-btn result-btn" bindtap="nextGroup">
  {{currentGroupIdx + 1 >= groups.length ? '查看总体结果' : '进入下一组'}}
</button>
```

没有防重复点击。

## 修复建议

在 data 中增加：

```js
resultTransitioning: false,
```

修改 `nextGroup()`：

```js
nextGroup() {
  if (this.data.resultTransitioning) return

  this.setData({ resultTransitioning: true })

  const nextGroupIdx = this.data.currentGroupIdx + 1

  if (nextGroupIdx >= this.data.groups.length) {
    const { totalCorrect, totalCompleted, allGroupResults } = this.data
    const denom = totalCompleted || allGroupResults.length
    this.setData({
      phase: 'final-result',
      resultTransitioning: false,
      _accuracyStyle: this._calcAccuracyStyle(totalCorrect, denom),
      _accuracyText: denom > 0 ? `${Math.round(totalCorrect / denom * 100)}%` : '0%',
    })
    return
  }

  this.setData({
    phase: 'practice',
    currentGroupIdx: nextGroupIdx,
    groupQuestions: this.data.groups[nextGroupIdx],
    answers: {},
    currentIndex: 0,
    groupResults: [],
    groupCorrect: 0,
    groupWrong: 0,
    resultTransitioning: false,
  })

  this._syncAnsweredFlags()
  this._showQuestion(0)
}
```

WXML 中可补充 loading/disabled：

```xml
<button
  class="gradient-btn result-btn"
  bindtap="nextGroup"
  loading="{{resultTransitioning}}"
  disabled="{{resultTransitioning}}"
>
  {{currentGroupIdx + 1 >= groups.length ? '查看总体结果' : '进入下一组'}}
</button>
```

------

# 九、建议统一修改后的关键代码片段

以下是建议整合后的核心修改方向。

## 1. 新增工具函数

文件：

```text
pages/review-today/review-today.js
```

放在 `_computeAnsweredCount` 后面即可：

```js
function _mergeResultsByScheduleId(oldResults, newResults) {
  const order = []
  const map = {}

  ;(oldResults || []).forEach(function(item) {
    const sid = String(item && item.schedule_id || '')
    if (!sid) return
    if (!map[sid]) order.push(sid)
    map[sid] = item
  })

  ;(newResults || []).forEach(function(item) {
    const sid = String(item && item.schedule_id || '')
    if (!sid) return
    if (!map[sid]) order.push(sid)
    map[sid] = item
  })

  return order.map(function(sid) {
    return map[sid]
  })
}
```

------

## 2. onLoad 初始化动画防重字段

```js
onLoad() {
  this._finalCelebrationShown = false
  this._groupCelebrationKey = ''
  setRenderGuardPage('review-today')
  this._setDateStr()
  this._loadEntry()
},
```

------

## 3. 新增 final 动画只播放一次的方法

放在“完成反馈”区域：

```js
_showFinalCelebrationOnce() {
  if (this._finalCelebrationShown) return
  this._finalCelebrationShown = true
  return this._showFinalCelebration()
},
```

------

## 4. startReview 补全状态重置

```js
async startReview() {
  this._clearCelebrationTimer()
  this._finalCelebrationShown = false
  this._groupCelebrationKey = ''

  this.setData({
    practiceLoading: true,
    phase: 'practice',
    showCelebration: false,
  })

  try {
    const res = await api.get('/review/today', { limit: 100 })
    const allQuestions = (res.questions || []).map(q => this._enrichQuestion(q))

    if (allQuestions.length === 0) {
      wx.showToast({ title: '今日没有待复习题目', icon: 'none' })
      this.setData({ practiceLoading: false, phase: 'entry' })
      this._loadEntry()
      return
    }

    const groups = this._splitGroups(allQuestions, this.data.groupSize)

    this.setData({
      allQuestions,
      groups,
      currentGroupIdx: 0,
      groupQuestions: groups[0] || [],
      answers: {},
      currentIndex: 0,
      currentQuestion: null,
      optionKeys: [],
      _answeredCount: 0,

      groupResults: [],
      groupCorrect: 0,
      groupWrong: 0,
      groupSkipped: 0,
      unansweredCount: 0,

      allGroupResults: [],
      totalCorrect: 0,
      totalWrong: 0,
      totalCompleted: 0,

      masterConfirmId: null,
      submittingGroup: false,
      resultTransitioning: false,
      animClass: '',

      safeModeActive: false,
      renderTraces: [],
      practiceLoading: false,
    })

    this._showQuestion(0)
    this._syncAnsweredFlags()
  } catch (e) {
    console.error('加载复习题目失败', e)
    this.setData({ practiceLoading: false, phase: 'entry' })
    this._loadEntry()
    wx.showToast({ title: '加载失败', icon: 'none' })
  }
}
```

------

## 5. submitGroup 中替换结果处理逻辑

把接口结果处理部分改为：

```js
const res = await api.post('/review/grade-batch', { reviews })
const results = Array.isArray(res && res.results) ? res.results : []

if (results.length < reviews.length) {
  wx.showToast({
    title: results.length ? '部分题目批改失败' : '批改结果为空，请重试',
    icon: 'none'
  })

  if (!results.length) {
    this.setData({ submittingGroup: false })
    return
  }
}

const groupResults = groupQuestions.map(q => {
  const r = results.find(rr => {
    if (rr.schedule_id !== undefined && rr.schedule_id !== null) {
      return String(rr.schedule_id) === String(q.schedule_id)
    }
    return String(rr.question_id) === String(q.question_id)
  })

  const isAnswered = _isQuestionAnswered(q, answers)
  const wasSubmitted = !!r

  return {
    ...q,
    isCorrect: r ? !!r.is_correct : false,
    correctAnswer: r ? (r.correct_answer || '') : '',
    userAnswer: answers[q.schedule_id] || '',
    wasAnswered: isAnswered,
    wasSubmitted,
    wasSkipped: !isAnswered && !wasSubmitted,
  }
})

const groupCorrect = groupResults.filter(r => r.isCorrect && r.wasSubmitted).length
const groupWrong = groupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
const groupSkipped = groupResults.filter(r => r.wasSkipped).length

const allGroupResults = _mergeResultsByScheduleId(this.data.allGroupResults, groupResults)
const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasSubmitted).length
const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length

const skippedQuestions = groupQuestions.filter(q => !_isQuestionAnswered(q, answers) && !treatUnansweredAsWrong)
const groups = skippedQuestions.length > 0
  ? [...this.data.groups, skippedQuestions]
  : this.data.groups

const isLastGroup = this.data.currentGroupIdx + 1 >= groups.length

this.setData({
  phase: 'group-result',
  groups,
  groupResults,
  groupCorrect,
  groupWrong,
  groupSkipped,
  submittingGroup: false,
  allGroupResults,
  totalCorrect,
  totalWrong,
  totalCompleted,
  unansweredCount: groupSkipped,
  _groupProgressStyle: this._calcGroupProgressStyle(this.data.currentGroupIdx + 1, groups.length),
})

if (isLastGroup) {
  this._showFinalCelebrationOnce()
} else {
  this._showGroupCelebration(groupCorrect, groupQuestions.length)
}
```

------

## 6. nextGroup 去掉 final 动画调用

```js
nextGroup() {
  if (this.data.resultTransitioning) return

  this.setData({ resultTransitioning: true })

  const nextGroupIdx = this.data.currentGroupIdx + 1

  if (nextGroupIdx >= this.data.groups.length) {
    const { totalCorrect, totalCompleted, allGroupResults } = this.data
    const denom = totalCompleted || allGroupResults.length

    this.setData({
      phase: 'final-result',
      resultTransitioning: false,
      _accuracyStyle: this._calcAccuracyStyle(totalCorrect, denom),
      _accuracyText: denom > 0 ? `${Math.round(totalCorrect / denom * 100)}%` : '0%',
    })

    // 注意：这里不要调用 _showFinalCelebration()
    return
  }

  this.setData({
    phase: 'practice',
    currentGroupIdx: nextGroupIdx,
    groupQuestions: this.data.groups[nextGroupIdx],
    answers: {},
    currentIndex: 0,
    groupResults: [],
    groupCorrect: 0,
    groupWrong: 0,
    groupSkipped: 0,
    unansweredCount: 0,
    resultTransitioning: false,
  })

  this._syncAnsweredFlags()
  this._showQuestion(0)
}
```

------

## 7. confirmMaster 中替换 final 动画调用

把：

```js
this._showFinalCelebration()
```

全部替换为：

```js
this._showFinalCelebrationOnce()
```

------

# 十、最终回归测试清单

修复完成后，请逐项测试。

## UI 测试

```text
1. 入口页：
   - “开始今日复习”按钮文字垂直居中。
   - “5题/10题/20题”标签文字垂直居中。
   - “记忆加固/全部完成”标签文字垂直居中。
   - “今日待复习”等统计卡片无明显偏移。

2. 练习页：
   - 题号圆点数字居中。
   - 科目标签文字居中。
   - “已掌握”图标居中。
   - 选项单行/多行显示自然。
   - “上一题/下一题/提交本组复盘”按钮文字居中。

3. 组结果页：
   - 奖章文字居中。
   - 统计数字居中。
   - “查看总体结果/进入下一组”按钮文字居中。

4. 最终结果页：
   - 正确率圆环文字居中。
   - “成长结算”标签文字居中。
   - “完成”按钮文字居中。
```

------

## 动画测试

```text
场景 A：非最后一组
1. 提交本组。
2. 只播放“本组完成”动画一次。
3. 点击“进入下一组”不播放最终完成动画。

场景 B：最后一组
1. 提交最后一组。
2. 只播放“今日复习完成”动画一次。
3. 点击“查看总体结果/查看复习详情”不再播放动画。

场景 C：快速点击
1. 快速重复点击“查看总体结果”。
2. 不重复进入 final-result。
3. 不重复播放动画。

场景 D：已掌握
1. 连续标记题目为已掌握。
2. 如果因此全部完成，最终动画最多播放一次。
```

------

## 跳过题测试

```text
测试数据：一组 5 题。

操作：
1. 只答 3 题。
2. 提交时选择“仅提交已答”。
3. 剩余 2 题进入后续复习组。
4. 再完成这 2 题。
5. 查看最终结果。

期望：
1. 最终复习题数 = 5。
2. totalCompleted = 5。
3. 跳过题数 = 0。
4. totalCorrect + totalWrong = 5。
5. 正确率分母 = 5。
6. 复习经验显示 +5，而不是 +7。
```

------

## 接口异常测试

```text
1. 模拟 /review/grade-batch 返回 results = undefined。
   - 页面不能崩溃。
   - 应提示“批改结果为空，请重试”。

2. 模拟 results.length < reviews.length。
   - 页面不能崩溃。
   - 应提示“部分题目批改失败”。
   - 有结果的题目正常展示。
```

------

## 语法检查

修复后执行：

```bash
node --check pages/review-today/review-today.js
```

要求无语法错误。

如果项目支持批量检查：

```bash
find pages/review-today -name "*.js" -print0 | xargs -0 -n1 node --check
```

------

# 十一、最终修复优先级

建议按以下顺序修：

```text
P0：
1. 修复跳过题重新入队导致 allGroupResults 重复统计的问题。

P1：
2. 修复查看复习详情/总体结果时重复触发完成动画的问题。
3. 修复按钮、标签、胶囊文字垂直居中问题。

P2：
4. startReview 补全状态重置。
5. grade-batch 结果匹配从 question_id 优先改为 schedule_id。
6. res.results 增加容错。

P3：
7. 结果页按钮增加防重复点击。
8. 微调选项 indicator 与文字的视觉对齐。
```

------

# 十二、修复完成后的交付要求

修复完成后请输出：

```text
1. 修改过的文件列表。
2. 每个文件具体修了什么。
3. 关键代码片段。
4. UI 垂直居中修复前后说明。
5. 动画重复触发的根因与修复说明。
6. 跳过题重复统计的根因与修复说明。
7. 自测结果：
   - JS 语法检查结果
   - 非最后一组提交流程
   - 最后一组提交流程
   - 查看复习详情/总体结果流程
   - 跳过题重新入队流程
   - Android / iOS 真机 UI 居中表现
```

最终目标：

```text
pages/review-today 页面不再出现字体垂直不居中；
提交后查看复习详情/总体结果不再重复触发完成动画；
跳过题重新复习后最终统计不重复；
页面状态切换稳定，接口异常时不崩溃。
```