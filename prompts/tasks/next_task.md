# 审计结论

**当前版本建议判定为“有条件不通过”，不建议按现状直接上线。**

从静态代码看，项目整体结构比较完整，生产环境已经使用 HTTPS，接口封装、Token 并发刷新、分包与缓存校验等也有一定工程化基础。但仍发现：

- **4 项上线前必须修复或确认的问题**
- **6 项中优先级优化**
- 若干工程质量和性能改进项

本次审计覆盖 JS、WXML、WXSS、JSON、项目配置、登录与 Token、文件导入、AI 内容、富文本和动画分包。所有 JSON 均可解析，非第三方 JS 未发现明显语法错误。由于没有后端源码、微信公众平台配置和真实设备环境，服务端鉴权、域名配置、隐私指引配置及实际运行表现仍需联调确认。

------

## 一、上线前必须处理

### 1. 隐私政策和账号注销机制不完整

**涉及位置：**

- `pages/agreement/privacy.wxml:12-28`
- `pages/agreement/user.wxml`
- `pages/agreement/ai.wxml`
- `pages/home/home.js:326-332`
- `app.js:59-64`
- `utils/api.js:90-91`

当前隐私政策只有几条概括性说明，主要缺少：

- 运营者名称、联系方式；
- 每类个人信息的收集目的、方式、范围；
- 登录标识、学习记录、错题记录、导入文件、图片和 AI 输入分别如何处理；
- 第三方 AI/OCR 服务商名称、接收信息类型、处理目的；
- 信息保存期限；
- 查询、复制、更正、删除、撤回同意的具体方式；
- 账号注销入口、处理期限和注销后的数据删除规则；
- 未成年人信息处理说明；
- 生效日期、更新日期和版本记录。

目前注销方式仅为：

> 发送邮件至 [support@xzshub.top](mailto:support@xzshub.top)

这不一定能够满足“便捷注销”的要求，至少应增加小程序内的注销入口、二次确认、身份验证、处理状态和完成通知。现行规则也要求在账号注销后依法删除相关个人信息；2026年网信部门通报中仍将小程序隐私规则、第三方信息披露和注销渠道问题作为重点治理事项。([国家市场监管总局](https://www.cac.gov.cn/2026-04/27/c_1779028107561553.htm?utm_source=chatgpt.com))

此外，`app.js:59-64` 在用户尚未勾选协议时就调用 `wx.login()` 进行预热，而 `utils/api.js:90-91` 又明确注释“wx.login 只能在用户同意后调用”，代码与设计约束相互矛盾。

**建议：**

1. 补充完整隐私政策和第三方服务清单。
2. 在“设置”中增加账号注销页面，而不只是邮箱。
3. 在微信公众平台完成《小程序用户隐私保护指引》配置，并逐项对应实际接口。
4. 删除启动阶段的 `_preWarmSession()`，或者调整为用户同意协议后执行。
5. 协议版本更新时，强制用户重新确认，而不是仅依靠本地旧版本状态。

------

### 2. 登录态清理不彻底，存在串号和遗留数据风险

**涉及位置：**

- `utils/auth.js:39-76`
- `utils/api.js:121-129`
- `utils/storage.js:16-21`
- `utils/auth.js:27-36`
- `utils/auth.js:110-116`

发现三个关联问题。

#### 2.1 退出登录只清本地，不撤销服务端 Refresh Token

`auth.logout()` 只是删除本地数据，没有调用服务端注销或 Token 撤销接口。Refresh Token 如果泄露，在过期前仍可能继续换取 Access Token。

建议后端提供：

```text
POST /auth/logout
```

注销时撤销当前 Refresh Token；如果支持多设备登录，最好提供“退出当前设备”和“退出全部设备”。

#### 2.2 Token 失效和手动退出使用了两套清理逻辑

`utils/api.js` 的 `_clearAuthAndRedirect()` 只删除：

- access token
- refresh token
- 过期时间
- 用户信息

但没有删除业务缓存，例如：

- `lastPracticeResult`
- `wrong_detail_nav`
- 番茄钟运行状态
- 今日目标
- 导入任务状态
- 其他没有按用户隔离的缓存

在同一台设备切换账号后，可能遗留前一个用户的数据或状态。

建议统一成一个方法：

```javascript
clearSession({
  clearBusinessCache: true,
  preservePrivacyAcceptance: true,
  reason: 'logout'
})
```

所有主动退出、Refresh Token 失效、401 重定向都调用同一方法。业务缓存最好使用用户 ID 作为命名空间，而不是全部使用全局键。

#### 2.3 登录信息写入失败被静默吞掉

`storage.set()` 捕获异常后只打印日志，登录流程不会知道 Token 是否真正写入成功。因此可能出现：

1. 服务端登录成功；
2. Token 写入失败；
3. 页面仍进入首页；
4. 后续全部接口报未登录。

Refresh Token 流程已经使用了 `setStrict()`，但首次登录没有使用，逻辑不一致。

建议首次登录也采用严格、原子化写入：任何一个认证字段写入失败，就回滚全部认证信息并停留在登录页。

------

### 3. 数学公式 KaTeX 集成疑似没有完成

**涉及位置：**

- `components/mp-html/latex/build.js`
- `components/mp-html/index.wxss`
- `components/mp-html/node/node.wxml`
- `components/mp-html/latex/katex.css`

`build.js` 明确要求构建过程执行两项修改：

1. 将 `katex.css` 引入 mp-html 样式；
2. 在 `node.wxml` 的渲染条件中加入 `n.l`。

但当前提交代码中：

- `components/mp-html/index.wxss` 没有引入 KaTeX 样式；
- `components/mp-html/node/node.wxml` 中也没有看到 `n.l` 补丁。

这会导致公式虽然生成了 HTML，但可能出现：

- 分数线、根号、上下标错位；
- 矩阵和多行公式布局异常；
- 行内公式被当成块级公式；
- KaTeX 字体和间距失效；
- Android、iOS 表现不一致。

而该小程序的题目、答案和解析大量使用 `mp-html`，属于核心功能风险。

另外，`katex.css` 中的字体文件来自外部 BootCDN。即使补上 CSS，也会产生第三方域名依赖、字体加载失败和隐私披露问题。更稳妥的做法是使用本地或自有域名静态资源，并确认字体授权。

**上线前至少回归测试：**

- 分数、根式、积分、极限；
- 上下标嵌套；
- 矩阵和分段函数；
- 中文、英文和公式混排；
- 长公式横向溢出；
- 公式与代码块混排；
- iOS、Android 和不同微信基础库版本。

------

### 4. 管理员导入权限和文件安全必须由后端重新验证

**涉及位置：**

- `pages/import/import.js`
- `utils/file-request.js:48-73`

前端根据本地保存的 `user.is_admin` 或权限字段决定是否展示导入页面。这只能用于界面控制，不能作为安全校验，因为本地用户信息可以被修改。

上线前必须确认服务端所有导入接口都重新验证：

- 当前用户身份；
- 管理员权限；
- 文件归属；
- pipeline/task ID 是否属于当前用户；
- 重试、取消、删除等操作权限。

文件校验目前主要依赖扩展名和文件大小，不能阻止伪装文件。服务端还应校验：

- MIME 类型和文件魔数；
- PDF 页数；
- Excel 工作表和单元格数量；
- 图片像素及解压后大小；
- ZIP/Office 解压炸弹；
- 病毒或恶意载荷；
- 单用户上传频率、并发量及总容量。

这是后端确认项，但由于导入功能具有管理员属性，应作为上线阻断性验收内容。

------

## 二、中高优先级问题

### 5. 动画分包加载失败后不能再次尝试

**涉及位置：**

- `app.js:15-38`
- `components/loading-lottie/loading-lottie.js`
- `components/AnimatedView/AnimatedView.js`

`loadRewardAnimationPackage()` 第一次加载失败时会 `resolve()`，但不会清空 `_animLoadPromise`。之后再次调用时始终返回第一次已经完成的 Promise，不会重新加载，除非用户重启小程序。

应在失败时执行：

```javascript
_animLoadPromise = null
```

或者在 `finally` 中根据 `_ANIM_LOADED` 状态重置。

此外，`AnimatedView` 会先调用 `loadRewardAnimationPackage()`，但 `loading-lottie` 直接：

```javascript
require('../../subpackages/animation/lottie-loader.js')
```

没有保证动画分包已经加载。两套加载逻辑不一致，加载动画可能长期退化为静态状态。

建议封装一个唯一的 `animationService`，所有组件都通过它加载分包和 Lottie 数据。

------

### 6. 导入任务初始数据结构不完整

**涉及位置：**

- `pages/import/import.js:239-255`
- `pages/import/import.wxml:87`
- `pages/import/import.wxml:95`

新建任务时的 `pipelineTask` 没有初始化：

- `stageList`
- `failed_chunk_details`
- `progressPercent`

但 WXML 直接访问：

```text
pipelineTask.stageList.length
pipelineTask.failed_chunk_details.length
```

在首次轮询返回前可能出现表达式警告、页面局部不渲染或不同基础库表现不一致。

建议始终初始化完整结构：

```javascript
pipelineTask: {
  status: 'pending',
  stageList: [],
  failed_chunk_details: [],
  progressPercent: 0
}
```

另外，导入页面和 `file-request.js` 中维护了两套支持格式列表，其中对 GIF、CSV 的定义不完全一致，应合并为一个配置源。

------

### 7. Token 过期时间和提前刷新策略过于脆弱

**涉及位置：**

- `utils/api.js:25-26`
- `utils/api.js:152-176`

当前代码直接执行：

```javascript
const timeToExpiry = expiresAt - Math.floor(Date.now() / 1000)
```

默认后端返回 Unix 秒。如果以后后端返回：

- ISO 日期字符串；
- Unix 毫秒；
- 字符串形式的秒数；
- `expires_in` 而不是 `expires_at`；

就可能出现持续刷新或永不刷新的问题。

同时提前刷新阈值固定为 24 小时。如果 Access Token 本身有效期就是 24 小时或更短，登录后的几乎每次请求都会尝试刷新。

建议：

- 明确接口契约，统一保存为 Unix 毫秒或 Unix 秒；
- 写入存储前完成格式标准化；
- 提前刷新改为 5～10 分钟，或者 Token 生命周期的 10%；
- 为秒、毫秒、ISO 时间和缺失字段分别增加单元测试。

------

### 8. AI 标识仍不够统一，缺少便捷投诉或纠错入口

`wrong-detail.wxml:158` 已经显示：

> 内容由 AI 生成，仅供参考

这一点处理得比较好。

但 `dashboard` 和 `wrong-book` 主要只显示“AI 分析”“AI 诊断”，没有在每段结果附近明确提示其为 AI 生成内容、可能存在错误，也没有针对单条 AI 结果的“纠错/反馈”入口。

《人工智能生成合成内容标识办法》及配套标准已于2025年9月1日实施，规定了显式和隐式标识机制；面向公众提供生成式人工智能服务时，还需结合具体服务模式评估投诉举报、内容安全和备案等要求。([国家市场监管总局](https://www.cac.gov.cn/2025-03/14/c_1743654685899683.htm?utm_source=chatgpt.com))

建议：

- dashboard、wrong-book 每个 AI 结果卡片增加“AI 生成，仅供学习参考”；
- 增加“结果有误”反馈按钮；
- 记录题目 ID、分析版本、模型版本和生成时间；
- 后台可以根据反馈停用或重新生成错误结果；
- 由合规人员确认所接入 AI 服务是否涉及算法备案、生成式 AI 服务备案或登记。

------

### 9. 富文本组件默认能力过多

`mp-html` 当前默认启用了：

- `setTitle: true`
- `copyLink: true`
- `previewImg: true`
- `showImgMenu: true`

题目和 AI 返回内容属于外部输入。默认 `setTitle: true` 可能允许内容里的 `<title>` 修改小程序导航栏标题；远程图片和链接也可能触发第三方请求或引导用户访问外部内容。

建议在所有题目和解析场景显式设置：

```xml
<mp-html
  content="{{content}}"
  set-title="{{false}}"
  copy-link="{{false}}"
/>
```

同时在进入组件前过滤：

- 非 HTTPS 地址；
- `javascript:`、`file:` 等协议；
- 非白名单图片域名；
- 不需要的音频、视频、表单和链接标签。

------

### 10. 发布环境配置不够可复现

发现：

- `project.config.json`：基础库 `3.3.4`
- `project.private.config.json`：基础库 `3.6.6`
- `urlCheck: false`
- `scopeDataCheck: false`
- `autoAudits: false`

开发人员本地实际运行的基础库可能是 3.6.6，但上传或其他电脑打开项目时可能使用 3.3.4，容易造成“本地没问题、上传后异常”。

建议：

1. 统一基础库版本。
2. 发布分支将 `urlCheck`、`scopeDataCheck` 打开。
3. 上线前执行开发者工具自动审计。
4. 分别使用最低支持版本和当前稳定版本做回归测试。
5. 确认微信后台已经配置：
   - request 合法域名；
   - uploadFile 合法域名；
   - downloadFile 合法域名；
   - 可能使用的图片或字体资源域名。
6. 不要依赖 `urlCheck:false` 掩盖域名配置问题。

------

## 三、工程与性能优化

### 1. 包体还有明显压缩空间

静态统计约为：

| 部分     | 未压缩体积  |
| -------- | ----------- |
| 主包     | 约 1.28 MiB |
| 动画分包 | 约 0.91 MiB |
| 合计     | 约 2.18 MiB |

体积目前不算失控，但动画目录中存在多组内容重复的 `.js` 和 `.json` 文件，KaTeX 和 Lottie vendor 文件也比较大。

建议：

- 每个动画只保留一种数据格式；
- 对 Lottie JSON 做小数精度压缩和无用图层清理；
- 按使用场景拆分动画分包；
- 删除没有实际使用的动画；
- 检查 `onAnimReady()` 等未使用代码；
- 生成包体分析报告并纳入发布流程。

### 2. 大文件需要拆分

较大的业务文件包括：

- `pages/pomodoro/pomodoro.js`
- `pages/dashboard/dashboard.wxml`
- `pages/dashboard/dashboard.wxss`
- `pages/review-today/review-today.js`
- 富文本渲染相关代码

建议将番茄钟拆成：

- timer state machine；
- persistence service；
- notification service；
- 页面 view model。

Dashboard 可拆成独立组件，降低单页更新的数据量和后续维护难度。

### 3. 缺少自动化测试

`package.json` 中没有可执行测试脚本，项目虽然忽略了 `tests`、`*.test.js`，但没有发现完整测试体系。

至少应补充：

- Token 刷新并发、刷新失败和存储失败；
- 登录后切换账号的数据隔离；
- 题目答案标准化；
- KaTeX 公式固定样例；
- 导入轮询、暂停、恢复和过期任务；
- 番茄钟切后台、进程终止、重新进入；
- AI 空结果、超时、重复生成；
- 弱网、断网及接口 401/403/429/500。

### 4. 增加生产监控

目前主要依赖 `console.error` 和 `console.warn`。正式上线后难以定位特定机型或用户的异常。

建议接入统一错误上报，至少记录：

- 页面和操作阶段；
- 接口路径和 HTTP 状态；
- trace ID；
- 基础库版本；
- 设备平台；
- 网络类型；
- 错误代码。

禁止上报 Token、完整题目图片、用户导入文件和未经脱敏的个人信息。

------

## 四、上线前最低验收清单

建议满足以下条件后再提交审核：

1. 完整更新隐私政策、用户协议、AI 说明和第三方服务清单。
2. 实现小程序内账号注销和服务端 Refresh Token 撤销。
3. 统一所有退出、401 和 Refresh 失败场景的数据清理。
4. 修复 KaTeX CSS 和 WXML 补丁并完成真机公式回归。
5. 修复动画分包失败后不能重试以及 `loading-lottie` 直接引用分包的问题。
6. 初始化完整的导入任务数据结构，并确认后端文件与权限校验。
7. 统一基础库版本，打开 URL、权限和自动审计检查。
8. 完成 Android、iOS、弱网、冷启动、切账号、长时间后台恢复测试。
9. 核对微信后台隐私指引、合法域名、备案信息和类目资质。
10. 为 dashboard、wrong-book 的 AI 输出增加明确标识和反馈入口。

**综合判断：**业务主体功能已接近上线状态，但隐私合规、认证清理、数学公式渲染和管理员导入安全这四个方面尚不适合带风险发布。完成上述高优先级整改并进行一次开发者工具编译和真机回归后，再进入灰度上线会更稳妥。
