# miniprogram(8) 全页面最终审查报告

审查对象：`pages` 全目录、核心 `utils`、`config.js`、组件 WXML 引用。

审查范围覆盖页面：

- 登录与协议：`login`、`agreement/user`、`agreement/privacy`、`agreement/ai`
- 首页与数据看板：`home`、`dashboard`
- 导入链路：`import`、`import-batch`
- 练习/复习/错题链路：`practice`、`practice-result`、`review-today`、`wrong-book`、`wrong-detail`
- 番茄钟链路：`pomodoro`、`pomodoro-stats`

审查方法：

- 解压源码并全量扫描 `pages` 下 JS/WXML/WXSS/JSON。
- 使用 `node --check` 对所有页面 JS、组件 JS、工具 JS 做语法检查。
- 使用 JSON 解析检查全部 JSON 配置文件。
- 静态扫描 WXML 中的页面级模板方法调用、空事件绑定、直接表达式风险。
- 复查上一轮报告中的 P0/P1/P2 问题是否修复。
- 重点追踪练习、今日复习、错题本、错题详情、导入批次、番茄钟恢复与统计链路。

## 一、总体结论

**仍然存在问题，不建议直接上线。**

这版已经修复了上一轮多数关键问题，尤其是：

1. `config.js` 已切换为 `DEV = false`，正式环境接口不再指向 `localhost`。
2. `review-today` 最终完成弹窗中的 `total` 未定义问题已修复。
3. `pomodoro` 暂停 + 网络波动时因 `Z+00:00` 导致 `NaN:NaN` 的主因已修复。
4. `pomodoro.wxml` 中的模板方法调用已移除，改为预计算字段。
5. `practice-result.js` 的 `stored` 作用域问题已修复。
6. `practice-result` 跳题后结果按数组下标错位的问题已改为按 `question_id` 映射。
7. `wrong-detail` 旧 storage 列表污染、判断题兜底、多空题顶层字段兼容等问题已修复。
8. `import` 页面长任务轮询在返回页面后恢复的逻辑已补上。

但本次全页面审查发现仍有新的/残留问题，其中 `wrong-book` 筛选态会触发运行时异常，是当前最重要的上线阻断项。

---

## 二、P0 阻断问题

### P0-1：`wrong-book` 任意筛选态可能导致错题列表加载失败

**影响页面**：`pages/wrong-book/wrong-book.js`

**影响场景**：

- 从 dashboard 点击某个知识点进入错题本；
- 在错题本中选择学科筛选；
- 在错题本中选择错因类型筛选；
- URL 携带 `topic` / `subject` 参数进入错题本。

**问题位置**：

```js
// pages/wrong-book/wrong-book.js:153-158
const hasFilter = this.data.selectedSubject || this.data.selectedErrorType || this.data.selectedTopic
const statsForAnalysis = hasFilter ? null : this.data.stats
this.setData({
  list: nextList,
  analysis: this._buildAnalysis(statsForAnalysis, nextList),
  ...
})
```

```js
// pages/wrong-book/wrong-book.js:254-267
_buildSummaryCards(stats = {}, list = [], weaknessTags = []) {
  const unmastered = this._positiveNumber(stats.unmastered, this.data.primaryStatCount || stats.total || list.length || 0)
  ...
}
```

**原因分析**：

筛选态下 `statsForAnalysis` 被设置为 `null`，随后传入 `_buildAnalysis(null, nextList)`。虽然 `_buildAnalysis(stats = {}, list = [])` 和 `_buildSummaryCards(stats = {}, ...)` 写了默认参数，但 **JS 默认参数只对 `undefined` 生效，对显式传入的 `null` 不生效**。

因此 `_buildSummaryCards(null, ...)` 中访问：

```js
stats.unmastered
stats.total
```

会触发：

```txt
TypeError: Cannot read property 'unmastered' of null
```

该异常发生在 `loadList()` 的 `try` 内，会进入 `catch`，导致筛选后的列表和分析区加载失败。尤其 dashboard 已经支持 `topic` 跳转，所以这个问题会直接影响数据看板到错题本的主链路。

**修复建议**：

方案一，调用处不要传 `null`：

```js
const statsForAnalysis = hasFilter ? {} : (this.data.stats || {})
```

方案二，所有分析函数入口统一兜底：

```js
_buildAnalysis(stats = {}, list = []) {
  stats = stats || {}
  ...
}

_buildSummaryCards(stats = {}, list = [], weaknessTags = []) {
  stats = stats || {}
  ...
}
```

建议两个都做：调用层传 `{}`，函数层再做 `stats = stats || {}`，避免后续维护再次踩坑。

**回归测试建议**：

1. 从 dashboard 点击某个 topic 进入 wrong-book。
2. 在 wrong-book 内选择任意学科筛选。
3. 在 wrong-book 内选择任意错因筛选。
4. 筛选态下滚动加载更多。
5. 确认列表、知识漏洞分析、行动建议都能正常展示。

---

## 三、P1 重要问题

### P1-1：`import-batch.wxml` 存在空 `catchtap` 绑定，可能导致编译/事件拦截异常

**影响页面**：`pages/import-batch/import-batch.wxml`

**问题位置**：

```xml
<!-- pages/import-batch/import-batch.wxml:40 -->
<text class="q-math-flag" wx:if="{{item._hasMath}}" bindtap="showMathPreview" catchtap data-id="{{item.id}}">含公式</text>
```

```xml
<!-- pages/import-batch/import-batch.wxml:51 -->
<view class="q-detail {{expanding === item.id ? 'show' : ''}}" catchtap>
```

**问题说明**：

这里存在没有指定处理函数的 `catchtap`。这类写法至少会导致事件拦截意图不明确，严重时微信开发者工具可能提示 WXML 编译/运行异常。

同时第 40 行同时写了 `bindtap="showMathPreview"` 和空 `catchtap`，如果空 `catchtap` 不生效，点击“含公式”可能同时触发外层卡片 `onCardTap`，导致一边弹公式预览、一边展开/收起卡片。

**修复建议**：

第 40 行改为只使用 `catchtap`：

```xml
<text
  class="q-math-flag"
  wx:if="{{item._hasMath}}"
  catchtap="showMathPreview"
  data-id="{{item.id}}"
>含公式</text>
```

第 51 行新增空处理函数：

```xml
<view class="q-detail {{expanding === item.id ? 'show' : ''}}" catchtap="noop">
```

并在 `import-batch.js` 中增加：

```js
noop() {},
```

**回归测试建议**：

1. 导入一个含公式题目的批次。
2. 点击“含公式”标签，只打开公式预览，不触发卡片展开/收起。
3. 点击已展开详情区内部，不触发外层卡片折叠。

---

### P1-2：登录页自动登录可能绕过“同意协议”校验

**影响页面**：`pages/login/login.js`

**问题位置**：

```js
// pages/login/login.js:13-17
onLoad() {
  if (this._tryDirectRedirect()) return
  this._autoLogin()
}
```

```js
// pages/login/login.js:42-70
async _autoLogin() {
  ...
  const { code } = await wx.login()
  const data = await api.post('/auth/login', { code })
  auth.loginDirect(...)
  wx.redirectTo({ url: '/pages/home/home' })
}
```

```js
// pages/login/login.js:102-124
ensureAgreementAccepted() {
  if (this.data.agreed) return true
  wx.showToast({ title: '请先阅读并同意相关协议', icon: 'none' })
  return false
}

async onWechatLogin() {
  if (!this.ensureAgreementAccepted()) return
  ...
}
```

**问题说明**：

手动点击微信登录和开发者登录时，会检查 `agreed`。但页面 `onLoad()` 会直接执行 `_autoLogin()`，在没有 token 或 token 失效时仍会走 `wx.login()` + `/auth/login`，成功后直接跳转首页。

这会导致首次使用或协议未勾选时，用户可能还没勾选协议就被自动登录。

**修复建议**：

建议将自动登录拆成两种情况：

1. **已有有效 token / 可刷新 token**：可以自动跳转或自动刷新。
2. **无 token，需要首次 `wx.login` 注册/登录**：必须等待用户勾选协议并点击按钮。

示例逻辑：

```js
onLoad() {
  if (this._tryDirectRedirect()) return
  if (auth.isLoggedIn()) {
    this._autoRefreshExistingToken()
  } else {
    this.setData({ loading: false })
  }
}
```

或者在 `_autoLogin()` 的 Phase 2 前增加：

```js
if (!this.data.agreed) {
  this.setData({ loading: false })
  return
}
```

但更推荐前一种拆分方式，避免页面一进来就请求登录接口。

**回归测试建议**：

1. 清空本地 token 和用户信息。
2. 首次打开小程序，确认不会自动进入首页。
3. 不勾选协议点击登录，应提示“请先阅读并同意相关协议”。
4. 勾选协议后点击登录，才能进入首页。
5. 已登录用户再次打开，可以正常自动进入首页。

---

## 四、P2 一般问题 / 体验风险

### P2-1：`review-today` 多空题只答一空时，题号圆点会误显示为“已答”

**影响页面**：`pages/review-today/review-today.wxml`

**问题位置**：

```xml
<!-- pages/review-today/review-today.wxml:132-135 -->
<view
  wx:for="{{groupQuestions}}" wx:key="schedule_id"
  class="q-dot {{answers[item.schedule_id] ? 'answered' : ''}} {{currentIndex === index ? 'current' : ''}}"
  catchtap="goQuestion"
  data-index="{{index}}"
>
```

**问题说明**：

JS 中 `_isQuestionAnswered()` 已经要求 `multi_blank_choice` 的所有空都答完才算完成，这个是正确的。但 WXML 题号圆点仍然只判断：

```js
answers[item.schedule_id]
```

所以多空题只答了一个空时，圆点会显示为“已答”，而底部统计和提交逻辑又认为它未完成。用户会看到两个口径不一致的反馈。

**修复建议**：

在 JS 中为每道题预计算 `_answered`，WXML 只读字段：

```js
question._answered = this._isQuestionAnswered(question, this.data.answers)
```

WXML 改为：

```xml
class="q-dot {{item._answered ? 'answered' : ''}} {{currentIndex === index ? 'current' : ''}}"
```

在 `selectOption`、`selectBlankOption`、`_showQuestion`、`submitGroup` 后同步刷新该字段。

---

### P2-2：`wrong-detail` 多空题“正确且我选中”的 blank option 缺少 `.both` 样式

**影响页面**：`pages/wrong-detail/wrong-detail.wxml`、`pages/wrong-detail/wrong-detail.wxss`

**问题位置**：

```xml
<!-- pages/wrong-detail/wrong-detail.wxml:58 -->
<view class="option-item blank-option-item {{opt._isBoth ? 'both' : ''}} ...">
```

WXSS 中目前有：

```css
.option-line.both { ... }
.option-value.both { ... }
```

但没有看到对应的：

```css
.blank-option-item.both { ... }
.blank-option-item.both .option-key { ... }
```

**问题说明**：

普通选择题的 `both` 已有样式；多空题 blank option 也会生成 `both` class，但没有对应样式。结果是多空题中“正确答案且我选中”的选项视觉上可能不突出，只能依赖其它样式或默认样式。

**修复建议**：

补充：

```css
.blank-option-item.both {
  background: #ECFDF3;
  border: 2rpx solid #22C55E;
}

.blank-option-item.both .option-key,
.blank-option-item.both .option-value {
  color: #22C55E;
  font-weight: 800;
}
```

---

### P2-3：`wrong-book` 首次无筛选加载时，分析区可能不是全局统计口径

**影响页面**：`pages/wrong-book/wrong-book.js`

**问题位置**：

```js
// pages/wrong-book/wrong-book.js:90-94
_loadPage() {
  this.setData({ list: [], page: 1 })
  this.loadStats()
  this.loadList(true)
  this.loadAiDiagnosis()
}
```

**问题说明**：

`loadStats()` 和 `loadList(true)` 并行执行。`loadList()` 中会用 `this.data.stats` 生成分析区。如果列表先返回，而 stats 后返回，分析区可能先按当前列表生成；之后 `loadStats()` 只更新 `stats` 和顶部数量，不会重新生成 `analysis`。

这不会导致崩溃，但无筛选首页的分析口径可能不是预期的全局统计口径。

**修复建议**：

任选一种：

1. `_loadPage()` 中先 `await loadStats()`，再 `loadList(true)`。
2. `loadStats()` 成功后，如果当前无筛选且已有 list，重新执行：

```js
this.setData({
  analysis: this._buildAnalysis(stats, this.data.list),
})
```

---

### P2-4：`practice` 无选中科目时缺少完整状态回退兜底

**影响页面**：`pages/practice/practice.js`

**问题位置**：

```js
// pages/practice/practice.js:493-498
if (!subjectId) {
  wx.showToast({ title: '请选择科目', icon: 'none' })
  this.setData({ loading: false })
  return
}
```

**问题说明**：

正常 UI 下开始按钮会被 `selectedSubjectId` 禁用，所以这个分支不容易触发。但如果科目树加载异常、状态竞争、或后续代码改动导致 `startPractice()` 被调用，此处只把 `loading` 设为 false，没有清计时器，也没有把 `started` 回退为 false。

**修复建议**：

```js
if (!subjectId) {
  this._clearTimer()
  this.setData({
    loading: false,
    started: false,
    questions: [],
    totalQuestions: 0,
    currentQuestion: null,
  })
  wx.showToast({ title: '请选择科目', icon: 'none' })
  return
}
```

---

### P2-5：`import-batch` 多空题调试日志未受 `DEV` 控制

**影响页面**：`pages/import-batch/import-batch.js`

**问题位置**：

```js
// pages/import-batch/import-batch.js:100-118
function debugMultiBlankQuestions(questions, batchId) {
  if (typeof console === 'undefined') return
  ...
  console.info('[import-batch] multi_blank_choice loaded', {...})
}
```

**问题说明**：

正式环境中仍会输出多空题导入调试日志。虽然不会直接影响用户界面，但可能产生不必要的控制台噪音，也可能暴露题目预览、批次 ID、题目 ID 等调试信息。

**修复建议**：

引入 `config.DEV` 或 `config.DEBUG_MODE` 控制：

```js
const config = require('../../config')

function debugMultiBlankQuestions(questions, batchId) {
  if (!config.DEV) return
  ...
}
```

---

### P2-6：`home` 修改今日目标后，成长等级信息可能短暂回退为本地估算

**影响页面**：`pages/home/home.js`

**问题说明**：

`loadOverview()` 会合并 `/stats/overview` 和 `/stats/growth` 的结果，生成成长等级信息。但用户修改今日目标后，页面使用 `_lastOverview` 重新构建 snapshot，没有同步传入最近一次 growth 数据，可能导致等级、经验条短暂回退为本地估算值。

这不是阻断问题，但会让首页成长信息在用户修改目标后出现轻微不一致。

**修复建议**：

缓存最近一次 growth 数据，例如：

```js
this._lastGrowth = growth
```

修改目标后：

```js
const snapshot = this.buildGrowthSnapshot(this._lastOverview || {}, this._lastGrowth || {})
```

---

## 五、上一轮重点问题复查结果

| 上一轮问题 | 本轮状态 | 说明 |
|---|---:|---|
| `config.js` 仍为 `DEV = true` | 已修复 | 当前为 `DEV = false`，生产地址为 `https://xzshub.top/api/v1` |
| `review-today` 最终弹窗 `total` 未定义 | 已修复 | `_showFinalCelebration()` 已改用 `denom` |
| `pomodoro` 暂停 + 网络波动显示 `NaN:NaN` | 主因已修复 | 已使用 `parseServerTime()`，并对本地缓存 `sessionStartTime` 做有限数字校验 |
| `pomodoro.wxml` 模板方法调用 | 已修复 | 页面级 WXML 未再发现 `subjectLabel(...)` / `presetLabel(...)` 这类调用 |
| `pomodoro` 休息倒计时速度快一倍 | 已修复 | 休息阶段已按时间差计算，而不是 500ms 扣 1 秒 |
| `practice-result.js` 的 `stored` 作用域错误 | 已修复 | 已改为 `let stored = null` |
| `practice-result` 跳题后题目错位 | 已修复 | 已按 `question_id` 映射题目 |
| `dashboard -> wrong-book` topic 参数未接收 | 已修复一半 | wrong-book 已接收 topic，但由于 P0-1，带 topic 后会触发筛选态 null stats 异常 |
| `import` 页面隐藏后轮询不恢复 | 已修复 | `onShow()` 已根据 `pipelinePolling` 恢复轮询 |
| `wrong-detail` 旧 ids 缓存污染 | 已修复 | 只有 storage 列表包含当前 id 时才启用滑动列表 |
| `wrong-detail` 多空题顶层字段兼容 | 已修复 | 已兼容 `content.blank_option_groups` 和顶层 `blank_option_groups` |

---

## 六、本次未发现明显问题的页面/模块

以下页面本轮没有发现新的阻断级问题：

- `agreement/user`
- `agreement/privacy`
- `agreement/ai`
- `dashboard` 主数据渲染链路
- `pomodoro-stats`
- `practice-result`
- `wrong-detail` 主详情加载链路
- `import` 主导入任务链路

但需要注意：`dashboard` 到 `wrong-book` 的 topic 跳转本身已实现，真正的失败点在 `wrong-book` 的筛选态分析构建。

---

## 七、建议修复顺序

建议按以下顺序处理：

1. **先修 P0-1：`wrong-book` 筛选态 null stats 崩溃。**
2. 修复 `import-batch.wxml` 的空 `catchtap`。
3. 明确登录页协议策略，避免首次自动登录绕过协议勾选。
4. 补齐 `wrong-detail` 多空题 `.both` 样式。
5. 统一 `review-today` 题号圆点的“已答”口径。
6. 优化 `wrong-book` 无筛选初始分析口径。
7. 清理生产环境调试日志和低概率状态兜底。

---

## 八、最终上线建议

当前版本相比上一版已经明显收敛，但仍然存在一个会影响核心路径的阻断问题：

> `wrong-book` 只要进入筛选态，就可能因为 `stats = null` 触发运行时异常，导致错题列表/分析加载失败。

因此建议：

- **不建议直接上线。**
- 修复 P0-1 和 P1-1 后，至少重新跑以下主流程：
  1. 首页进入练习并交卷；
  2. 今日复习完成一组和全部完成；
  3. dashboard 点击 topic/subject 进入 wrong-book；
  4. wrong-book 手动筛选学科、错因、清除 topic；
  5. wrong-detail 左右滑动、多选题、多空题展示；
  6. import 上传后进入 import-batch，点击含公式标签和展开详情；
  7. pomodoro 开始、暂停、断网恢复、完成、进入统计页。
