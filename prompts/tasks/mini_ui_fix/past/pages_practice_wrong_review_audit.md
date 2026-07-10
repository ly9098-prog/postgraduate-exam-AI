# pages 目录练习/错题/复习页面问题审计报告

## 1. 审计范围

本次静态审计对象为小程序 `pages` 目录下以下页面，并结合后端 `app` 中相关接口契约做交叉核对：

- `pages/practice`
- `pages/practice-result`
- `pages/review-today`
- `pages/wrong-book`
- `pages/wrong-detail`

审计重点：WXML 模板合法性、页面状态流转、题型支持、答题判定一致性、接口字段契约、异常/空状态、筛选与详情联动、AI 分析异步竞态、基础 UI 可用性。

## 2. 总体结论

这 5 个页面均存在并能形成“刷题 → 结果 → 错题本 → 错题详情 → 今日复习”的主流程，但当前有多处会影响真实使用的 UI/逻辑风险。

按严重程度统计：

| 严重级别 | 数量 | 说明 |
|---|---:|---|
| P0 阻塞/高概率错误 | 3 | 可能导致页面渲染异常、复习题型无法作答、前后端判题不一致 |
| P1 主要流程缺陷 | 9 | 会造成结果统计失真、筛选诊断不一致、详情展示错误、异步串题等 |
| P2 体验/健壮性问题 | 6 | 错误态空白、加载失败后状态残留、加载更多重复请求等 |

优先修复建议：先处理 WXML 表达式、选择题答案规范化、`review-today` 多选/多空题支持、`wrong-detail` 选项展示与 AI 串题问题，再处理统计口径与空状态。

## 3. 关键问题清单

### P0-1：`practice.wxml` 在模板层直接调用 JS 方法和 `Math.round`，微信 WXML 可能无法正常编译/渲染

**位置：**

- `pages/practice/practice.wxml:31`：`{{modeLabel(selectedMode)}}`
- `pages/practice/practice.wxml:127`：`{{modeLabel(selectedMode)}}`
- `pages/practice/practice.wxml:199`：`{{Math.round(...)}}`
- `pages/practice/practice.js:1129-1131`：`modeLabel(m)` 是 Page 方法，而非 WXS 或 data 字段

**问题说明：**

WXML 模板表达式不应直接调用 Page 方法，也不应依赖 `Math.round()` 这类运行时 JS 函数。当前写法在小程序模板层存在高风险，可能导致模式标签/进度百分比不显示，甚至编译报错。

**影响：**

刷题设置页顶部“出题节奏”、挑战模式 chip、答题进度百分比显示异常。

**建议修复：**

在 JS 中预计算并写入 data：

- `selectedModeLabel`
- `progressPercent`
- `growthValue`

在 `chooseMode`、`setCount`、`selectOption`、`selectBlankOption`、`_showQuestion` 等会影响展示的地方同步更新。模板中只绑定普通字段，例如 `{{selectedModeLabel}}`、`{{progressPercent}}%`。

---

### P0-2：多选题答案前后端判定口径不一致，可能“前端认为对，后端判错”

**位置：**

- `pages/practice/practice.js:720-725`：多选答案按点击顺序拼接，例如 `C,A`
- `pages/practice/practice.js:122-149`：前端本地 `_isAnswerCorrect` 会排序归一化
- `app/services/practice_service.py:1396-1401`：后端除多空/判断外，直接 `user_answer.strip().lower() == question.answer.strip().lower()`
- `app/api/v1/review.py:206-209`：今日复习批改也直接字符串比较

**问题说明：**

如果正确答案存储为 `A,C`，用户点击顺序为 `C` 再 `A`，前端内部归一化后会认为正确，但提交给后端是 `C,A`，后端直接字符串比较会判错。

**影响：**

- 练习结果正确率失真；
- 错题本会错误记录本来答对的多选题；
- 今日复习多选题同样会误判。

**建议修复：**

前后端都统一答案规范化函数：

- 多选题统一拆分为集合，排序后比较；
- 支持 `A,C`、`AC`、`A C`、`A；C` 等常见格式；
- 前端提交前也排序：`sel.sort().join(',')`；
- 后端判题必须以规范化后的答案为准，不能直接字符串相等。

---

### P0-3：`review-today` 今日复习只支持单选/判断，不完整支持多选题和多空选择题

**位置：**

- `pages/review-today/review-today.js:213-240`：只按普通 `options` 和判断题构造选项
- `pages/review-today/review-today.js:324-336`：`selectOption` 每题只保存一个选项
- `pages/review-today/review-today.wxml:170-186`：只有普通选项列表，无多选 UI 和多空选择 UI
- `app/schemas/review_scheduler.py:6-16`：复习题包含 `question_type`，理论上可能出现不同题型

**问题说明：**

复习池如果包含 `multiple_choice` 或 `multi_blank_choice`：

- 多选题只能选一个选项；
- 多空选择题没有按空位分组选项；
- 提交后会因为答案格式不完整被判错；
- 用户无法完成这类复习任务。

**影响：**

今日复习主流程被题型卡住，尤其是错题复习池中如果有多选/多空题，会造成系统性误判。

**建议修复：**

复用 `practice` 页已有的多选/多空逻辑：

- 引入 `_normalizeBlankAnswer`、`_enrichBlankOptionGroups`、`_serializeBlankAnswer`；
- `selectOption` 根据 `question_type === 'multiple_choice'` 支持多选切换；
- `multi_blank_choice` 单独渲染 `blank_option_groups`；
- 后端 `/review/grade-batch` 也要复用 practice 的判题归一化逻辑。

---

### P1-1：`practice` 提交时未作答题目被排除，结果页统计口径容易失真

**位置：**

- `pages/practice/practice.js:1032-1037`：统计未作答
- `pages/practice/practice.js:1064-1069`：只提交 `completedQuestions`
- `pages/practice-result/practice-result.js:30-35`：结果页用原始 `total` 计算正确率
- `app/services/practice_service.py:1510-1550`：后端只统计收到的 answers

**问题说明：**

用户确认“还有题目未作答，确定提交”后，未作答题目不会提交给后端，也不会计入 wrong，只在结果页 total 中保留。

例如：10 题中只答 1 题且答对：

- 后端：`correct=1, wrong=0`
- 前端结果：`total=10, passRate=10%`
- 错题本：不会记录 9 道未答题

**影响：**

“错误数”“错题本”“成长/复盘反馈”与用户直觉不一致，也不利于复习调度。

**建议修复：**

明确产品口径：

- 如果未答应视为错误：提交所有题，未答题 `user_answer=''`，后端计 wrong；
- 如果未答应视为跳过：结果页增加“跳过 N 题”，不要把跳过题混入 wrong，但也不要让错题本缺少用户需要复盘的题。

---

### P1-2：`practice` 加载失败/无题时状态回退不完整，可能停留在空白答题页且计时器继续运行

**位置：**

- `pages/practice/practice.js:428-457`：开始练习时先 `started=true` 并启动计时器，再加载题目
- `pages/practice/practice.js:482-535`：无科目、无题、加载异常时没有统一恢复状态
- `pages/practice/practice.js:520-528`：无题弹窗取消“继续等待”后不触发重试也不退出
- `pages/practice/practice.js:475-480`：有清理计时器方法，但异常路径未调用

**问题说明：**

如果接口失败或该科目无题，页面可能进入 `started && !loading` 状态但没有 `currentQuestion`，顶部显示第 1/0 题，底部仍可尝试交卷；计时器也可能继续运行。

**建议修复：**

加载题目前先不要切换 `started=true`，或失败时统一：

```js
this._clearTimer()
this.setData({ started: false, loading: false, questions: [], currentQuestion: null })
```

无题弹窗建议只保留“返回选择科目 / 重新加载”，不要出现“继续等待”但无后续动作。

---

### P1-3：`review-today` 未答题选择“仅提交已答”时，若 0 题已答会向后端提交空数组并失败

**位置：**

- `pages/review-today/review-today.js:503-548`：允许未作答时选择“仅提交已答”
- `pages/review-today/review-today.js:543-553`：构造 `reviews`，未答且不按错处理时跳过
- `app/api/v1/review.py:176-177`：后端 `reviews` 为空直接 400：`复习列表不能为空`

**问题说明：**

如果用户一题没答就点到最后提交，并选择“仅提交已答”，前端会提交 `reviews=[]`，后端返回 400，用户只看到“提交失败，请重试”。

**建议修复：**

在提交前增加判断：

```js
if (reviews.length === 0) {
  wx.showToast({ title: '请至少作答 1 题，或选择按不会处理', icon: 'none' })
  this.setData({ submittingGroup: false })
  return
}
```

---

### P1-4：`wrong-book` 筛选后，“知识漏洞分析/雷达/优先级”仍优先使用全局 stats，和当前筛选列表不一致

**位置：**

- `pages/wrong-book/wrong-book.js:162-171`：筛选只重新加载列表，不重新加载筛选后的统计
- `pages/wrong-book/wrong-book.js:145-148`：`loadList` 用 `this.data.stats` 生成 analysis
- `pages/wrong-book/wrong-book.js:207-213`：`_buildAnalysis` 优先使用 `stats.by_error_type/by_subject`，有 stats 时不会按当前 list 统计

**问题说明：**

用户筛选“数学”或某一错因后，列表已经变成筛选后的结果，但上方知识漏洞分析仍可能是全局错题统计。

**影响：**

“当前列表”和“诊断建议”互相矛盾，用户可能被错误引导。

**建议修复：**

筛选态下二选一：

1. 请求支持筛选参数的 stats；
2. 筛选后 `_buildAnalysis(null, nextList)`，强制按当前列表生成分析。

---

### P1-5：`wrong-detail` 判断题缺少兜底选项，可能只显示题干不显示“正确/错误”选项

**位置：**

- `pages/wrong-detail/wrong-detail.js:43-50`：`opts = wq.options || null`，没有判断题兜底
- `app/api/v1/wrong_questions.py:102-104`：错题详情直接返回 `question.options`，未像 practice 接口那样补齐判断题选项

**问题说明：**

`practice` 页对判断题会补 `{A:'正确', B:'错误'}`，但 `wrong-detail` 没有。如果数据库中判断题 `options` 为空，错题详情页不会展示选项，也无法高亮“正确答案/我的选项”。

**建议修复：**

在前端 `_processWqData` 或后端 `enrich_wq` 中增加判断题兜底：

```js
if (!opts && (wq.question_type === 'true_false' || wq.question_type === 'judgement')) {
  opts = { A: '正确', B: '错误' }
}
```

同时后端 `WrongQuestionResponse` 建议包含 `question_type`，避免前端只能猜。

---

### P1-6：`wrong-detail` 多选题正确答案/我的答案高亮逻辑错误

**位置：**

- `pages/wrong-detail/wrong-detail.js:56-57`

**问题说明：**

当前写法是：

```js
const isCorrect = key === wq.answer
const isUserAnswer = key === wq.wrong_answer
```

这只适用于单选。若正确答案是 `A,C`，选项 A/C 都不会被标记为正确；若用户答案是 `A,B`，A/B 也不会被标记为我的选项。

**建议修复：**

将答案拆成集合：

```js
const correctSet = normalizeAnswerSet(wq.answer)
const userSet = normalizeAnswerSet(wq.wrong_answer)
const isCorrect = correctSet.has(key)
const isUserAnswer = userSet.has(key)
```

---

### P1-7：`wrong-detail` AI 分析存在异步串题风险

**位置：**

- `pages/wrong-detail/wrong-detail.js:171`：加载详情后发起 AI 分析
- `pages/wrong-detail/wrong-detail.js:179-200`：AI 返回后直接写入 `aiResult`
- `pages/wrong-detail/wrong-detail.js:317-337`：左右滑动切题也会重新请求详情和 AI，但没有请求版本号/当前题校验

**问题说明：**

用户快速左右滑动时，上一题的 `/ai/error-analysis` 可能晚于下一题返回，并覆盖当前页的 AI 分析内容，出现“题干是 B 题，AI 分析是 A 题”的串题问题。

**建议修复：**

给 AI 请求加 request token：

```js
const token = `${wqId}-${Date.now()}`
this._aiToken = token
const result = await api.post(...)
if (this._aiToken !== token || this.data.wq?.id !== wqId) return
```

---

### P1-8：`wrong-detail` 页面加载失败后没有错误态 UI

**位置：**

- `pages/wrong-detail/wrong-detail.wxml:1-5`：只处理 loading 和 `!loading && wq`
- `pages/wrong-detail/wrong-detail.js:172-175`：加载失败只 toast，然后 `loading=false`

**问题说明：**

加载失败或错题不存在时，页面会变成空白，只弹一次 toast。用户无法重试，也无法返回错题本。

**建议修复：**

增加 `errorText` 和错误态：

- “错题不存在或已被移除”
- “重新加载”
- “返回错题本”

---

### P2-1：`review-today` safe mode 自愈逻辑基本无效

**位置：**

- `pages/review-today/review-today.js:226-229`：`_renderModel` 在 `_enrichQuestion` 时一次性构造
- `pages/review-today/review-today.js:297-304`：进入 safe mode 后只是再次 `_showQuestion(idx)`
- `pages/review-today/review-today.js:308-318`：`_showQuestion` 使用已有 `q._renderModel`，没有重建

**问题说明：**

当发现 CODE/MIXED 渲染异常时，`safeModeActive=true` 之后没有重新 build render model，因此无法真正切换到 safe mode。

**建议修复：**

进入 safe mode 后，对当前题或全部 `groupQuestions` 重新执行 `_enrichQuestion(q)`，或在 `_showQuestion` 中根据 safeMode 重新 build 当前题的 `_renderModel`。

---

### P2-2：`wrong-detail` 滑动切题时未沿用 safe mode，也未执行渲染校验

**位置：**

- `pages/wrong-detail/wrong-detail.js:317-337`

**问题说明：**

`_navigateTo` 中 `_processWqData(wq)` 没有传入 `this.data.safeModeActive`，并且切换后的题没有调用 `_checkRenderInvariant/_recordRenderTrace`。如果前一题已触发 safe mode，下一题滑动进入后会退回非 safe mode。

**建议修复：**

```js
const data = _processWqData(wq, this.data.safeModeActive)
this._checkRenderInvariant(data._renderModel)
this._recordRenderTrace(data._renderModel?.renderTrace)
```

---

### P2-3：`wrong-book` 加载更多缺少并发和边界保护

**位置：**

- `pages/wrong-book/wrong-book.js:174-176`

**问题说明：**

`loadMore()` 直接调用 `loadList()`，没有判断 `loading` 和 `hasMore`。用户快速点击可能重复请求同一页或在无更多数据时继续请求。

**建议修复：**

```js
loadMore() {
  if (this.data.loading || !this.data.hasMore) return
  this.loadList()
}
```

---

### P2-4：`wrong-book -> wrong-detail` 通过 URL 传所有已加载 id，列表变长后可能超出 URL 长度，也只能在已加载数据内滑动

**位置：**

- `pages/wrong-book/wrong-book.js:178-181`

**问题说明：**

详情页滑动依赖 `ids=this.data.list.map(...).join(',')`。当错题列表加载多页后，URL 参数可能过长；同时未加载的分页错题无法在详情中继续滑动。

**建议修复：**

使用本地缓存传递 id 列表，或详情页按筛选条件和当前页游标分页加载下一题。

---

### P2-5：`review-today` 练习页没有显式上一题/下一题按钮，可发现性较弱

**位置：**

- `pages/review-today/review-today.js:351-379`：有 `goNext/goPrev`
- `pages/review-today/review-today.wxml`：未绑定上一题/下一题按钮，只能通过题号点和左右滑动切题

**问题说明：**

小程序用户不一定知道可以左右滑动；在部分设备/调试环境中，点题号比按钮效率低。

**建议修复：**

在题卡底部加“上一题 / 下一题”按钮，最后一题显示“提交本组复盘”。

---

### P2-6：`practice-result` 详情页只展示答案，不展示用户答案和题干，复盘价值不足

**位置：**

- `pages/practice-result/practice-result.wxml:76-91`
- `pages/practice-result/practice-result.js:36-47`

**问题说明：**

当前“答题详情”只展示序号、对错和正确答案。用户无法在结果页快速知道自己错在哪里，也不能看到自己的选择。需要进入错题本才能复盘。

**建议修复：**

结果项至少展示：

- 题干摘要；
- 我的答案；
- 正确答案；
- 解析入口；
- 错题详情跳转。

---

## 4. 跨页面/环境风险

### 全局风险：`config.js` 当前 `DEV = true`，正式环境会请求 localhost

**位置：**

- `config.js:1-15`

**问题说明：**

当前 `DEV = true`，`BASE_URL` 为 `http://localhost:8000/api/v1`。如果这份代码直接上传体验版/正式版，真机环境会请求用户手机自己的 localhost，所有练习、错题、复习接口都会失败。

**建议修复：**

- 提交生产版本前将 `DEV=false`；
- 更推荐通过构建环境变量或 `project.private.config.json` 区分环境，避免手工改漏。

## 5. 建议修复优先级

### 第一优先级：保证主流程正确

1. 修复 `practice.wxml` 方法调用和 `Math.round` 模板表达式；
2. 统一多选题答案格式，前后端都做规范化；
3. `review-today` 支持多选/多空题，或后端今日复习暂时过滤掉不支持题型；
4. 修复 `wrong-detail` 判断题选项兜底和多选高亮；
5. 修复 `wrong-detail` AI 异步串题。

### 第二优先级：保证统计和复盘可信

1. 明确未作答题统计口径；
2. `wrong-book` 筛选态下诊断必须基于筛选结果；
3. 结果页增加用户答案和题干摘要；
4. 今日复习空提交做前端拦截。

### 第三优先级：增强健壮性和体验

1. 所有加载失败页面增加错误态和重试按钮；
2. `wrong-book` 加载更多加并发保护；
3. `review-today` 增加上一题/下一题按钮；
4. safe mode 逻辑真正重建 render model。

## 6. 建议回归用例

| 用例 | 预期 |
|---|---|
| 多选题正确答案 `A,C`，用户按 `C -> A` 顺序选择 | 前后端均判正确 |
| 今日复习出现多选题 | 可多选，提交后判题正确 |
| 今日复习出现多空选择题 | 按空位分组选择，提交后判题正确 |
| 练习 10 题只答 1 题后提交 | 结果页明确显示答对/答错/跳过，统计口径一致 |
| 错题详情为判断题且 options 为空 | 页面显示“正确/错误”并高亮正确/我的选项 |
| 错题详情为多选题，正确答案 `A,C`，我的答案 `A,B` | A/C 标正确，A/B 标我的选项，交集样式可区分 |
| 快速在错题详情左右滑动 | AI 分析始终对应当前题 |
| 错题本筛选数学 | 知识漏洞分析、雷达、列表都基于数学筛选结果 |
| 今日复习 0 题作答后选择“仅提交已答” | 前端提示至少作答 1 题，不发空请求 |
| 接口失败/无题 | 页面显示错误态或返回设置页，计时器停止 |
