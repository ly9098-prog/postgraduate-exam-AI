你是一名资深微信小程序前端工程师。请基于当前项目代码完成一次“刷题 UI 统一化改造”。

## 一、改造背景

当前小程序中，`pages/practice/` 的刷题体验明显优于其他刷题相关页面。它具备完整的沉浸式刷题 UI，包括顶部状态栏、进度条、题目卡片、左右滑动、选项反馈、底部导航、答题卡弹窗等。

但是 `pages/review-today/`、`pages/wrong-detail/` 等页面虽然也涉及题目展示、答题或复盘，但 UI 和交互体验与 `practice` 不一致，导致用户在今日复习、错题详情等页面中的使用感受弱于普通刷题页面。

本次任务目标是：**让 review-today、wrong-detail 等页面尽可能复用 practice 页面的刷题运行态 UI，但不要直接复用整个 practice 页面业务逻辑。**

------

## 二、核心目标

请将 `practice` 页面中“刷题运行态”的 UI 抽象为公共组件，并让相关页面复用它。

推荐新增组件：

```text
components/quiz-runner/
  quiz-runner.js
  quiz-runner.json
  quiz-runner.wxml
  quiz-runner.wxss
```

该组件负责统一刷题体验，页面自身只保留业务逻辑。

------

## 三、不要做的事

请不要把 `review-today`、`wrong-detail` 直接跳转到 `pages/practice/practice` 页面。

原因：

1. `practice` 是普通练习流程；
2. `review-today` 是今日复习流程；
3. `wrong-detail` 是错题复盘流程；
4. 三者接口、数据结构、提交方式和业务状态不同；
5. 如果强行通过 `source=review`、`source=wrong` 等方式复用整个 practice 页面，会导致 `practice.js` 变得臃肿、难维护。

正确做法是：

```text
复用 practice 的刷题 UI
保留各页面自己的业务逻辑
通过统一的数据适配层把题目数据喂给公共组件
```

------

## 四、需要重点参考的现有文件

请重点阅读并参考以下文件：

```text
pages/practice/practice.wxml
pages/practice/practice.wxss
pages/practice/practice.js

pages/review-today/review-today.wxml
pages/review-today/review-today.wxss
pages/review-today/review-today.js

pages/wrong-detail/wrong-detail.wxml
pages/wrong-detail/wrong-detail.wxss
pages/wrong-detail/wrong-detail.js

utils/stem-render.js
utils/answer.js
components/math-question/
components/mp-html/
```

其中，`practice` 页面的答题态 UI 是本次改造的视觉和交互基准。

------

## 五、公共组件 quiz-runner 的职责

`components/quiz-runner/` 应负责以下 UI 和交互结构：

1. 顶部状态栏
   对应 practice 中类似：

```text
top-bar
bar-left
bar-right
bar-subject
bar-counter
bar-subtitle
bar-timer
bar-sheet-btn
```

1. 进度条
   对应 practice 中类似：

```text
progress-shell
progress-track
progress-fill
progress-label
```

1. 题目区域
   对应 practice 中类似：

```text
question-area
q-wrap
q-card-head
q-badge
q-card-kicker
q-card-index
question-body
```

1. 题干渲染
   必须兼容当前项目已有的渲染模型：

```text
_renderModel
RENDER_MODE.RICH_TEXT
RENDER_MODE.LATEX
RENDER_MODE.SEGMENTS
RENDER_MODE.CODE
RENDER_MODE.MIXED
```

不要破坏 `utils/stem-render.js` 的渲染约束。

1. 选项渲染
   支持：

```text
single_choice
multiple_choice
true_false
judgement
multi_blank_choice
```

1. 多空选择题
   支持 `blank_option_groups` / `_blankOptionGroups` / `_hasBlankOptionGroups` 这类数据结构。
2. 左右滑动切题
   保留 practice 页类似的左右滑动体验。
3. 底部导航
   包括：

```text
上一题
下一题
提交 / 完成本组 / 查看下一题
答题卡入口
```

1. 答题卡弹窗
   支持显示每道题是否已答、当前题位置、点击跳题。
2. 只读模式
   用于 `wrong-detail`，只展示题目、选项、用户答案、正确答案，不允许重新作答。
3. 可选即时反馈
   用于 `practice`，答题后显示正确/错误反馈；`review-today` 可根据现有逻辑决定是否启用；`wrong-detail` 应默认显示答案状态而非提交反馈。

------

## 六、建议的组件属性设计

请在 `quiz-runner.js` 中设计类似以下 properties：

```js
properties: {
  mode: {
    type: String,
    value: 'practice'
  },

  title: {
    type: String,
    value: ''
  },

  subtitle: {
    type: String,
    value: ''
  },

  subjectName: {
    type: String,
    value: ''
  },

  questions: {
    type: Array,
    value: []
  },

  currentQuestion: {
    type: Object,
    value: null
  },

  currentIndex: {
    type: Number,
    value: 0
  },

  totalCount: {
    type: Number,
    value: 0
  },

  answeredCount: {
    type: Number,
    value: 0
  },

  progressPercent: {
    type: Number,
    value: 0
  },

  elapsedText: {
    type: String,
    value: ''
  },

  readonly: {
    type: Boolean,
    value: false
  },

  submitted: {
    type: Boolean,
    value: false
  },

  submitting: {
    type: Boolean,
    value: false
  },

  showAnswer: {
    type: Boolean,
    value: false
  },

  showFeedback: {
    type: Boolean,
    value: true
  },

  submitText: {
    type: String,
    value: '提交'
  },

  prevDisabled: {
    type: Boolean,
    value: false
  },

  nextDisabled: {
    type: Boolean,
    value: false
  }
}
```

可以根据实际代码适当调整，但必须满足 practice、review-today、wrong-detail 三类页面的使用需求。

------

## 七、建议的组件事件设计

组件不直接修改页面业务数据，只通过事件通知页面。

建议事件：

```js
this.triggerEvent('selectoption', {
  option: opt,
  question: currentQuestion,
  index: currentIndex
})

this.triggerEvent('selectblankoption', {
  blankId,
  option,
  question: currentQuestion,
  index: currentIndex
})

this.triggerEvent('prev', {
  index: currentIndex
})

this.triggerEvent('next', {
  index: currentIndex
})

this.triggerEvent('jump', {
  index
})

this.triggerEvent('submit', {
  questions,
  currentIndex
})

this.triggerEvent('toggleanswercard')
```

页面负责处理：

```text
答案写入
answeredCount 计算
提交接口
切题逻辑
跳转结果页
AI 分析
错题复盘
```

组件只负责展示和交互触发。

------

## 八、数据适配层要求

请新增一个统一适配工具，建议文件：

```text
utils/question-runner-adapter.js
```

用于把不同页面的题目数据转换成 `quiz-runner` 统一可消费的数据结构。

推荐输出结构：

```js
{
  id,
  runnerId,
  scheduleId,
  questionType,
  questionTypeLabel,
  subjectLabel,

  stem,
  content,
  options,

  _renderModel,
  _optionList,
  _optionKeys,

  _blankOptionGroups,
  _hasBlankOptionGroups,

  userAnswer,
  correctAnswer,

  _answered,
  _readonly,
  _showAnswer
}
```

其中：

1. `practice` 页面可以用题目 `id` 作为主要 key；
2. `review-today` 页面可以保留 `schedule_id`，但适配后提供统一的 `runnerId`；
3. `wrong-detail` 页面可以用错题记录 id 或题目 id 作为 `runnerId`；
4. 多选题答案仍需兼容 `utils/answer.js`；
5. 多空选择题仍需兼容当前已有的 blank answer 序列化方式；
6. 不要在页面里重复写大量 `_normalizeBlankAnswer`、`_enrichBlankOptionGroups`、`_buildOptionList` 逻辑，能合并到工具层的尽量合并。

------

## 九、practice 页面改造要求

`pages/practice/` 需要作为第一优先级稳定保留。

请将 `practice.wxml` 中答题态 UI 抽到 `quiz-runner` 组件中。

`practice` 页面自身保留以下能力：

```text
选择科目
选择挑战模式
选择题目数量
加载练习题
计时
记录答题
提交 /practice/batch-submit
跳转 practice-result
```

`practice` 中原有的答题态：

```text
top-bar
progress-shell
question-area
q-wrap
options
blank-options
bottom-bar
sheet-overlay
answer-feedback
```

应迁移到组件中。

迁移完成后，`practice.wxml` 的答题态应类似：

```html
<quiz-runner
  mode="practice"
  title="练习"
  subjectName="{{selectedSubjectName}}"
  questions="{{questions}}"
  currentQuestion="{{currentQuestion}}"
  currentIndex="{{currentIndex}}"
  totalCount="{{totalQuestions}}"
  answeredCount="{{answeredCount}}"
  progressPercent="{{progressPercent}}"
  elapsedText="{{elapsedText}}"
  readonly="{{false}}"
  submitted="{{submitted}}"
  submitting="{{submitting}}"
  showFeedback="{{true}}"
  submitText="提交练习"
  bind:selectoption="selectOption"
  bind:selectblankoption="selectBlankOption"
  bind:prev="goPrev"
  bind:next="goNext"
  bind:jump="goQuestion"
  bind:submit="submitPractice"
/>
```

注意：实际函数名可以保持现有页面中的函数名，不必强行改名，但组件事件必须清晰。

------

## 十、review-today 页面改造要求

`pages/review-today/` 是本次体验提升的重点页面。

目标：让今日复习的答题体验接近 practice，而不是继续使用当前独立的 `group-header`、`question-card`、`nav-row` 视觉体系。

请将 `review-today.wxml` 中复习答题态替换为 `quiz-runner`。

保留 `review-today.js` 中的业务逻辑，包括：

```text
今日复习入口
分组逻辑
groupQuestions
currentGroupIdx
currentIndex
answers
submitGroup
grade-batch 接口调用
已掌握 / 取消掌握逻辑
```

改造后，`review-today.wxml` 的刷题部分应类似：

```html
<quiz-runner
  mode="review"
  title="今日复习"
  subtitle="第 {{currentGroupIdx + 1}} / {{groups.length}} 组"
  subjectName="{{currentQuestion.subject_name || currentQuestion.subjectLabel || ''}}"
  questions="{{groupQuestions}}"
  currentQuestion="{{currentQuestion}}"
  currentIndex="{{currentIndex}}"
  totalCount="{{groupQuestions.length}}"
  answeredCount="{{_answeredCount}}"
  progressPercent="{{groupQuestions.length > 0 ? Math.round(_answeredCount / groupQuestions.length * 100) : 0}}"
  readonly="{{false}}"
  submitting="{{submittingGroup}}"
  showFeedback="{{false}}"
  submitText="提交本组复盘"
  bind:selectoption="selectOption"
  bind:selectblankoption="selectBlankOption"
  bind:prev="goPrev"
  bind:next="goNext"
  bind:jump="goQuestion"
  bind:submit="submitGroup"
/>
```

如 WXML 不支持复杂表达式，请在 JS 中提前计算：

```js
runnerProgressPercent
runnerSubtitle
runnerSubjectName
```

不要在 WXML 中写过多计算逻辑。

------

## 十一、wrong-detail 页面改造要求

`pages/wrong-detail/` 不要完全改成普通刷题页。

它的定位是“错题复盘详情页”，所以应采用：

```text
上半部分复用 quiz-runner 的只读题目卡片
下半部分保留错题解析、我的答案、正确答案、AI 错题复盘
```

`wrong-detail` 中的组件使用模式建议：

```html
<quiz-runner
  mode="wrong-detail"
  title="错题复盘"
  subtitle="{{currentIdx + 1}} / {{totalQuestions}}"
  subjectName="{{wq.subject_name || subjectLabel || ''}}"
  questions="{{wrongQuestions}}"
  currentQuestion="{{currentQuestion}}"
  currentIndex="{{currentIdx}}"
  totalCount="{{totalQuestions}}"
  answeredCount="{{totalQuestions}}"
  progressPercent="{{totalQuestions > 0 ? Math.round((currentIdx + 1) / totalQuestions * 100) : 0}}"
  readonly="{{true}}"
  showAnswer="{{true}}"
  showFeedback="{{false}}"
  submitText="继续复盘"
  bind:prev="goPrevWrong"
  bind:next="goNextWrong"
  bind:jump="goWrongQuestion"
/>
```

如果当前 `wrong-detail` 不是数组模式，而是单条错题详情，也可以只传：

```js
questions: [currentQuestion]
currentIndex: 0
totalCount: 1
```

但是组件要支持只读状态下展示：

```text
用户错误答案
正确答案
正确选项高亮
错误选项高亮
多选题多个答案高亮
多空选择题每个空的正确/错误状态
```

AI 错题复盘卡片继续保留在 `wrong-detail.wxml` 中，不要塞进 `quiz-runner` 组件。

------

## 十二、样式要求

`quiz-runner.wxss` 应优先迁移并整理 `practice.wxss` 中答题态相关样式。

保留 practice 的整体体验：

```text
沉浸式卡片
柔和背景
顶部状态条
清晰进度条
大题目卡片
选项卡片有点击反馈
底部固定操作栏
答题卡弹窗
左右滑动动画
```

请避免三套页面继续维护三份重复样式。

建议迁移样式时按模块拆分注释：

```css
/* runner layout */
/* top bar */
/* progress */
/* question card */
/* render modes */
/* options */
/* blank choice */
/* answer feedback */
/* bottom nav */
/* answer sheet */
/* readonly answer state */
```

------

## 十三、兼容性要求

必须确保以下题型正常：

```text
single_choice
multiple_choice
true_false
judgement
multi_blank_choice
```

必须确保以下内容正常渲染：

```text
普通文本题干
富文本题干
LaTeX / 数学公式
代码题
混合内容题
图片化公式 segments
```

不得破坏：

```text
utils/stem-render.js
components/math-question/
components/mp-html/
utils/answer.js
```

如需复用 render 逻辑，只能通过已有工具函数或新增适配层，不能在页面层临时 patch 渲染结果。

------

## 十四、交互验收标准

完成后请逐项验证：

### practice

1. 可以选择科目；
2. 可以选择挑战模式；
3. 可以选择题目数量；
4. 可以正常开始练习；
5. 单选题可选择答案；
6. 多选题可多选和取消；
7. 判断题可选择；
8. 多空选择题每个空可单独选择；
9. 左右滑动可切题；
10. 上一题/下一题按钮正常；
11. 答题卡弹窗正常；
12. 进度条和已完成数量正常；
13. 答题反馈正常；
14. 提交后接口正常；
15. 提交后结果页正常。

### review-today

1. 今日复习入口正常；
2. 可以选择每组数量；
3. 可以开始复习；
4. 复习中的题目 UI 与 practice 基本一致；
5. 单选、多选、判断、多空选择题正常；
6. 上一题/下一题正常；
7. 左右滑动正常；
8. 答题卡正常；
9. 已答数量正常；
10. 提交本组复盘正常；
11. 未答题处理逻辑保持原样；
12. 已掌握/取消掌握逻辑保持原样；
13. 分组切换正常；
14. 复习完成态正常。

### wrong-detail

1. 错题详情可以正常进入；
2. 题目展示区视觉接近 practice；
3. 页面为只读模式，不允许重新作答；
4. 用户错误答案可以高亮；
5. 正确答案可以高亮；
6. 多选题多个答案显示正确；
7. 多空选择题每个空的答案状态显示正确；
8. 解析内容正常；
9. AI 错题复盘正常；
10. 上一题/下一题错题切换正常；
11. 原有返回逻辑正常。

------

## 十五、代码质量要求

1. 不要大面积重复复制 `practice` 的 JS 逻辑到其他页面；
2. 能组件化的 UI 必须组件化；
3. 能抽到 `utils/question-runner-adapter.js` 的题目适配逻辑尽量抽出；
4. 页面只负责业务状态和接口；
5. 组件只负责展示和交互事件；
6. 不要破坏已有接口参数；
7. 不要删除已有功能；
8. 不要引入新的大型依赖；
9. 保持微信小程序基础语法兼容；
10. 如 WXML 表达式复杂，请提前在 JS 中计算字段。

------

## 十六、推荐实施顺序

请按以下顺序执行，不要一次性无序大改：

### 第一步：抽组件骨架

新增：

```text
components/quiz-runner/
```

先把 practice 答题态的 WXML/WXSS 迁移进去，保证组件能展示单题、选项、底部导航和答题卡。

### 第二步：接入 practice

让 `practice` 页面先使用 `quiz-runner`。

目标：改造后 practice 页面体验不能下降。

### 第三步：接入 review-today

将 `review-today` 的答题区域替换为 `quiz-runner`，保留原有复习业务逻辑。

目标：今日复习页面获得和 practice 接近的刷题体验。

### 第四步：接入 wrong-detail 只读模式

让 `wrong-detail` 的题目区域使用 `quiz-runner readonly` 模式，错题解析和 AI 复盘继续保留在页面中。

### 第五步：清理重复代码

检查并减少以下重复逻辑：

```text
_normalizeBlankAnswer
_enrichBlankOptionGroups
_buildOptionList
_buildAnsweredFlags
_computeAnsweredCount
题型 label 生成
选项 selected/correct/wrong 状态生成
```

能放入 `utils/question-runner-adapter.js` 的尽量放入统一工具。

------

## 十七、最终交付内容

请最终提交以下内容：

```text
components/quiz-runner/quiz-runner.js
components/quiz-runner/quiz-runner.json
components/quiz-runner/quiz-runner.wxml
components/quiz-runner/quiz-runner.wxss

utils/question-runner-adapter.js

改造后的：
pages/practice/practice.wxml
pages/practice/practice.js
pages/practice/practice.json
pages/practice/practice.wxss

pages/review-today/review-today.wxml
pages/review-today/review-today.js
pages/review-today/review-today.json
pages/review-today/review-today.wxss

pages/wrong-detail/wrong-detail.wxml
pages/wrong-detail/wrong-detail.js
pages/wrong-detail/wrong-detail.json
pages/wrong-detail/wrong-detail.wxss
```

如果某些 WXSS 样式已完全迁移到组件中，页面 WXSS 可以只保留页面自身业务区域样式。

------

## 十八、最终说明

请在完成后说明：

1. 新增了哪些文件；
2. 修改了哪些页面；
3. 哪些 UI 从 practice 抽成了公共组件；
4. review-today 如何复用了该组件；
5. wrong-detail 如何使用只读模式；
6. 有哪些兼容性处理；
7. 哪些地方仍建议后续优化。

本次任务的最终目标不是简单“复制 practice 页面”，而是建立一个可长期复用的刷题 UI 基础设施，让后续的错题再练、收藏题练习、专项练习、今日复习都可以复用同一套高质量刷题体验。