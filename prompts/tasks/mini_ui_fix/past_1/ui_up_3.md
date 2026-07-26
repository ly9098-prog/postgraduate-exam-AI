你是一名资深微信小程序前端工程师。请继续优化 `pages/review-today/` 的今日复习最终结果页 UI。

## 一、优化目标

当前结果页不要再使用大面积 Hero 头部，也不要把数据分散到多个卡片中。

本次优化目标是：

```text
去掉 Hero 头部
减少装饰性区域
减少卡片数量
核心数据集中展示
页面首屏更紧凑
行动按钮更明确
整体更像“结果摘要页”，而不是“完成庆祝页”
```

最终页面应突出：

```text
今日复习是否完成
正确率
复习题数
答对数
错题数
完成组数
下一步建议
```

不要把这些数据分散在过多模块中。

------

## 二、核心设计原则

请遵循以下原则：

1. 不使用大 Hero；
2. 不使用大插画；
3. 不使用大面积渐变背景；
4. 不做复杂完成动效；
5. 不要堆叠太多卡片；
6. 核心数据集中在一个主卡片中；
7. 建议区域只保留一条最重要的建议；
8. 底部只保留一个主按钮和一个次按钮；
9. 页面整体应简洁、紧凑、易扫读。

------

## 三、推荐页面结构

最终结果页建议压缩为以下 4 个区域：

```text
1. 页面标题栏 / 简短完成状态
2. 集中式结果摘要卡
3. 简短复盘建议卡
4. 底部固定操作按钮
```

不再使用：

```text
大型 Hero
独立正确率卡
独立错题卡
独立分组卡
独立完成卡
多层鼓励文案
大面积成长 / 成就模块
```

------

## 四、推荐 WXML 结构

请将最终结果态改造成类似以下结构：

```html
<view class="review-result-page" wx:if="{{reviewFinished}}">
  <!-- 顶部简短标题，不做 Hero -->
  <view class="result-header">
    <text class="result-title">{{reviewResultVm.resultTitle}}</text>
    <text class="result-subtitle">{{reviewResultVm.resultDesc}}</text>
  </view>

  <!-- 集中式结果摘要卡 -->
  <view class="result-summary-card {{reviewResultVm.resultLevelClass}}">
    <view class="summary-top">
      <view class="accuracy-block">
        <text class="accuracy-value">{{reviewResultVm.accuracy}}</text>
        <text class="accuracy-unit">%</text>
        <text class="accuracy-label">正确率</text>
      </view>

      <view class="summary-status">
        <text class="status-text">{{reviewResultVm.statusText}}</text>
        <text class="status-desc">{{reviewResultVm.statusDesc}}</text>
      </view>
    </view>

    <view class="summary-grid">
      <view class="summary-item">
        <text class="summary-value">{{reviewResultVm.total}}</text>
        <text class="summary-label">复习题数</text>
      </view>

      <view class="summary-item">
        <text class="summary-value">{{reviewResultVm.correct}}</text>
        <text class="summary-label">答对</text>
      </view>

      <view class="summary-item">
        <text class="summary-value">{{reviewResultVm.wrong}}</text>
        <text class="summary-label">错题</text>
      </view>

      <view class="summary-item">
        <text class="summary-value">{{reviewResultVm.completedGroupCount}}/{{reviewResultVm.groupCount}}</text>
        <text class="summary-label">完成组</text>
      </view>
    </view>

    <view class="summary-extra" wx:if="{{reviewResultVm.skipped > 0 || reviewResultVm.masteredCount > 0}}">
      <text wx:if="{{reviewResultVm.skipped > 0}}">未完成 {{reviewResultVm.skipped}} 题</text>
      <text wx:if="{{reviewResultVm.skipped > 0 && reviewResultVm.masteredCount > 0}}"> · </text>
      <text wx:if="{{reviewResultVm.masteredCount > 0}}">已掌握 {{reviewResultVm.masteredCount}} 题</text>
    </view>
  </view>

  <!-- 简短建议，只保留一条核心行动建议 -->
  <view class="result-advice-card {{reviewResultVm.nextStepType}}">
    <view class="advice-head">
      <text class="advice-title">{{reviewResultVm.nextStepTitle}}</text>
      <text class="advice-tag">{{reviewResultVm.nextStepTag}}</text>
    </view>
    <text class="advice-desc">{{reviewResultVm.nextStepDesc}}</text>
  </view>

  <!-- 可选：仅当有错题时显示轻量错题入口，不再单独做大卡片 -->
  <view class="wrong-inline-tip" wx:if="{{reviewResultVm.wrong > 0}}" bindtap="goWrongBook">
    <text class="wrong-tip-text">今日新增 {{reviewResultVm.wrong}} 道错题，建议立即复盘</text>
    <text class="wrong-tip-action">去复盘</text>
  </view>

  <view class="bottom-safe-space"></view>

  <!-- 底部操作 -->
  <view class="review-bottom-actions">
    <button
      class="action-primary"
      wx:if="{{reviewResultVm.wrong > 0}}"
      bindtap="goWrongBook"
    >
      复盘错题
    </button>

    <button
      class="action-primary"
      wx:else
      bindtap="goHome"
    >
      完成
    </button>

    <button class="action-secondary" bindtap="goPractice">
      继续练习
    </button>
  </view>
</view>
```

注意：
如果当前页面没有 `reviewFinished` 字段，请使用实际完成态字段替代。

------

## 五、结果页数据集中展示要求

所有核心数据必须集中在 `result-summary-card` 内，不要分散到多个卡片。

核心数据包括：

```text
正确率
复习题数
答对数
错题数
完成组数
跳过 / 未完成题数
已掌握数量
```

其中：

```text
正确率：主视觉
复习题数 / 答对 / 错题 / 完成组：四宫格
跳过 / 已掌握：放在卡片底部一行轻提示
```

不要再单独创建：

```text
错题大卡片
完成组大卡片
正确率大 Hero
今日完成大横幅
```

------

## 六、JS 视图模型要求

请在 `review-today.js` 中新增或继续优化：

```js
_buildReviewResultViewModel()
```

推荐输出字段：

```js
reviewResultVm: {
  total: 0,
  correct: 0,
  wrong: 0,
  skipped: 0,
  answered: 0,

  accuracy: 0,

  groupCount: 0,
  completedGroupCount: 0,
  masteredCount: 0,

  resultLevelClass: '',
  resultTitle: '',
  resultDesc: '',

  statusText: '',
  statusDesc: '',

  nextStepType: '',
  nextStepTitle: '',
  nextStepDesc: '',
  nextStepTag: '',

  hasWrong: false,
  hasSkipped: false,
  isPerfect: false
}
```

不要在 WXML 中写复杂计算。
所有文案、状态 class、按钮逻辑需要尽量在 JS 中提前计算。

------

## 七、文案规则

### 1. total 为 0

```js
resultLevelClass = 'empty'
resultTitle = '暂无复习结果'
resultDesc = '今天还没有完成可统计的复习题'
statusText = '未开始'
statusDesc = '完成一组复习后，这里会生成结果'
nextStepType = 'start'
nextStepTitle = '先开始一组复习'
nextStepDesc = '完成今日复习后，系统会帮你整理正确率和错题情况'
nextStepTag = '未开始'
```

### 2. 正确率 >= 90 且 wrong === 0

```js
resultLevelClass = 'excellent'
resultTitle = '今日复习完成'
resultDesc = '整体掌握很好，可以保持当前节奏'
statusText = '状态很好'
statusDesc = '今天没有明显薄弱点'
nextStepType = 'continue'
nextStepTitle = '可以结束今日复习'
nextStepDesc = '如果还有精力，也可以继续练习新题巩固手感'
nextStepTag = '完成'
```

### 3. 正确率 >= 80 且 wrong > 0

```js
resultLevelClass = 'good'
resultTitle = '今日复习完成'
resultDesc = '整体表现不错，但仍有少量错题'
statusText = '少量错题'
statusDesc = '建议趁热复盘'
nextStepType = 'review'
nextStepTitle = '建议先复盘错题'
nextStepDesc = '先处理今天的错题，再继续下一组练习'
nextStepTag = '推荐'
```

### 4. 正确率 >= 60

```js
resultLevelClass = 'normal'
resultTitle = '今日复习完成'
resultDesc = '本次复习暴露了一些薄弱点'
statusText = '需要复盘'
statusDesc = '错题有较高复盘价值'
nextStepType = 'review'
nextStepTitle = '优先处理薄弱点'
nextStepDesc = '建议立即查看错题，找出今天容易失误的知识点'
nextStepTag = '复盘优先'
```

### 5. 正确率 < 60

```js
resultLevelClass = 'weak'
resultTitle = '今日复习完成'
resultDesc = '今天错题较多，不建议直接继续刷题'
statusText = '错题较多'
statusDesc = '先复盘比继续刷题更重要'
nextStepType = 'review'
nextStepTitle = '建议立即复盘'
nextStepDesc = '先把错误原因搞清楚，再继续练习，复习效果会更好'
nextStepTag = '重点'
```

------

## 八、底部按钮逻辑

底部按钮只保留两个。

### 有错题时

```text
主按钮：复盘错题
次按钮：继续练习
```

### 无错题时

```text
主按钮：完成
次按钮：继续练习
```

### total 为 0 时

```text
主按钮：开始复习
次按钮：返回首页
```

不要出现三个同等重量按钮。
不要在页面中部和底部重复放置多个相同按钮。

------

## 九、WXSS 优化要求

请重点重写最终结果页样式，目标是紧凑、清晰、统一。

推荐样式结构：

```css
/* result page */
/* simple header */
/* summary card */
/* accuracy block */
/* summary grid */
/* advice card */
/* inline wrong tip */
/* bottom actions */
/* states */
```

页面背景：

```css
.review-result-page {
  min-height: 100vh;
  padding: 32rpx 24rpx 0;
  background: #F6F8FF;
  box-sizing: border-box;
}
```

顶部标题区域应轻量：

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

核心结果卡：

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

四宫格数据：

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

辅助数据：

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
.review-bottom-actions {
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

## 十、状态颜色要求

不同结果状态只做轻微强调，不要大面积变色。

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

不要给整个页面加过重的状态色背景。

------

## 十一、需要删除或弱化的旧元素

请检查并删除或弱化以下类型的旧 UI：

```text
大 Hero 区域
大面积完成横幅
复杂插画
重复统计卡片
分散的数据模块
大面积渐变
过长鼓励文案
多个同级按钮
默认展开的分组明细
冗长完成说明
```

如果旧页面里有成长、徽章、动画类元素，请默认隐藏或删除。
今日复习结果页优先服务于“看结果”和“去复盘”。

------

## 十二、边界状态

必须处理以下情况：

### 1. 今日无任务

```text
标题：今日暂无待复习内容
说明：可以去练习新题，或查看错题本
主按钮：去练习
次按钮：返回首页
```

### 2. total 为 0

不能显示 `NaN%`。
正确率显示 `0%` 或空状态。

### 3. 有错题

主按钮必须是：

```text
复盘错题
```

并显示轻量错题提示。

### 4. 无错题

主按钮是：

```text
完成
```

不显示错题提示。

### 5. 有跳过题

在主结果卡底部显示：

```text
未完成 X 题
```

不要单独做一张大提醒卡。

------

## 十三、验收标准

完成后请逐项检查：

1. 最终结果页没有 Hero 大头部；
2. 核心数据集中在一个主结果卡中；
3. 正确率是主视觉；
4. 复习题数、答对、错题、完成组数在同一个四宫格内；
5. 跳过题 / 已掌握数据只作为轻量补充；
6. 页面卡片数量明显减少；
7. 页面首屏不拥挤；
8. 有错题时主按钮是“复盘错题”；
9. 无错题时主按钮是“完成”；
10. 不出现三个同等重量按钮；
11. 不出现 `NaN%`；
12. 小屏手机显示正常；
13. 底部按钮不遮挡内容；
14. 原有今日复习、提交、分组、错题入口功能不受影响；
15. 微信开发者工具无 WXML / WXSS / JS 报错。

------

## 十四、最终交付说明

完成后请说明：

1. 删除了哪些 Hero / 装饰性元素；
2. 核心数据如何集中展示；
3. `reviewResultVm` 新增或调整了哪些字段；
4. 有错题、无错题、无任务、total 为 0 时分别如何展示；
5. 底部按钮逻辑如何调整；
6. 是否保持了原有复习流程功能。