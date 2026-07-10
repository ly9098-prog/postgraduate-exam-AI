# miniprogram(6) 页面复查与番茄钟 NaN 根因分析报告

## 一、复查范围

本次基于 上一般修复后的代码进行静态审计，重点检查：

1. `pages/practice`
2. `pages/practice-result`
3. `pages/review-today`
4. `pages/wrong-book`
5. `pages/wrong-detail`
6. `pages/pomodoro`
7. `pages/pomodoro-stats`
8. 番茄钟在“暂停 + 网络波动”场景下显示 `NaN` 的原因链路

补充说明：项目中实际目录是 `pages/pomodoro-stats`，不是 `pages/pomodoro-stat`。`app.json` 和代码跳转均使用 `pomodoro-stats`。

---

## 二、总体结论

**还有问题，不建议直接上线。**

前 5 个学习/错题相关页面相比上一版已有明显修复，但仍有一些统计口径、异步覆盖和边界态问题。`pomodoro` 页面存在两个高优先级问题：

1. **暂停状态下网络异常恢复会触发 `NaN:NaN`，根因明确。**
2. **`pomodoro.wxml` 仍直接调用 JS 方法，微信模板层存在渲染失败风险。**

另外，`config.js` 当前仍为 `DEV = true`，体验版/正式版会请求 `localhost`，这是上线前必须处理的全局阻断项。

---

## 三、P0 / 阻断级问题

### P0-1：`pomodoro` 暂停 + 网络波动时倒计时显示 `NaN:NaN`

**位置：**

- `pages/pomodoro/pomodoro.js:493-515`
- `pages/pomodoro/pomodoro.js:521-524`
- `pages/pomodoro/pomodoro.js:539-540`
- `pages/pomodoro/pomodoro.js:586-587`

**问题链路：**

1. 用户开始番茄钟并暂停。
2. 页面隐藏或重新进入时，`onHide()` 会写入本地缓存 `pomodoro_running_state`。
3. 网络波动时，`_fetchActiveSession()` 请求 `/pomodoro/active` 失败，进入本地缓存恢复逻辑。
4. 本地恢复时构造了：

```js
start_time: new Date(local.sessionStartTime).toISOString()
```

该值类似：

```js
2026-07-02T14:07:25.227Z
```

5. 但 `_restoreSession()` 又执行：

```js
const startTime = new Date(session.start_time + '+00:00').getTime()
```

拼接后变成：

```js
2026-07-02T14:07:25.227Z+00:00
```

这是非法时间，`getTime()` 得到 `NaN`。

6. 后续计算全部被污染：

```js
elapsed = Math.floor((Date.now() - NaN - totalPausedMs) / 1000) // NaN
remaining = Math.max(0, totalSec - NaN) // NaN
displayMin = String(Math.floor(NaN / 60)).padStart(2, '0') // 'NaN'
displaySec = String(NaN % 60).padStart(2, '0') // 'NaN'
progress = NaN
```

所以页面最终显示 `NaN:NaN`，并且进度环也可能异常。

**为什么“暂停过程中 + 网络波动”更容易触发：**

暂停后页面隐藏/返回时会依赖 `pomodoro_pause` 和 `pomodoro_running_state` 恢复；网络异常时不会使用服务端 `/pomodoro/active` 的数据，而是使用本地缓存构造出来的 ISO 时间。这个本地 ISO 时间已经带 `Z`，再次拼接 `+00:00` 就会出错。

**修复建议：**

新增统一时间解析函数，禁止无条件拼接 `+00:00`：

```js
function parseServerTime(value) {
  if (!value) return NaN
  if (typeof value === 'number') return value
  const s = String(value)
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTimezone ? s : s + '+00:00').getTime()
}
```

替换：

```js
new Date(session.start_time + '+00:00').getTime()
new Date(session.paused_at + '+00:00').getTime()
```

同时在 `_restoreSession()` 里加防御：

```js
if (!Number.isFinite(startTime) || !Number.isFinite(totalSec) || totalSec <= 0) {
  wx.removeStorageSync('pomodoro_pause')
  wx.removeStorageSync('pomodoro_running_state')
  this._resetToIdle()
  wx.showToast({ title: '番茄钟状态异常，已重置', icon: 'none' })
  return
}
```

---

### P0-2：`config.js` 仍是 `DEV = true`，正式/体验环境会请求 localhost

**位置：**

- `config.js:9-20`

当前配置：

```js
const DEV = true
```

因此 `BASE_URL` 会是：

```js
http://localhost:8000/api/v1
```

在真机、体验版、正式版中，`localhost` 指向用户手机自身，不是你的后端服务，所以所有 API 会失败。

**影响范围：**

- `practice`
- `practice-result` 增长值接口
- `review-today`
- `wrong-book`
- `wrong-detail`
- `pomodoro`
- `pomodoro-stats`
- 其它所有依赖 `utils/api.js` 的页面

**修复建议：**

至少上线前改为：

```js
const DEV = false
```

更推荐改成构建时环境变量注入，避免人工漏改。

---

### P0-3：`pomodoro.wxml` 仍直接调用 JS 方法，模板层存在渲染风险

**位置：**

- `pages/pomodoro/pomodoro.wxml:102`
- `pages/pomodoro/pomodoro.wxml:115-119`
- `pages/pomodoro/pomodoro.wxml:131`

当前写法：

```xml
{{subjectLabel(selectedSubject)}}
{{subjectEmoji(selectedSubject)}}
{{presetLabel(selectedPreset)}}
```

微信小程序 WXML 模板层不应依赖 Page 实例方法调用。之前 `practice.wxml` 的 `modeLabel()` / `Math.round()` 已经处理过，这里属于同类问题。

**影响：**

- 从刷题页进入番茄钟时，科目提示可能不显示或报模板表达式错误。
- 仪式页科目名、科目 emoji、预设名称可能渲染失败。
- 运行页顶部科目显示可能异常。

**修复建议：**

在 JS data 中维护预计算字段：

```js
selectedSubjectLabel: ''
selectedSubjectEmoji: '📚'
selectedPresetLabel: '标准'
modeInfoText: ''
contextSubjectText: ''
```

每次以下状态变化后统一调用 `_updateComputedFields()`：

- `selectSubject`
- `selectPreset`
- `onWorkChange`
- `onBreakChange`
- `_beginCountdown`
- `_restoreSession`
- `_resolveAndMapSubjectId`
- `_resetToIdle`

WXML 改成：

```xml
{{selectedSubjectLabel}}
{{selectedSubjectEmoji}}
{{selectedPresetLabel}}
{{modeInfoText}}
```

---

## 四、P1 / 高优先级问题

### P1-1：`practice` 允许 0 题作答后提交，可能导致空数组批改

**位置：**

- `pages/practice/practice.js:1070-1123`

当前逻辑中，用户可以一道题都不答，弹窗确认后继续提交：

```js
const completedQuestions = questions.filter(q => answeredFlags[String(q.id)])
const answers = completedQuestions.map(...)
await api.post('/practice/batch-submit', { answers })
```

当 `completedQuestions.length === 0` 时，会提交空 `answers` 数组。

**影响：**

- 后端若不接受空数组，会直接提交失败。
- 即便后端接受，结果页可能出现“总题数有值、正确/错误为 0、全部跳过”的特殊状态，用户体验不明确。

**修复建议：**

提交前增加保护：

```js
if (answeredCount === 0) {
  wx.showToast({ title: '请至少作答 1 题', icon: 'none' })
  return
}
```

或者提供两个明确选项：

- 返回继续答题
- 结束并不提交批改

---

### P1-2：`review-today` “仅提交已答”时，最终统计仍把跳过题算进完成题数

**位置：**

- `pages/review-today/review-today.js:723-733`
- `pages/review-today/review-today.js:744-764`
- `pages/review-today/review-today.js:836-846`

当前提交时，如果用户选择“仅提交已答”，payload 确实会跳过未答题：

```js
if (!isAnswered && !treatUnansweredAsWrong) continue
```

但后续构造结果时仍然对 `groupQuestions` 全量 `map`：

```js
groupQuestions.map(q => { ... })
```

然后全部加入：

```js
const allGroupResults = [...this.data.allGroupResults, ...groupResults]
```

最终页使用：

```js
const total = this.data.allGroupResults.length
```

**影响：**

如果一组 10 题，只答 2 题并选择“仅提交已答”，最终页可能显示完成 10 题，而不是完成 2 题 / 跳过 8 题。正确率 denominator 也会受影响。

**修复建议：**

明确区分：

- `submittedResults`：真正提交批改的题
- `skippedResults`：未提交、跳过的题
- `displayResults`：页面展示用
- `accuracyDenominator`：正确率是否包含跳过题，要产品口径明确

如果“仅提交已答”语义成立，最终统计建议：

```js
completedCount = allGroupResults.filter(r => r.wasSubmitted).length
skippedCount = allGroupResults.filter(r => r.wasSkipped).length
accuracy = completedCount > 0 ? correct / completedCount : 0
```

---

### P1-3：`review-today` 多空题“部分作答”在结果态仍可能被标记为已作答

**位置：**

- `pages/review-today/review-today.js:725-732`
- `pages/review-today/review-today.js:746-755`

提交 payload 使用的是：

```js
const isAnswered = _isQuestionAnswered(q, answers)
```

这是正确方向，可以识别多空题是否每个空都答完。

但结果构造时又使用：

```js
const wasAnswered = !!answers[q.schedule_id]
```

对于多空题，只答一个空也会产生非空字符串，例如：

```js
空1:A
```

于是 `wasAnswered === true`，即使 `_isQuestionAnswered()` 认为它没有完整作答。

**影响：**

- 多空题部分作答时，统计、结果页、跳过状态可能不一致。
- 用户选择“按不会处理”时，payload 可能提交空答案，但结果页仍显示用户有作答。

**修复建议：**

结果构造统一使用：

```js
const wasAnswered = _isQuestionAnswered(q, answers)
```

不要再用 `!!answers[q.schedule_id]` 判断作答完成。

---

### P1-4：`wrong-book` 统计分析存在异步覆盖风险，筛选态分析仍可能被全局统计覆盖

**位置：**

- `pages/wrong-book/wrong-book.js:85-90`
- `pages/wrong-book/wrong-book.js:92-100`
- `pages/wrong-book/wrong-book.js:134-157`

`_loadPage()` 同时触发：

```js
this.loadStats()
this.loadList(true)
this.loadAiDiagnosis()
```

`loadList()` 中已经有筛选态修复：

```js
const hasFilter = this.data.selectedSubject || this.data.selectedErrorType
const statsForAnalysis = hasFilter ? null : this.data.stats
analysis: this._buildAnalysis(statsForAnalysis, nextList)
```

但 `loadStats()` 是异步并行执行的，里面仍会：

```js
analysis: this._buildAnalysis(stats, this.data.list)
```

如果 `loadStats()` 比 `loadList()` 晚返回，就可能把 `loadList()` 刚算好的“当前列表统计”覆盖回“全局统计”。

**影响：**

- 从 dashboard 带 subject 进入错题本时，知识漏洞分析可能仍显示全局错题分析。
- 用户快速切换筛选条件时，分析区和列表可能不一致。

**修复建议：**

方案一：`loadStats()` 不再直接写 `analysis`，只写 `stats` 和顶部计数；`analysis` 统一由 `loadList()` 根据当前筛选状态生成。

方案二：增加 request token：

```js
const token = ++this._loadToken
await ...
if (token !== this._loadToken) return
```

并且 `loadStats()` 写入前检查当前是否有筛选条件。

---

### P1-5：`wrong-detail` 多空题只读取 `content.blank_option_groups`，不支持顶层字段

**位置：**

- `pages/wrong-detail/wrong-detail.js:54`

当前：

```js
const blankOptionGroups = _enrichBlankOptionGroups(wq.content && wq.content.blank_option_groups, wq.answer, wq.wrong_answer)
```

但 `practice` 和 `review-today` 都已经兼容：

```js
q.content.blank_option_groups
q.blank_option_groups
```

**影响：**

如果错题详情接口返回的是顶层 `blank_option_groups`，`wrong-detail` 将无法展示多空题选项组，只能显示题干和答案，复盘体验不完整。

**修复建议：**

统一新增：

```js
function _getBlankOptionGroups(q) {
  if (!q) return []
  if (q.content && Array.isArray(q.content.blank_option_groups)) return q.content.blank_option_groups
  if (Array.isArray(q.blank_option_groups)) return q.blank_option_groups
  return []
}
```

然后替换 line 54。

---

### P1-6：`pomodoro` 恢复暂停状态时没有设置 `progress`，进度环可能停在旧状态

**位置：**

- `pages/pomodoro/pomodoro.js:577-591`
- `pages/pomodoro/pomodoro.js:593-602`

`_restoreSession()` 在恢复暂停状态时设置了：

```js
remainingSec
displayMin
displaySec
isPaused
totalPausedMs
pauseStartTime
```

但没有设置：

```js
progress
```

非暂停时会进入 `_startTimer(totalSec)`，由 tick 重新设置 progress；但暂停状态不会启动 timer，因此 progress 可能保持旧值或默认值。

**影响：**

- 文本时间可能是恢复后的时间，进度环却仍是旧进度。
- 如果叠加 P0-1 的 NaN，进度环也可能进入异常状态。

**修复建议：**

在 `_restoreSession()` setData 中补充：

```js
progress: totalSec > 0 ? remaining / totalSec : 0
```

并在 `isPaused` 分支里初始化 canvas 后 draw 一次。

---

### P1-7：`pomodoro-stats` 历史记录也存在同类时间解析风险

**位置：**

- `pages/pomodoro-stats/pomodoro-stats.js:182-190`

当前：

```js
const start = new Date(s.start_time + '+00:00')
```

如果后端返回 `2026-07-02T14:07:25Z` 或带 `+00:00` 的时间，这里同样会变成非法时间。

**影响：**

- 历史记录时间可能显示 `NaN:NaN`。
- 日期可能显示 `NaN/NaN`。

**修复建议：**

和 `pomodoro.js` 共用 `parseServerTime()`。

---

## 五、P2 / 中低优先级问题

### P2-1：`wrong-detail` 的“返回错题本”按钮直接 `navigateBack()`，直达场景可能无效

**位置：**

- `pages/wrong-detail/wrong-detail.wxml:13-14`
- `pages/wrong-detail/wrong-detail.js:369-371`

错误态按钮文案是“返回错题本”，但实际逻辑是：

```js
wx.navigateBack()
```

如果用户从分享、调试入口、直接 URL 进入详情页，页面栈没有错题本，点击可能无效。

**修复建议：**

```js
goBack() {
  const pages = getCurrentPages()
  if (pages.length > 1) wx.navigateBack()
  else wx.redirectTo({ url: '/pages/wrong-book/wrong-book' })
}
```

---

### P2-2：`practice-result` 答题详情长答案仍可能被截断

**位置：**

- `pages/practice-result/practice-result.wxml:96-99`
- `pages/practice-result/practice-result.wxss:443-452`

当前答案样式：

```css
overflow: hidden;
text-overflow: ellipsis;
white-space: nowrap;
```

对于多空题、解析式答案、较长公式答案，会只显示一行省略。

**影响：**

用户可能看不到完整正确答案，复盘价值下降。

**修复建议：**

对 `.detail-answer` 改为允许换行：

```css
white-space: normal;
overflow: visible;
word-break: break-word;
```

或为答案区域增加“展开完整答案”。

---

### P2-3：`wrong-detail` 多空题中“我选对的空”没有 both 状态

**位置：**

- `pages/wrong-detail/wrong-detail.js:117-123`
- `pages/wrong-detail/wrong-detail.wxml:58`

当前逻辑：

```js
_isCorrect: isCorrect,
_isUserAnswer: !isCorrect && wrongAnswers[groupId] === key,
```

如果用户某一个空选对了，页面只显示“正确答案”状态，不显示“这也是我的选项”。

**影响：**

多空题部分错时，用户不容易区分“我哪些空答对了，哪些空答错了”。

**修复建议：**

增加 `_isBoth`：

```js
const isUser = wrongAnswers[groupId] === key
_isCorrect: isCorrect,
_isUserAnswer: isUser,
_isBoth: isCorrect && isUser
```

并补充 `.blank-option-item.both` 样式。

---

### P2-4：`pomodoro-stats` 统计页接口失败后只有 toast，没有页面级重试入口

**位置：**

- `pages/pomodoro-stats/pomodoro-stats.js:174-179`
- `pages/pomodoro-stats/pomodoro-stats.wxml:4-103`

当前失败后：

```js
this.setData({ loading: false })
wx.showToast({ title: '加载失败', icon: 'none' })
```

页面没有 `errorText` 和重试按钮。

**影响：**

网络波动时，用户只看到空白/旧数据，不知道如何恢复。

**修复建议：**

增加：

```js
errorText: ''
```

失败时设置错误态，并在 WXML 提供“重新加载”。

---

### P2-5：`pomodoro-stats` 历史记录时长字段兼容性不足

**位置：**

- `pages/pomodoro-stats/pomodoro-stats.js:185`

当前只读取：

```js
s.actual_duration
```

但项目其它位置提交完成时使用过：

```js
actual_duration_sec
```

如果历史接口返回的是 `actual_duration_sec`，统计页会显示 `0分钟`。

**修复建议：**

兼容多个字段：

```js
const duration = s.actual_duration ?? s.actual_duration_sec ?? s.duration_sec ?? 0
```

---

## 六、已确认修复或基本正常的点

以下问题在 `当前版本` 中已看到修复痕迹：

1. `practice.wxml` 中原先的 `modeLabel()`、`Math.round()` 模板函数调用已移除。
2. `practice-result.js` 中 `stored` 作用域问题已修复。
3. `practice-result` 已改为按 `question_id` 匹配题干，不再按数组下标错配。
4. `review-today.wxml` 中上一版 `answers[...].indexOf(...)` 的模板层调用已改为 `_optionList` 预计算。
5. `review-today` 中 `groupSizeOptions` 已放入 data，上一版 `wx:for="{{[5, 10, 20]}}"` 已修复。
6. `wrong-detail` 已验证 storage 中的 `wrong_detail_ids` 必须包含当前 id，旧缓存污染问题已基本修复。
7. `wrong-detail` 已补充 `.both` 样式。
8. `wrong-book` 的 `loadMore()` 已有 `loading || !hasMore` 并发防护。
9. JS 文件通过 `node --check` 语法检查。

---

## 七、番茄钟 NaN 的最小复现路径

1. 开始一个番茄钟。
2. 点击暂停。
3. 切到后台或离开页面，触发 `onHide()` 保存 `pomodoro_running_state` 和 `pomodoro_pause`。
4. 返回页面时制造网络异常，使 `/pomodoro/active` 请求失败。
5. `_fetchActiveSession()` 使用本地缓存恢复，并生成带 `Z` 的 ISO 字符串。
6. `_restoreSession()` 对该字符串再次拼接 `+00:00`。
7. `Date` 解析失败，`startTime = NaN`。
8. 页面显示 `NaN:NaN`。

---

## 八、建议修复顺序

1. **先修 P0-1：统一时间解析，彻底解决番茄钟 NaN。**
2. **再修 P0-3：移除 `pomodoro.wxml` 模板方法调用。**
3. **上线前必须处理 P0-2：`DEV=false` 或构建环境变量。**
4. 修 `review-today` 的跳过/部分作答统计口径。
5. 修 `wrong-book` 的 stats/list 并发覆盖。
6. 修 `wrong-detail` 顶层 `blank_option_groups` 兼容。
7. 最后处理结果页长答案、统计页错误态等体验问题。

---

## 九、核心修复代码建议：番茄钟时间解析

建议在 `pages/pomodoro/pomodoro.js` 和 `pages/pomodoro-stats/pomodoro-stats.js` 复用：

```js
function parseServerTime(value) {
  if (!value) return NaN
  if (typeof value === 'number') return value
  const s = String(value).trim()
  if (!s) return NaN
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTimezone ? s : s + '+00:00').getTime()
}

function isValidNumber(n) {
  return typeof n === 'number' && Number.isFinite(n)
}
```

替换所有：

```js
new Date(x + '+00:00').getTime()
```

并在计算 `remaining/displayMin/displaySec/progress` 前做防御：

```js
if (!Number.isFinite(remaining)) {
  this._resetToIdle()
  wx.showToast({ title: '番茄钟状态异常，已重置', icon: 'none' })
  return
}
```

---

## 十、最终判断

当前版本可以继续作为开发修复版推进，但不适合直接发布。最需要优先解决的是番茄钟 NaN、模板方法调用、正式环境配置、复习统计口径和错题本异步覆盖问题。
