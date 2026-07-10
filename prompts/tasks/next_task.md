# 再次审计结论

**当前版本比上一版明显改善，但仍不建议直接提交正式上线。**

本次静态审计结果：

- JS 文件语法检查全部通过；
- JSON 文件全部可正常解析；
- 页面、分包页面和组件引用未发现缺失；
- 正式 API 已使用 HTTPS；
- 上次提出的多项问题已修复；
- 仍有 **6 项上线前高优先级问题**，以及若干中优先级问题。

综合判定仍为：**有条件不通过**。

------

## 一、已经修复的问题

### 1. 启动前调用 `wx.login()` 已删除

上一版 `app.js` 会在用户同意协议前预热微信登录。当前版本已经删除 `_preWarmSession()`，不再在启动阶段主动执行 `wx.login()`。

**状态：已修复。**

------

### 2. 动画分包失败后可以重试

`app.js:15-38` 中，分包加载失败时已经增加：

```javascript
_animLoadPromise = null
```

不会再永久缓存一次失败的 Promise。

**状态：已修复，但加载动画组件本身仍有问题，见后文。**

------

### 3. KaTeX 基础集成已经补齐

当前版本已完成：

- `components/mp-html/index.wxss:1` 引入 `katex.css`；
- `components/mp-html/node/node.wxml:85-101` 增加 `n.l` 条件；
- 多处 `mp-html` 增加 `set-title="{{false}}"` 和 `copy-link="{{false}}"`。

数学公式不能渲染的核心集成问题已经修复。

**状态：基本修复，但字体 CDN 仍有风险。**

------

### 4. 导入任务初始字段已经补全

`pages/import/import.js:240-251` 已初始化：

```javascript
stageList: [],
failed_chunk_details: [],
progressPercent: 0
```

WXML 直接访问 `.length` 的风险已经解除。

**状态：已修复。**

------

### 5. Token 过期时间处理有所改进

`utils/api.js:34-55` 新增时间标准化，支持：

- Unix 秒；
- Unix 毫秒；
- 数字字符串；
- ISO 日期字符串。

主动刷新阈值也从 24 小时调整为 1 小时。

**状态：已改善。**

------

### 6. AI 结果增加了提示信息

Dashboard 和错题本新增了：

> 内容由 AI 生成，仅供学习参考，可能存在错误

相关页面也增加了“结果有误”入口。

**状态：提示已补充，但反馈按钮目前并未真正提交反馈。**

------

# 二、上线前仍需处理的高优先级问题

## 1. 隐私政策和账号注销仍未完成闭环

### 涉及位置

- `pages/agreement/privacy.wxml:12-28`
- `pages/agreement/user.wxml:10-28`
- `pages/agreement/ai.wxml:10-24`
- `pages/home/home.js:326-332`

当前隐私政策仍然只有 5 条概括性说明，例如：

```text
本小程序可能收集微信登录标识、学习记录、错题记录……
```

仍缺少至少以下内容：

- 运营者主体名称和联系方式；
- 各类数据的具体收集目的、方式和范围；
- 登录标识、学习记录、图片、文件、AI 输入分别如何处理；
- 第三方 AI/OCR 服务商及其接收的数据类型；
- 信息保存期限；
- 用户查询、更正、删除、复制数据的具体路径；
- 撤回同意后的处理方式；
- 账号注销后的数据删除规则；
- 未成年人信息处理说明；
- 隐私政策生效日期、更新时间和版本号。

目前注销仍然只有：

```javascript
content: '如需反馈问题或申请账号注销，请发送邮件至：support@xzshub.top'
```

前端没有真正的：

- 账号注销入口；
- 注销二次确认；
- 身份验证；
- 注销请求 API；
- 注销状态查询；
- 注销完成通知。

`utils/privacy.js` 增加了协议版本管理，这是好的，但它只能解决“协议是否重新同意”，无法代替完整隐私政策和账号注销流程。

### 建议

设置页增加“注销账号”，调用类似：

```text
POST /users/me/deletion-request
```

或：

```text
DELETE /users/me
```

注销前明确说明将删除哪些数据、哪些数据依法需要保留，以及是否存在冷静期。

**优先级：P0，上线阻断项。**

------

## 2. 首次登录凭证仍然使用非严格写入

### 涉及位置

- `utils/auth.js:27-36`
- `utils/auth.js:110-115`
- `utils/storage.js:16-21`

首次微信登录仍然使用：

```javascript
storage.set(KEYS.TOKEN, data.access_token)
storage.set(KEYS.TOKEN_EXPIRES_AT, ...)
storage.set(KEYS.REFRESH_TOKEN, data.refresh_token)
storage.set(KEYS.USER, user)
```

而 `storage.set()` 会吞掉写入异常：

```javascript
function set(key, value) {
  try {
    wx.setStorageSync(key, value)
  } catch (e) {
    console.error('Storage set error:', e)
  }
}
```

因此可能出现：

1. 后端登录成功；
2. Token 因本地存储异常没有写入；
3. `wechatLogin()` 仍然返回成功；
4. 页面进入首页；
5. 随后的接口全部提示未登录。

Refresh Token 流程已经使用 `setStrict()`，首次登录却没有使用，两处行为不一致。

### 建议

首次登录和 `loginDirect()` 都改成严格、可回滚写入：

```javascript
function saveAuthSession(data, user) {
  try {
    storage.setStrict(KEYS.TOKEN, data.access_token)
    storage.setStrict(
      KEYS.TOKEN_EXPIRES_AT,
      api.normalizeExpiresAt(data.expires_at)
    )
    storage.setStrict(KEYS.REFRESH_TOKEN, data.refresh_token)
    storage.setStrict(KEYS.USER, user)
  } catch (error) {
    storage.remove(KEYS.TOKEN)
    storage.remove(KEYS.TOKEN_EXPIRES_AT)
    storage.remove(KEYS.REFRESH_TOKEN)
    storage.remove(KEYS.USER)
    throw new Error('登录信息保存失败，请清理存储空间后重试')
  }
}
```

协议同意记录 `privacy.savePrivacyAcceptance()` 也建议使用严格写入。

**优先级：P0，上线阻断项。**

------

## 3. Token 失效后的清理仍不完整，存在跨账号数据残留

### 涉及位置

- `utils/api.js:145-153`
- `utils/auth.js:39-76`

手动退出调用 `auth.logout()` 时，会清除部分业务缓存。

但 Token 刷新失败或接口返回 401 时，调用的是：

```javascript
function _clearAuthAndRedirect() {
  storage.remove(KEYS.TOKEN)
  storage.remove(KEYS.TOKEN_EXPIRES_AT)
  storage.remove(KEYS.REFRESH_TOKEN)
  storage.remove(KEYS.USER)
  wx.reLaunch({ url: '/pages/login/login' })
}
```

它不会清除：

- `lastPracticeResult`
- `wrong_detail_nav`
- 番茄钟运行状态；
- 今日目标；
- AI 诊断本地缓存；
- 调试快照；
- 其他业务缓存。

因此可能出现：

1. A 用户 Token 过期；
2. 只清除身份信息；
3. B 用户重新登录；
4. B 用户读取到 A 用户的部分本地结果或页面导航数据。

特别是 `utils/ai-diagnosis-cache.js` 使用了独立缓存键，但目前 `auth.logout()` 的固定业务键列表也没有明确清理所有 AI 缓存。

### 建议

抽取唯一的会话清理方法，例如：

```javascript
clearSession({
  clearBusinessCache: true,
  preservePrivacyAcceptance: true,
  reason: 'token_expired'
})
```

以下路径全部调用同一个方法：

- 手动退出；
- Refresh Token 失效；
- 401；
- 切换账号；
- 账号注销。

业务缓存最好使用用户 ID 命名空间，例如：

```text
user:123:lastPracticeResult
user:123:aiDiagnosis
```

**优先级：P0，上线阻断项。**

------

## 4. 退出登录没有撤销服务端 Refresh Token

### 涉及位置

- `utils/auth.js:39-76`
- `pages/home/home.js:335-343`

当前退出只是删除本地 Token：

```javascript
auth.logout()
wx.reLaunch({ url: '/pages/login/login' })
```

没有发现：

```text
POST /auth/logout
```

也没有设备会话撤销逻辑。

如果 Refresh Token 曾被复制、泄漏或保存在其他环境，仅删除本地数据不能让服务端 Token 立即失效。

### 建议流程

```javascript
async function logout() {
  try {
    await api.post('/auth/logout', {
      refresh_token: storage.get(KEYS.REFRESH_TOKEN),
    })
  } finally {
    clearSession(...)
  }
}
```

后端应做到：

- 撤销当前 Refresh Token；
- 支持 Refresh Token 轮换；
- 支持退出当前设备；
- 必要时支持退出全部设备。

**优先级：P0，上线阻断项，需要后端配合。**

------

## 5. `loading-lottie` 仍未真正触发动画分包加载

### 涉及位置

- `components/loading-lottie/loading-lottie.js:3-6`
- `components/loading-lottie/loading-lottie.js:116-131`
- `app.js:15-38`

`AnimatedView` 会调用：

```javascript
getApp().loadRewardAnimationPackage()
```

但 `loading-lottie` 仍然直接执行：

```javascript
require('../../subpackages/animation/lottie-loader.js')
```

它没有调用 `loadRewardAnimationPackage()`。

在冷启动且动画分包尚未加载时：

1. `require` 失败；
2. 组件进入 fallback；
3. 2 秒后再次 `require`；
4. 但期间没有任何代码真正请求下载分包；
5. 第二次大概率仍然失败。

该组件使用范围较广，包括：

- 错题详情；
- 错题本；
- 今日复习；
- 练习提交；
- 导入恢复；
- 番茄钟统计。

因此加载动画可能长期只显示降级样式，而不是 Lottie。

### 建议

`attached` 中显式加载分包：

```javascript
attached: function () {
  this._initState()

  var app = getApp()
  if (app && app.loadRewardAnimationPackage) {
    app.loadRewardAnimationPackage()
      .then(() => {
        this._detectSupport()
        this._start()
      })
      .catch(() => this._fallback())
  } else {
    this._detectSupport()
    this._start()
  }
}
```

同时避免 `_start()` 在分包请求完成前立即执行一次。

**优先级：P1，核心功能体验问题。**

------

## 6. 发布配置仍然是开发检查关闭状态

### 涉及位置

- `project.config.json:20-21`
- `project.config.json:29`
- `project.config.json:53`
- `project.private.config.json:2`

当前配置：

```json
"urlCheck": false,
"scopeDataCheck": false,
"autoAudits": false
```

同时存在版本不一致：

```json
// project.config.json
"libVersion": "3.3.4"

// project.private.config.json
"libVersion": "3.6.6"
```

这会导致不同开发人员、上传环境或 CI 使用不同基础库。

同时关闭 URL 检查，会让本地开发时无法提前发现：

- request 合法域名遗漏；
- uploadFile 合法域名遗漏；
- downloadFile 合法域名遗漏；
- KaTeX 字体 CDN 域名遗漏；
- 图片域名遗漏。

### 建议发布前设置

```json
"urlCheck": true,
"scopeDataCheck": true,
"autoAudits": true
```

并统一基础库版本。

正式上传前至少执行：

- 微信开发者工具代码质量审计；
- 真机预览；
- 最低支持基础库测试；
- Android 和 iOS 测试；
- 关闭调试模式后的正式包测试。

**优先级：P1，提审前必须处理。**

------

# 三、中优先级问题

## 1. “结果有误”按钮实际没有提交任何反馈

### 涉及位置

- `pages/dashboard/dashboard.js:571-577`
- `pages/wrong-book/wrong-book.js:519-525`

当前逻辑只显示菜单和 Toast：

```javascript
success: function (res) {
  wx.showToast({
    title: '感谢反馈，我们将持续优化',
    icon: 'none',
  })
}
```

没有：

- API 请求；
- 本地持久化；
- 题目 ID；
- AI 结果 ID；
- 用户选择的错误类型；
- 模型版本；
- 反馈时间。

这会让用户认为反馈已经提交，但后台实际上收不到任何内容。

### 建议

调用类似：

```text
POST /ai/feedback
```

请求内容至少包括：

```javascript
{
  source: 'dashboard',
  result_id: llmAnalysis.id,
  feedback_type: selectedType,
  generated_at: llmAnalysisGeneratedAt
}
```

接口成功后才能显示“反馈已提交”；失败时提示重新提交。

**优先级：P1。**

------

## 2. Refresh Token 可能被覆盖成空值

### 涉及位置

```
utils/api.js:126-133
```

当前刷新成功后直接执行：

```javascript
storage.setStrict(KEYS.REFRESH_TOKEN, res.data.refresh_token)
```

如果后端刷新接口只返回新的 Access Token，不返回新的 Refresh Token，当前代码会把原有 Refresh Token 覆盖为空值。

下一次刷新时就会被强制退出。

### 建议

```javascript
const nextRefreshToken =
  res.data.refresh_token || refreshToken

storage.setStrict(KEYS.REFRESH_TOKEN, nextRefreshToken)
```

同时明确后端接口契约：是否每次都轮换 Refresh Token。

------

## 3. `ensureValidToken()` 返回失败后，请求仍可能继续发送

### 涉及位置

```
utils/api.js:218-221
```

当前代码：

```javascript
if (!_skipProactiveRefresh(url)) {
  await ensureValidToken()
}
```

但 `ensureValidToken()` 在两次刷新失败后会返回 `false`，而不是一定抛出异常。

`request()` 没有判断返回值，随后仍会构造 Header 并发送请求。此时本地 Token 可能已经被清理，导致一次多余的未认证请求。

### 建议

```javascript
if (!_skipProactiveRefresh(url)) {
  const valid = await ensureValidToken()
  if (!valid && storage.get(KEYS.TOKEN)) {
    throw new ApiError('登录已过期，请重新登录', {
      code: 'AUTH_REQUIRED',
      statusCode: 401,
    })
  }
}
```

更简单的方式是让 `ensureValidToken()` 失败时统一抛出 `ApiError`，不要同时存在“返回 false”和“抛异常”两套失败语义。

------

## 4. KaTeX 已修复，但新增了外部字体 CDN 依赖

### 涉及位置

```
components/mp-html/latex/katex.css:1-118
```

当前所有 KaTeX 字体来自：

```text
https://cdn.bootcdn.net/...
```

这会带来：

- CDN 故障时公式字体异常；
- 首次公式页面需要加载大量字体；
- 域名未配置时无法加载；
- 第三方资源访问需要纳入隐私和第三方服务核对；
- 不同网络环境下字体加载速度不稳定。

### 建议

优先将实际使用的 `.woff2` 字体：

- 放到自有静态资源域名；
- 或根据公式实际需求裁剪字体种类；
- 配置长期缓存；
- 真机验证弱网和 CDN 不可用时的降级效果。

目前 CSS 定义了大量字体，每个字体又提供 woff2、woff、ttf 三种 URL，实际可能产生较多网络请求。

------

## 5. `package.json` 与 `package-lock.json` 不一致

### 涉及位置

`package.json`：

```json
{
  "name": "MemoGrad-miniprogram",
  "dependencies": {}
}
```

`package-lock.json`：

```json
{
  "name": "2240ai-miniprogram",
  "dependencies": {
    "lottie-miniprogram": "^1.0.12"
  }
}
```

同时项目配置中：

```json
"nodeModules": true,
"packNpmManually": true
```

这会导致：

- 执行 `npm install` 后依赖结果不可预测；
- 构建 npm 时可能与当前 vendor 文件不一致；
- 项目名称和锁文件来源不一致；
- 新环境不能可靠复现当前构建。

### 建议

选择一种方式：

**方式一：使用 npm 包**

在 `package.json` 中恢复：

```json
"dependencies": {
  "lottie-miniprogram": "1.0.12"
}
```

重新生成锁文件并执行“构建 npm”。

**方式二：完全使用已复制的 vendor 文件**

删除无效依赖锁文件，并关闭不需要的 npm 构建配置。

------

## 6. 文件校验仍然只检查扩展名和大小

### 涉及位置

- `utils/file-request.js:19-36`
- `utils/file-request.js:48-74`
- `pages/import/import.js:6-7`

虽然定义了：

```javascript
SUPPORTED_MIME_TYPES
```

但 `validateFile()` 完全没有使用它，只检查：

- 文件扩展名；
- 文件大小。

另外两处格式列表仍不一致：

```javascript
// import.js
['xlsx', 'xls', 'pdf', 'txt', 'jpg', 'jpeg', 'png', 'webp']

// file-request.js
包含 csv 和 gif
```

需要统一配置源。

前端无法可靠验证文件真实性，因此后端仍必须验证：

- 文件魔数；
- MIME 类型；
- Office/ZIP 解压后的体积；
- PDF 页数；
- 图片像素；
- Excel 单元格数量；
- 病毒或恶意文件；
- 文件归属和管理员权限；
- pipeline ID 是否属于当前用户。

该项无法仅通过前端代码确认已经安全。

------

# 四、其他优化建议

## 1. 动画文件存在重复数据

当前动画分包约 **0.91 MiB**，多个动画同时存在 `.js` 和 `.json` 两份，例如：

- `trophy.js` 与 `trophy.json`
- `celebration.js` 与 `celebration.json`
- `award.js` 与 `award.json`
- `medal.js` 与 `medal.json`
- `thumbs-up.js` 与 `thumbs-up.json`

实际加载器只引用 `.js`，对应 `.json` 很可能是冗余文件。

删除未使用副本可以显著缩小分包。

当前静态体积约为：

| 范围     | 体积        |
| -------- | ----------- |
| 主包     | 约 1.28 MiB |
| 动画分包 | 约 0.91 MiB |
| 总计     | 约 2.19 MiB |

------

## 2. 缺少自动化测试脚本

`package.json` 没有测试脚本，也没有可见的正式测试套件。

建议至少覆盖：

- 首次登录存储失败；
- 多请求并发刷新 Token；
- 刷新接口不返回 Refresh Token；
- Token 过期后切换账号；
- KaTeX 分数、根号、矩阵和长公式；
- 动画分包首次加载失败和再次加载；
- AI 反馈接口失败；
- 导入文件伪装扩展名；
- 导入轮询切后台再恢复；
- 番茄钟进程被终止后恢复。

------

# 五、当前上线建议

## 必须先完成

1. 完整隐私政策和小程序内账号注销；
2. 首次登录认证信息改为严格、可回滚写入；
3. 统一 401、Refresh 失败和主动退出的缓存清理；
4. 增加服务端退出登录和 Refresh Token 撤销；
5. 修复 `loading-lottie` 未触发分包加载；
6. 打开发布检查并统一基础库版本。

## 建议同时完成

1. 让 AI 反馈真正提交到后端；
2. 防止 Refresh Token 被空值覆盖；
3. 修正 `ensureValidToken()` 失败后仍继续请求；
4. 将 KaTeX 字体迁移到自有域名；
5. 统一 `package.json` 和锁文件；
6. 统一文件格式配置并确认后端文件安全校验。

**最终判断：当前版本已经从“存在多项明显问题”提升到“接近可上线”，但认证安全、隐私注销和发布配置仍未闭环。至少完成前六项后，再进行微信开发者工具正式编译、自动审计和真机回归，才适合提交审核。**
