你现在需要基于当前项目代码，对小程序前端 `miniprogram` 和后端 `app` 进行问题修复。请不要重构无关模块，不要改动已有业务逻辑中已经稳定的部分，只针对本次审计发现的问题做最小必要修复。修复完成后需要保证前端页面无明显运行时报错，后端接口字段与前端依赖一致，测试脚本能正常运行。

## 一、修复目标总览

本次需要修复以下 5 类问题：

1. `wrong-detail` 错题详情页依赖 `question_type`，但后端错题详情接口未返回该字段，导致判断题、多选题展示不准确。
2. `wrong-book` 错题本页面前端会传 `topic` 参数，但后端列表接口未接收、未过滤，导致知识点筛选是假筛选。
3. `import-batch.wxml` 中存在空 `catchtap` 写法，可能导致事件冒泡或编译隐患。
4. `import` 导入流程中，后端已有 `/resume` 恢复接口，但前端 paused/failed 状态没有接入恢复逻辑，前后端功能不一致。
5. 测试文件 `tests/test-latex-symbols.js` 依赖 `scripts/check-latex-symbols-sync.js`，但当前项目缺少该脚本，导致测试不能全绿。

请按下面的任务逐项修复。

------

# 任务 1：修复 wrong-detail 缺少 question_type 字段的问题

## 问题描述

前端文件：

```
miniprogram/pages/wrong-detail/wrong-detail.js
```

错题详情页中存在类似逻辑：

```js
isTrueFalseType(wq.question_type)
isMultipleChoiceType(wq.question_type)
```

前端需要根据 `question_type` 判断题型：

- 判断题：需要在没有 options 时自动补 `{ A: '正确', B: '错误' }`
- 多选题：需要按集合方式高亮多个正确答案
- 单选题：按普通选项处理

但是后端错题相关响应没有返回 `question_type`。

后端相关文件：

```text
app/schemas/wrong_question.py
app/api/v1/wrong_questions.py
app/services/wrong_question_service.py
```

当前 `WrongQuestionResponse` 中缺少：

```python
question_type: str | None = None
```

`enrich_wq()` 或构造响应对象时也没有设置：

```python
question_type=question.question_type if question else None
```

## 修复要求

### 1. 修改 schema

在 `app/schemas/wrong_question.py` 中找到 `WrongQuestionResponse`，添加字段：

```python
question_type: str | None = None
```

建议完整字段结构包含：

```python
class WrongQuestionResponse(BaseModel):
    id: int
    question_id: int
    wrong_answer: str | None = None
    error_type: str
    review_count: int
    created_at: datetime
    updated_at: datetime

    subject: str | None = None
    question_type: str | None = None
    content: dict | None = None
    options: dict | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_points: list | None = None
```

如果项目使用 Pydantic v2，需要保持现有 `model_config` 风格，不要破坏原配置。

### 2. 修改错题详情/列表响应组装逻辑

在 `app/api/v1/wrong_questions.py` 中找到负责把 `WrongQuestion` 和 `Question` 合并成响应对象的函数，例如：

```python
def enrich_wq(wq, question):
    ...
```

或类似逻辑。

补充：

```python
question_type=question.question_type if question else None
```

示例：

```python
def enrich_wq(wq, question):
    return WrongQuestionResponse(
        id=wq.id,
        question_id=wq.question_id,
        wrong_answer=wq.wrong_answer,
        error_type=wq.error_type,
        review_count=wq.review_count,
        created_at=wq.created_at,
        updated_at=wq.updated_at,
        subject=question.subject_ref.code if question and question.subject_ref else None,
        question_type=question.question_type if question else None,
        content=_sanitize_content(question.content) if question else None,
        options=_sanitize_options(question.options) if question else None,
        answer=question.answer if question else None,
        analysis=question.analysis if question else None,
        knowledge_points=question.knowledge_points if question else None,
    )
```

注意：

- 不要只修详情接口，错题列表如果也复用该响应，也应该包含 `question_type`。
- 保持接口向后兼容，新增字段不会影响旧客户端。
- 如果 `question.question_type` 是枚举类型，需要转成字符串。

### 3. 前端容错增强

在 `miniprogram/pages/wrong-detail/wrong-detail.js` 中，保留现有题型判断逻辑，但需要增加兜底：

```js
const questionType = wq.question_type || wq.type || ''
```

避免后端异常数据导致页面崩溃。

判断题 options 兜底逻辑建议保留：

```js
if (this.isTrueFalseType(questionType) && (!options || Object.keys(options).length === 0)) {
  options = {
    A: '正确',
    B: '错误'
  }
}
```

多选题高亮时，不能用 `key === answer` 判断整体字符串，需要支持：

```js
answer = 'A,C'
wrong_answer = 'A,B'
```

请确保多选题选项状态能够正确识别：

- 是否为正确答案
- 是否为用户错选答案
- 是否漏选答案

------

# 任务 2：修复 wrong-book 的 topic 知识点筛选是假筛选问题

## 问题描述

前端文件：

```text
miniprogram/pages/wrong-book/wrong-book.js
```

会发送：

```js
if (this.data.selectedTopic) {
  params.topic = this.data.selectedTopic
}
```

页面上也会展示当前筛选条件：

```xml
知识点：{{selectedTopic}}
```

但是后端接口：

```python
async def list_wrong(
    subject: str | None = Query(None),
    error_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
)
```

没有 `topic` 参数，服务层也没有基于知识点过滤，所以前端显示“已按知识点筛选”，但实际列表没有筛选。

## 修复要求

### 1. 后端 API 增加 topic 参数

在 `app/api/v1/wrong_questions.py` 的错题列表接口中增加：

```python
topic: str | None = Query(None)
```

修改前类似：

```python
async def list_wrong(
    subject: str | None = Query(None),
    error_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
```

修改后：

```python
async def list_wrong(
    subject: str | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
```

并把 `topic` 传入 service：

```python
items, total = await svc.list_wrong(
    db=db,
    user_id=current_user.id,
    subject=subject,
    error_type=error_type,
    topic=topic,
    page=page,
    page_size=page_size,
)
```

如果当前项目不是关键字参数风格，请按原项目代码风格调整，但必须传递 `topic`。

### 2. 服务层实现 topic 过滤

在 `app/services/wrong_question_service.py` 中找到 `list_wrong()`。

增加参数：

```python
topic: str | None = None
```

查询逻辑需要关联题目表 `Question`，并基于题目的 `knowledge_points` 字段过滤。

请根据当前数据库字段类型选择实现：

#### 情况 A：`knowledge_points` 是 JSON / JSONB / list

如果是 PostgreSQL JSONB，可以使用 contains 或文本兼容方式。

优先使用项目现有 ORM 写法，示例：

```python
if topic:
    query = query.where(Question.knowledge_points.contains([topic]))
```

如果 contains 不适配当前数据库，可退化为文本匹配：

```python
if topic:
    query = query.where(cast(Question.knowledge_points, String).contains(topic))
```

#### 情况 B：`knowledge_points` 是字符串

可用：

```python
if topic:
    query = query.where(Question.knowledge_points.contains(topic))
```

### 3. 分页 total 必须同步过滤

修复时注意：

- 列表查询要按 topic 过滤。
- total 统计也要按 topic 过滤。
- 不能只在 Python 层过滤当前页，否则分页会错误。
- 不能只前端过滤，否则 total 和分页仍然错误。

### 4. 前端参数保留，但增加编码安全

在 `miniprogram/pages/wrong-book/wrong-book.js` 中，继续保留：

```js
if (this.data.selectedTopic) {
  params.topic = this.data.selectedTopic
}
```

如果项目的 request 工具不会自动 encode，需保证 topic 里有中文、空格、特殊符号时不会请求失败。

### 5. 验收标准

从 dashboard 或其他页面带 topic 跳转错题本时：

```text
/pages/wrong-book/wrong-book?topic=某知识点
```

应满足：

- 页面展示“知识点：某知识点”
- 列表中只出现该知识点相关错题
- total 数量与筛选结果一致
- 翻页时仍保持 topic 筛选
- 清除筛选后恢复全部错题

------

# 任务 3：修复 import-batch.wxml 空 catchtap 问题

## 问题描述

文件：

```text
miniprogram/pages/import-batch/import-batch.wxml
```

存在两处空 `catchtap`：

```xml
<text class="q-math-flag" wx:if="{{item._hasMath}}" bindtap="showMathPreview" catchtap data-id="{{item.id}}">含公式</text>
<view class="q-detail {{expanding === item.id ? 'show' : ''}}" catchtap>
```

问题：

1. 空 `catchtap` 写法不规范。
2. 第一处同时写了 `bindtap` 和空 `catchtap`，容易导致点击“含公式”时既打开公式预览，又冒泡触发父级点击事件。
3. 第二处可能原本想阻止冒泡，但没有绑定方法。

## 修复要求

### 1. 修复“含公式”点击事件

将：

```xml
<text class="q-math-flag" wx:if="{{item._hasMath}}" bindtap="showMathPreview" catchtap data-id="{{item.id}}">含公式</text>
```

改为：

```xml
<text
  class="q-math-flag"
  wx:if="{{item._hasMath}}"
  catchtap="showMathPreview"
  data-id="{{item.id}}"
>含公式</text>
```

这样点击“含公式”只触发 `showMathPreview`，不会继续冒泡到父级卡片。

### 2. 修复详情区域 catchtap

将：

```xml
<view class="q-detail {{expanding === item.id ? 'show' : ''}}" catchtap>
```

改为：

```xml
<view class="q-detail {{expanding === item.id ? 'show' : ''}}" catchtap="noop">
```

### 3. 在 JS 中补 noop 方法

文件：

```text
miniprogram/pages/import-batch/import-batch.js
```

在 Page 方法中增加：

```js
noop() {},
```

注意不要写在 `data` 里面，要写在 Page 对象的方法区。

### 4. 验收标准

- 微信开发者工具不再提示空事件绑定。
- 点击“含公式”只打开公式预览，不触发卡片展开/收起。
- 点击详情区域不会异常冒泡。
- 页面原有展开/收起逻辑保持不变。

------

# 任务 4：统一 import paused/failed 状态的恢复逻辑

## 问题描述

后端已有恢复接口：

```text
POST /import/pipelines/{pipeline_id}/resume
```

但前端 `miniprogram/pages/import/import.js` 遇到 paused 状态时，只提示：

```js
wx.showModal({
  title: '导入中断',
  content: '部分内容处理失败，请重新上传文件',
  showCancel: false,
})
```

这导致：

- 后端支持恢复。
- 前端没有恢复入口。
- 用户只能重新上传。
- 产品行为与接口能力不一致。

## 修复要求

请根据产品意图选择一种方案，但必须统一前后端行为。

------

## 方案 A：推荐方案，前端接入 resume 恢复接口

### 1. 前端增加 paused/failed 状态 UI

在导入页中，当 pipeline 状态为：

```text
paused
failed
```

且存在 `pipeline_id` 时，显示按钮：

```text
选择原 PDF 并恢复导入
```

按钮说明文案建议：

```text
导入中断。你可以选择原 PDF 文件继续恢复导入，也可以重新上传文件开始新的导入。
```

### 2. 增加恢复导入方法

在 `miniprogram/pages/import/import.js` 中增加方法：

```js
resumePipeline() {
  const pipelineId = this.data.pipelineId || this.data.pipeline_id
  if (!pipelineId) {
    wx.showToast({
      title: '缺少导入任务ID',
      icon: 'none'
    })
    return
  }

  wx.chooseMessageFile({
    count: 1,
    type: 'file',
    extension: ['pdf'],
    success: (res) => {
      const file = res.tempFiles && res.tempFiles[0]
      if (!file || !file.path) {
        wx.showToast({
          title: '未选择文件',
          icon: 'none'
        })
        return
      }

      this.uploadResumeFile(pipelineId, file.path)
    },
    fail: () => {
      wx.showToast({
        title: '已取消选择',
        icon: 'none'
      })
    }
  })
}
```

### 3. 增加上传恢复文件方法

根据当前项目 request/config 写法调整，示例：

```js
uploadResumeFile(pipelineId, filePath) {
  const token = wx.getStorageSync('token')

  this.setData({
    uploading: true,
    importStatus: 'resuming'
  })

  wx.uploadFile({
    url: `${config.BASE_URL}/import/pipelines/${pipelineId}/resume`,
    filePath,
    name: 'file',
    header: {
      Authorization: `Bearer ${token}`
    },
    success: (res) => {
      let data = {}
      try {
        data = JSON.parse(res.data || '{}')
      } catch (e) {
        data = {}
      }

      if (res.statusCode >= 200 && res.statusCode < 300) {
        wx.showToast({
          title: '已恢复导入',
          icon: 'success'
        })

        this.setData({
          uploading: false,
          pipelineId,
          importStatus: data.status || 'processing'
        })

        this.startPolling(pipelineId)
      } else {
        wx.showToast({
          title: data.detail || data.message || '恢复失败',
          icon: 'none'
        })

        this.setData({
          uploading: false
        })
      }
    },
    fail: () => {
      wx.showToast({
        title: '网络异常，恢复失败',
        icon: 'none'
      })

      this.setData({
        uploading: false
      })
    }
  })
}
```

注意：

- `config.BASE_URL` 请使用项目实际配置名称。
- token key 请使用项目实际登录存储 key。
- 如果项目已有统一 upload 工具，优先复用。
- 不要硬编码 localhost。
- 上传字段名必须与后端接口参数一致，如果后端接收的是 `file`，前端 name 就必须是 `file`。

### 4. 修改 paused 状态提示

当前逻辑如果遇到 paused，不要只提示“重新上传文件”。

改为：

```text
导入中断，可选择原 PDF 恢复导入，或重新上传开始新的导入。
```

### 5. 验收标准

- 正常上传流程不受影响。
- 当状态为 paused/failed 时，页面出现恢复按钮。
- 点击恢复按钮后可以选择 PDF。
- 恢复接口请求路径正确：
  `/import/pipelines/{pipeline_id}/resume`
- 恢复成功后继续轮询 pipeline 状态。
- 恢复失败时有明确错误提示。
- 用户取消选择文件时不报错。

------

## 方案 B：如果产品决定不支持恢复，则删除/隐藏后端 resume 能力

如果不打算支持恢复，则需要：

1. 前端文案统一为“请重新上传文件”。
2. 后端 `/resume` 接口标记废弃或移除。
3. 接口文档不要再暴露恢复能力。
4. 页面不要出现“继续查询”“恢复”等暗示性文案。

但不推荐方案 B，因为后端已经有恢复接口。

------

# 任务 5：修复缺失的 check-latex-symbols-sync.js 测试脚本

## 问题描述

测试文件：

```text
tests/test-latex-symbols.js
```

依赖：

```text
scripts/check-latex-symbols-sync.js
```

但当前项目中没有该脚本，导致测试失败：

```text
Cannot find module 'scripts/check-latex-symbols-sync.js'
```

## 修复要求

有两种可选方案。

------

## 方案 A：补回脚本，推荐

新建文件：

```text
scripts/check-latex-symbols-sync.js
```

该脚本应完成：

1. 检查前端 LaTeX 符号配置与题目导入/公式识别模块中的符号映射是否同步。
2. 如果不同步，输出差异并返回非 0 退出码。
3. 如果同步，正常退出 0。
4. 支持被 Node 直接执行，也支持被测试 require 调用。

示例结构：

```js
#!/usr/bin/env node

const fs = require('fs')
const path = require('path')

function loadJson(filePath) {
  if (!fs.existsSync(filePath)) {
    return null
  }

  const raw = fs.readFileSync(filePath, 'utf8')
  return JSON.parse(raw)
}

function checkLatexSymbolsSync() {
  // TODO: 根据项目实际配置路径填写
  // 示例：
  // const frontendPath = path.resolve(__dirname, '../miniprogram/utils/latex-symbols.js')
  // const backendPath = path.resolve(__dirname, '../app/...')

  // 如果项目暂无双端配置，可以先实现基本存在性检查，
  // 但不要让脚本无意义地永远通过。
  return {
    ok: true,
    message: 'LaTeX symbols sync check passed'
  }
}

if (require.main === module) {
  const result = checkLatexSymbolsSync()

  if (!result.ok) {
    console.error(result.message || 'LaTeX symbols are not synchronized')
    process.exit(1)
  }

  console.log(result.message || 'LaTeX symbols sync check passed')
}

module.exports = {
  checkLatexSymbolsSync
}
```

注意：

- 请根据项目现有 LaTeX 符号文件的实际位置补全逻辑。
- 如果已有类似脚本，只是路径不同，则优先修改测试路径，不要重复造脚本。
- 不要为了测试通过写一个永远返回 true 的空脚本，除非项目确实已不需要该检查，并在注释中说明原因。

------

## 方案 B：如果该测试已废弃，则修改测试

如果确认项目已经不需要 LaTeX 符号同步检查，则修改：

```text
tests/test-latex-symbols.js
```

删除对缺失脚本的依赖，或者将其替换为当前真实存在的同步检查逻辑。

验收标准：

```bash
npm test
```

或项目对应测试命令执行后，不再出现：

```text
Cannot find module 'scripts/check-latex-symbols-sync.js'
```

------

# 六、全局回归检查要求

完成以上修复后，请执行以下检查。

## 1. 前端 JS 语法检查

对所有小程序 JS 文件执行：

```bash
find miniprogram -name "*.js" -print0 | xargs -0 -n1 node --check
```

要求：无语法错误。

## 2. 后端 Python 编译检查

在后端根目录执行：

```bash
python -m compileall app
```

要求：无编译错误。

## 3. 测试脚本检查

如果项目有 npm 测试：

```bash
npm test
```

或运行当前已有 tests：

```bash
node tests/test-latex-symbols.js
```

要求：不再因为缺少 `check-latex-symbols-sync.js` 失败。

## 4. 接口字段检查

手动或自动请求错题详情接口，确认响应包含：

```json
{
  "question_type": "single_choice"
}
```

或项目实际题型值。

错题列表接口也建议包含 `question_type`。

## 5. 错题详情页面真机/开发者工具验证

重点验证：

### 判断题

后端返回：

```json
{
  "question_type": "true_false",
  "options": null,
  "answer": "A",
  "wrong_answer": "B"
}
```

前端应显示：

```text
A 正确
B 错误
```

并能正确标出正确答案和用户错答。

### 多选题

后端返回：

```json
{
  "question_type": "multiple_choice",
  "answer": "A,C",
  "wrong_answer": "A,B"
}
```

前端应能正确识别：

- A：正确且用户选择
- C：正确但用户漏选
- B：用户错选
- D：无关选项

不能再把 `"A,C"` 当成一个整体字符串去和单个 key 比较。

## 6. 错题本知识点筛选验证

从 dashboard 点击薄弱知识点进入错题本，或直接访问：

```text
/pages/wrong-book/wrong-book?topic=某知识点
```

要求：

- 页面显示当前知识点筛选。
- 请求参数里带 topic。
- 后端真实按 topic 过滤。
- total 与列表一致。
- 翻页仍保持 topic。
- 清除筛选后恢复全部错题。

## 7. import-batch 点击验证

进入批量导入详情页，验证：

- 点击题目卡片仍能展开/收起。
- 点击“含公式”只打开公式预览，不触发父级展开/收起。
- 点击详情区域不产生异常跳动或报错。
- 微信开发者工具不再出现空 `catchtap` 相关警告。

## 8. import 恢复验证

如果采用方案 A，需要验证：

- 上传中断状态显示恢复入口。
- 点击恢复后可以选择 PDF。
- 请求后端 `/import/pipelines/{pipeline_id}/resume`。
- 恢复成功后继续轮询状态。
- 恢复失败有错误提示。
- 用户取消选择文件不报错。

------

# 七、不要做的事情

请不要做以下操作：

1. 不要大规模重构页面结构。
2. 不要修改无关页面样式。
3. 不要把错题筛选只做在前端当前页。
4. 不要删除已有登录、练习、番茄钟、导入等稳定逻辑。
5. 不要硬编码 localhost、测试 token 或固定用户 ID。
6. 不要为了通过测试写完全无效的假脚本。
7. 不要改变接口已有字段含义。
8. 不要破坏分页、排序和已有筛选条件。
9. 不要引入新的第三方依赖，除非项目已经使用且确有必要。
10. 不要吞掉错误，所有失败状态都要给用户可理解的提示。

------

# 八、最终交付物

修复完成后，请输出：

1. 修改过的文件列表。
2. 每个文件修复了什么问题。
3. 关键代码片段。
4. 自测结果，包括：
   - 前端 JS 语法检查结果
   - 后端 compileall 结果
   - 测试脚本结果
   - 错题详情验证结果
   - 错题本 topic 筛选验证结果
   - import-batch 点击验证结果
   - import 恢复流程验证结果
5. 如果某项未修复，必须说明原因和影响范围。

最终目标：修复后项目不再存在本轮审计指出的残留问题，错题详情展示准确，错题本知识点筛选真实生效，导入相关页面事件绑定规范，暂停恢复逻辑前后端一致，测试脚本不再因缺失文件失败。