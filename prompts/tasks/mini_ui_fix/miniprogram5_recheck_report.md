# miniprogram(5).zip 修复后复查报告

## 复查结论

本轮相较 `上一版` 已修复若干关键问题，例如：

- `practice-result.js` 的 `stored` 作用域问题已修复。
- `practice-result` 已改为按 `question_id` 匹配题干，跳题后错位问题基本解决。
- `review-today.wxml` 中直接调用 `indexOf()` 的模板表达式已移除，改为 `_optionList` 预计算。
- `wrong-detail` 已避免旧 `wrong_detail_ids` 缓存污染：只有缓存列表包含当前 `id` 时才启用滑动列表。
- `wrong-detail.wxss` 已补充 `.both` 样式。

但仍存在残留问题，尤其是 `review-today` 多空题提交统计仍有逻辑漏洞，另有上线环境配置风险。因此当前版本仍不建议直接上线。

---

## P0 / 上线阻断问题

### P0-1：`review-today` 多空题“部分作答”仍被当作已作答提交

**位置：**

- `pages/review-today/review-today.js:665-719`
- 关键代码：

```js
const answeredCount = Object.keys(answers).filter(k => answers[k]).length
...
const answer = answers[q.schedule_id]
if (!answer && !treatUnansweredAsWrong) continue
reviews.push({
  schedule_id: q.schedule_id,
  question_id: q.question_id,
  user_answer: answer || '',
})
```

**问题说明：**

页面前面已经新增了 `_computeAnsweredCount(groupQuestions, answers)`，该函数可以正确判断多空题是否每一空都已选择。但 `submitGroup()` 中没有使用它，仍然用 `Object.keys(answers)` 统计。

这会导致：

1. 多空题有 3 个空，只答了 1 个空。
2. `answers[schedule_id]` 已经有值，例如 `blank1:A`。
3. `submitGroup()` 会把它当作“已作答”。
4. 点击“仅提交已答”时，这道题仍会被提交到后端。
5. 后端大概率判错，但用户以为这题属于未完成/跳过。

**影响：**

- 今日复习的完成数、未答数、跳过数不准确。
- 用户选择“仅提交已答”时，部分作答的多空题仍会被错误提交。
- 复习计划可能被错误推进或错误记录。

**修复建议：**

新增一个题目级判断函数，例如：

```js
function _isReviewQuestionAnswered(q, answers) {
  const answer = (answers || {})[q.schedule_id] || ''
  if (isMultiBlankType(q.question_type)) {
    const blankAnswers = _normalizeBlankAnswer(answer)
    const groups = _getBlankOptionGroups(q)
    if (!groups.length) return !!answer
    return groups.every(function(group) {
      return !!blankAnswers[String((group && group.id) || '').trim()]
    })
  }
  return !!answer
}
```

然后在 `submitGroup()` 中统一使用：

```js
const answeredCount = groupQuestions.filter(q => _isReviewQuestionAnswered(q, answers)).length
...
const isAnswered = _isReviewQuestionAnswered(q, answers)
if (!isAnswered && !treatUnansweredAsWrong) continue
reviews.push({
  schedule_id: q.schedule_id,
  question_id: q.question_id,
  user_answer: isAnswered ? (answers[q.schedule_id] || '') : '',
})
```

---

## P1 / 重要逻辑问题

### P1-1：`review-today` 的多选题答案切换没有使用统一归一化函数

**位置：**

- `pages/review-today/review-today.js:449-459`

当前逻辑：

```js
const prev = answers[q.schedule_id] || ''
const sel = prev ? prev.split(',') : []
const idx = sel.indexOf(opt)
...
sel.sort()
const newAnswer = sel.join(',')
```

**问题说明：**

项目已新增 `utils/answer.js`，并在 `review-today.js` 顶部引入了：

```js
normalizeChoiceAnswer, serializeChoiceAnswer
```

但实际切换多选题时仍手写 `split(',')`。如果历史答案或缓存答案格式为 `AC`、`A，C`、`A C` 等格式，当前逻辑无法正确识别已选项。

**影响：**

- 历史/缓存数据格式不统一时，多选题选中态可能错乱。
- 与 `utils/answer.js` 的统一答案口径不完全一致。

**修复建议：**

改为：

```js
const sel = normalizeChoiceAnswer(prev)
...
const newAnswer = serializeChoiceAnswer(sel.join(','))
```

或直接基于数组去重、排序后再 `join(',')`。

---

### P1-2：`review-today` 的普通选项选中态也未使用归一化函数

**位置：**

- `pages/review-today/review-today.js:72-82`

当前逻辑：

```js
var selected = isMulti ? answer.split(',').indexOf(key) >= 0 : answer === key
```

**问题说明：**

这里和 P1-1 属于同类问题。多选题选项显示状态仍依赖 `split(',')`，没有使用 `normalizeChoiceAnswer()`。

**修复建议：**

```js
var selected = isMulti
  ? normalizeChoiceAnswer(answer).indexOf(key) >= 0
  : String(answer).trim().toUpperCase() === key
```

---

### P1-3：`practice-result` 的题干摘要取值可能漏掉部分题型字段

**位置：**

- `pages/practice-result/practice-result.js:44-52`

当前逻辑：

```js
const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
```

**问题说明：**

其他页面渲染题干时使用的是 `buildRenderModel()`，题干来源可能包含更复杂的字段，例如 `content.stem`、`content.text`、选项结构、富文本/LaTeX/代码块等。结果页只做简单取值和截断，可能导致部分题目摘要为空或显示不完整。

**影响：**

- 部分题目的答题详情只显示答案，不显示题干摘要。
- 用户复盘体验下降。

**修复建议：**

至少增加兼容字段，例如：

```js
const stemText =
  (q.content && (q.content.stem || q.content.text || q.content.title || q.content.question)) ||
  q.stem || q.title || q.question || q.text || ''
```

更理想的方案是复用已有的题干纯文本抽取工具。

---

## P2 / 发布前建议修复

### P2-1：`review-today.wxml` 仍使用数组字面量作为 `wx:for` 数据源

**位置：**

- `pages/review-today/review-today.wxml:82`

当前代码：

```xml
wx:for="{{[5, 10, 20]}}"
```

**问题说明：**

微信小程序 WXML 对复杂表达式支持有限。数组字面量在不同基础库/编译链下存在兼容风险。建议放到 data 中，例如 `groupSizeOptions: [5, 10, 20]`。

**修复建议：**

JS：

```js
data: {
  groupSizeOptions: [5, 10, 20],
}
```

WXML：

```xml
wx:for="{{groupSizeOptions}}"
```

---

### P2-2：`config.js` 仍为 `DEV = true`，正式包会请求 localhost

**位置：**

- `config.js:11-20`

当前代码：

```js
const DEV = true
...
const env = DEV ? 'development' : 'production'
```

**问题说明：**

这不是开发环境问题，但属于上线前强校验项。`DEV=true` 时，接口地址是：

```js
http://localhost:8000/api/v1
```

体验版/正式版中，手机访问的是手机自己的 localhost，会导致接口全部失败。

**修复建议：**

至少上线前改为：

```js
const DEV = false
```

更好的方案是接入构建环境变量，避免人工切换遗漏。

---

## 已确认修复的问题

### 1. `practice-result.js` 的 `stored` 作用域问题已修复

`stored` 已在 `try` 外部声明：

```js
let stored = null
try {
  stored = wx.getStorageSync('lastPracticeResult')
  ...
}
```

结果页不再因 `stored is not defined` 直接崩溃。

### 2. `practice-result` 已改为按 `question_id` 匹配题干

当前已构建：

```js
const questionById = {}
questions.forEach(function(q) { if (q && q.id) questionById[String(q.id)] = q })
...
const q = questionById[String(r.question_id)] || {}
```

跳题后按数组下标错配的问题已基本解决。

### 3. `review-today.wxml` 模板层 `indexOf()` 已移除

当前普通选项已使用：

```xml
currentQuestion._optionList
item._selected
item._icon
```

比上一版安全。

### 4. `wrong-detail` 旧缓存污染问题已修复

当前只有缓存列表包含当前 `id` 时才启用滑动列表：

```js
if (normalized.includes(currentId)) questionIds = normalized
```

直接打开详情页时不会盲目使用旧的 `wrong_detail_ids`。

### 5. `wrong-detail` 的 `.both` 样式已补充

`pages/wrong-detail/wrong-detail.wxss` 已包含：

```css
.option-line.both { ... }
.option-value.both { ... }
```

多选题“正确且我选中”的视觉反馈已补齐。

---

## 建议回归测试清单

1. `review-today` 多空题：3 个空只答 1 个，提交时应提示未完成，不应算作已答。
2. `review-today` 多空题：选择“仅提交已答”时，部分作答的多空题不应提交。
3. `review-today` 多空题：选择“按不会处理”时，未完整作答题可按空答案/错误处理。
4. `review-today` 多选题：历史答案为 `AC`、`C,A`、`A，C` 时，选中态应一致。
5. `practice-result`：跳过第 1 题，只答第 2 题，结果详情应显示第 2 题题干。
6. `wrong-detail`：从错题本进入可滑动；从单题入口进入不应套用旧滑动列表。
7. `config.js`：体验版/正式版包确认请求生产域名，不请求 localhost。

---

## 最终判断

`当前版本` 比上一版有明显进步，但仍存在一个 P0 级残留逻辑问题：`review-today` 多空题部分作答统计与提交口径不一致。

建议先修复 P0-1，再做一次针对 `review-today` 的专项回归测试。修完后，如果 `config.js` 的生产环境切换也处理好，可以进入小范围真机验收。
