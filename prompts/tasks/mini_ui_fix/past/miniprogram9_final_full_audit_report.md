# miniprogram(9) 全页面最终审查报告

审查对象：`当前版本`  
审查范围：`pages` 目录下所有页面、`app.json` 页面注册、关键工具函数与生产配置。  
审查方式：解压后静态扫描 + 逐页阅读关键 WXML/JS/WXSS + 复查上一轮问题 + 运行 JS 语法检查。

## 一、总体结论

**仍然存在问题，不建议直接视为“完全无风险版本”上线。**

不过，相比上一版，阻断性问题已经明显减少：

- `node --check` 检查所有业务 JS 文件，未发现 JS 语法错误。
- `config.js` 已切为 `DEV = false`，正式环境不再默认请求 `localhost`。
- `pomodoro` 中 `Z+00:00` 重复拼接导致 `NaN:NaN` 的主因已修复。
- `pomodoro.wxml`、`practice.wxml`、`review-today.wxml` 中未再发现业务模板层直接调用 JS 方法的问题。
- `review-today` 最终结算弹窗中 `total` 未定义的问题已修复。
- `wrong-book` 筛选态 `stats=null` 触发 `_buildSummaryCards()` 崩溃的问题已修复。
- `wrong-detail` 旧缓存污染、多空题兼容、`both` 样式等上一轮问题已修复。

当前版本没有发现明显新的 P0 级语法崩溃问题，但仍有 **P1/P2 级用户可感知问题**，主要集中在：

1. `pomodoro-stats` 首次加载失败后再重试成功，页面仍可能停留错误态。
2. `pomodoro` 暂停态旧缓存/异常 `paused_at` 仍有二次触发 `NaN` 的风险。
3. `review-today` “仅提交已答”会把未答题跳过并进入下一组/最终结果，流程语义不严谨。
4. `wrong-book` 筛选态分析卡数字仍可能混入全局统计。
5. `import-batch` 页面没有注册到 `app.json`，且 WXML 中仍存在空 `catchtap`。
6. `import` 长任务轮询连续失败后缺少恢复入口。

---

## 二、复查上一轮问题修复情况

| 上一轮问题 | 当前状态 | 说明 |
|---|---:|---|
| `review-today` 最终弹窗 `total` 未定义 | 已修复 | 当前 `nextGroup()` 使用 `denom` 计算准确率，未再发现 `total` 未定义。 |
| 登录页生产环境仍显示开发者入口 | 已修复 | `showDevLogin: !!config.DEV`，且 `DEV=false`。 |
| `config.js` 仍为 `DEV=true` | 已修复 | `config.js:9` 为 `const DEV = false`。 |
| `pomodoro` 主流程 `Z+00:00` 导致 `NaN` | 主因已修复 | `parseServerTime()` 已判断是否已有时区，不再重复拼接。 |
| `pomodoro.wxml` 模板方法调用 | 已修复 | 未再发现 `subjectLabel()` / `presetLabel()` 等模板函数调用。 |
| `wrong-book` 筛选态 `stats=null` 崩溃 | 已修复 | `stats = stats || {}`，筛选态传 `{}`。 |
| `wrong-detail` 多空题顶层字段兼容 | 已修复 | 已兼容 `content.blank_option_groups` 与顶层 `blank_option_groups`。 |
| `wrong-detail` `both` 样式缺失 | 已修复 | `wrong-detail.wxss` 已补充 `both` 相关样式。 |
| `review-today` 多空题部分作答显示已答 | 基本修复 | `_isQuestionAnswered()` 与 `_syncAnsweredFlags()` 已要求多空题全部空位完成。 |
| `import-batch` 空 `catchtap` | 未修复 | 仍存在空 `catchtap`，详见 P1-4。 |
| `import-batch` 正式环境调试日志 | 未修复 | 仍有无 DEV 控制的 `console.info`。 |

---

## 三、问题清单

### P1-1：`pomodoro-stats` 首次加载失败后，重试成功仍可能停留错误态

**位置：**

- `pages/pomodoro-stats/pomodoro-stats.js:113-165`
- `pages/pomodoro-stats/pomodoro-stats.js:184-188`
- `pages/pomodoro-stats/pomodoro-stats.wxml:10-22`

**问题说明：**

`loadData()` 失败时会设置：

```js
this.setData({ loading: false, errorText: '加载失败，请检查网络后重试' })
```

但成功分支的 `setData()` 没有清空 `errorText`。WXML 中优先判断：

```xml
<block wx:elif="{{errorText}}">
```

因此如果用户第一次进入统计页网络失败，页面进入错误态；之后点击“重新加载”即使接口成功返回，`errorText` 仍然存在，页面仍显示错误态，而不是统计数据。

**影响：**

用户点击“重新加载”后看不到已成功加载的数据，误以为功能仍然失败。

**修复建议：**

在 `loadData()` 开始或成功分支清空错误：

```js
async loadData() {
  const reqId = ++this._requestId
  this.setData({ loading: true, errorText: '' })
  ...
  this.setData({
    ...,
    loading: false,
    errorText: '',
  })
}
```

同时建议 `onShow()` 进入页面时若重新加载，也先清空 `errorText`。

---

### P1-2：`pomodoro` 暂停态旧缓存/异常暂停时间仍可能导致 `NaN`

**位置：**

- `pages/pomodoro/pomodoro.js:546-625`

**问题说明：**

新版已经修复了服务端时间 `Z+00:00` 重复拼接的主因，但 `_restoreSession()` 在恢复暂停态时仍没有对暂停时间做完整数值兜底：

```js
totalPausedMs = (savedPause.totalPausedMs || 0) + (Date.now() - (savedPause.pauseStartTime || Date.now()))
```

以及：

```js
const pausedAtMs = parseServerTime(session.paused_at)
totalPausedMs = Math.max(0, Date.now() - pausedAtMs)
```

如果老用户本地已有异常缓存，例如：

```js
savedPause.totalPausedMs = 'abc'
savedPause.pauseStartTime = 'bad-time'
```

或服务端/缓存中 `paused_at` 为非法时间，`totalPausedMs` 仍可能变成 `NaN`。随后：

```js
const elapsed = Math.floor((Date.now() - startTime - totalPausedMs) / 1000)
const remaining = Math.max(0, totalSec - elapsed)
```

会继续把 `remaining/displayMin/displaySec/progress` 推成异常值。

**影响：**

虽然主链路已修复，但在“暂停中 + 旧缓存/异常缓存 + 网络波动恢复”的组合场景下，仍可能再次出现 `NaN:NaN` 或进度异常。

**修复建议：**

对暂停恢复增加强兜底：

```js
let totalPausedMs = 0

if (savedPause && savedPause.sessionId === session.id) {
  const savedTotal = Number(savedPause.totalPausedMs || 0)
  const savedStart = Number(savedPause.pauseStartTime || Date.now())
  const delta = Date.now() - savedStart
  totalPausedMs = savedTotal + delta
  isPaused = true
} else if (session.paused_at) {
  const pausedAtMs = parseServerTime(session.paused_at)
  totalPausedMs = Number.isFinite(pausedAtMs) ? Math.max(0, Date.now() - pausedAtMs) : 0
  isPaused = Number.isFinite(pausedAtMs)
}

if (!Number.isFinite(totalPausedMs) || totalPausedMs < 0) {
  totalPausedMs = 0
}
```

并在 `setData()` 前再次校验：

```js
if (!Number.isFinite(remaining)) {
  wx.removeStorageSync('pomodoro_pause')
  wx.removeStorageSync('pomodoro_running_state')
  this._resetToIdle()
  wx.showToast({ title: '番茄钟状态异常，已重置', icon: 'none' })
  return
}
```

---

### P1-3：`review-today` “仅提交已答”会让未答题被流程跳过

**位置：**

- `pages/review-today/review-today.js:753-764`
- `pages/review-today/review-today.js:773-812`
- `pages/review-today/review-today.js:822-834`

**问题说明：**

当本组存在未答题，用户选择“仅提交已答”时，代码会跳过未答题，不提交到后端：

```js
if (!isAnswered && !treatUnansweredAsWrong) continue
```

但后面仍然会把整组题目都映射到 `groupResults`，未答题被标记为 `wasSkipped`，并追加到 `allGroupResults`：

```js
const allGroupResults = [...this.data.allGroupResults, ...groupResults]
```

用户点击“下一组”后，流程直接进入下一组；最后一组结束后直接进入最终结果页。

**影响：**

未答题没有提交给后端，也没有被重新安排到后续组里，但前端流程可能显示“今日复习完成”。这会导致：

- 用户以为今日复习已完成；
- 实际后端仍可能保留这些 schedule；
- 前端最终结果中的“跳过题”只是展示结果，没有形成明确补做闭环。

**修复建议：**

建议二选一：

方案 A：未答题保留在当前组，用户不能进入下一组，除非选择“按不会处理”。

方案 B：允许仅提交已答，但把未答题重新组成一个新组，追加到 `groups` 末尾：

```js
const skippedQuestions = groupQuestions.filter(q => !_isQuestionAnswered(q, answers))
const newGroups = skippedQuestions.length
  ? [...this.data.groups, skippedQuestions]
  : this.data.groups
```

同时最终结果判断不要只看 `currentGroupIdx`，还应确认没有未提交题。

---

### P1-4：`import-batch.wxml` 仍存在空 `catchtap`，页面本身也未注册到 `app.json`

**位置：**

- `pages/import-batch/import-batch.wxml:40`
- `pages/import-batch/import-batch.wxml:51`
- `app.json:2-17`

**问题说明：**

WXML 中仍有空事件绑定：

```xml
<text ... bindtap="showMathPreview" catchtap ...>含公式</text>
```

以及：

```xml
<view class="q-detail ..." catchtap>
```

这类空 `catchtap` 没有指定 handler，可能导致开发者工具告警、事件拦截行为不稳定，或者点击“含公式”时同时触发父级 `onCardTap`。

另外，`pages/import-batch/import-batch` 存在完整 JS/WXML/WXSS，但没有注册在 `app.json` 的 `pages` 或分包页面列表中。当前 `app.json` 主包页面列表只包含 `pages/import/import`，未包含 `pages/import-batch/import-batch`。

**影响：**

- 如果该页面仍准备使用，则目前无法通过正常小程序页面路由打开。
- 即使注册后打开，也可能存在点击公式标记时冒泡导致卡片展开/收起异常的问题。
- 如果该页面已废弃，保留未注册页面和调试代码会增加维护噪音。

**修复建议：**

如果页面仍要使用：

1. 在 `app.json` 注册：

```json
"pages/import-batch/import-batch"
```

2. 修复事件绑定：

```xml
<text class="q-math-flag" wx:if="{{item._hasMath}}" catchtap="showMathPreview" data-id="{{item.id}}">含公式</text>
<view class="q-detail {{expanding === item.id ? 'show' : ''}}" catchtap="noop">
```

3. 在 JS 中新增：

```js
noop() {}
```

如果页面已废弃，建议删除整个 `pages/import-batch` 目录，避免后续误以为它是可用页面。

---

### P1-5：`wrong-book` 筛选态分析卡数字仍可能混入全局统计

**位置：**

- `pages/wrong-book/wrong-book.js:260-263`

**问题说明：**

筛选态下，`loadList()` 已改为传 `{}` 生成当前列表分析，避免 `stats=null` 崩溃。但 `_buildSummaryCards()` 中：

```js
const unmastered = this._positiveNumber(
  stats.unmastered,
  this.data.primaryStatCount || stats.total || list.length || 0
)
```

当筛选态传入 `{}` 时，`stats.unmastered` 和 `stats.total` 都为空，fallback 会优先使用 `this.data.primaryStatCount`。而 `primaryStatCount` 通常来自全局统计，可能不是当前筛选列表数量。

**影响：**

用户从 dashboard 带 topic/subject 进入错题本，或手动筛选学科/错因后，上方“待攻克”卡片可能显示全局数量，而不是筛选后的当前列表数量。虽然不崩溃，但会造成数据口径不一致。

**修复建议：**

在筛选态下明确传入上下文，或在无 `stats` 时优先使用 `list.length`：

```js
_buildSummaryCards(stats = {}, list = [], weaknessTags = [], opts = {}) {
  const hasStats = stats && Object.keys(stats).length > 0
  const unmastered = hasStats
    ? this._positiveNumber(stats.unmastered, stats.total || list.length || 0)
    : list.length
  ...
}
```

或者在 `loadList()` 中为筛选态构造：

```js
const statsForAnalysis = hasFilter ? { unmastered: nextList.length, total: nextList.length } : (this.data.stats || {})
```

---

### P2-1：`import` 长任务轮询连续失败后缺少恢复入口

**位置：**

- `pages/import/import.js:54-58`
- `pages/import/import.js:365-373`

**问题说明：**

当前 `pollPipeline()` 查询失败后会重试 3 次；连续失败后：

```js
this.setData({ pipelinePolling: false })
```

但如果此时任务本身并未失败，只是网络短暂抖动，页面会停止轮询。`onShow()` 的恢复条件是：

```js
if (task && task.pipeline_id && this.data.pipelinePolling) {
  this.pollPipeline(task.pipeline_id)
}
```

因为 `pipelinePolling` 已经被置为 `false`，用户切回来也不会恢复查询。

**影响：**

导入长任务实际可能仍在后端运行，但前端不会继续刷新进度，用户容易误以为导入卡住。

**修复建议：**

连续失败后保留任务卡片并显示“继续查询”按钮：

```js
this.setData({
  pipelinePolling: false,
  pipelinePollError: '网络异常，进度查询已暂停',
})
```

WXML 中增加按钮：

```xml
<button wx:if="{{pipelineTask && !pipelinePolling && !isTerminal}}" bindtap="resumePipelinePolling">继续查询</button>
```

JS：

```js
resumePipelinePolling() {
  const id = this.data.pipelineTask && this.data.pipelineTask.pipeline_id
  if (!id) return
  this._pollRetries = 0
  this.setData({ pipelinePolling: true, pipelinePollError: '' })
  this.pollPipeline(id)
}
```

---

### P2-2：`practice-result` 正确率口径包含跳过题，可能与用户认知不一致

**位置：**

- `pages/practice/practice.js:1137-1167`
- `pages/practice-result/practice-result.js:31-36`

**问题说明：**

练习提交时只提交已答题：

```js
const answers = completedQuestions.map(...)
```

但跳转结果页时传入的 `total` 是整套题目数量：

```js
`&total=${total}`
```

结果页正确率使用：

```js
const passRate = total > 0 ? Math.round(correct / total * 100) : 0
```

因此如果用户 10 题只答 1 题且答对，页面会显示正确率 10%。这不是代码崩溃，但可能与“已答题正确率”认知不一致。

**影响：**

用户可能觉得系统判分异常。尤其在允许跳题提交的情况下，结果页没有明确说明这是“本组得分率”，而非“已答题正确率”。

**修复建议：**

建议同时展示两个指标：

- 完成率：`answeredCount / total`
- 已答正确率：`correct / answeredCount`
- 本组得分率：`correct / total`

至少需要把当前 `passRate` 文案改成“本组得分率”，避免误解。

---

### P2-3：`login` 正式环境仍输出较多认证日志

**位置：**

- `pages/login/login.js:64-82`

**问题说明：**

正式环境中仍有：

```js
console.log('[AUTH] Phase 2 attempt ...')
console.warn('[AUTH] Phase 2 attempt ... FAILED:', msg)
```

**影响：**

不是功能阻断，但正式版调试日志偏多，可能增加排查噪音。若错误对象中包含敏感上下文，也有不必要的信息暴露风险。

**修复建议：**

用 `config.DEBUG_MODE` 包裹：

```js
const config = require('../../config')
if (config.DEBUG_MODE) console.log(...)
```

---

### P2-4：`import-batch` 多空题调试日志未受生产环境开关控制

**位置：**

- `pages/import-batch/import-batch.js:100-118`

**问题说明：**

`debugMultiBlankQuestions()` 中直接输出：

```js
console.info('[import-batch] multi_blank_choice loaded', {...})
```

没有 `DEV` 或 `DEBUG_MODE` 控制。

**影响：**

正式环境仍会输出题目、题型、题干预览、空位结构等调试信息。不是主流程阻断，但会造成正式环境日志污染。

**修复建议：**

```js
const config = require('../../config')
function debugMultiBlankQuestions(...) {
  if (!config.DEBUG_MODE) return
  ...
}
```

如果 `import-batch` 页面已废弃，则直接删除更好。

---

## 四、逐页面审查结论

| 页面 | 结论 | 主要问题 |
|---|---:|---|
| `pages/login/login` | 基本可用 | 生产开发入口已修复；仍有 P2 日志噪音。 |
| `pages/agreement/user` | 未发现明显问题 | 静态协议页。 |
| `pages/agreement/privacy` | 未发现明显问题 | 静态协议页。 |
| `pages/agreement/ai` | 未发现明显问题 | 静态协议页。 |
| `pages/home/home` | 基本可用 | 未发现阻断问题。 |
| `pages/practice/practice` | 基本可用 | 模板调用、多选、多空主问题已修复；结果口径仍需优化。 |
| `pages/practice-result/practice-result` | 基本可用 | `stored` 作用域和错位问题已修复；正确率口径建议优化。 |
| `pages/review-today/review-today` | 有 P1 逻辑问题 | “仅提交已答”会让未答题被流程跳过，建议补闭环。 |
| `pages/wrong-book/wrong-book` | 有 P1 展示口径问题 | 筛选态分析卡可能混入全局统计。 |
| `pages/wrong-detail/wrong-detail` | 基本可用 | 上一轮旧缓存、多空题、`both` 样式问题已修复。 |
| `pages/import/import` | 有 P2 恢复问题 | 长任务轮询连续失败后缺少“继续查询”入口。 |
| `pages/import-batch/import-batch` | 有 P1/P2 问题 | 未注册到 `app.json`，且存在空 `catchtap` 和正式日志。 |
| `pages/dashboard/dashboard` | 基本可用 | dashboard 到 wrong-book 的 subject/topic 传参已被 wrong-book 接收。 |
| `pages/pomodoro/pomodoro` | 有 P1 边界风险 | 主 NaN 已修复；异常暂停缓存仍需强兜底。 |
| `pages/pomodoro-stats/pomodoro-stats` | 有 P1 显示问题 | 重试成功后未清 `errorText`，可能仍停留错误态。 |
| `subpackages/animation/animation-index` | 未发现明显问题 | 页面注册正常。 |

---

## 五、建议上线前最小修复清单

如果只做上线前最小修复，建议优先完成以下 5 项：

1. **修复 `pomodoro-stats` 成功加载后不清 `errorText`。**
2. **给 `pomodoro._restoreSession()` 的暂停时间计算增加 `Number.isFinite` 强兜底。**
3. **修复 `import-batch.wxml` 空 `catchtap`；确认页面是否需要注册到 `app.json`，不用则删除。**
4. **修复 `review-today` 跳过题闭环：跳过题要么保留重做，要么明确不进入“完成”口径。**
5. **修复 `wrong-book` 筛选态 summary card 统计口径，确保使用当前筛选列表数量。**

完成后建议重新跑以下主流程：

- 登录页：未勾协议、勾协议登录、已有 token 直达。
- 练习页：单选、多选、多空题、跳题提交、结果页展示。
- 今日复习：一组全答、一组部分答仅提交已答、一组未答选择按不会处理、多空题部分作答。
- 错题本：从 dashboard 带 subject/topic 跳转、手动筛选、加载更多、进入详情滑动。
- 番茄钟：开始、暂停、退出页面、断网/恢复、继续计时、完成、统计页重试。
- 导入：长任务进行中切后台、网络异常后恢复查询、导入完成跳转。

