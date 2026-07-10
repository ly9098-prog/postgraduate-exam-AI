# miniprogram(7) 全页面最终审查报告

> 审查对象：`当前版本`  
> 审查范围：`pages` 目录下所有页面，以及与页面运行强相关的 `config.js`、`utils/answer.js`、部分组件调用。  
> 审查方式：解压源码后进行静态代码审查、页面路由核对、JS 语法检查、JSON 解析检查、WXML 模板风险检索、关键业务链路追踪。  
> 说明：本报告为源码级审查结果，未包含微信开发者工具编译结果、真机兼容性结果和真实接口联调结果。

---

## 一、总览结论

`当前版本` 相比上一版已有明显修复，尤其是之前的几个高风险点：

- `config.js` 已由 `DEV = true` 改为 `DEV = false`，默认不再请求 `localhost`。
- `practice.wxml`、`review-today.wxml`、`pomodoro.wxml` 中前几轮指出的模板函数调用问题已基本移除。
- `pomodoro` 中本地 ISO 时间再次拼接 `+00:00` 导致 `Invalid Date -> NaN:NaN` 的主因已修复。
- `practice-result.js` 中 `stored` 作用域问题已修复。
- `practice-result` 已改为按 `question_id` 匹配题目与结果，跳题后错位风险已修复。
- `wrong-detail` 的 `both` 样式已补充。
- `wrong-detail` 已校验 `wrong_detail_ids` 是否包含当前题目，旧缓存污染风险已降低。
- `wrong-detail` 已兼容顶层 `blank_option_groups` 和 `content.blank_option_groups`。

但最终版仍然存在问题，当前结论是：

**不建议直接上线。**

主要原因是：

1. `review-today` 最终完成页存在未定义变量 `total`，会导致今日复习全部完成时运行时报错。
2. `login` 页面在生产环境下仍可能显示开发者登录入口。
3. `pomodoro` 虽然已修复上轮 NaN 主因，但仍缺少旧缓存异常值防护，老用户本地已有脏缓存时仍可能触发异常。
4. `pomodoro` 休息倒计时实际按 0.5 秒扣 1 秒，休息时间会快一倍。
5. `dashboard` 跳转 `wrong-book` 时传入的 `topic` 参数没有被 `wrong-book` 使用，弱点知识点点击后不会生效。
6. `import` 页面轮询在页面隐藏后被清除，返回页面后不会自动恢复，长任务进度可能卡住。

---

## 二、问题分级汇总

| 等级 | 数量 | 是否阻断上线 | 说明 |
|---|---:|---|---|
| P0 | 1 | 是 | 会导致核心流程直接运行时报错 |
| P1 | 6 | 建议修复后再上线 | 会影响功能正确性、生产体验或核心交互 |
| P2 | 8 | 可排期修复 | 主要是体验、边界异常或一致性问题 |

---

## 三、P0 阻断问题

### P0-1：`review-today` 最终复习完成弹窗使用未定义变量 `total`

**位置：**

`pages/review-today/review-today.js`

相关代码：

```js
async _showFinalCelebration() {
  const denom = this.data.totalCompleted || this.data.allGroupResults.length
  const correct = this.data.totalCorrect
  const accuracy = denom > 0 ? Math.round(correct / denom * 100) : 0
  await this._loadGrowthForCelebration()
  this._showCelebration({
    celebrationType: 'final',
    celebrationTitle: '今日复习完成',
    celebrationDetail: `完成 ${total} 题 · 答对 ${correct} 题`,
    celebrationMotto: '记忆曲线已更新，今天的积累会在明天生效',
    celebrationProgressText: `今日正确率 ${accuracy}%`,
    celebrationRewardText: '解锁今日复习徽章',
  }, 3600)
}
```

**问题说明：**

`total` 没有定义。用户完成最后一组复习，进入最终庆祝弹窗时，会触发：

```text
ReferenceError: total is not defined
```

**影响：**

- 今日复习完成流程可能直接中断。
- 最终结果页或庆祝弹窗无法正常展示。
- 这是核心学习链路的运行时阻断问题。

**修复建议：**

明确总数口径，然后定义 `total`。

如果“完成题数”指实际提交/作答题数：

```js
async _showFinalCelebration() {
  const total = this.data.totalCompleted || this.data.allGroupResults.length
  const correct = this.data.totalCorrect
  const accuracy = total > 0 ? Math.round(correct / total * 100) : 0

  await this._loadGrowthForCelebration()
  this._showCelebration({
    celebrationType: 'final',
    celebrationTitle: '今日复习完成',
    celebrationDetail: `完成 ${total} 题 · 答对 ${correct} 题`,
    celebrationMotto: '记忆曲线已更新，今天的积累会在明天生效',
    celebrationProgressText: `今日正确率 ${accuracy}%`,
    celebrationRewardText: '解锁今日复习徽章',
  }, 3600)
}
```

如果产品口径需要区分“本组题数 / 实际提交题数 / 跳过题数”，建议同时展示：

```js
const reviewed = this.data.totalCompleted
const total = this.data.allGroupResults.length
const skipped = Math.max(0, total - reviewed)
```

并在 UI 中显示“完成 X 题，跳过 Y 题”。

---

## 四、P1 重要问题

### P1-1：生产环境下 `login` 页面仍可能显示开发者登录入口

**位置：**

`pages/login/login.js`

相关代码：

```js
this.setData({
  error: '[auto] ' + errMsg,
  showDevLogin: config.DEV || true,
  loading: false,
})
```

**问题说明：**

`config.DEV || true` 永远为 `true`。即使当前 `config.js` 中 `DEV = false`，只要自动登录失败，登录页仍会展示开发者登录入口。

**影响：**

- 正式环境用户可能看到“开发者模式”相关入口。
- 影响生产环境专业度。
- 如果开发者登录接口未严格限制，可能带来权限风险。

**修复建议：**

改为：

```js
showDevLogin: !!config.DEV
```

或者生产包完全移除开发者登录入口。

---

### P1-2：`pomodoro` 对旧版脏缓存缺少防护，老用户仍可能出现异常

**位置：**

`pages/pomodoro/pomodoro.js`

相关代码：

```js
if (local && (Date.now() - local.savedAt < 7200000)) {
  return {
    id: local.sessionId,
    start_time: new Date(local.sessionStartTime).toISOString(),
    duration_minutes: local.durationMinutes,
    subject: local.subject,
    status: local.status || 'running',
    pause_total_seconds: local.pauseTotalSeconds || 0,
    paused_at: local.pausedAt ? new Date(local.pausedAt).toISOString() : null,
  }
}
```

**问题说明：**

上一轮 `NaN:NaN` 的主要根因已经修复，但如果用户本地已经存在旧版本写入的异常缓存，例如：

```js
local.sessionStartTime = NaN
```

则：

```js
new Date(NaN).toISOString()
```

会抛出：

```text
RangeError: Invalid time value
```

这段代码位于本地兜底恢复路径中，一旦触发，会影响番茄钟页面恢复。

**影响：**

- 新用户大概率不受影响。
- 老用户、灰度用户、之前经历过 NaN 问题的用户可能继续出现异常。
- 网络异常时更容易走到本地缓存恢复路径。

**修复建议：**

在读取本地缓存时强校验时间字段：

```js
const startTime = Number(local.sessionStartTime)
const duration = Number(local.durationMinutes)

if (!Number.isFinite(startTime) || !Number.isFinite(duration) || duration <= 0) {
  wx.removeStorageSync('pomodoro_active_session')
  return null
}
```

同时对 `pausedAt` 也做校验：

```js
const pausedAt = Number(local.pausedAt)
const validPausedAt = Number.isFinite(pausedAt) ? new Date(pausedAt).toISOString() : null
```

---

### P1-3：`pomodoro` 开始倒计时缺少兜底校验，异常后端时间仍可能导致显示异常

**位置：**

`pages/pomodoro/pomodoro.js`

相关逻辑：

```js
_beginCountdown(session) {
  const startTime = parseServerTime(session.start_time)
  const durationMs = session.duration_minutes * 60 * 1000
  ...
}
```

**问题说明：**

`parseServerTime()` 已修复重复拼接时区的问题，但 `_beginCountdown()` 本身没有对 `startTime`、`durationMs` 做最终兜底判断。

如果后端返回异常时间、空字符串、非法 duration，倒计时仍可能出现异常显示。

**修复建议：**

在 `_beginCountdown()` 起始位置加入防御：

```js
const startTime = parseServerTime(session.start_time)
const durationMinutes = Number(session.duration_minutes)

if (!Number.isFinite(startTime) || !Number.isFinite(durationMinutes) || durationMinutes <= 0) {
  this._clearTimer()
  this.setData({
    state: 'idle',
    running: false,
    paused: false,
    displayMin: '00',
    displaySec: '00',
    remainingSec: 0,
    progress: 0,
  })
  wx.showToast({ title: '番茄钟数据异常，请重新开始', icon: 'none' })
  return
}
```

---

### P1-4：`pomodoro` 休息倒计时速度是正常速度的 2 倍

**位置：**

`pages/pomodoro/pomodoro.js`

相关代码：

```js
const tick = () => {
  const remaining = Math.max(0, this.data.remainingSec - 1)
  ...
}
tick()
this._timer = setInterval(tick, 500)
```

**问题说明：**

休息倒计时每 500ms 扣 1 秒，实际会以 2 倍速度结束。

例如 5 分钟休息，实际约 2 分 30 秒结束。

**影响：**

- 番茄钟休息时间不准确。
- 用户实际休息不足。
- 统计和体验都会受到影响。

**修复建议：**

方案一：改为 1000ms：

```js
this._timer = setInterval(tick, 1000)
```

方案二：更推荐按真实时间差计算，避免后台/卡顿造成误差：

```js
const breakStart = Date.now()
const tick = () => {
  const elapsed = Math.floor((Date.now() - breakStart) / 1000)
  const remaining = Math.max(0, totalSec - elapsed)
  ...
}
```

---

### P1-5：`dashboard` 传入 `topic` 参数，但 `wrong-book` 不处理，知识点跳转筛选无效

**位置：**

`pages/dashboard/dashboard.js`

存在类似跳转：

```js
wx.navigateTo({
  url: `/pages/wrong-book/wrong-book?topic=${encodeURIComponent(topic)}`,
})
```

但 `pages/wrong-book/wrong-book.js` 的 `onLoad()` 只处理了 `subject`，未处理 `topic`。

**问题说明：**

用户在仪表盘点击“高频遗忘知识点”“薄弱知识点”等 topic 入口后，进入错题本页面不会按 topic 过滤。

**影响：**

- 仪表盘弱点入口看似可点击，但实际筛选不生效。
- 用户会误以为系统分析不准确。
- 影响错题闭环体验。

**修复建议：**

`wrong-book` 增加 `selectedTopic` 状态，并在请求参数里带上：

```js
onLoad(options) {
  this.setData({
    selectedSubject: options.subject || '',
    selectedTopic: options.topic ? decodeURIComponent(options.topic) : '',
  })
  this._loadPage()
}
```

请求列表时：

```js
if (this.data.selectedTopic) params.topic = this.data.selectedTopic
```

同时 UI 上展示当前 topic 筛选标签，并提供清除筛选按钮。

---

### P1-6：`import` 页面长任务轮询被清除后不会自动恢复

**位置：**

`pages/import/import.js`

相关逻辑：

- `onHide()` / `onUnload()` 会清除 `pollTimer`。
- `onShow()` 当前为空。
- 如果用户在导入任务运行中切后台、切页面，再返回导入页，可能不再继续轮询。

**影响：**

- 导入任务实际可能已经完成，但页面进度卡住。
- 用户可能重复导入或误以为失败。
- 长文本导入、AI 解析、批量导入场景下影响较明显。

**修复建议：**

在 `onShow()` 中恢复轮询：

```js
onShow() {
  const task = this.data.pipelineTask
  if (task && task.pipeline_id && this.data.pipelinePolling) {
    this.pollPipeline(task.pipeline_id)
  }
}
```

或者将当前 pipeline task 存入 storage，页面恢复时读取并继续轮询。

---

### P1-7：`import-batch` 页面存在但未注册，且页面内有 WXML 事件写法风险

**位置：**

`pages/import-batch/import-batch`

**问题说明：**

`pages/import-batch/import-batch` 目录存在，但 `app.json` 中没有注册该页面。若该页是正式流程的一部分，则当前生产包中无法直接通过普通页面路由进入。

另外，该页 WXML 中存在无值事件绑定写法，例如：

```xml
bindtap="showMathPreview" catchtap data-id="{{item.id}}"
```

以及：

```xml
<view ... catchtap>
```

这种写法存在编译或事件阻断不符合预期的风险。

**影响：**

- 如果该页是计划用于导入后的题目审核/批量确认，则当前流程可能断裂。
- 如果之后把该页注册到 `app.json`，WXML 事件绑定需要先修复。

**修复建议：**

如果页面需要上线：

1. 在 `app.json` 注册：

```json
"pages/import-batch/import-batch"
```

2. 修复 WXML 事件绑定：

```xml
bindtap="showMathPreview" catchtap="showMathPreview" data-id="{{item.id}}"
```

或者定义空方法：

```xml
catchtap="noop"
```

并在 JS 中实现：

```js
noop() {}
```

如果该页暂不使用，建议从提交包中移除或标记为实验页面，避免后续误接入。

---

## 五、P2 体验与边界问题

### P2-1：`wrong-book` 初始加载时分析区可能因 stats/list 返回顺序不同而口径不一致

**位置：**

`pages/wrong-book/wrong-book.js`

当前 `_loadPage()` 并行执行：

```js
this.loadStats()
this.loadList(true)
this.loadAiDiagnosis()
```

`loadList()` 构建分析时依赖 `this.data.stats`。如果 `loadList()` 先返回，分析可能用初始空 stats；如果 `loadStats()` 先返回，分析可能使用全局 stats。

**影响：**

- 页面顶部知识漏洞分析偶发不一致。
- 不一定每次复现，但网络慢时更明显。

**修复建议：**

让 stats 与 list 的依赖关系明确化。

方案一：先加载 stats，再加载 list：

```js
await this.loadStats()
await this.loadList(true)
```

方案二：`loadStats()` 返回后，在无筛选且 list 已存在时重新构建 analysis。

---

### P2-2：`review-today` 跳过题在结果列表中视觉上仍容易被当作错误题

**位置：**

`pages/review-today/review-today.wxml`

当前组结果样式类似：

```xml
<view class="ga-item {{item.isCorrect ? 'ga-correct' : 'ga-wrong'}}">
```

跳过题 `isCorrect` 为 `false`，因此视觉上会进入错误样式。

**影响：**

- 用户选择“仅提交已答”后，跳过题仍可能被红色/错误样式展示。
- 与“跳过”语义不一致。

**修复建议：**

增加 skipped 样式：

```xml
<view class="ga-item {{item.wasSkipped ? 'ga-skipped' : (item.isCorrect ? 'ga-correct' : 'ga-wrong')}}">
```

并在 WXSS 中设置中性样式。

---

### P2-3：`review-today` 最终统计未清晰区分“总题数 / 已答题数 / 跳过题数”

**位置：**

`pages/review-today/review-today.wxml` / `pages/review-today/review-today.js`

当前最终结果主要显示：

```xml
复习题数 {{allGroupResults.length}}
正确题数 {{totalCorrect}}
```

如果用户选择“仅提交已答”，则 `allGroupResults.length` 可能包含跳过题，容易和“实际完成题数”混淆。

**修复建议：**

最终结果页建议展示：

- 总题数
- 已答题数
- 跳过题数
- 正确题数
- 已答正确率

例如：

```js
const totalQuestions = this.data.allGroupResults.length
const completed = this.data.totalCompleted
const skipped = Math.max(0, totalQuestions - completed)
const accuracy = completed > 0 ? Math.round(this.data.totalCorrect / completed * 100) : 0
```

---

### P2-4：`pomodoro-stats` 快速切换日期时，历史记录存在旧请求覆盖新请求的风险

**位置：**

`pages/pomodoro-stats/pomodoro-stats.js`

`loadHistory(date)` 内部使用 `this._requestId`，但日期切换时没有递增独立序列号。如果用户快速切换日期，旧日期请求后返回时，可能覆盖新日期数据。

**修复建议：**

增加独立的 history 请求序列：

```js
this._historySeq = (this._historySeq || 0) + 1
const seq = this._historySeq
...
if (seq !== this._historySeq) return
```

---

### P2-5：`import` 页面任务耗时格式化缺少非法时间兜底

**位置：**

`pages/import/import.js`

相关代码：

```js
const diffSec = Math.floor((Date.now() - new Date(status.started_at).getTime()) / 1000)
```

如果 `status.started_at` 为空或非法，`diffSec` 会变成 `NaN`，页面可能显示：

```text
NaN分NaN秒
```

**修复建议：**

```js
const startedAt = new Date(status.started_at).getTime()
if (Number.isFinite(startedAt)) {
  const diffSec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
  ...
} else {
  this.setData({ elapsedText: '--' })
}
```

---

### P2-6：`home` 页面数字动画定时器未在页面隐藏/卸载时清理

**位置：**

`pages/home/home.js`

`_animateNumber()` 中创建了多个 `setInterval`，但页面隐藏或卸载时没有统一清理。

**影响：**

- 页面离开后仍可能执行 `setData`。
- 低概率出现控制台警告或性能浪费。

**修复建议：**

增加：

```js
_clearAnimTimers() {
  Object.keys(this).forEach((key) => {
    if (key.startsWith('_animTimer') && this[key]) {
      clearInterval(this[key])
      this[key] = null
    }
  })
}

onHide() {
  this._clearAnimTimers()
}

onUnload() {
  this._clearAnimTimers()
}
```

---

### P2-7：`dashboard` 的 insights 重试请求存在旧请求覆盖风险

**位置：**

`pages/dashboard/dashboard.js`

如果用户快速切换趋势天数或多次触发加载，旧的 `loadInsights()` 请求可能在新的请求之后返回并覆盖页面数据。

**修复建议：**

同样使用请求序列号：

```js
this._insightSeq = (this._insightSeq || 0) + 1
const seq = this._insightSeq
...
if (seq !== this._insightSeq) return
```

---

### P2-8：协议页面存在品牌名不一致问题

**位置：**

`pages/agreement/user/user.wxml`

用户协议中出现类似“2240AI”的品牌名，而当前小程序其他位置使用的是 `MemoGrad`。

**影响：**

- 品牌一致性不足。
- 正式上线时容易显得像模板残留。

**修复建议：**

统一替换为当前产品正式名称，并检查隐私政策、AI 协议页面是否也存在同类残留。

---

## 六、重点页面复查结论

### 1. `practice`

**结论：基本可用，未发现新的阻断问题。**

已确认：

- WXML 中前几轮指出的 `modeLabel()`、`Math.round()` 直接调用已移除。
- 多选题、多空题作答判断已有统一化处理。
- 加载失败时已有回退逻辑。
- 结果页所需 storage 数据结构已有增强。

建议优化：

- 进度条宽度仍在 WXML 中做表达式计算，虽然风险低，但如需完全统一规范，可继续预计算为 `progressWidth`。
- 跳过题是否计入最终正确率分母，需要产品口径最终确认。

---

### 2. `practice-result`

**结论：上一轮核心问题已修复。**

已确认：

- `stored` 作用域问题已修复。
- 题目和结果已按 `question_id` 匹配，跳题后错位风险已修复。
- 正确/错误/跳过统计已展示。
- 我的答案、正确答案、题干摘要展示已实现。

暂未发现新的阻断问题。

---

### 3. `review-today`

**结论：仍有 P0 问题，不建议上线。**

已修复：

- WXML 中 `.indexOf()` 模板调用风险已消除。
- 多空题“只答一空就算已答”的问题已明显改善。
- `groupSizeOptions` 已从 WXML 字面量迁移到 data。

仍存在：

- P0：最终庆祝弹窗使用未定义变量 `total`。
- P2：跳过题视觉上仍像错误题。
- P2：最终统计未清楚区分总题数、已答题数、跳过题数。

---

### 4. `wrong-book`

**结论：功能主体可用，但仍有筛选与分析口径问题。**

已修复：

- `loadMore` 已有 loading / hasMore 并发防护。
- 筛选态下已倾向按当前列表构建分析。

仍存在：

- P1：不处理 `topic` 参数，导致 dashboard 知识点入口筛选无效。
- P2：初始加载时 stats/list 返回顺序可能造成分析口径不稳定。

---

### 5. `wrong-detail`

**结论：上一轮主要问题已修复，暂未发现新的核心阻断问题。**

已确认：

- 判断题兜底存在。
- 多选题高亮集合判断已完善。
- `both` 样式已补充。
- AI 异步串题 token 防护存在。
- 错误态 UI 存在。
- storage 中的 `wrong_detail_ids` 已校验是否包含当前题，避免旧列表污染。
- 多空题已兼容 `content.blank_option_groups` 和顶层 `blank_option_groups`。

---

### 6. `pomodoro`

**结论：上一轮 NaN 主因已修复，但仍有时间边界和休息倒计时问题。**

已修复：

- `parseServerTime()` 已判断时间字符串是否自带时区，避免 `Z+00:00`。
- `pomodoro.wxml` 中 `subjectLabel()`、`subjectEmoji()`、`presetLabel()` 模板调用已移除。
- 暂停恢复逻辑整体比上一版更稳。

仍存在：

- P1：旧版脏缓存可能导致 `toISOString()` 抛错。
- P1：`_beginCountdown()` 对异常后端时间缺少最终兜底。
- P1：休息倒计时每 500ms 扣 1 秒，休息时间快一倍。

---

### 7. `pomodoro-stats`

**结论：核心统计页可用，暂未发现 NaN 主因残留。**

已确认：

- 时间解析已使用 `parseServerTime()`。
- `_formatSession()` 对异常时间有 fallback。
- 页面隐藏/卸载时有部分动画与请求保护。

仍建议优化：

- 快速切换日期时，历史记录请求需要独立序列号，避免旧请求覆盖新日期数据。

---

### 8. `home`

**结论：主体可用，有轻微定时器清理问题。**

建议修复：

- 数字动画定时器在页面隐藏/卸载时统一清理。

---

### 9. `dashboard`

**结论：主体可用，但与错题本 topic 跳转存在断点。**

问题：

- `dashboard` 会传 `topic` 到 `wrong-book`，但 `wrong-book` 没有消费该参数。
- insights 请求建议增加序列号防旧请求覆盖。

---

### 10. `import` / `import-batch`

**结论：导入主流程需要继续做边界修复。**

问题：

- `import` 页面长任务轮询在页面隐藏后清除，返回后不会自动恢复。
- `import` 任务耗时格式化缺少非法时间兜底。
- `import-batch` 页面存在但未注册，如果这是正式流程页面，需要接入路由并修复 WXML 事件写法。

---

### 11. `login`

**结论：需要修复生产环境开发者入口问题。**

问题：

- `showDevLogin: config.DEV || true` 永远为 true。

这是生产体验问题，建议上线前修掉。

---

### 12. `agreement` 系列页面

**结论：逻辑简单，主要是文案一致性问题。**

问题：

- 用户协议中疑似存在旧品牌名残留，需要统一品牌名称。

---

## 七、番茄钟暂停 + 网络波动显示 NaN 的最终分析

上一版的核心根因是：

1. 网络异常时进入本地缓存恢复路径。
2. 本地缓存恢复生成了带 `Z` 的 ISO 时间，例如：

```js
2026-07-02T14:07:25.227Z
```

3. 恢复逻辑中再次拼接 `+00:00`：

```js
session.start_time + '+00:00'
```

4. 变成非法时间：

```js
2026-07-02T14:07:25.227Z+00:00
```

5. `Date` 解析失败，后续 `startTime`、`remaining`、`displayMin`、`displaySec` 变成 `NaN`。

本版中已增加 `parseServerTime()`，会判断时间字符串是否已经包含时区：

```js
const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
return new Date(hasTimezone ? s : s + '+00:00').getTime()
```

因此，上轮指出的主要 NaN 触发链路已经修复。

但仍建议继续补两个兜底：

1. 本地缓存恢复前校验 `sessionStartTime` 是否为有限数字。
2. `_beginCountdown()` 内部校验 `startTime`、`durationMinutes` 是否有效。

这样可以覆盖旧缓存、异常后端数据、灰度升级数据不一致等边界情况。

---

## 八、建议修复优先级

### 必须先修

1. `review-today` `_showFinalCelebration()` 中未定义变量 `total`。
2. `login` 页面 `showDevLogin: config.DEV || true`。
3. `pomodoro` 旧缓存时间校验与 `_beginCountdown()` 兜底。
4. `pomodoro` 休息倒计时速度错误。

### 建议上线前修

5. `dashboard -> wrong-book` 的 `topic` 参数接收与筛选。
6. `import` 页面轮询恢复。
7. `import-batch` 是否上线、是否注册、WXML 事件写法修复。

### 可排期优化

8. `wrong-book` 初始分析区 stats/list 口径稳定性。
9. `review-today` 跳过题视觉样式与最终统计口径。
10. `pomodoro-stats` 历史记录请求序列号。
11. `home` 数字动画定时器清理。
12. 协议页面品牌名统一。

---

## 九、最终结论

`当前版本` 已经修复了前几轮的大部分核心问题，整体质量明显提升，但仍然不是“无问题可上线”的状态。

当前最主要的上线阻断点是：

```text
review-today 最终完成弹窗使用未定义变量 total
```

只要用户完成今日复习，就可能触发运行时报错。

此外，`login` 生产环境开发者入口、`pomodoro` 旧缓存兜底、休息倒计时速度错误，也建议在上线前一并处理。

**建议结论：修完 P0 和 P1 后，再用微信开发者工具 + 真机完整跑一遍以下回归链路：**

1. 首页进入练习，完成、跳题、查看结果。
2. 今日复习：单选、多选、多空题，跳过题，仅提交已答，全部完成最终弹窗。
3. 错题本：筛选、加载更多、从 dashboard topic 入口进入、进入错题详情左右滑动。
4. 番茄钟：开始、暂停、断网、切后台、恢复、完成、休息倒计时。
5. 番茄统计：切换日期、切换周/月/年趋势。
6. 登录：正式环境自动登录失败时不出现开发者入口。
7. 导入：长任务中切后台/切页面后返回，进度仍能继续刷新。

