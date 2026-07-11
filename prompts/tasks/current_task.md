你是一名资深微信小程序性能优化工程师。请基于当前 MemoGrad 微信小程序源码和根目录下的 `audits.json`，直接修改代码，修复微信开发者工具审计发现的问题。

# 一、总体目标

在不改变现有业务逻辑、接口协议、页面跳转路径和视觉风格的前提下，完成以下目标：

1. 修复审计中可以通过代码解决的失败项。
2. 将首页 `setData` 峰值从每秒 67 次降低至每秒不超过 10 次，推荐控制在每秒 5～8 次。
3. 清理所有仅供 JavaScript 逻辑使用、却通过 `setData` 写入的数据。
4. 修复点击态、滚动体验、点击热区和文字颜色对比度问题。
5. 保证登录、首页、练习、练习结果、错题本、错题详情、学习统计、番茄钟、番茄统计和今日复习流程不发生功能回归。
6. 修复后重新执行微信开发者工具审计，目标为：
   - 总分不低于 90；
   - 体验分类不低于 90；
   - 性能分类保持 90 以上；
   - 不出现新的 JavaScript 异常。

不要只给修改建议，请直接修改源码。完成后输出修改文件列表、关键改动说明、测试结果和仍需人工配置的事项。

# 二、P0：修复首页高频 setData

重点文件：

- `pages/home/home.js`
- `pages/home/home.wxml`

当前 `_animateNumbers()` 同时启动三个独立数字动画：

- `_animStreakDays`
- `_animGoalDone`
- `_animLevelProgress`

每个动画内部以约 16 ms 的间隔单独调用一次 `setData`，造成首页峰值达到每秒 67 次。

请按以下原则重构：

1. 不允许三个动画各自创建一套 16 ms `setTimeout + setData` 循环。
2. 改为一个统一的动画调度器，一次计算三个动画字段，并合并成一次 `setData`。
3. 动画刷新间隔调整为 80～120 ms，或者使用 CSS transition 实现；不得继续以 16 ms 向渲染层传输数据。
4. 只有字段值实际发生变化时才写入 `setData`。
5. 动画结束时必须把三个字段精确设置为最终目标值，不能出现少 1、进度不到 100% 等误差。
6. 在 `onHide` 和 `onUnload` 中清理动画定时器，防止页面退出后继续更新。
7. 多次执行 `onShow` 或重新加载成长数据时，只保留最新一轮动画。
8. `streakDays`、`todayGoalDone` 当前没有直接绑定 WXML，只作为动画目标值使用。应优先移到页面实例变量，例如：

```js
this._growthTargets = {
  streakDays: 0,
  todayGoalDone: 0,
  levelProgress: 0
}
```

不得为了消除审计提示而删除功能。

验收标准：

- 首页加载和切回首页时，数字动画仍然正常。
- 首页每秒 `setData` 不超过 10 次。
- 页面退出后没有动画定时器继续运行。
- 审计不再出现 `set-data-freq`。

# 三、P0：处理未绑定 WXML 的 setData 数据

审计发现多个字段没有绑定到对应页面 WXML，却通过 `setData` 写入。

处理原则：

1. 对每个字段先检查全部 JS 使用场景，不得看到“未绑定”就直接删除。
2. 只用于接口参数、计时、统计、缓存、流程控制、请求防重、哈希比对或会话状态的字段，应移到页面实例变量中，例如：
   - `this._runtimeState`
   - `this._session`
   - `this._requestContext`
   - `this._answers`
3. 实例变量不得通过 `setData` 更新。
4. 真正用于 WXML 显示或控制渲染的字段继续保留在 `data`。
5. 若某字段属于视图派生数据，应绑定实际展示字段，而不是保留两个含义重复的状态。
6. 不得直接修改 `this.data.xxx`。
7. 页面重新进入、重新开始练习、切换题组和退出页面时，正确初始化或清理实例状态。
8. 对异步请求增加页面存活检查或请求序列检查，避免旧请求覆盖新页面状态。

逐文件检查以下字段：

## `pages/home/home.js`

- `streakDays`
- `todayGoalDone`
- `authed`

其中 `streakDays`、`todayGoalDone` 可作为数字动画目标移出 `data`；`authed` 若只用于 JS 分支，也应改为实例状态。

## `pages/practice/practice.js`

- `traceId`
- `safeModeActive`
- `answerMap`
- `answeredFlags`
- `correctCount`
- `comboCount`
- `elapsedSec`
- `startTime`
- `questionTimeMap`
- `currentQuestionStartedAt`
- `requestId`
- `optionKeys`

这些字段大部分属于答题会话、统计和请求状态，建议统一收口为：

```js
this._practiceSession = {
  traceId: '',
  safeModeActive: false,
  answerMap: {},
  answeredFlags: {},
  correctCount: 0,
  comboCount: 0,
  elapsedSec: 0,
  startTime: 0,
  questionTimeMap: {},
  currentQuestionStartedAt: 0,
  requestId: '',
  optionKeys: []
}
```

调整所有读取和写入位置，确保提交答案、切题、计时、结果统计和安全模式逻辑保持一致。

## `pages/practice-result/practice-result.js`

- `growthBadgeCount`

若只用于生成结果文案或业务判断，改为局部变量或实例变量。

## `pages/wrong-book/wrong-book.js`

- `primaryStatLabel`

若页面实际没有展示该字段，改为局部派生值；若设计上应展示，则补充正确的 WXML 绑定。

## `pages/wrong-detail/wrong-detail.js`

- `errorTypeLabelText`
- `currentWqId`
- `aiResult`
- `switching`

其中题目 ID、AI 原始结果和切换锁通常属于运行态，应移出 `data`。页面真正需要展示的 AI ViewModel、遮罩状态等字段仍保留在 `data`。

## `pages/dashboard/dashboard.js`

- `insight`
- `masteryRate`
- `refreshing`
- `_heroHash`
- `_trendHash`
- `_subjectHash`
- `_masteryHash`
- `_growthHash`
- `_adaptiveHash`
- `insightsLoading`
- `insightsError`

所有哈希字段必须移到实例变量，不能通过 `setData` 保存。

对于 `refreshing`、`insightsLoading` 和 `insightsError`，检查 WXML 是否确实不展示这些状态。若页面已经使用其他加载字段，应合并状态；若应展示加载或错误反馈，则绑定到对应 WXML。

## `pages/pomodoro/pomodoro.js`

- `todayDurationSec`
- `sessionId`
- `sessionStartTime`
- `totalPausedMs`
- `pauseStartTime`
- `elapsedSec`
- `freeFriendlyText`
- `progress`
- `endConfirmMode`
- `breakStartTime`
- `remainingSec`

番茄钟中的原始时间戳、累计暂停时长、会话 ID、内部剩余秒数应优先放入：

```js
this._timerState = {
  sessionId: '',
  sessionStartTime: 0,
  totalPausedMs: 0,
  pauseStartTime: 0,
  elapsedSec: 0,
  remainingSec: 0,
  breakStartTime: 0,
  endConfirmMode: ''
}
```

WXML 仅保留格式化后的展示时间、环形进度样式、暂停状态、阶段状态等必要数据。

注意：`progress` 可能通过样式或子组件间接使用，移动前必须核查所有动态属性和组件传参，避免误判。

## `pages/pomodoro-stats/pomodoro-stats.js`

- `weekSessions`
- `weekDurationText`
- `trends`
- `historyTotal`

若页面使用的是 `_dispWeekSessions`、`_dispWeekDurationText` 等展示字段，应删除重复的数据层传输，将原始统计数据放入实例缓存。

## `pages/review-today/review-today.js`

- `todayNewDueCount`
- `remainingBatchCount`
- `allTodayQuestionIds`
- `completedQuestionIds`
- `remainingQuestionIds`
- `reviewOverview`
- `overviewLoading`
- `allQuestions`
- `answers`
- `sessionId`
- `currentGroupId`
- `allGroupResults`
- `totalCorrect`
- `totalWrong`
- `totalCompleted`
- `safeModeActive`
- `renderTraces`
- `optionKeys`
- `_groupProgressStyle`
- `celebrationProgressText`

建议建立统一复习会话对象：

```js
this._reviewSession = {
  allTodayQuestionIds: [],
  completedQuestionIds: [],
  remainingQuestionIds: [],
  allQuestions: [],
  answers: {},
  sessionId: '',
  currentGroupId: '',
  allGroupResults: [],
  totalCorrect: 0,
  totalWrong: 0,
  totalCompleted: 0,
  safeModeActive: false,
  renderTraces: [],
  optionKeys: []
}
```

视图层只保留当前题组、题组展示结果、按钮状态、加载状态、错误提示和进度展示等字段。

验收标准：

- 审计不再出现上述字段的 `set-data-no-binding`。
- 练习和复习结果统计与修改前一致。
- 番茄钟暂停、恢复、结束、跳过休息和自由计时正常。
- 不出现因实例变量未初始化导致的 `undefined` 异常。

# 四、P1：用 hover-class 替换 CSS :active

禁止继续使用 CSS `:active` 实现小程序点击态。使用 WXML 的 `hover-class`、`hover-start-time` 和 `hover-stay-time`。

建议统一设置：

```xml
hover-start-time="20"
hover-stay-time="80"
```

修复以下位置：

## 1. `components/quiz-runner/quiz-runner.wxss`

删除：

```css
.runner-option-item:active::after
.runner-option-item:active
.runner-nav-btn:active
```

现有选项已经使用：

```xml
hover-class="runner-option-pressed"
```

因此只保留 `.runner-option-pressed` 样式。

为上一题、下一题按钮增加独立点击类，例如：

```xml
hover-class="{{currentIndex <= 0 ? 'none' : 'runner-nav-pressed'}}"
```

以及：

```css
.runner-nav-pressed {
  opacity: 0.72;
}
```

禁用状态不得触发点击态。

## 2. `pages/practice-result`

为 `.action-secondary` 按钮添加 `hover-class="action-secondary-pressed"`，将原来的 `.action-secondary:active` 改成 `.action-secondary-pressed`。

同时检查同文件中同类主按钮的 `:active`，使用相同模式统一处理，避免下一次审计再次命中。

## 3. `pages/dashboard`

为 `.weak-item` 增加 `hover-class="weak-item-pressed"`，将：

```css
.weak-item:active
```

改为：

```css
.weak-item-pressed
```

## 4. `pages/wrong-book`

为 `.wl-item` 增加 `hover-class="wl-item-pressed"`，替换 `.wl-item:active`。

## 5. `pages/pomodoro-stats`

检查 `.history-item` 是否真的具有点击行为：

- 若没有绑定任何点击事件，直接删除其 `:active` 样式，不要凭空增加交互；
- 若存在点击行为，则添加 `hover-class="history-item-pressed"`。

## 6. `pages/pomodoro`

为 `.ctrl-primary` 增加 `hover-class="ctrl-primary-pressed"`。

同时处理：

```css
.ctrl-primary:active
.page-free .ctrl-primary:active
```

改成对应 hover 类组合。

## 7. `pages/review-today`

为 `.gradient-btn` 增加 `hover-class="gradient-btn-pressed"`，替换 `.gradient-btn:active`。

同一文件其他实际可交互元素若仍使用 `:active`，一并按相同方式处理，但不得修改纯展示元素。

## 8. 全局 `active-surface`

实际定义位于：

- `styles/tokens.wxss`

当前错误写法：

```css
.active-surface:active {
  background: #EEF4FF;
}
```

由于 `active-surface` 本身已经作为 `hover-class` 使用，应改为：

```css
.active-surface {
  background: #EEF4FF;
}
```

不要在 hover 类后再次追加 `:active`。

验收标准：

- 审计不再出现 `ele-active-state`。
- 滑动列表时不会产生残留点击态。
- 禁用按钮不会显示按压效果。

# 五、P1：修复番茄统计页惯性滚动

文件：

- `pages/pomodoro-stats/pomodoro-stats.wxss`

审计命中 `.page-inner`。

在确认其为实际滚动容器后加入：

```css
.page-inner {
  -webkit-overflow-scrolling: touch;
}
```

若 `.page-inner` 本身负责内部滚动，则同时设置合适的：

```css
overflow-y: auto;
```

但必须避免形成“页面滚动 + 内层滚动”两个纵向滚动容器。

若当前页面依赖系统页面滚动，不要盲目制造嵌套滚动；可以将内容改为明确的 `scroll-view`，但需要验证顶部、底部安全区、图表触摸和历史记录滚动行为。

验收标准：

- iOS 上历史列表滚动顺畅。
- 页面不出现双滚动条、滚动锁死或底部内容无法访问。
- 审计不再出现 `overflow-scroll`。

# 六、P1：扩大可点击元素响应区域

## 1. 题目导航圆点

文件：

- `components/quiz-runner/quiz-runner.wxml`
- `components/quiz-runner/quiz-runner.wxss`

当前 `.runner-dot` 视觉尺寸只有约 12～26 rpx，却直接绑定 `bindtap`。

不要单纯把视觉圆点放大。应将“点击热区”和“视觉圆点”拆分，例如：

```xml
<view
  class="runner-dot-hit"
  wx:for="{{questions}}"
  wx:key="index"
  data-index="{{index}}"
  bindtap="goQuestion"
  hover-class="runner-dot-hit-pressed"
>
  <view class="runner-dot {{item._answered ? 'runner-done' : ''}} {{index === currentIndex ? 'runner-active' : ''}}"></view>
</view>
```

要求：

1. `.runner-dot-hit` 的实际点击区域尽量达到 80rpx × 80rpx。
2. 内部 `.runner-dot` 保持当前视觉大小。
3. 题目较多时，导航区允许横向滚动，不得压缩点击热区。
4. 横向滚动时不得误触切题。
5. 当前题、已完成题的视觉状态保持不变。

该组件会影响：

- `pages/practice/practice`
- `pages/wrong-detail/wrong-detail`
- `pages/review-today/review-today`

必须分别回归测试。

## 2. 年度记录入口

文件：

- `pages/dashboard/dashboard.wxml`
- `pages/dashboard/dashboard.wxss`

当前：

```xml
<text class="yearly-more" bindtap="onToggleYearly">
```

响应区域高度过小。

建议改成语义明确的 `view` 或 `button`，并设置：

- 最小高度 80rpx；
- 左右内边距；
- `display:flex`；
- `align-items:center`；
- `justify-content:center`；
- 对应 hover-class。

不得仅通过增大字体解决热区问题。

验收标准：

- 审计不再出现 `small-response-area`。
- 题目圆点仍能准确切换到对应题目。
- 年度记录入口容易点击，且布局不发生明显位移。

# 七、P1：提高今日复习结果页颜色对比度

文件：

- `pages/review-today/review-today.wxss`

目标：普通文字与背景对比度不低于 4.5:1，大号加粗文字不低于 3:1。

建议调整：

```css
.grp-group-tag {
  color: #3157D5;
  background: #EEF4FF;
}

.grp-accuracy-value {
  color: #3157D5;
}

.grp-accuracy-label,
.grp-summary-lbl,
.grp-summary-val.muted {
  color: #5F6F86;
}

.grp-summary-val.success {
  color: #137A3D;
}

.grp-summary-val.danger {
  color: #B42318;
}

.grp-status-pill.correct {
  color: #137A3D;
  background: #CDF5DD;
}

.grp-status-pill.wrong {
  color: #B42318;
  background: #FCD8D8;
}
```

以上颜色可根据现有设计系统微调，但不能继续使用浅绿色文字叠加浅绿色背景、浅红文字叠加浅红背景的低对比方案。

同时检查：

- `.grp-summary-card`
- `.grp-summary-grid`
- `.grp-group-tag`
- `.grp-accuracy-label`
- `.grp-summary-lbl`
- `.grp-summary-val.success`
- `.grp-summary-val.danger`
- `.grp-summary-val.muted`
- `.grp-status-pill.correct`
- `.grp-status-pill.wrong`

验收标准：

- 审计不再出现 `color-contrast`。
- 正确、错误、跳过状态仍有清晰的视觉区分。
- 不使用纯黑替代所有状态色，不破坏现有蓝色设计体系。

# 八、P2：基础库版本兼容性

当前 `project.config.json` 和 `project.private.config.json` 中本地基础库版本为 `3.6.6`，但审计提示线上最低基础库版本可能低于部分组件要求。

涉及的最低版本包括：

- `view.aria-label`：2.5.0
- `rich-text`：1.4.0
- `text.decode`：1.4.0
- `slider.block-color`：1.9.0
- `slider.block-size`：1.9.0
- `cover-view`：1.4.0

处理要求：

1. 不要为了兼容极旧基础库删除 `rich-text`、数学题渲染、滑块样式或无障碍属性。
2. 在最终报告中明确标注：需要在微信公众平台将最低基础库版本设置为不低于 2.5.0。
3. 若项目明确要求支持低于 2.5.0 的基础库，再为 `aria-label` 提供兼容方案。
4. 该项属于线上配置项，代码无法完全代替后台版本设置。

# 九、P2：未使用 WXSS 清理

审计提示以下文件可能存在大量未使用样式：

- `app.wxss`
- `pages/practice/practice.wxss`
- `components/AnimatedView/AnimatedView.wxss`
- `components/mp-html/index.wxss`
- `components/quiz-runner/quiz-runner.wxss`
- `pages/wrong-detail/wrong-detail.wxss`
- `pages/wrong-book/wrong-book.wxss`
- `pages/dashboard/dashboard.wxss`
- `pages/pomodoro-stats/pomodoro-stats.wxss`

注意：该审计结果与本次审计实际访问路径有关，可能把条件渲染、异常状态、弹窗状态、动画状态和第三方组件样式误判为未使用。

处理原则：

1. 不得按审计节省比例直接批量删除 CSS。
2. 先静态检索 WXML 中的 class、动态 class、hover-class 和 JS 拼接 class。
3. 检查 `wx:if`、错误态、空状态、管理员状态、动画状态和响应式样式。
4. `components/mp-html` 属于复杂富文本组件，除非能完整验证公式、图片、表格、代码块和富文本节点，否则不要大范围裁剪。
5. `AnimatedView` 中动画状态可能由 JS 动态添加，必须检查组件逻辑。
6. 只删除能够确认：
   - 没有任何 WXML 引用；
   - 没有 JS 动态拼接；
   - 没有 hover-class 引用；
   - 没有组件外部样式类依赖；
   - 不属于第三方组件必要样式；
     的选择器。
7. 优先拆分页面专属样式，避免所有页面全局引入。
8. 删除前后记录 WXSS 文件体积变化。

该项优先级低于功能、性能和体验修复，不得为了提高审计覆盖率造成界面回归。

# 十、生命周期与稳定性要求

所有新增的定时器、延迟任务和动画调度器都必须：

1. 保存句柄；
2. 在重新启动前清理旧句柄；
3. 在 `onHide`、`onUnload` 或组件 `detached` 中清理；
4. 异步回调执行前检查页面是否仍然存活；
5. 不允许卸载后调用 `setData`；
6. 不允许出现重复提交、重复请求或旧请求覆盖新状态。

# 十一、回归测试

至少完成以下测试：

1. 未登录进入登录页。
2. 登录后进入首页，成长数据和数字动画正常。
3. 调整每日目标。
4. 开始随机练习。
5. 单选、多选、填空题选择和切题。
6. 点击题目导航圆点。
7. 提交练习并查看练习结果。
8. 进入错题本和错题详情。
9. 在错题详情切换上一题、下一题。
10. 生成或重新生成 AI 分析。
11. 打开学习统计，切换趋势范围。
12. 展开和收起年度记录。
13. 点击薄弱知识点。
14. 启动、暂停、继续、终止番茄钟。
15. 跳过休息阶段。
16. 查看番茄统计和历史记录。
17. 开始今日复习、切题、完成题组和进入下一组。
18. 查看今日复习最终结果。
19. 验证空数据、请求失败和重新加载状态。
20. 连续快速进入和退出页面，确认无报错和残留定时器。

# 十二、最终输出格式

完成修改后，按以下结构输出：

## 1. 修改摘要

说明修复了哪些审计项，以及修复前后的核心指标。

## 2. 修改文件

逐个列出修改过的文件及其用途。

## 3. setData 优化结果

列出首页修复前后的每秒调用次数，并说明未绑定数据如何迁移。

## 4. 交互与无障碍修复

说明 hover-class、点击热区、滚动和颜色对比度的处理。

## 5. 未使用样式处理

列出删除的选择器、保留但被审计误判的样式及保留理由。

## 6. 人工配置项

明确提示微信公众平台最低基础库版本应设置为 2.5.0 或更高。

## 7. 测试结果

逐项列出通过、未通过和未执行的测试，不得笼统声称“全部正常”。

## 8. 剩余风险

如存在无法通过源码完全修复的审计项，说明原因和下一步操作。

# 十三、禁止事项

1. 不得修改后端 API 地址、参数或返回结构。
2. 不得改变页面路由。
3. 不得删除核心功能。
4. 不得通过隐藏元素、移除点击事件等方式规避审计。
5. 不得把逻辑状态全部继续留在 `data` 中。
6. 不得使用 `this.data.xxx = value` 绕过 `setData`。
7. 不得批量删除被审计判定为“未使用”的第三方组件样式。
8. 不得只修改 `audits.json` 或关闭自动审计。
9. 不得为了通过颜色审计，把所有文字统一改成黑色。
10. 不得只输出建议而不修改代码。
