请直接检查并修改当前微信小程序项目，修复“今日复习”答题计时和每组题数切换功能。不要只给修改建议，需要实际编辑代码、补充回归测试并运行测试。

## 涉及文件

主要检查：

- components/quiz-runner/quiz-runner.js
- components/quiz-runner/quiz-runner.wxml
- components/quiz-runner/quiz-runner.wxss
- pages/review-today/review-today.js
- pages/review-today/review-today.wxml
- pages/review-today/review-today.wxss

同时检查 quiz-runner 的其他调用方，避免回归：

- pages/practice/practice.js
- pages/practice/practice.wxml
- pages/wrong-detail/wrong-detail.js
- pages/wrong-detail/wrong-detail.wxml

---

# 一、修复 quiz-runner 右上角计时始终为 00:00

## 当前问题

`components/quiz-runner` 已定义：

```js
elapsedText: { type: String, value: '00:00' }
```

并在 WXML 中显示：

```xml
<text class="runner-timer">{{elapsedText}}</text>
```

`pages/practice` 已经实现计时器，并传入：

```xml
elapsedText="{{elapsedText}}"
```

但 `pages/review-today` 使用 `<quiz-runner>` 时没有传入 `elapsedText`，页面自身也没有维护复习计时，因此组件一直使用默认值 `00:00`。

不要通过写死数字、CSS 动画或单纯修改默认值来伪修复。

## 修复要求

### 1. 在 review-today 中实现真实计时

在 `pages/review-today/review-today.js` 中新增：

```js
elapsedText: '00:00'
```

并实现职责清晰的计时方法，例如：

- `_resetReviewTimer()`
- `_startReviewTimer()`
- `_pauseReviewTimer()`
- `_resumeReviewTimer()`
- `_clearReviewTimer()`
- `_formatElapsedTime(seconds)`

计时必须基于：

```js
Date.now()
```

计算真实时间差，不要简单地每秒执行 `seconds++`，避免小程序后台调度、页面卡顿或定时器延迟导致计时不准确。

显示格式为：

```text
MM:SS
```

示例：

- 0 秒 → `00:00`
- 1 秒 → `00:01`
- 9 秒 → `00:09`
- 65 秒 → `01:05`
- 3600 秒 → `60:00`

分钟超过 59 时允许继续显示累计分钟，不需要改成三段式时分秒。

### 2. 将计时文本传给 quiz-runner

修改 `pages/review-today/review-today.wxml` 中的 `<quiz-runner>`：

```xml
elapsedText="{{elapsedText}}"
```

确保以下两个位置都会同步变化：

- 展开状态右上角 `.runner-timer`
- 顶部折叠状态 `.runner-collapsed-meta`

### 3. 正确控制计时生命周期

计时范围定义为“当前复习组的实际作答时间”。

必须满足：

1. 获取一组题目成功、正式进入 `reviewing` 后，从 `00:00` 开始计时。
2. 切换题目时不重置计时。
3. 当前组提交成功并进入 `group-result` 时停止计时。
4. 点击“下一组”并进入新的复习组时，从 `00:00` 重新计时。
5. 加载下一批题目时，从新批次的 `00:00` 开始。
6. 页面卸载时清理 `setInterval`，不能残留定时器。
7. 页面进入后台时暂停计时；重新回到仍处于 `reviewing` 的页面时继续计时。
8. 暂停和恢复不能丢失已经累计的时长。
9. 提交确认弹窗取消后，计时应继续。
10. 提交接口失败后，计时应从原来的累计时长继续，不能重置为零。
11. 用户确认退出答题时清理计时器。
12. `overview`、`loading`、`group-result`、`final-result`、`empty`、`error` 阶段不能继续运行答题计时器。

建议在 `_createReviewSession()` 中保存非响应式计时状态，例如：

```js
timerStartedAt
timerElapsedMs
timerRunning
```

不要把 interval id 放入 `setData`。

### 4. 不要破坏共享组件的其他调用方

不要直接在 `quiz-runner` 内无条件启动一个内部 `setInterval`。

原因：

- `pages/practice` 已有自己的计时器；
- `pages/wrong-detail` 是只读复盘，不应该自动显示不断增长的答题时间；
- 无条件启动会造成重复计时、资源泄漏和语义混乱。

继续保持 `elapsedText` 是 quiz-runner 的展示属性，由需要计时的页面负责传入。

可以在组件中增加必要的容错，但不能让组件在所有场景自动计时。

------

# 二、review-today 增加每组题数切换

## 当前问题

`pages/review-today/review-today.wxml` 当前只显示：

```xml
<view class="mission-batch">每组 {{reviewBatchSize}} 道</view>
```

用户无法点击修改每组题数。

页面请求接口时已经使用：

```js
batch_size: this.data.reviewBatchSize
```

涉及至少两处：

- `startTodayReview`
- `nextGroup` 获取下一批题目

需要让用户在开始复习前选择每组题数。

## 可选题数

固定支持以下四个值，并严格按照递增顺序展示：

```js
[5, 10, 20, 30]
```

界面顺序必须是：

```text
每组 5 道
每组 10 道
每组 20 道
每组 30 道
```

不能显示成 `10、20、30、5`，也不要根据当前值旋转顺序。

## 交互要求

### 1. “每组 N 道”变成可点击控件

修改概览页右上角的：

```xml
<view class="mission-batch">
```

使其具有明确的点击反馈，可以增加小箭头，例如：

```text
每组 10 道⌄
```

需要增加：

- `bindtap`
- `hover-class`
- 合理的 aria-label
- 点击区域不能过小

视觉风格保持当前深绿色卡片和半透明胶囊样式，不重做页面设计。

### 2. 点击后展示选择项

优先使用微信小程序原生：

```js
wx.showActionSheet
```

或项目中已经存在的同类选择组件。

不要引入新的 npm 依赖。

示例方法：

```js
showBatchSizeSelector()
```

选项来源必须由统一常量生成，不能在多个位置分别写死：

```js
const REVIEW_BATCH_SIZE_OPTIONS = [5, 10, 20, 30]
```

用户选择后立即更新：

```js
reviewBatchSize
```

当前胶囊文本同步变为：

```text
每组 5 道
每组 10 道
每组 20 道
每组 30 道
```

取消 action sheet 时不修改当前值。

### 3. 只允许合法值

增加纯函数，例如：

```js
normalizeReviewBatchSize(value)
```

规则：

- 只接受 `5、10、20、30`
- 非数字、NaN、0、负数和其他数字回退为 10
- 接口返回字符串 `"20"` 时应正确转换为 20

### 4. 用户选择不能被接口概览刷新覆盖

当前 `buildReviewOverviewVM()` 每次都会执行：

```js
reviewBatchSize: Number(overview.batch_size || 10)
```

这会导致用户刚选择 20 道，在以下操作后又被接口返回的默认 10 道覆盖：

- `loadTodayReviewOverview`
- `refreshOverviewStatsSilently`
- 提交一组后刷新统计
- 页面从后台恢复

请增加“用户是否主动选择过”的实例状态，例如：

```js
this._userSelectedReviewBatchSize
```

或者等价实现。

规则：

1. 用户未手动选择时，允许使用接口返回的合法 `overview.batch_size`。
2. 用户手动选择后，本次页面会话内始终优先使用用户选择。
3. `refreshOverviewStatsSilently()` 不能把用户选择重置成接口默认值。
4. 不要求跨小程序重启永久保存。
5. 不要把临时标记放进后端请求。
6. 不修改后端接口结构。

### 5. 请求必须使用最新选择

确认以下两个请求都始终使用当前选择值：

```js
api.post('/review/today/next-batch', {
  batch_size: this.data.reviewBatchSize,
})
```

覆盖：

- 第一次点击“开始今日复习”
- 完成一组后获取下一批题目

不得只修改界面文字却仍然固定请求 10。

### 6. 切换限制

每组题数仅允许在 `overview` 阶段修改。

以下状态点击时不应修改：

- 正在请求 `isStarting`
- 正在继续 `isContinuing`
- 已进入 `reviewing`
- `group-result`
- `final-result`

由于选择控件目前只显示在 overview，也请在 JS 方法中再次校验状态，避免快速连点或异步状态变化造成错误。

### 7. 边界行为

如果今日剩余题目少于所选题数：

- 不报错；
- 仍然把用户选择的 `batch_size` 传给接口；
- 实际题量以接口返回为准。

不要在前端伪造不存在的题目。

接口返回的 `total_batch_count`、`batch_no` 等仍以服务端响应为准，不要自行猜测。

------

# 三、样式要求

修改 `pages/review-today/review-today.wxss`：

1. 保留现有 `.mission-batch` 视觉风格。
2. 增加可点击状态和轻微按压反馈。
3. 可以增加箭头旋转或透明度变化，但不要复杂动画。
4. 当前值需要清楚可读。
5. 不得遮挡 `MEMORY CURVE` 标题或右侧区域。
6. 在窄屏设备上不能换行挤压主卡片。
7. 禁用状态下需要降低透明度且不能触发选择。

------

# 四、回归测试

请新增 Node 回归测试，例如：

```text
scripts/test-review-today-interactions.js
```

可以通过 mock：

- `Page`
- `Component`
- `wx.showActionSheet`
- `setInterval`
- `clearInterval`
- `Date.now`

获取页面配置并测试纯方法和状态变化。

至少覆盖以下场景。

## 计时测试

1. 初始值是 `00:00`。
2. 1 秒格式化为 `00:01`。
3. 65 秒格式化为 `01:05`。
4. 3600 秒格式化为 `60:00`。
5. `_startReviewTimer()` 不会重复创建多个 interval。
6. `_pauseReviewTimer()` 会清理 interval 并保留累计时长。
7. 暂停后恢复不会从零开始。
8. `_resetReviewTimer()` 会恢复为 `00:00`。
9. `onUnload()` 会清理 interval。
10. review-today WXML 必须包含：

```xml
elapsedText="{{elapsedText}}"
```

1. quiz-runner 中两个计时显示位置仍绑定 `elapsedText`。
2. 不能在 quiz-runner 中新增无条件自动启动的定时器。

## 每组题数测试

1. 选项常量严格等于：

```js
[5, 10, 20, 30]
```

1. action sheet 的 itemList 顺序严格为：

```text
每组 5 道
每组 10 道
每组 20 道
每组 30 道
```

1. 选择索引 0 后 `reviewBatchSize === 5`。
2. 选择索引 1 后 `reviewBatchSize === 10`。
3. 选择索引 2 后 `reviewBatchSize === 20`。
4. 选择索引 3 后 `reviewBatchSize === 30`。
5. action sheet 取消时保持原值。
6. 非 overview 阶段不能修改。
7. `normalizeReviewBatchSize('20') === 20`。
8. `normalizeReviewBatchSize(15) === 10`。
9. 用户选择 20 后，再执行 `buildReviewOverviewVM({ batch_size: 10 })` 或静默刷新，最终仍保持 20。
10. 用户未选择时，接口返回合法值 30，可以使用 30。
11. `startTodayReview` 请求使用当前 `reviewBatchSize`。
12. `nextGroup` 请求也使用当前 `reviewBatchSize`。
13. WXML 的 `.mission-batch` 必须具有点击事件。

同时确认原有公式阅读测试继续通过。

------

# 五、测试命令

完成后运行新增测试：

```bash
node scripts/test-review-today-interactions.js
```

再运行全部已有测试：

```bash
for f in scripts/test-*.js; do
  echo "== $f =="
  node "$f" || exit 1
done
```

如果项目中存在其他 lint、类型检查或小程序构建检查，也一并运行。

------

# 六、约束

- 不修改后端接口。
- 不修改题目数据结构。
- 不引入新的 npm 依赖。
- 不重做页面设计。
- 不破坏左右滑动切题。
- 不破坏选项点击、答题卡、提交本组、掌握题目和退出确认逻辑。
- 不让 practice 页面出现两个计时器。
- 不让 wrong-detail 只读复盘页面自动计时。
- 所有 interval、timeout 都必须在相应生命周期清理。
- 保持微信小程序运行环境兼容。
- 修改应尽量局部、清晰，并为计时生命周期和用户自选批量逻辑添加必要注释。

完成后请输出：

1. 根因分析。
2. 修改过的文件列表。
3. 计时器的启动、暂停、恢复、重置和销毁时机。
4. 每组题数选择的状态优先级。
5. 新增的测试用例。
6. 实际执行的测试命令和结果。
7. 尚存风险或未覆盖场景。

