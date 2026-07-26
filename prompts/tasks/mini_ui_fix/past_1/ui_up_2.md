你是一名资深微信小程序前端工程师。请继续优化并重构 `pages/practice-result/` 练习结果页 UI。

## 一、优化目标

当前 `practice-result` 页面虽然已经计划做结果页重构，但仍然存在信息分散、模块偏多、Hero 头部占空间、数据展示不够集中的问题。

本次优化目标是：

```text
去掉 Hero 头部
去掉大面积结果横幅
减少独立卡片数量
核心数据集中在一个主结果卡中
成长信息弱化为辅助行
错题入口轻量化
答题详情默认折叠
底部只保留一个主按钮和一个次按钮
```

最终页面不要做成“庆祝型结算页”，而应做成：

```text
简洁的练习结果摘要页
```

用户进入页面后，应能在首屏快速看到：

```text
正确率
答对数
错题数
总题数
用时
跳过数
最推荐的下一步动作
```

不要让这些数据分散到多个大卡片中。

------

## 二、涉及文件

请重点修改：

```text
pages/practice-result/practice-result.wxml
pages/practice-result/practice-result.wxss
pages/practice-result/practice-result.js
pages/practice-result/practice-result.json
```

不要影响：

```text
pages/practice/
pages/review-today/
pages/wrong-book/
pages/wrong-detail/
pages/home/
components/AnimatedView/
utils/api.js
utils/math-format.js
```

除非确有必要，不要修改全局样式和其他页面。

------

## 三、当前页面已有数据

当前页面已有或可计算的数据包括：

```js
correct
wrong
skipped
total
answeredCount
passRate
subject
subjectDisplay
duration
durationText
results
showDetail
growthTitle
growthDesc
growthLevel
growthExpText
growthLevelPct
growthBadgeCount
```

真正需要作为主视觉展示的是：

```text
正确率 passRate
答对数 correct
错题数 wrong
总题数 total
跳过数 skipped
用时 durationText
科目 subjectDisplay
```

`results` 用于折叠答题详情。

`growthTitle`、`growthDesc`、`growthLevel`、`growthExpText`、`growthLevelPct`、`growthBadgeCount` 只能作为辅助信息，不应抢占结果页主视觉。

------

## 四、核心设计原则

请遵循以下原则：

1. 不使用 Hero 头部；
2. 不使用大面积渐变结果横幅；
3. 不使用大插画；
4. 不默认展示复杂庆祝动效；
5. 不拆出过多独立统计卡；
6. 正确率、答对、错题、总题、用时、跳过数集中在一个主结果卡；
7. 成长信息只作为主结果卡底部的轻量辅助行；
8. 错题入口只做轻量提醒，不做大卡片；
9. 答题详情默认折叠；
10. 底部只保留两个操作按钮；
11. 页面整体应紧凑、清晰、结果导向。

------

## 五、推荐页面结构

最终页面压缩为以下 5 个区域：

```text
1. 简短页面标题
2. 集中式结果摘要卡
3. 简短行动建议卡
4. 折叠答题详情
5. 底部固定操作按钮
```

不再使用：

```text
大型 Hero
独立正确率卡
独立错题大卡
独立成长大卡
独立完成状态大卡
多个并列操作按钮
大面积装饰背景
默认展开的答题详情
```

------

## 六、推荐 WXML 结构

请将 `practice-result.wxml` 改造成类似以下结构：

```html
<view class="page result-page">
  <!-- 高分时可保留轻量动效，但不要作为主内容 -->
  <animated-view
    wx:if="{{showCelebration && shouldShowCelebration}}"
    bind:close="dismissCelebration"
  />

  <!-- 1. 简短标题，不做 Hero -->
  <view class="result-header">
    <text class="result-title">{{resultTitle}}</text>
    <text class="result-subtitle">{{resultDesc}}</text>
  </view>

  <!-- 2. 集中式结果摘要卡 -->
  <view class="result-summary-card {{resultLevelClass}}">
    <view class="summary-top">
      <view class="accuracy-block">
        <text class="accuracy-value">{{passRate || 0}}</text>
        <text class="accuracy-unit">%</text>
        <text class="accuracy-label">正确率</text>
      </view>

      <view class="summary-status">
        <text class="status-text">{{statusText}}</text>
        <text class="status-desc">{{statusDesc}}</text>
      </view>
    </view>

    <view class="summary-grid">
      <view class="summary-item">
        <text class="summary-value">{{correct}}</text>
        <text class="summary-label">答对</text>
      </view>

      <view class="summary-item">
        <text class="summary-value">{{wrong}}</text>
        <text class="summary-label">错题</text>
      </view>

      <view class="summary-item">
        <text class="summary-value">{{total}}</text>
        <text class="summary-label">总题</text>
      </view>

      <view class="summary-item">
        <text class="summary-value">{{durationText}}</text>
        <text class="summary-label">用时</text>
      </view>
    </view>

    <view class="summary-extra" wx:if="{{skipped > 0 || subjectDisplay || growthExpText}}">
      <text wx:if="{{subjectDisplay}}">{{subjectDisplay}}</text>
      <text wx:if="{{subjectDisplay && skipped > 0}}"> · </text>
      <text wx:if="{{skipped > 0}}">跳过 {{skipped}} 题</text>
      <text wx:if="{{(subjectDisplay || skipped > 0) && growthExpText}}"> · </text>
      <text wx:if="{{growthExpText}}">{{growthExpText}}</text>
    </view>

    <view class="growth-mini-line" wx:if="{{growthLevel && growthLevelPct >= 0}}">
      <view class="growth-mini-texts">
        <text class="growth-mini-title">{{growthTitle || '成长进度'}}</text>
        <text class="growth-mini-level">{{growthLevel}}</text>
      </view>
      <view class="growth-mini-track">
        <view class="growth-mini-fill" style="width: {{growthLevelPct}}%"></view>
      </view>
    </view>
  </view>

  <!-- 3. 简短行动建议 -->
  <view class="result-advice-card {{nextStepType}}">
    <view class="advice-head">
      <text class="advice-title">{{nextStepTitle}}</text>
      <text class="advice-tag">{{nextStepTag}}</text>
    </view>
    <text class="advice-desc">{{nextStepDesc}}</text>
  </view>

  <!-- 有错题时，只显示轻量入口，不做大错题卡 -->
  <view class="wrong-inline-tip" wx:if="{{wrong > 0}}" bindtap="goWrongBook">
    <text class="wrong-tip-text">本次产生 {{wrong}} 道错题，建议优先复盘</text>
    <text class="wrong-tip-action">去复盘</text>
  </view>

  <!-- 4. 答题详情：默认折叠 -->
  <view class="detail-card" wx:if="{{results.length > 0}}">
    <view class="detail-toggle" bindtap="toggleDetail">
      <view class="detail-toggle-main">
        <text class="detail-title">答题详情</text>
        <text class="detail-subtitle">查看每道题的对错情况</text>
      </view>
      <text class="detail-toggle-text">{{showDetail ? '收起' : '展开'}}</text>
    </view>

    <view class="detail-list" wx:if="{{showDetail}}">
      <view
        class="detail-row {{item._cls}}"
        wx:for="{{compactResults}}"
        wx:key="question_id"
      >
        <view class="detail-row-left">
          <text class="detail-index">{{item._displayIndex}}</text>
          <text class="detail-status">{{item._label}}</text>
        </view>

        <view class="detail-row-body">
          <text class="detail-stem" wx:if="{{item._stemPreview}}">{{item._stemPreview}}</text>

          <view class="detail-answer-line">
            <text class="detail-user-answer" wx:if="{{item._userAnswer}}">
              我的：{{item._userAnswer}}
            </text>
            <text class="detail-right-answer" wx:if="{{item.correct_answer}}">
              正确：{{item.correct_answer}}
            </text>
          </view>
        </view>
      </view>
    </view>
  </view>

  <view class="bottom-safe-space"></view>

  <!-- 5. 底部固定按钮 -->
  <view class="bottom-actions">
    <button
      class="action-primary"
      wx:if="{{wrong > 0}}"
      bindtap="goWrongBook"
    >
      复盘错题
    </button>

    <button
      class="action-primary"
      wx:else
      bindtap="practiceAgain"
    >
      再来一组
    </button>

    <button
      class="action-secondary"
      wx:if="{{wrong > 0}}"
      bindtap="practiceAgain"
    >
      继续练习
    </button>

    <button
      class="action-secondary"
      wx:else
      bindtap="goHome"
    >
      返回首页
    </button>
  </view>
</view>
```

如果 WXML 中不适合直接使用 `compactResults`，请在 JS 中提前计算。
不要在 WXML 中写复杂表达式。

------

## 七、JS 视图模型要求

请在 `practice-result.js` 中新增或继续优化：

```js
_buildResultViewModel()
```

它负责生成页面展示所需的衍生字段。

推荐新增字段：

```js
resultLevelClass: '',
resultTitle: '',
resultDesc: '',
statusText: '',
statusDesc: '',

nextStepType: '',
nextStepTitle: '',
nextStepDesc: '',
nextStepTag: '',

shouldShowCelebration: false,
compactResults: []
```

不要把大量判断逻辑写在 WXML 里。

------

## 八、结果文案规则

### 1. total 为 0

```js
resultLevelClass = 'empty'
resultTitle = '暂无练习结果'
resultDesc = '本次没有可统计的答题数据'
statusText = '未完成'
statusDesc = '返回练习后再试一次'
nextStepType = 'start'
nextStepTitle = '重新开始练习'
nextStepDesc = '完成一组练习后，这里会生成正确率和答题情况'
nextStepTag = '未开始'
shouldShowCelebration = false
```

### 2. passRate >= 90

```js
resultLevelClass = 'excellent'
resultTitle = '练习完成'
resultDesc = '这组正确率很高，整体掌握不错'
statusText = '表现很稳'
statusDesc = '可以继续保持节奏'
nextStepType = 'continue'
nextStepTitle = wrong > 0 ? '先复盘少量错题' : '可以继续挑战'
nextStepDesc = wrong > 0
  ? '本组仍有少量错题，建议先处理后再继续练习'
  : '本组没有明显薄弱点，可以再来一组巩固手感'
nextStepTag = wrong > 0 ? '推荐' : '继续'
```

### 3. passRate >= 70

```js
resultLevelClass = 'good'
resultTitle = '练习完成'
resultDesc = '整体掌握较好，但还有可以优化的地方'
statusText = '完成不错'
statusDesc = '错题值得复盘'
nextStepType = wrong > 0 ? 'review' : 'continue'
nextStepTitle = wrong > 0 ? '建议先复盘错题' : '可以继续练习'
nextStepDesc = wrong > 0
  ? '把本组错题处理掉，再继续下一组练习'
  : '本组完成情况不错，可以继续保持'
nextStepTag = wrong > 0 ? '复盘优先' : '继续'
```

### 4. passRate >= 50

```js
resultLevelClass = 'normal'
resultTitle = '练习完成'
resultDesc = '这组暴露了一些薄弱点'
statusText = '需要复盘'
statusDesc = '先看错题更有效'
nextStepType = 'review'
nextStepTitle = '优先处理薄弱点'
nextStepDesc = '建议先查看错题，找出容易失误的知识点'
nextStepTag = '复盘优先'
```

### 5. passRate < 50

```js
resultLevelClass = 'weak'
resultTitle = '练习完成'
resultDesc = '本组错题较多，不建议直接继续刷题'
statusText = '错题较多'
statusDesc = '先复盘比继续刷题更重要'
nextStepType = 'review'
nextStepTitle = '建议立即复盘'
nextStepDesc = '先把错误原因搞清楚，这次练习才真正有效'
nextStepTag = '重点'
```

------

## 九、动效优化要求

当前页面可以保留 `AnimatedView`，但必须弱化触发条件。

要求：

1. 不要所有结果都显示庆祝动效；
2. 低正确率不要显示强庆祝动效；
3. 动效不能遮挡结果太久；
4. 保留 `dismissCelebration`、`onHide`、`onUnload` 清理逻辑；
5. 不要把动效作为页面主要视觉。

推荐规则：

```js
shouldShowCelebration = passRate >= 90 || (total <= 5 && passRate === 100)
```

如果 `wrong > 0` 且 `passRate < 90`，默认不显示庆祝动效。

------

## 十、答题详情优化要求

答题详情必须默认折叠。

展开后使用紧凑列表，不展示完整解析。

每条只展示：

```text
题号
正确 / 错误 / 跳过状态
题干摘要
我的答案
正确答案
```

不要在结果页展示：

```text
完整题干长内容
完整解析
AI 复盘
大量公式详情
```

这些应交给错题详情页或错题本页面。

建议在 JS 中生成：

```js
compactResults = results.map((item, index) => ({
  ...item,
  _displayIndex: index + 1,
  _isWrong: item.is_correct === false || item._cls === 'wrong',
  _label: item._label || computedLabel,
  _stemPreview: computedStemPreview,
  _userAnswer: computedUserAnswer
}))
```

如果 `wrong > 0`，详情列表可以将错题排在前面，但必须保留原题号。

------

## 十一、成长信息优化要求

成长信息不能再作为独立大卡片展示。

请将成长内容压缩为主结果卡底部的轻量辅助区域：

```text
成长经验
当前等级
经验进度条
```

要求：

1. 不使用大面积深色卡片；
2. 不使用大渐变；
3. 不比正确率更抢眼；
4. 没有成长数据时不显示；
5. 不影响主结果和复盘建议。

------

## 十二、操作按钮逻辑

底部只保留两个按钮。

### 有错题时

```text
主按钮：复盘错题
次按钮：继续练习
```

### 没有错题时

```text
主按钮：再来一组
次按钮：返回首页
```

### total 为 0 时

```text
主按钮：返回练习
次按钮：返回首页
```

不要出现三个同等重量按钮。
不要在页面中部和底部重复放置相同按钮。
错题入口如果已经在底部作为主按钮，页面中部只保留轻量提示，不再放大按钮。

------

## 十三、WXSS 优化要求

请重写或清理 `practice-result.wxss` 中结果页相关样式。

目标：

```text
紧凑
清晰
少装饰
高信息密度
单主卡片
弱化成长
弱化动效
强行动引导
```

建议样式模块：

```css
/* page */
/* simple header */
/* summary card */
/* accuracy block */
/* summary grid */
/* growth mini */
/* advice card */
/* wrong inline tip */
/* detail compact list */
/* bottom actions */
/* states */
```

页面基础样式：

```css
.result-page {
  min-height: 100vh;
  padding: 32rpx 24rpx 0;
  background: #F6F8FF;
  box-sizing: border-box;
}
```

简短标题：

```css
.result-header {
  margin-bottom: 20rpx;
}

.result-title {
  display: block;
  font-size: 38rpx;
  font-weight: 800;
  color: #18233A;
  line-height: 1.25;
}

.result-subtitle {
  display: block;
  margin-top: 8rpx;
  font-size: 25rpx;
  color: #617089;
  line-height: 1.5;
}
```

主结果卡：

```css
.result-summary-card {
  padding: 28rpx;
  border-radius: 28rpx;
  background: #FFFFFF;
  border: 1rpx solid #E2EAF7;
  box-shadow: 0 12rpx 32rpx rgba(27, 59, 114, 0.06);
}

.summary-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24rpx;
  padding-bottom: 24rpx;
  border-bottom: 1rpx solid #EEF2F8;
}

.accuracy-block {
  min-width: 190rpx;
}

.accuracy-value {
  font-size: 72rpx;
  font-weight: 900;
  color: #4F7FFF;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.accuracy-unit {
  font-size: 30rpx;
  font-weight: 800;
  color: #4F7FFF;
}

.accuracy-label {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #8EA0BA;
}

.summary-status {
  flex: 1;
  text-align: right;
}

.status-text {
  display: block;
  font-size: 30rpx;
  font-weight: 800;
  color: #18233A;
}

.status-desc {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #617089;
  line-height: 1.5;
}
```

数据四宫格：

```css
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12rpx;
  margin-top: 24rpx;
}

.summary-item {
  min-width: 0;
  padding: 16rpx 8rpx;
  border-radius: 18rpx;
  background: #F7FAFF;
  text-align: center;
}

.summary-value {
  display: block;
  font-size: 32rpx;
  font-weight: 850;
  color: #18233A;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.summary-label {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #8EA0BA;
}
```

辅助行：

```css
.summary-extra {
  margin-top: 18rpx;
  padding-top: 16rpx;
  border-top: 1rpx dashed #E2EAF7;
  font-size: 24rpx;
  color: #617089;
  line-height: 1.5;
}
```

成长轻量条：

```css
.growth-mini-line {
  margin-top: 18rpx;
  padding-top: 16rpx;
  border-top: 1rpx dashed #E2EAF7;
}

.growth-mini-texts {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 10rpx;
}

.growth-mini-title {
  font-size: 24rpx;
  color: #617089;
}

.growth-mini-level {
  font-size: 24rpx;
  font-weight: 700;
  color: #4F7FFF;
}

.growth-mini-track {
  height: 10rpx;
  border-radius: 999rpx;
  background: #EEF4FF;
  overflow: hidden;
}

.growth-mini-fill {
  height: 100%;
  border-radius: 999rpx;
  background: #4F7FFF;
}
```

建议卡：

```css
.result-advice-card {
  margin-top: 20rpx;
  padding: 22rpx 24rpx;
  border-radius: 24rpx;
  background: #FFFFFF;
  border: 1rpx solid #E2EAF7;
}

.advice-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.advice-title {
  font-size: 29rpx;
  font-weight: 800;
  color: #18233A;
}

.advice-tag {
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  background: #EEF4FF;
  color: #4F7FFF;
  font-size: 21rpx;
  font-weight: 700;
}

.advice-desc {
  display: block;
  margin-top: 10rpx;
  font-size: 25rpx;
  color: #617089;
  line-height: 1.55;
}
```

轻量错题提示：

```css
.wrong-inline-tip {
  margin-top: 18rpx;
  padding: 20rpx 22rpx;
  border-radius: 22rpx;
  background: #FFF5F5;
  border: 1rpx solid #FFE0E0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.wrong-tip-text {
  flex: 1;
  font-size: 25rpx;
  color: #B42318;
  line-height: 1.45;
}

.wrong-tip-action {
  font-size: 25rpx;
  font-weight: 800;
  color: #EF4444;
}
```

底部按钮：

```css
.bottom-actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 18rpx 24rpx calc(18rpx + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.96);
  border-top: 1rpx solid rgba(226, 234, 247, 0.9);
  display: flex;
  gap: 16rpx;
  z-index: 20;
}

.action-primary {
  flex: 1;
  height: 88rpx;
  border-radius: 999rpx;
  background: #4F7FFF;
  color: #FFFFFF;
  font-size: 29rpx;
  font-weight: 800;
}

.action-secondary {
  width: 210rpx;
  height: 88rpx;
  border-radius: 999rpx;
  background: #EEF4FF;
  color: #4F7FFF;
  font-size: 28rpx;
  font-weight: 700;
}

.bottom-safe-space {
  height: 140rpx;
}
```

------

## 十四、状态颜色要求

不同结果状态只轻微改变正确率颜色，不要给整个页面加大面积状态色。

```css
.result-summary-card.excellent .accuracy-value,
.result-summary-card.excellent .accuracy-unit {
  color: #22C55E;
}

.result-summary-card.good .accuracy-value,
.result-summary-card.good .accuracy-unit {
  color: #4F7FFF;
}

.result-summary-card.normal .accuracy-value,
.result-summary-card.normal .accuracy-unit {
  color: #F59E0B;
}

.result-summary-card.weak .accuracy-value,
.result-summary-card.weak .accuracy-unit {
  color: #EF4444;
}
```

------

## 十五、需要删除或弱化的旧元素

请检查并删除或弱化以下 UI：

```text
Hero 头部
大面积结果横幅
大面积渐变背景
复杂庆祝装饰
独立错题摘要大卡
独立成长结算大卡
多个重复统计卡
默认展开答题详情
三个同级按钮
过长鼓励文案
过重阴影
```

------

## 十六、边界状态处理

必须处理以下情况：

### total 为 0

不能显示 `NaN%`。
显示：

```text
暂无练习结果
本次没有可统计的答题数据
```

按钮：

```text
返回练习
返回首页
```

### results 为空

不显示答题详情卡片。

### wrong 为 0

不显示错题提示。
主按钮为：

```text
再来一组
```

### skipped > 0

不要单独做大提醒卡。
只在主结果卡底部显示：

```text
跳过 X 题
```

### growth 数据为空

不显示成长辅助行。

------

## 十七、不要破坏的功能

必须保持以下功能正常：

```text
从 practice 页面跳转到 practice-result
通过 options 正确读取 correct / wrong / total / duration / subject_id / subject_name
从 storage 中读取 lastPracticeResult
格式化 correct_answer
展示 / 折叠答题详情
查看错题 goWrongBook
再来一组 practiceAgain
返回首页 goHome
加载 growth 数据
清理 celebration timer
```

不要改变接口：

```js
api.get('/stats/growth')
```

不要改变 storage key：

```js
lastPracticeResult
```

------

## 十八、验收标准

完成后请逐项检查：

1. 页面没有 Hero 大头部；
2. 页面没有大面积结果横幅；
3. 正确率是主视觉；
4. 答对、错题、总题、用时集中在同一个主结果卡；
5. 跳过数、科目、成长信息只作为辅助行；
6. 页面卡片数量明显减少；
7. 成长结算不抢主视觉；
8. 有错题时，主按钮是“复盘错题”；
9. 无错题时，主按钮是“再来一组”；
10. 不出现三个同等重量按钮；
11. 答题详情默认折叠；
12. 答题详情展开后紧凑清晰；
13. `total = 0` 时不出现 `NaN%`；
14. `results` 为空时不显示空详情卡；
15. 底部按钮固定且不遮挡内容；
16. 小屏手机首屏不拥挤；
17. 原有跳转、数据读取、growth 加载不被破坏；
18. 微信开发者工具无 WXML / WXSS / JS 报错。

------

## 十九、推荐实施顺序

请按以下顺序执行：

### 第一步：调整 JS 视图模型

在 `practice-result.js` 中新增或优化 `_buildResultViewModel()`，生成：

```text
resultLevelClass
resultTitle
resultDesc
statusText
statusDesc
nextStepType
nextStepTitle
nextStepDesc
nextStepTag
shouldShowCelebration
compactResults
```

### 第二步：重构 WXML

将页面结构压缩为：

```text
result-header
result-summary-card
result-advice-card
wrong-inline-tip
detail-card
bottom-actions
```

### 第三步：清理 WXSS

删除 Hero、大结果横幅、大成长卡、大错题卡等旧样式。
按新模块重写样式。

### 第四步：回归测试

至少测试：

```text
高正确率无错题
高正确率有少量错题
低正确率多错题
有跳过题
total 为 0
results 为空
growth 数据为空
```

------

## 二十、最终交付说明

完成后请说明：

1. 删除或弱化了哪些 Hero / 装饰性元素；
2. 核心数据如何集中展示；
3. 新增或调整了哪些视图模型字段；
4. 成长信息如何被弱化；
5. 答题详情如何变为紧凑折叠；
6. 有错题、无错题、total 为 0 时底部按钮如何展示；
7. 是否保留原有跳转、数据读取、growth 加载和动效清理功能。