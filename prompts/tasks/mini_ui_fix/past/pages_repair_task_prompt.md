# 详细修复任务 Prompt：练习 / 错题 / 今日复习页面 UI 与逻辑问题修复

你是一名熟悉微信小程序前端、Python/FastAPI 后端、题库/错题本/复习调度业务的资深全栈工程师。请基于当前项目代码，修复 `pages` 目录下以下页面的 UI 与逻辑问题，并同步修复必要的后端接口判题契约问题：

- `pages/practice`
- `pages/practice-result`
- `pages/review-today`
- `pages/wrong-book`
- `pages/wrong-detail`

后端相关代码主要涉及：

- `app/services/practice_service.py`
- `app/api/v1/review.py`
- `app/api/v1/wrong_questions.py`
- `app/schemas/*` 中与错题、复习、判题返回相关的 schema

## 一、修复总目标

请在不大规模重构、不破坏现有页面风格、不改动无关业务的前提下，完成以下目标：

1. 确保 5 个页面能够在微信小程序环境中正常编译、渲染、跳转和交互。
2. 确保单选题、判断题、多选题、多空选择题在练习、今日复习、错题详情中的展示、作答、提交、判题、高亮逻辑一致。
3. 确保前后端答案判定口径统一，尤其是多选题 `A,C` 与用户点击顺序 `C,A` 不应被误判。
4. 确保加载失败、无题、空提交、错题不存在等异常状态有明确 UI 反馈和恢复路径。
5. 确保错题本筛选后的诊断分析与当前筛选列表一致。
6. 确保错题详情页 AI 分析不会因快速切题而串题。
7. 确保结果页统计口径可信，并能展示用户答案、正确答案和题干摘要。

## 二、强制开发约束

1. 不要删除现有主要功能。
2. 不要引入大型第三方依赖。
3. 不要为了修复一个页面而重写整套业务。
4. WXML 中不要直接调用 Page 方法，不要调用 `Math.round()` 等 JS 运行时函数。
5. 所有会影响判题的答案格式，都必须经过统一 normalize/serialize 逻辑。
6. 前端本地判题、练习提交后端判题、今日复习批改后端判题，三者结果必须一致。
7. 修改后请检查小程序 WXML/WXSS/JS 语法合法性。
8. 请尽量复用已有工具方法；如果新增工具方法，请放在清晰的位置，例如 `utils/answer.js` 或类似文件。
9. 修复完成后，请输出：修改文件列表、每个问题的修复说明、回归测试结果、仍需人工验证的事项。

## 三、优先级 P0：必须首先修复的问题

### P0-1：修复 `practice.wxml` 模板层直接调用 JS 方法 / `Math.round()` 的问题

涉及文件：

- `pages/practice/practice.wxml`
- `pages/practice/practice.js`

当前风险：

- WXML 中存在类似 `{{modeLabel(selectedMode)}}`、`{{Math.round(...)}}` 的表达式。
- 微信小程序模板层不应直接调用 Page 方法或运行时 JS 函数，可能导致编译或渲染异常。

修复要求：

1. 在 `practice.js` 的 `data` 中新增或维护以下字段：
   - `selectedModeLabel`
   - `progressPercent`
   - 如页面存在成长值、节奏标签、百分比展示等类似动态计算，也统一预计算到 data。
2. 在以下场景同步刷新这些字段：
   - 页面初始化
   - `chooseMode`
   - `setCount`
   - 开始练习
   - 切题
   - 选择选项
   - 选择多空选项
   - 提交前后
3. WXML 中只绑定普通 data 字段，例如：
   - `{{selectedModeLabel}}`
   - `{{progressPercent}}%`
4. 保留原有视觉布局，不要改变页面结构风格。

验收标准：

- `practice.wxml` 中不再出现 `modeLabel(`、`Math.round(`。
- 练习设置页、答题页、挑战模式 chip、进度百分比都能正常显示。

---

### P0-2：统一多选题前后端判题口径

涉及文件：

- `pages/practice/practice.js`
- `pages/review-today/review-today.js`
- `pages/wrong-detail/wrong-detail.js`
- `app/services/practice_service.py`
- `app/api/v1/review.py`

当前风险：

- 前端本地 `_isAnswerCorrect` 对多选题可能会排序归一化。
- 提交给后端时，用户点击顺序可能是 `C,A`。
- 后端直接字符串比较，如果标准答案为 `A,C`，会把 `C,A` 判错。

修复要求：

前端新增统一答案工具函数，建议包括：

```js
normalizeChoiceAnswer(answer)
serializeChoiceAnswer(answer)
isChoiceAnswerCorrect(userAnswer, correctAnswer, questionType)
normalizeBlankAnswer(answer)
serializeBlankAnswer(answer)
```

后端新增或复用统一答案工具函数，建议包括：

```python
def normalize_choice_answer(answer: str) -> list[str]:
    ...

def serialize_choice_answer(answer: str) -> str:
    ...

def is_answer_correct(user_answer: str, correct_answer: str, question_type: str) -> bool:
    ...
```

多选题 normalize 规则：

1. 支持以下输入格式：
   - `A,C`
   - `C,A`
   - `AC`
   - `A C`
   - `A；C`
   - `A，C`
   - `a,c`
2. 去空格、统一大写。
3. 去重。
4. 按选项字母排序。
5. 比较时按集合/排序后数组比较，而不是直接字符串比较。
6. 提交后端前，多选题答案必须序列化为稳定格式，例如 `A,C`。

单选题和判断题规则：

1. 去空格。
2. 字母统一大写。
3. 判断题如当前系统约定 `A=正确`、`B=错误`，保持该约定。

多空选择题规则：

1. 必须保持每个空位的答案顺序。
2. 每个空位内如允许多选，再进行该空位内部排序；如果每空只选一个，则直接比较每个空位。
3. 前后端使用同一序列化格式，例如 `1:A|2:C|3:B` 或项目已有格式，必须全链路一致。

验收标准：

- 正确答案 `A,C`，用户按 `C -> A` 选择，练习页本地、练习提交后端、今日复习后端均判正确。
- 错题本不会错误记录这类本来答对的多选题。
- 后端不再使用简单的 `user_answer.strip().lower() == question.answer.strip().lower()` 处理多选题。

---

### P0-3：补全 `review-today` 对多选题和多空选择题的支持

涉及文件：

- `pages/review-today/review-today.js`
- `pages/review-today/review-today.wxml`
- `pages/review-today/review-today.wxss`
- `app/api/v1/review.py`

当前风险：

- 今日复习页目前主要按单选/判断题模式渲染。
- 如果复习池包含 `multiple_choice`，用户只能选一个。
- 如果复习池包含 `multi_blank_choice`，页面没有按空位分组选项，用户无法正确作答。

修复要求：

1. 在 `review-today.js` 中识别题型：
   - `single_choice`
   - `true_false` / `judgement`
   - `multiple_choice`
   - `multi_blank_choice`
2. 对 `multiple_choice`：
   - 支持多选切换。
   - 已选项再次点击可取消。
   - 保存为数组或集合，提交前序列化为稳定格式 `A,C`。
   - UI 上明确显示“多选题”。
3. 对 `multi_blank_choice`：
   - 复用或移植 `practice` 页已有的 `_enrichBlankOptionGroups`、`_normalizeBlankAnswer`、`_serializeBlankAnswer` 等逻辑。
   - WXML 按空位渲染选项组。
   - 每个空位的选择互不影响。
   - 提交时按后端约定格式序列化。
4. 对判断题：
   - 如果后端未返回 options，前端兜底为 `{ A: '正确', B: '错误' }`。
5. 后端 `/review/grade-batch` 必须复用统一判题逻辑。

验收标准：

- 今日复习出现多选题时，可以选择多个选项，提交后正确判题。
- 今日复习出现多空选择题时，可以按空位作答，提交后正确判题。
- 今日复习出现判断题且 options 为空时，仍显示“正确/错误”。

## 四、优先级 P1：主要流程与统计可信度修复

### P1-1：明确并修复 `practice` 未作答题目的提交与统计口径

涉及文件：

- `pages/practice/practice.js`
- `pages/practice-result/practice-result.js`
- `pages/practice-result/practice-result.wxml`
- `app/services/practice_service.py`

当前风险：

- 用户提交时，未作答题目可能被排除在提交 answers 之外。
- 结果页仍用 total 计算正确率，导致统计口径混乱。
- 错题本可能不会记录未答题。

请先在代码中选择并落实一种清晰口径，建议采用：

方案 A：未作答视为跳过

1. 后端返回 `correct_count`、`wrong_count`、`skipped_count`。
2. 前端结果页展示“答对 / 答错 / 跳过”。
3. 正确率建议按 `correct / total` 或 `correct / answered` 明确标注，不要混淆。
4. 跳过题是否进入错题本，由产品口径决定；若不进入，也应在结果页提示。

或方案 B：未作答视为错误

1. 前端提交所有题。
2. 未答题使用空答案 `''`。
3. 后端判错并进入错题本。
4. 结果页展示未答题数量，但计入错误。

优先推荐方案 A，因为更符合“未答”和“答错”区分。

验收标准：

- 10 题只答 1 题后提交，结果页必须明确显示答对、答错、跳过数量。
- 后端统计、结果页统计、错题本记录口径一致。

---

### P1-2：修复 `practice` 加载失败/无题时状态回退不完整的问题

涉及文件：

- `pages/practice/practice.js`
- `pages/practice/practice.wxml`

修复要求：

1. 加载题目前不要过早进入不可恢复的 `started=true` 状态；如果必须先置 `started=true`，失败时必须统一恢复。
2. 新增或完善错误态字段：
   - `errorText`
   - `emptyText`
   - `canRetry`
3. 接口失败、无科目、无题、返回空数组时：
   - 停止计时器。
   - 清空当前题。
   - 退出答题态或显示明确错误态。
   - 提供“重新加载”和“返回设置页/重新选择科目”。
4. 去掉“继续等待”这种没有实际动作的按钮，或为其补充真实轮询/重试逻辑。

验收标准：

- 接口失败不会停留在第 `1/0` 题。
- 无题时计时器停止。
- 用户能重试或返回设置页。

---

### P1-3：修复 `review-today` 0 题已答却提交空数组的问题

涉及文件：

- `pages/review-today/review-today.js`

修复要求：

1. 构造 `reviews` 后，如果数组长度为 0，不要请求后端。
2. 给出明确 toast 或弹窗：`请至少作答 1 题，或选择按不会处理`。
3. 恢复 `submittingGroup=false`。

验收标准：

- 今日复习 0 题作答时选择“仅提交已答”，前端拦截，不发送空请求。

---

### P1-4：修复 `wrong-book` 筛选后诊断分析仍使用全局统计的问题

涉及文件：

- `pages/wrong-book/wrong-book.js`
- 如有必要，后端错题统计接口也可扩展筛选参数

修复要求：

筛选态下必须保证以下三者口径一致：

1. 错题列表。
2. 知识漏洞分析。
3. 雷达/优先级/错因统计。

可以采用以下方案之一：

方案 A：后端 stats 接口支持筛选参数

- `subject`
- `error_type`
- `status`
- 其他当前页面已有筛选条件

方案 B：前端筛选后强制按当前列表重建分析

- 当存在筛选条件时，不使用全局 `stats`。
- 调用 `_buildAnalysis(null, nextList)` 或等价逻辑。

验收标准：

- 筛选“数学”后，上方分析只基于数学错题。
- 筛选某个错因后，上方分析只基于该错因列表。

---

### P1-5：修复 `wrong-detail` 判断题缺少兜底选项的问题

涉及文件：

- `pages/wrong-detail/wrong-detail.js`
- `app/api/v1/wrong_questions.py`
- 错题 response schema

修复要求：

1. 后端错题详情 response 中建议返回 `question_type`。
2. 前端 `_processWqData` 中根据 `question_type` 做判断题兜底：

```js
if ((!opts || Object.keys(opts).length === 0) && isTrueFalseQuestion(wq.question_type)) {
  opts = { A: '正确', B: '错误' }
}
```

3. 如果后端也做兜底，前端仍保留兜底作为防御式处理。

验收标准：

- 判断题 options 为空时，错题详情仍显示“正确/错误”。
- 正确答案和我的答案能正常高亮。

---

### P1-6：修复 `wrong-detail` 多选题正确答案/我的答案高亮逻辑

涉及文件：

- `pages/wrong-detail/wrong-detail.js`
- `pages/wrong-detail/wrong-detail.wxml`
- `pages/wrong-detail/wrong-detail.wxss`

修复要求：

1. 不要使用 `key === wq.answer` 判断多选题正确项。
2. 将正确答案和用户答案都 normalize 成集合。
3. 每个选项上计算：
   - `isCorrect`
   - `isUserAnswer`
   - `isBothCorrectAndUser`
4. UI 样式需要能区分：
   - 正确答案。
   - 我的错误选择。
   - 我选中且也是正确答案的选项。
5. 保持单选题、判断题原有高亮效果不退化。

验收标准：

- 正确答案 `A,C`，我的答案 `A,B` 时：
  - A 显示为“我选了且正确”。
  - B 显示为“我误选”。
  - C 显示为“正确但我漏选”。

---

### P1-7：修复 `wrong-detail` AI 分析异步串题风险

涉及文件：

- `pages/wrong-detail/wrong-detail.js`

修复要求：

1. 每次请求 AI 分析时生成唯一 token，例如：

```js
const token = `${wqId}-${Date.now()}`
this._aiToken = token
```

2. AI 请求返回后，必须校验：

```js
if (this._aiToken !== token) return
if (!this.data.wq || this.data.wq.id !== wqId) return
```

3. 切题时清空上一题 AI 结果或显示当前题 AI loading。
4. 请求失败时只影响当前题，不覆盖新题状态。

验收标准：

- 快速左右滑动错题详情，AI 分析始终对应当前题。
- 上一题的慢请求不会覆盖下一题内容。

---

### P1-8：给 `wrong-detail` 增加加载失败错误态 UI

涉及文件：

- `pages/wrong-detail/wrong-detail.js`
- `pages/wrong-detail/wrong-detail.wxml`
- `pages/wrong-detail/wrong-detail.wxss`

修复要求：

1. 增加 `errorText` 字段。
2. 加载失败、错题不存在、接口 404、接口异常时显示错误态。
3. 错误态至少包含：
   - 错误说明。
   - “重新加载”按钮。
   - “返回错题本”按钮。
4. 不能只 toast 后空白。

验收标准：

- 错题 id 不存在时页面不空白。
- 用户能重新加载或返回错题本。

## 五、优先级 P2：体验与健壮性修复

### P2-1：修复 `review-today` safe mode 自愈逻辑无效问题

涉及文件：

- `pages/review-today/review-today.js`

修复要求：

1. 当检测到 CODE/MIXED 渲染异常并进入 safe mode 后，必须重建当前题或全部题目的 `_renderModel`。
2. `_showQuestion` 中应根据当前 `safeModeActive` 动态构建或刷新当前题 render model。
3. 不要只设置 `safeModeActive=true` 后重复显示旧 `_renderModel`。

验收标准：

- 触发 safe mode 后，当前题实际使用 safe mode 渲染模型。

---

### P2-2：修复 `wrong-detail` 滑动切题时未沿用 safe mode、未执行渲染校验的问题

涉及文件：

- `pages/wrong-detail/wrong-detail.js`

修复要求：

1. `_navigateTo` 切题时调用 `_processWqData(wq, this.data.safeModeActive)` 或等价逻辑。
2. 切题后继续执行 `_checkRenderInvariant` 和 `_recordRenderTrace`。
3. 前一题已触发 safe mode 时，下一题不要退回非 safe mode。

验收标准：

- 滑动切题后 safe mode 状态连续有效。

---

### P2-3：给 `wrong-book` 加载更多增加并发和边界保护

涉及文件：

- `pages/wrong-book/wrong-book.js`

修复要求：

```js
loadMore() {
  if (this.data.loading || !this.data.hasMore) return
  this.loadList()
}
```

如当前已有类似逻辑，请确认所有入口都受保护。

验收标准：

- 快速点击加载更多不会重复请求同一页。
- `hasMore=false` 时不会继续请求。

---

### P2-4：优化 `wrong-book -> wrong-detail` 的 ids 传递方式

涉及文件：

- `pages/wrong-book/wrong-book.js`
- `pages/wrong-detail/wrong-detail.js`

当前风险：

- 通过 URL 传递所有已加载错题 id，列表变长后可能超出 URL 长度限制。
- 详情页只能在已加载列表内滑动，不能自然继续分页。

修复要求：

可采用以下方案之一：

方案 A：使用本地缓存传 id 列表

```js
wx.setStorageSync('wrong_detail_ids', ids)
wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}&index=${index}` })
```

详情页从 storage 读取 ids。

方案 B：详情页基于当前筛选条件分页加载

- URL 只传当前 id、筛选条件、排序条件。
- 详情页滑到边界时请求下一页。

优先采用方案 A，改动较小。

验收标准：

- URL 不再携带超长 ids 字符串。
- 已加载错题范围内仍可正常左右滑动。

---

### P2-5：给 `review-today` 增加显式上一题/下一题按钮

涉及文件：

- `pages/review-today/review-today.wxml`
- `pages/review-today/review-today.wxss`
- `pages/review-today/review-today.js`

修复要求：

1. 保留题号点击和左右滑动。
2. 额外增加底部操作区：
   - 上一题。
   - 下一题。
   - 最后一题显示“提交本组复盘”。
3. 按钮禁用状态清晰：
   - 第一题禁用上一题。
   - 最后一题不显示下一题或替换为提交。

验收标准：

- 用户不依赖手势也能完成整组复习。

---

### P2-6：增强 `practice-result` 复盘信息展示

涉及文件：

- `pages/practice-result/practice-result.js`
- `pages/practice-result/practice-result.wxml`
- `pages/practice-result/practice-result.wxss`
- 后端练习提交返回结构，如有必要

当前风险：

- 当前结果页只展示序号、对错和正确答案。
- 用户看不到自己的答案和题干摘要，复盘价值不足。

修复要求：

每道结果项至少展示：

1. 题干摘要，建议截断到 30-60 字。
2. 我的答案。
3. 正确答案。
4. 对错状态。
5. 如已有解析字段，展示解析入口或简短解析。
6. 对错题可跳转错题详情或题目详情；如果当前后端没有错题 id，可先保留入口占位或只展示详情。

验收标准：

- 用户在结果页即可判断自己错在哪里。
- 不影响原有统计卡片展示。

## 六、全局环境风险修复建议

涉及文件：

- `config.js`

当前风险：

- `DEV = true` 时，`BASE_URL` 可能为 `http://localhost:8000/api/v1`。
- 真机体验版/正式版会请求手机自己的 localhost，导致接口全部失败。

修复要求：

1. 不要让生产构建依赖手工修改 `DEV`。
2. 建议增加环境配置，例如：
   - `development`
   - `staging`
   - `production`
3. 至少在代码注释中明确：上线前必须使用生产 API 地址。
4. 如果项目已有构建环境变量，请接入该机制。

验收标准：

- 开发环境仍可请求本地后端。
- 体验版/正式版不会默认请求 localhost。

## 七、建议新增/调整的统一工具方法

### 前端答案工具建议

建议新增：`utils/answer.js`

需要覆盖能力：

```js
function normalizeChoiceAnswer(answer) {}
function serializeChoiceAnswer(answer) {}
function normalizeAnswerSet(answer) {}
function isMultipleChoiceType(questionType) {}
function isTrueFalseType(questionType) {}
function isMultiBlankType(questionType) {}
function normalizeBlankAnswer(answer) {}
function serializeBlankAnswer(answer) {}
function isAnswerCorrect(userAnswer, correctAnswer, questionType) {}
```

使用位置：

- `practice.js`
- `review-today.js`
- `wrong-detail.js`
- 其他已有本地判题逻辑的位置

### 后端答案工具建议

建议放入：

- `app/services/practice_service.py` 内部工具函数，或
- 新增 `app/utils/answer_normalizer.py`

需要覆盖能力：

```python
def is_multiple_choice_type(question_type: str) -> bool: ...
def is_true_false_type(question_type: str) -> bool: ...
def is_multi_blank_type(question_type: str) -> bool: ...
def normalize_choice_answer(answer: str) -> list[str]: ...
def serialize_choice_answer(answer: str) -> str: ...
def normalize_blank_answer(answer: str): ...
def is_answer_correct(user_answer: str, correct_answer: str, question_type: str) -> bool: ...
```

使用位置：

- 练习提交判题。
- 今日复习批量批改。
- 错题统计中如存在判题或重算逻辑，也应复用。

## 八、必须执行的回归测试用例

请至少手动或自动验证以下用例，并在最终回复中记录结果。

| 编号 | 用例 | 预期 |
|---|---|---|
| T1 | 进入 practice 页面 | WXML 正常编译，无模板函数调用报错 |
| T2 | 切换练习模式 | 模式标签正常变化 |
| T3 | 做多选题，正确答案 `A,C`，用户按 `C -> A` 选择 | 前端本地判正确，后端提交判正确 |
| T4 | 今日复习出现多选题 | 可多选、可取消、提交判题正确 |
| T5 | 今日复习出现多空选择题 | 按空位展示和选择，提交判题正确 |
| T6 | 判断题 options 为空 | practice/review/wrong-detail 都显示“正确/错误” |
| T7 | 练习 10 题只答 1 题提交 | 结果页清楚显示答对/答错/跳过或未答统计 |
| T8 | practice 接口失败 | 不显示 1/0 题，计时器停止，有重试/返回入口 |
| T9 | 今日复习 0 题作答选择“仅提交已答” | 前端拦截，不发送空数组 |
| T10 | wrong-book 筛选数学 | 列表和知识漏洞分析都只基于数学错题 |
| T11 | wrong-detail 多选题：正确 `A,C`，我的 `A,B` | A/B/C 高亮语义正确 |
| T12 | 快速左右滑动 wrong-detail | AI 分析不串题 |
| T13 | wrong-detail 加载不存在 id | 显示错误态，可重试/返回 |
| T14 | wrong-book 快速点加载更多 | 不重复请求，不越界请求 |
| T15 | wrong-book 跳 wrong-detail | URL 不携带超长 ids，滑动仍可用 |
| T16 | review-today 不使用手势 | 通过上一题/下一题按钮可完成复习 |
| T17 | practice-result | 展示题干摘要、我的答案、正确答案、对错状态 |

## 九、最终交付格式

修复完成后，请输出以下内容：

```md
# 修复完成说明

## 1. 修改文件列表
- xxx
- xxx

## 2. 按问题编号的修复说明
### P0-1
- 修复方式：
- 影响文件：
- 验证结果：

### P0-2
...

## 3. 回归测试结果
| 用例 | 是否通过 | 说明 |
|---|---|---|
| T1 | 通过/未通过 | ... |

## 4. 仍需人工确认的问题
- ...

## 5. 风险提示
- ...
```

请开始修复。优先完成 P0 和 P1；如果时间有限，P2 可以分批提交，但必须明确哪些已完成、哪些未完成。
