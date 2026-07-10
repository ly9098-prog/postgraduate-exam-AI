# miniprogram(4).zip 修复后复查报告

复查范围：`pages/practice`、`pages/practice-result`、`pages/review-today`、`pages/wrong-book`、`pages/wrong-detail` 以及与这些页面直接相关的 `utils/answer.js`、`config.js`。

复查结论：**不建议直接上线**。本次修复确实补上了多选答案归一化、复习页多空题渲染、错题详情错误态、AI 异步串题防护、错题列表 ids 改 storage 传递等内容；但仍存在结果页直接崩溃、复习页模板层残留方法调用、错题详情滑动列表受旧缓存污染、结果详情题目匹配错误等问题。

---

## P0 必须修复

### P0-1：practice-result 页面 onLoad 会因 `stored` 作用域错误直接崩溃

位置：`pages/practice-result/practice-result.js:37-58`

当前代码在 `try` 块内部使用 `const stored = wx.getStorageSync('lastPracticeResult')`，但在 `try` 外部又执行：

```js
const skipped = (stored && stored.skipped) || 0
```

由于 `const/let` 是块级作用域，`stored` 在第 58 行不可见，进入结果页时会触发 `ReferenceError: stored is not defined`，导致练习结果页无法正常打开。

建议修复：

```js
let stored = null
try {
  stored = wx.getStorageSync('lastPracticeResult')
  if (stored && stored.results) {
    // ...
  }
} catch (_) {}

const skipped = (stored && stored.skipped) || 0
```

---

### P0-2：review-today.wxml 仍在模板层调用 `indexOf(item)`

位置：`pages/review-today/review-today.wxml:205`、`:210`、`:211`

当前多选题选中态仍写在 WXML 表达式中：

```xml
answers[currentQuestion.schedule_id].indexOf(item) >= 0
```

这属于模板层方法调用残留，和之前 `practice.wxml` 的 `Math.round()` / `modeLabel()` 问题属于同类风险。微信小程序 WXML 不应依赖这种方法调用来计算 UI 状态，容易出现编译失败、渲染失败或真机表现不一致。

建议修复：像 `practice` 页一样，在 JS 中构造 `currentQuestion._optionList`，每个选项预计算：

```js
{
  key: 'A',
  _selected: true,
  _indicatorChecked: true,
  _checkIcon: 'check' // 或 dot
}
```

WXML 只写：

```xml
<view wx:for="{{currentQuestion._optionList}}" class="option-item {{item._selected ? 'opt-selected' : ''}}">
```

---

### P0-3：config.js 当前仍是 `DEV = true`，体验版/正式版会请求 localhost

位置：`config.js:9-18`

当前配置：

```js
const DEV = true
BASE_URL: 'http://localhost:8000/api/v1'
```

如果上传体验版或正式版，手机端会请求手机自己的 `localhost`，所有接口都会失败。

建议修复：上线前必须改为：

```js
const DEV = false
```

或者接入构建环境变量，避免人工切换遗漏。

---

## P1 高优先级修复

### P1-1：practice-result 逐题详情按数组下标匹配题目，跳题后会题干错位

位置：`pages/practice-result/practice-result.js:41-53`

当前逻辑：

```js
results = stored.results.map((r, i) => {
  const q = questions[i] || {}
})
```

但 `stored.results` 只来自已提交/已作答题目，`stored.questions` 是整组题目。若用户跳过第 1 题，只答第 2 题，那么第 2 题的结果会被错误匹配到第 1 题题干。

建议修复：按 `question_id` 建立索引：

```js
const questionById = {}
questions.forEach(q => { questionById[String(q.id)] = q })
results = stored.results.map(r => {
  const q = questionById[String(r.question_id)] || {}
})
```

---

### P1-2：wrong-detail 使用旧的 `wrong_detail_ids` 缓存时可能污染当前详情页

位置：`pages/wrong-detail/wrong-detail.js:153-171`

当前逻辑只要 storage 中存在 `wrong_detail_ids`，就直接用它作为滑动列表。问题是：

1. 用户从别的入口直接打开详情页时，storage 里可能残留上一轮错题列表 ids。
2. 当前 `id` 不在旧 ids 中时，页面仍会设置 `swiperEnabled = true`、`totalQuestions = old length`、`currentIdx = 0`。
3. 进度条和左右滑动会指向无关错题。

建议修复：只有当 storage ids 包含当前 `id` 时才启用滑动；否则退化为单题详情。

```js
const currentId = Number(options.id)
let questionIds = []
const stored = wx.getStorageSync('wrong_detail_ids')
const normalized = Array.isArray(stored) ? stored.map(Number).filter(Number.isFinite) : []
if (normalized.includes(currentId)) {
  questionIds = normalized
} else {
  questionIds = [currentId]
}
```

---

### P1-3：wrong-detail 生成了 `both` 状态，但 WXSS 没有定义 `.both`

位置：`pages/wrong-detail/wrong-detail.js:75-79`、`pages/wrong-detail/wrong-detail.wxss`

JS 已经给“正确且是我选的”选项设置：

```js
lineClass = 'both'
valueClass += ' both'
```

但 `wrong-detail.wxss` 中没有 `.option-line.both`、`.option-value.both` 样式。结果是多选题中“正确且我选中”的选项无法形成明确视觉反馈。

建议补充：

```css
.option-line.both {
  background: #ECFDF3;
  border-radius: 12rpx;
  padding: 14rpx 16rpx;
  border: 2rpx solid #22C55E;
}

.option-value.both {
  color: #22C55E;
  font-weight: 800;
}
```

---

### P1-4：review-today 多空题“部分作答”会被统计为已作答

位置：`pages/review-today/review-today.js:398`、`:437`、`:468`、`:633-635`

当前 `_answeredCount` 和提交前 `answeredCount` 都用：

```js
Object.keys(answers).length
```

这会导致多空选择题只选了一个空，也被算作整题已作答。提交时也会把部分答案作为已答题提交，用户看到的“已选 X / Y 题”和实际完成度不一致。

建议修复：增加 `_isReviewQuestionAnswered(q, answer)`，多空题必须所有 blank group 都有选择才算已作答。

---

### P1-5：wrong-book 的 AI 诊断接口字段缺失时可能报错

位置：`pages/wrong-book/wrong-book.js:106-124`

第 120 行直接访问：

```js
diagnosis.weak_points.length
```

如果后端返回 `{ summary: '...' }`、`weak_points: null` 或缺少 `strong_points / learning_suggestions`，这里会报错并导致 AI 诊断区域无法正常显示。

建议修复：在使用前统一兜底：

```js
diagnosis.weak_points = Array.isArray(diagnosis.weak_points) ? diagnosis.weak_points : []
diagnosis.strong_points = Array.isArray(diagnosis.strong_points) ? diagnosis.strong_points : []
diagnosis.learning_suggestions = Array.isArray(diagnosis.learning_suggestions) ? diagnosis.learning_suggestions : []
```

---

## P2 建议修复

### P2-1：wrong-detail 错误态“重新加载”在直接打开详情页时无法重试当前 id

位置：`pages/wrong-detail/wrong-detail.js:359-365`

当前 `reloadData()` 依赖 `questionIds[currentIdx]`。如果用户直接打开详情页，且没有有效 `questionIds`，点击“重新加载”会直接 `goBack()`，无法重试当前 id。

建议：在 data 中保存 `currentWqId`，`reloadData()` 优先用 `currentWqId`。

---

### P2-2：subject label 映射不完整，新科目可能显示原始枚举值

位置：

- `pages/wrong-book/wrong-book.js:367-375`
- `pages/wrong-detail/wrong-detail.js:29-39`
- `pages/review-today/review-today.js` 的 `subjectLabel()`

`wrong-book` 的筛选项已经包含 `advanced_math`、`linear_algebra`、`computer`、`ds`、`os`、`co`、`cn` 等新科目，但 `_subjectLabel()` 主要仍是旧映射。错题卡片、错题详情、复习页可能显示 `advanced_math` 这类原始字段。

建议：统一抽一个 `utils/subject.js`，所有页面共用同一份映射。

---

### P2-3：wrong-book 筛选后“AI 深度诊断”仍是全局诊断，容易和筛选态混淆

位置：`pages/wrong-book/wrong-book.js:106-129`、`pages/wrong-book/wrong-book.wxml:91-126`

前面的“知识漏洞分析”已经在筛选态改为当前列表分析，但下面的“AI 深度诊断”仍然来自 `/stats/ai-diagnosis` 全局接口。用户筛选“线性代数”后，AI 诊断可能仍显示全局薄弱点，造成口径不一致。

建议：筛选态下给 AI 诊断加“全局诊断”标签，或隐藏全局诊断，或支持按筛选参数请求诊断。

---

### P2-4：practice-result 详情只展示已提交结果，不展示跳过题目明细

位置：`pages/practice-result/practice-result.js:37-54`、`practice-result.wxml:80-102`

现在统计区显示“跳过”，但逐题详情只渲染 `stored.results`。如果用户跳过了题目，无法在详情里看到哪些题被跳过。

建议：基于 `stored.questions` 构造完整详情列表，已答题合并 result，未答题标记为 skipped。

---

### P2-5：practice.js 中保留了旧的 `modeLabel()` 方法，已无模板使用

位置：`pages/practice/practice.js:1178-1181`

当前已新增 `_modeLabel()` 和 `selectedModeLabel`，旧的 `modeLabel()` 可以删除，避免后续误以为 WXML 可直接调用。

---

## 已验证通过的修复点

以下内容在当前包中已能看到对应修改：

1. `practice.wxml` 不再直接调用 `modeLabel()` / `Math.round()`，已改成 `selectedModeLabel` 和 `progressPercent`。
2. 新增 `utils/answer.js`，包含 choice/multi_blank 的答案归一化工具。
3. `practice` 页多选题选择后会排序为稳定答案字符串。
4. `practice` 页多空题已有 blank option groups 渲染和选择逻辑。
5. `review-today` 已加入多空题渲染和 `selectBlankOption()`。
6. `wrong-book` 的 `loadMore()` 已有 `loading || !hasMore` 并发防护。
7. `wrong-book -> wrong-detail` 已改为 storage 传 ids，避免 URL 超长。
8. `wrong-detail` 已加入错误态、AI token 防串题、防 stale response。
9. `wrong-detail` 判断题 options 为空时已有 A/B 兜底。

---

## 建议回归测试清单

必须至少覆盖：

1. 完成一组练习后进入 `practice-result`，确认不报 `stored is not defined`。
2. 跳过第 1 题，只答第 2 题，进入结果详情，确认第 2 题题干、我的答案、正确答案不串位。
3. `review-today` 多选题选择 C、A，确认 A/C 都高亮，取消一个后高亮同步消失。
4. `review-today` 多空题只答一空时，不应被统计为整题完成。
5. `wrong-detail` 从错题本第 N 题进入，确认进度条显示 N/总数，并可左右滑动到相邻错题。
6. 直接打开 `wrong-detail?id=xxx`，确认不会使用旧的 `wrong_detail_ids`。
7. 多选错题中“正确且我选中”的选项，应有明确绿色或双状态样式。
8. 筛选错题本后，知识漏洞分析和 AI 深度诊断的口径要清楚区分。
9. 体验版/正式版前确认 `config.js` 不再是 `DEV = true`。

