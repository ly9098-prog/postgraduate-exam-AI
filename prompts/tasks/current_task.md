# 小程序前端上线前修复任务 Prompt

请对当前微信小程序前端项目进行一次完整的上线前修复。项目源代码位于当前工作区，目标是解决已审计出的正式环境配置、权限、提交幂等、异步状态、隐私合规、请求竞争、导航栈、错误处理和性能问题。

本次任务不是只给出建议，而是需要直接修改代码。修改时应保持现有业务功能、接口字段和主要 UI 风格不变，不随意重构无关模块。

------

# 一、总体目标

完成修复后，项目应达到以下状态：

1. 正式构建不会访问 localhost 或启用开发权限。
2. 普通用户无法进入或调用题库导入功能。
3. 答题提交不会因为本地缓存失败而误报服务器提交失败。
4. Token 过期时，普通请求、上传和下载行为一致。
5. 页面切换、快速筛选、AI 分析和异步请求不会产生旧数据覆盖或永久骨架屏。
6. 不存在绑定未实现事件、空对象调用或明显运行时警告。
7. 登录、隐私协议、退出登录和用户数据处理入口形成基本闭环。
8. 首页导航栈不会重复堆叠。
9. 科目编码在所有页面均能正确显示中文名称。
10. 正式包移除测试资源、重复动画资源和不必要的调试逻辑。

------

# 二、最高优先级：上线阻断项

## 任务 1：重构开发环境和正式环境配置

检查并修改：

```text
config.js
utils/auth.js
app.js
登录页
番茄钟页面
其他引用 DEV、DEBUG_MODE、localhost 的文件
```

当前问题：

```js
const DEV = true
```

开发环境接口使用：

```text
http://localhost:8000/api/v1
```

正式包可能继续启用：

- localhost 接口
- 开发登录
- 管理员权限绕过
- DEV 标记
- 调试日志
- 渲染追踪

### 修复要求

建立统一环境配置，例如：

```js
const ENV = 'production'
```

或使用项目现有构建配置实现：

```js
const CONFIG = {
  development: {
    apiBaseUrl: 'http://localhost:8000/api/v1',
    debug: true
  },
  production: {
    apiBaseUrl: 'https://正式接口域名/api/v1',
    debug: false
  }
}
```

正式环境必须满足：

```js
DEV === false
DEBUG_MODE === false
```

正式环境不得：

- 使用 localhost
- 使用 127.0.0.1
- 暴露开发登录入口
- 默认授予管理员权限
- 展示 DEV 标签
- 输出大量调试日志

增加发布保护：

```js
if (
  env === 'production' &&
  /localhost|127\.0\.0\.1/i.test(apiBaseUrl)
) {
  throw new Error('Production build cannot use localhost')
}
```

管理员判断必须只基于后端返回的真实用户角色，不能因为开发模式自动返回 `true`。

### 验收标准

- 全局搜索 `localhost`，正式运行路径中不存在可执行引用。
- 全局搜索管理员绕过逻辑，正式环境不能命中。
- 正式环境登录页不显示开发入口。
- 正式环境番茄钟不显示 DEV。
- 项目仍可通过显式开发配置连接本地服务。

------

## 任务 2：补齐题库导入页面权限校验

重点检查：

```text
pages/import/import.js
pages/import/import.wxml
utils/auth.js
首页导入入口
```

当前仅在首页使用 `wx:if="{{isAdmin}}"` 隐藏入口，但用户仍可能通过页面路径直接进入。

### 修复要求

在导入页 `onLoad` 或 `onShow` 中执行管理员校验：

```js
onLoad() {
  if (!auth.requireAdminAccess()) {
    wx.showToast({
      title: '无访问权限',
      icon: 'none'
    })

    setTimeout(() => {
      wx.reLaunch({
        url: '/pages/home/home'
      })
    }, 500)

    return
  }

  this.initPage()
}
```

`requireAdminAccess()` 应：

1. 检查当前用户是否登录。
2. 检查用户角色是否为管理员。
3. 不允许依赖前端 DEV 开关绕过。
4. 权限不足时返回 `false`。
5. Token 无效时跳转登录页。

页面中所有初始化、上传恢复、任务查询逻辑必须在权限验证成功后执行。

同时检查所有导入相关接口是否携带鉴权 Token。前端无法保证后端权限，请在代码注释或交付报告中明确列出后端必须校验的接口：

- 上传文件
- 查询导入任务
- 恢复导入任务
- 下载模板
- 提交解析结果
- 题目批量入库

### 验收标准

- 普通用户直接访问 `/pages/import/import` 时会被拦截。
- 页面不会先发接口请求再跳走。
- 管理员可以正常使用全部导入功能。
- Token 失效时不会停留在空白导入页。

------

## 任务 3：修复答题提交“服务器成功但前端提示失败”

重点检查：

```text
pages/practice/practice.js
答题结果页
utils/api.js
```

当前服务器提交、本地缓存和页面跳转处于同一个 `try...catch` 中。

当服务器提交成功后，如果：

```js
wx.setStorageSync('lastPracticeResult', ...)
```

失败，页面仍会提示“提交失败”，用户可能重复提交。

### 修复要求

将流程拆分为三个阶段。

#### 阶段一：服务器提交

```js
const submitResult = await api.post(
  '/practice/batch-submit',
  payload
)
```

只有此步骤失败时，才能提示“提交失败”。

#### 阶段二：本地结果缓存

```js
try {
  wx.setStorageSync(
    'lastPracticeResult',
    minimalResult
  )
} catch (storageError) {
  console.warn(
    '答题已提交成功，但本地结果缓存失败',
    storageError
  )
}
```

本地缓存失败时：

- 不得提示服务器提交失败。
- 不得让用户重复提交。
- 应继续进入结果页。
- 可提示“结果缓存失败，请联网查看记录”，但不得阻断流程。

#### 阶段三：进入结果页

优先使用：

```text
submission_id
practice_record_id
```

结果页通过记录 ID 查询结果。

如果后端暂未支持按 ID 查询，则本地只保存结果页必需的最小数据，例如：

- 总题数
- 正确数
- 错误数
- 得分
- 每题 ID
- 用户答案
- 正确答案
- 是否正确

不要缓存整套题目对象、解析模型和冗余后端数据。

### 幂等要求

提交请求中增加或保留唯一请求标识：

```js
request_id
```

同一次答题过程只能生成一个稳定的 `request_id`，重试时不得重新生成。

前端应避免按钮连点：

```js
if (this.data.submitting) return
```

后端必须使用 `request_id` 做幂等去重。请在交付说明中明确标注该后端要求。

### 计时器要求

当前提交前会停止计时器。若服务器提交失败：

- 恢复页面可操作状态。
- 恢复计时器，或保留已用时并重新启动。
- 不得出现“提交失败后计时器永久停止”。

### 验收标准

验证以下场景：

1. 服务器提交成功，本地缓存成功。
2. 服务器提交成功，本地存储已满。
3. 服务器提交失败。
4. 用户快速连续点击提交。
5. 网络超时后重新提交。
6. 同一 `request_id` 被重复发送。

------

## 任务 4：完善隐私协议和登录状态闭环

重点检查：

```text
pages/login
隐私政策页面
用户协议页面
个人中心或设置页面
app.js
本地存储
```

### 修复要求

不得只保存页面内的：

```js
agreed: false
```

应持久化当前协议版本及同意记录：

```js
{
  privacy_version: '当前版本号',
  accepted_at: Date.now(),
  accepted_items: [
    'user_agreement',
    'privacy_policy',
    'ai_service'
  ]
}
```

登录流程应判断：

```js
storedPrivacyVersion === currentPrivacyVersion
```

若协议版本发生变化，即使用户已有 Token，也必须重新确认协议。

增加统一工具：

```text
utils/privacy.js
```

建议提供：

```js
getCurrentPrivacyVersion()
hasAcceptedCurrentPrivacy()
savePrivacyAcceptance()
clearPrivacyAcceptance()
```

### 设置页或个人中心至少增加

- 退出登录
- 清除本地学习缓存
- 查看用户协议
- 查看隐私政策
- 数据删除或账号注销申请入口
- 联系方式或反馈入口

退出登录时应清除：

- access token
- refresh token
- 用户信息
- 管理员状态
- 与当前用户绑定的敏感缓存
- 当前答题临时状态
- AI 分析用户缓存索引

不要误删无需清除的公共配置。

### 隐私政策内容补充

检查现有文案，至少包含：

1. 运营主体。
2. 联系方式。
3. 收集的信息类型。
4. 收集目的。
5. 使用场景。
6. 保存期限。
7. 数据删除方式。
8. 用户查询、更正和撤回同意方式。
9. AI/OCR 第三方服务说明。
10. 向第三方传输的数据类型。
11. 协议生效日期。
12. 协议版本号。
13. 未成年人使用说明。
14. 账号注销或数据删除申请方式。

同时检查微信公众平台的隐私保护指引是否声明：

- 选择图片
- 选择聊天文件
- 上传文件
- 网络请求
- 可能涉及的设备或用户信息

### 验收标准

- 首次登录必须同意协议。
- 已同意当前版本的用户可直接进入。
- 协议版本升级后必须重新同意。
- 退出登录后无法访问登录态页面。
- 普通用户能够找到隐私政策和数据处理入口。

------

# 三、高优先级运行缺陷

## 任务 5：统一上传、下载与普通请求的 Token 刷新

重点检查：

```text
utils/api.js
utils/auth.js
pages/import/import.js
```

当前普通请求支持 Token 刷新，但：

```js
wx.uploadFile()
wx.downloadFile()
```

直接读取本地 Token，不支持过期刷新和 401 重试。

### 修复要求

新增统一工具，例如：

```text
utils/file-request.js
```

提供：

```js
authUploadFile(options)
authDownloadFile(options)
```

统一流程：

1. 请求前执行 `ensureValidToken()`。
2. 设置最新 Token。
3. 收到 401 时刷新 Token。
4. 刷新成功后自动重试一次。
5. 最多重试一次，防止死循环。
6. 刷新失败时清理登录态并 `reLaunch` 登录页。
7. 返回标准 Promise。
8. 统一错误对象。

示例结构：

```js
async function authUploadFile(
  options,
  retried = false
) {
  const token = await ensureValidToken()

  try {
    return await uploadWithToken(
      options,
      token
    )
  } catch (error) {
    if (
      error.code === 401 &&
      !retried
    ) {
      await refreshAccessToken()

      return authUploadFile(
        options,
        true
      )
    }

    throw error
  }
}
```

增加文件校验：

- 扩展名
- MIME 类型
- 文件大小
- 空文件
- 非法文件名
- 不支持的格式

文件过大时在上传前提示，不要等服务器返回。

### 验收标准

- Token 有效时上传、下载正常。
- Token 过期时自动刷新并重试。
- Refresh Token 失效时跳转登录页。
- 401 不会无限循环。
- 文件过大不会开始上传。
- 上传错误提示能区分权限、网络和文件问题。

------

## 任务 6：修复错题详情 AI 骨架屏永久停留

重点检查：

```text
pages/wrong-detail/wrong-detail.js
pages/wrong-detail/wrong-detail.wxml
```

当前重新生成 AI 分析时会设置：

```js
aiSkeletonVisible: true
```

但部分退出分支只重置：

```js
aiRegenerating: false
```

### 修复要求

建立统一 AI 请求状态清理方法：

```js
_resetAiLoadingState() {
  this.setData({
    aiLoading: false,
    aiRegenerating: false,
    aiSkeletonVisible: false,
    aiInlineNotice: ''
  })
}
```

在以下位置调用：

- 新题加载前
- 切换上一题
- 切换下一题
- 请求成功
- 请求失败
- stale response
- 页面隐藏
- 页面卸载
- 用户主动取消
- AI Token 失效

为每次 AI 请求生成递增序号：

```js
const requestId =
  ++this._aiRequestId
```

结果返回时检查：

```js
if (
  requestId !== this._aiRequestId ||
  !this._alive
) {
  return
}
```

`onUnload` 中：

```js
this._alive = false
this._aiRequestId++
clearTimeout(this._switchMaskTimer)
```

### 验收标准

测试：

1. 生成过程中切换下一题。
2. 连续快速切换 5 次。
3. 生成过程中返回上一页。
4. 请求失败。
5. 缓存命中。
6. 重新生成成功。
7. 旧请求后返回。

任何场景都不能永久显示骨架屏，也不能用上一题结果覆盖当前题。

------

## 任务 7：修复错题详情渲染检查逻辑

当前构造的是：

```js
data.currentQuestion._renderModel
```

但检查使用：

```js
data._renderModel
```

同时 `renderTraces` 未保证已初始化。

### 修复要求

在页面 `data` 中增加：

```js
renderTraces: []
```

修正读取：

```js
const renderModel =
  data.currentQuestion?._renderModel

if (renderModel) {
  this._checkRenderInvariant(
    renderModel
  )

  this._recordRenderTrace(
    renderModel.renderTrace
  )
}
```

记录方法必须兼容空值：

```js
_recordRenderTrace(trace) {
  if (!trace) return

  const traces = Array.isArray(
    this.data.renderTraces
  )
    ? this.data.renderTraces
    : []

  this.setData({
    renderTraces: traces
      .concat(trace)
      .slice(-20)
  })
}
```

正式环境中关闭或限制追踪：

```js
if (!config.debug) return
```

### 验收标准

- 初次进入错题详情不报错。
- `_renderModel` 存在时能执行检查。
- `_renderModel` 不存在时不会报错。
- 正式环境不会长期积累调试追踪数据。

------

## 任务 8：补充缺失的 noop 方法

检查：

```text
components/submit-confirm/submit-confirm.wxml
components/submit-confirm/submit-confirm.js
pages/pomodoro/pomodoro.wxml
pages/pomodoro/pomodoro.js
```

存在：

```xml
catchtap="noop"
```

但 JS 中没有对应方法。

### 修复要求

在对应组件或页面中增加：

```js
noop() {}
```

若同一页面中多处只为阻止冒泡，可以统一使用该方法。

同时全项目搜索：

```text
bindtap=
catchtap=
bindchange=
bindinput=
bindconfirm=
bindsubmit=
```

检查所有事件名称是否在对应页面或组件中实现。

### 验收标准

- 点击弹窗内部不关闭弹窗。
- 控制台不再出现不存在事件处理函数的警告。
- 所有 WXML 事件引用均能在 JS 中找到。

------

## 任务 9：修复 Dashboard 隐藏后的异步更新

重点检查：

```text
pages/dashboard/dashboard.js
```

### 修复要求

区分页面存活状态和可见状态：

```js
onLoad() {
  this._alive = true
  this._visible = false
  this._loadSeq = 0
}

onShow() {
  this._visible = true
  this.loadDashboard()
}

onHide() {
  this._visible = false
  this._loadSeq++
  this._clearChartTimers()
}

onUnload() {
  this._alive = false
  this._visible = false
  this._loadSeq++
  this._clearChartTimers()
}
```

发起请求：

```js
const seq = ++this._loadSeq
```

请求返回：

```js
if (
  !this._alive ||
  !this._visible ||
  seq !== this._loadSeq
) {
  return
}
```

所有延迟绘图、Canvas 绘制和动画回调都必须检查页面是否仍可见。

### 验收标准

- Dashboard 请求未完成时切换页面，不会继续绘图。
- 返回 Dashboard 后加载的是最新数据。
- 旧请求不会覆盖新请求。
- 不存在隐藏页面反复创建计时器。

------

## 任务 10：修复错题筛选请求竞争

重点检查：

```text
pages/wrong-book/wrong-book.js
```

### 修复要求

为列表请求增加序号：

```js
const seq =
  ++this._listRequestSeq
```

请求返回前检查：

```js
if (
  seq !== this._listRequestSeq ||
  !this._alive
) {
  return
}
```

筛选条件变化时：

- 清空旧列表。
- 重置页码。
- 设置当前筛选。
- 递增请求序号。
- 取消旧加载状态。
- 发起新请求。

分页加载增加锁：

```js
if (
  this.data.loading ||
  this.data.loadingMore ||
  !this.data.hasMore
) {
  return
}
```

分页请求返回时还要确认：

- 当前筛选条件未变化。
- 页码仍匹配。
- 请求序号仍有效。

### 验收标准

快速点击：

```text
高数 → 线代 → 计算机 → 政治
```

最终列表必须与当前选中的“政治”一致，不能被早期请求覆盖。

连续触底不得重复追加同一页。

------

## 任务 11：统一首页跳转方式，避免导航栈重复

检查所有跳转首页的代码：

```text
wx.navigateTo('/pages/home/home')
wx.redirectTo('/pages/home/home')
```

### 修复要求

首页作为根页面时统一使用：

```js
wx.reLaunch({
  url: '/pages/home/home'
})
```

登录页作为身份失效后的根页面，也使用：

```js
wx.reLaunch({
  url: '/pages/login/login'
})
```

普通详情页之间可以保留：

- `navigateTo`
- `navigateBack`
- `redirectTo`

但不得通过 `navigateTo` 再打开一个首页。

对答题结果页、今日复习页、错题详情页和番茄钟完成页重点排查。

### 验收标准

连续执行以下流程 20 次：

```text
首页
→ 练习
→ 提交
→ 返回首页
→ 今日复习
→ 返回首页
```

页面栈不持续增长，返回键行为正常。

------

## 任务 12：统一科目编码和展示名称

当前不同页面分别维护科目映射，部分新编码会直接显示内部值。

### 修复要求

新增：

```text
utils/subject-meta.js
```

统一定义：

```js
const SUBJECT_META = {
  advanced_math: {
    name: '高等数学',
    shortName: '高数',
    icon: '...',
    aliases: [
      'math',
      'higher_math'
    ]
  },
  linear_algebra: {
    name: '线性代数',
    shortName: '线代',
    icon: '...'
  },
  computer: {
    name: '计算机基础',
    shortName: '计算机',
    icon: '...'
  },
  data_structure: {
    name: '数据结构',
    shortName: '数据结构',
    icon: '...'
  },
  operating_system: {
    name: '操作系统',
    shortName: '操作系统',
    icon: '...'
  },
  politics: {
    name: '政治',
    shortName: '政治',
    icon: '...'
  }
}
```

提供：

```js
getSubjectName(code)
getSubjectShortName(code)
getSubjectIcon(code)
normalizeSubjectCode(code)
```

修改以下页面，全部从统一模块读取：

- Dashboard
- 错题本
- 错题详情
- 今日复习
- 练习页
- 结果页
- 番茄钟
- 其他显示科目的页面

未知编码使用：

```js
'其他科目'
```

或经过安全格式化的编码，不要直接显示原始后端内部字段。

### 验收标准

以下编码均能显示正确中文名称：

```text
advanced_math
linear_algebra
computer
data_structure
operating_system
politics
```

------

## 任务 13：统一 API 错误对象

重点检查：

```text
utils/api.js
Dashboard
错题页面
登录页面
导入页面
```

当前部分代码抛普通对象，部分页面读取：

```js
e.errMsg
```

其他地方读取：

```js
e.message
e.code
e.detail
```

### 修复要求

新增统一错误类或创建方法：

```js
class ApiError extends Error {
  constructor(
    message,
    options = {}
  ) {
    super(message)

    this.name = 'ApiError'
    this.code = options.code
    this.statusCode =
      options.statusCode
    this.detail = options.detail
    this.raw = options.raw
  }
}
```

所有网络错误统一转换为：

```js
throw new ApiError(message, {
  code,
  statusCode,
  detail,
  raw
})
```

页面统一读取：

```js
error.code
error.message
error.detail
```

修复 Dashboard 中类似：

```js
e.errMsg.includes(
  'LLM_NOT_CONFIGURED'
)
```

改为：

```js
error.code ===
  'LLM_NOT_CONFIGURED'
```

或：

```js
error.detail ===
  'LLM_NOT_CONFIGURED'
```

### Toast 责任划分

建议：

- 网络层只标准化错误，不直接弹 Toast。
- 页面层决定是否提示用户。
- 401 刷新失败属于全局登录跳转，可由网络层处理。
- 同一个错误不得连续弹两次。

### 验收标准

验证：

- 网络断开
- 401
- 403
- 404
- 500
- 超时
- 后端业务错误
- AI 未配置
- 上传失败

错误对象格式一致，页面不会因读取不存在字段而报错。

------

# 四、性能与包体优化

## 任务 14：动画分包改为真正按需加载

重点检查：

```text
app.js
动画分包
奖励动画调用位置
```

当前在 `onLaunch` 中立即加载动画分包，削弱分包价值。

### 修复要求

删除启动时主动加载逻辑：

```js
tryLoadAnimSubpkg()
```

在第一次需要播放奖励动画时加载：

```js
await loadRewardAnimationPackage()
```

加载期间使用轻量 CSS 动画或静态图兜底。

禁止使用：

```text
启动时 navigateTo 隐藏页面
setTimeout
navigateBack
```

来强制加载分包。

建立加载状态：

```js
let rewardPackagePromise = null
```

避免并发重复加载：

```js
function loadRewardPackage() {
  if (rewardPackagePromise) {
    return rewardPackagePromise
  }

  rewardPackagePromise =
    wx.loadSubpackage({
      name: 'reward-animation'
    })

  return rewardPackagePromise
}
```

根据项目基础库版本，正确封装 Promise。

### 验收标准

- 冷启动不下载动画分包。
- 第一次播放动画时才加载。
- 加载失败不会影响主流程。
- 不会出现隐藏页面闪烁或导航栈变化。

------

## 任务 15：删除重复和未引用动画资源

检查动画分包中的：

```text
*.js
*.json
```

当前动画通过 JS 模块加载，但同时保留未引用 JSON 文件。

### 修复要求

全局搜索引用关系，只保留真实使用的一份资源。

如果运行时使用：

```js
require('./xxx.js')
```

且 JSON 没有任何引用，则删除重复 JSON。

如果决定统一使用 JSON，则：

- 修改加载逻辑。
- 删除重复 JS 数据文件。
- 确保小程序运行时支持。
- 保证动画效果一致。

不要同时维护两份内容相同的数据。

### 验收标准

- 动画仍可正常播放。
- 动画分包体积明显下降。
- 不存在未引用重复文件。
- 构建不报资源缺失。

------

## 任务 16：处理 KaTeX 外部字体依赖

重点检查：

```text
components/mp-html/latex/katex.css
```

### 修复要求

评估当前使用的所有 KaTeX 字体。

优先方案：

1. 将常用字体部署到自有 HTTPS CDN。
2. 使用 `woff2`。
3. 移除未使用字体。
4. 设置合理的字体降级。
5. 确认域名已加入小程序合法域名。

不得依赖不可控的公共 CDN 作为唯一公式字体来源。

如果当前阶段无法迁移自有 CDN，则至少：

- 增加降级字体。
- 记录加载失败。
- 保证字体失败后公式仍可读。
- 在交付报告中列出待配置 CDN 域名。

### 验收标准

- 正常网络下公式显示正确。
- 弱网下不会长期空白。
- 字体请求失败后公式仍可阅读。
- 不出现大量无用字体请求。

------

## 任务 17：正式包移除测试和调试资源

检查：

```text
__mocks__
测试 fixture
本地调试文件
未引用资源
project.config.json
```

### 修复要求

在构建忽略配置中排除：

- `__mocks__`
- 测试数据
- 测试脚本
- Markdown 文档
- 设计稿
- 调试截图
- 本地开发说明
- 未引用动画资源
- 临时文件
- 日志文件

示例：

```json
{
  "packOptions": {
    "ignore": [
      {
        "type": "folder",
        "value": "__mocks__"
      },
      {
        "type": "suffix",
        "value": ".md"
      }
    ]
  }
}
```

具体格式应遵循当前微信开发者工具配置规范。

### 验收标准

- 正式预览包不包含 `__mocks__`。
- 不包含 localhost 测试 fixture。
- 不影响本地开发和测试。
- 包体积有所下降。

------

## 任务 18：优化 sitemap

当前：

```json
{
  "action": "allow",
  "page": "*"
}
```

### 修复要求

禁止搜索索引以下页面：

- 登录页
- 管理员导入页
- 用户协议页
- 隐私政策页
- 错题详情
- 答题结果
- 需要业务上下文才能打开的页面
- 个人用户数据页面

仅允许适合搜索打开的公共页面。

若当前小程序不存在适合被微信搜索打开的公共页面，可整体设置为禁止索引。

### 验收标准

- 管理员页面不可被搜索打开。
- 带用户数据的页面不可被搜索索引。
- sitemap 配置合法。

------

# 五、代码可维护性优化

## 任务 19：拆分番茄钟超大页面逻辑

重点检查：

```text
pages/pomodoro/pomodoro.js
```

当前单文件同时负责：

- 普通计时
- 自由计时
- 暂停恢复
- 后台恢复
- 本地持久化
- 服务端同步
- 确认弹窗
- 休息计时
- 动画
- 订阅消息

### 修复要求

在不改变现有 UI 和业务行为的前提下，将纯逻辑拆分为：

```text
services/pomodoro-session.js
services/pomodoro-persistence.js
services/pomodoro-sync.js
services/pomodoro-notification.js
utils/pomodoro-state.js
```

建议职责：

### `pomodoro-session.js`

- 状态机
- 开始
- 暂停
- 恢复
- 结束
- 休息阶段
- 时间计算

### `pomodoro-persistence.js`

- 本地保存
- 恢复
- 数据版本
- 异常数据清理

### `pomodoro-sync.js`

- 服务端同步
- 幂等
- 失败重试
- 离线状态

### `pomodoro-notification.js`

- 订阅消息
- 授权检查
- 通知参数

页面只保留：

- 页面生命周期
- 用户事件
- `setData`
- UI 状态映射

### 验收标准

- 原功能全部保留。
- 页面 JS 体积明显下降。
- 后台恢复、暂停、自由计时和普通计时行为不变。
- 拆分模块没有循环依赖。

------

# 六、全局质量检查

完成上述修复后，进行一次全局静态检查。

## 1. 检查事件绑定

扫描所有 WXML：

```text
bindtap
catchtap
bindinput
bindchange
bindconfirm
bindsubmit
bindload
binderror
```

确认对应 JS 方法存在。

## 2. 检查页面路径

确认：

- `app.json` 页面均存在。
- 分包页面均存在。
- 自定义组件路径均存在。
- 跳转路径均已注册。

## 3. 检查生命周期清理

所有使用以下能力的页面：

```text
setTimeout
setInterval
Canvas
网络请求序号
自定义请求 Token
动画实例
音频实例
```

必须在 `onHide` 或 `onUnload` 中正确清理。

## 4. 检查异步结果保护

所有可能并发的请求增加：

- 页面存活检查
- 页面可见检查
- 请求序号检查
- 当前筛选条件检查

重点页面：

- Dashboard
- 错题本
- 错题详情
- 今日复习
- 导入页
- 练习页
- 番茄钟

## 5. 检查本地缓存

所有缓存必须考虑：

- 用户隔离
- 版本号
- 过期时间
- 数据大小
- 写入失败
- 退出登录清理

AI 分析缓存必须以用户 ID、题目 ID 和分析版本作为组合键，避免用户间或题目版本间误复用。

------

# 七、必须执行的回归测试

修复后至少完成以下测试，并在交付报告中逐条写明结果。

## 登录与权限

1. 新用户首次登录。
2. 未勾选协议登录。
3. 已同意当前协议登录。
4. 协议版本升级。
5. Token 过期。
6. Refresh Token 过期。
7. 普通用户直接进入导入页。
8. 管理员进入导入页。
9. 退出登录后访问业务页面。

## 答题

1. 正常提交。
2. 连续点击提交。
3. 断网提交。
4. 超时后重试。
5. 本地存储已满。
6. 服务器成功、本地缓存失败。
7. 重复 `request_id`。
8. 提交失败后计时器恢复。
9. 提交成功后结果页正常展示。

## 错题本和 AI

1. 快速切换学科。
2. 快速切换错题。
3. AI 分析过程中切题。
4. AI 分析过程中返回。
5. AI 请求失败。
6. AI 缓存命中。
7. AI 重新生成。
8. 旧请求晚于新请求返回。
9. 骨架屏正常消失。

## Dashboard

1. 加载过程中离开页面。
2. 快速进入和离开。
3. 返回页面后刷新。
4. 旧请求晚返回。
5. Canvas 延迟绘制。
6. 无数据状态。
7. AI 服务未配置状态。

## 导入

1. 正常上传。
2. Token 过期上传。
3. 文件过大。
4. 文件类型不支持。
5. 网络断开。
6. 恢复导入任务。
7. 下载模板。
8. 普通用户调用导入接口。

## 番茄钟

1. 普通计时。
2. 自由计时。
3. 暂停恢复。
4. 切后台。
5. 杀进程后恢复。
6. 完成同步。
7. 同步失败。
8. 休息计时。
9. 订阅消息拒绝。
10. 弹窗内部点击不报 `noop` 错误。

## 导航栈

连续执行 20 次：

```text
首页
→ 练习
→ 结果页
→ 首页
→ 今日复习
→ 首页
```

确认：

- 页面栈不持续增长。
- 不出现重复首页。
- 返回键逻辑正常。

------

# 八、实施约束

1. 不修改后端接口路径和字段，除非当前修复确实需要新增 `request_id` 或结果记录 ID。
2. 若必须调整接口字段，请在交付报告中单独列出。
3. 不改变现有主要 UI 风格。
4. 不删除现有业务功能。
5. 不使用前端隐藏按钮替代权限校验。
6. 不使用大量 `try...catch` 吞掉错误。
7. 不通过延迟跳转掩盖状态问题。
8. 不允许旧异步请求覆盖新状态。
9. 不将完整题目列表长期保存到本地。
10. 不在正式环境输出敏感数据、Token、用户答案或后端原始响应。
11. 所有新增工具函数需有明确命名和注释。
12. 保持兼容当前微信小程序基础库版本。

------

# 九、交付要求

完成修改后，请输出以下内容。

## 1. 修改文件清单

格式：

```text
文件路径
- 修改内容
- 修复的问题
```

## 2. 问题修复对照表

格式：

| 编号 | 问题                 | 修改位置  | 修复结果 |
| ---- | -------------------- | --------- | -------- |
| 1    | 正式包使用 localhost | config.js | 已修复   |

## 3. 后端仍需配合的事项

必须明确列出：

- 管理员接口服务端鉴权
- 答题提交 `request_id` 幂等
- 结果记录按 ID 查询
- 用户数据删除或账号注销接口
- AI/OCR 第三方数据说明
- 正式 HTTPS 接口地址
- 自有 KaTeX 字体 CDN 地址

## 4. 测试结果

逐条列出回归测试结果，不得只写“已测试”。

## 5. 未解决问题

如有无法只通过前端完成的问题，必须说明：

- 原因
- 影响
- 需要谁配合
- 推荐处理方式

------

# 十、完成标准

只有同时满足以下条件，任务才算完成：

- 不存在正式环境 localhost。
- 不存在管理员权限绕过。
- 普通用户无法进入导入页。
- 提交成功不会因缓存失败而误报失败。
- 上传下载支持 Token 刷新。
- AI 骨架屏不会永久停留。
- 快速筛选不会出现旧数据覆盖。
- Dashboard 隐藏后不会继续绘图。
- 不存在缺失的 WXML 事件函数。
- 首页不会重复堆叠。
- 科目名称统一显示。
- API 错误对象格式统一。
- 动画分包按需加载。
- 正式包不包含测试和重复资源。
- 隐私协议具备版本化同意记录。
- 已提供完整修改清单和测试报告。
