你现在是这个仓库的资深微信小程序发布工程师、前后端集成工程师和性能工程师。

你的目标不是只输出建议，而是：

**直接审计并修改当前代码仓库，把微信小程序修到具备生产发布条件，然后执行能够执行的测试和静态检查，最后给出真实的 GO / NO-GO 上线结论。**

项目包含：

- `miniprogram/`：原生微信小程序
- `backend/`：FastAPI 后端
- `admin-frontend/`
- `deploy/`
- `docs/`
- `CLAUDE.md`

请首先阅读仓库根目录的 `CLAUDE.md`、README、相关开发规范和现有测试，但不要把 README 当成实际代码的唯一真相。

------

# 一、工作原则

1. 直接修改代码，不要只给建议。
2. 先执行 `git status`，保护用户已有的未提交修改。
3. 不得覆盖、回滚或删除与本任务无关的用户修改。
4. 不要进行无关的大规模重构或 UI 改版。
5. 保持现有业务功能、视觉表现和接口兼容性，除非当前实现本身就是错误的。
6. 所有结论必须以实际代码、实际测试或实际工具输出为依据。
7. 不得伪造“测试通过”“微信开发者工具编译通过”“真机验证通过”。
8. 无法自动验证的项目必须明确列为人工发布门禁。
9. 优先级按：
   - P0：阻塞发布
   - P1：高风险生产缺陷 / 明显性能问题
   - P2：优化与维护性问题
10. 每完成一个问题，都要同步补充必要的自动化测试或可重复验证方式。

------

# 二、先执行完整基线审计

先建立修改前基线：

1. 检查所有小程序 `.js` 语法。
2. 检查所有 JSON 文件可解析。
3. 检查 `app.json`：
   - 主包页面
   - 分包页面
   - `usingComponents`
   - 分包路径
   - 页面所需 `.js/.json/.wxml/.wxss`
4. 检查所有相对路径 `require/import` 是否真实存在。
5. 检查微信小程序代码中是否误用了 Node.js 内置模块。
6. 执行仓库已有测试。
7. 枚举小程序所有 API 请求，与 FastAPI 实际路由进行自动或半自动契约核对。
8. 统计实际可能进入发布包的主包和分包文件。
9. 若本机存在微信开发者工具 CLI、`miniprogram-ci` 或仓库已有构建工具，则执行真实编译/预览验证；不存在则明确记录，不得声称已验证。

先记录基线失败项，然后开始修复。

------

# 三、P0：修复发布包混入 Node 专用测试脚本的问题

当前重点检查：

```text
miniprogram/project.config.json
miniprogram/scripts/test-*.js
```

现有发布忽略规则可能只排除了：

```text
*.test.js
*.spec.js
```

但没有排除：

```text
scripts/test-*.js
```

这些测试脚本可能包含：

```text
assert
node:assert/strict
fs
path
```

要求：

1. 判断 `miniprogram/scripts/` 中哪些文件仅用于 Node 测试，哪些属于小程序运行时。
2. 不得误排除真正的运行时代码。
3. 将纯 Node 测试移出小程序发布范围，或者完善 `project.config.json` 的 `packOptions.ignore`。
4. 确保正式发布包不会包含 Node-only 测试代码。
5. 增加一个可重复执行的 release audit：
   - 检查拟发布源码中是否出现非允许的 Node builtin import/require；
   - 检查明显不存在的相对模块路径；
   - 检查测试文件是否误入发布范围。
6. 重新统计包体积。

验收标准：

- 发布包不包含 Node-only `scripts/test-*.js`。
- 小程序运行时代码没有 `fs/path/assert/node:*` 等 Node 内置依赖。
- 现有 Node 测试仍然可以在其正确环境中运行。

------

# 四、P0：完成前后端 API 契约核对

不要仅对照 README。

请直接扫描：

```text
miniprogram/
backend/app/api/
backend/app/schemas/
```

枚举：

```text
HTTP method
完整 URL path
请求 body/query/path 参数
主要响应字段
认证要求
```

重点核对小程序中发现的这些接口：

```text
POST /api/v1/ai/feedback

GET  /api/v1/pomodoro/subjects
POST /api/v1/pomodoro/{id}/interrupt

POST /api/v1/review/grade-batch
GET  /api/v1/review/today/next-batch
GET  /api/v1/review/today/overview
GET  /api/v1/review/today/result
POST /api/v1/review/{id}/master
POST /api/v1/review/{id}/unmaster

GET  /api/v1/stats/dashboard-insights
GET  /api/v1/stats/dashboard-llm-analysis
GET  /api/v1/stats/growth

POST /api/v1/wrong-questions/batch
```

要求：

1. 对每一个接口确认后端真实存在。
2. 检查 method 是否一致。
3. 检查 path 参数命名是否一致。
4. 检查 query/body 格式是否一致。
5. 检查前端使用的响应字段是否真实存在。
6. 检查空数据、401、404、409、422、500 时前端是否能正确处理。
7. 如果是 README 过时：
   - 更新文档。
8. 如果前端路径错误：
   - 修改前端。
9. 如果后端应该提供但缺失：
   - 在遵循现有后端架构的前提下实现。
10. 如果功能实际上已废弃：

- 不允许继续静默调用 404；
- 删除入口或明确 feature gate，并提供可理解的 UI fallback。

建议增加一个接口契约检查脚本，使核心 API 的 path/method 漂移能在 CI 中被发现。

验收标准：

- 所有小程序核心请求都有真实后端实现或明确 feature gate。
- 不存在已知的核心页面请求必然 404/405。
- 前端实际消费字段与 Pydantic response schema 一致。

------

# 五、P1：彻底修复动画分包加载

重点检查：

```text
miniprogram/app.js
miniprogram/utils/animation-loader.js
miniprogram/subpackages/animation/
```

当前疑似问题包括：

```js
wx.loadSubPackage
wx.preloadSubPackage
```

以及：

```js
require('../../subpackages/animation/lottie-loader.js')
```

要求：

1. 根据当前项目使用的微信基础库版本和官方类型定义，确认正确 API 名称和调用参数。

2. 重点核对：

   - `wx.loadSubpackage`
   - 分包参数使用 `name` 还是当前 API 实际要求的其他字段

3. 不要简单把：

   ```text
   ../../
   ```

   改成：

   ```text
   ../
   ```

   就结束。

4. 主包同步 `require` 子包代码如果不被微信运行机制支持，必须改为官方支持的异步加载方案，例如当前基础库实际支持的异步模块/分包机制。

5. 如果现有 Lottie 架构不适合跨分包加载：

   - 将最小 loader 放在合适的位置；
   - 只把真正的大资源放进分包；
   - 或者明确采用可靠的静态 fallback。

6. 删除不存在或错误的 API 分支。

7. 修复加载失败后的重试语义：

   - 首次失败不能把一个永久 resolved 的 `_loadingPromise` 留在那里；
   - 后续可以根据策略重新尝试；
   - App 层和 loader 层的 promise 状态必须一致。

8. 防止并发多次加载。

9. 加载失败必须：

   - 不崩溃；
   - 不产生未处理 Promise rejection；
   - 有确定性 fallback。

10. 添加针对以下情况的测试或测试 harness：

    - 第一次成功；
    - 并发加载；
    - 第一次失败后重试；
    - 分包加载失败；
    - Lottie 模块初始化失败；
    - fallback 可用。

验收标准：

- 不再出现错误的 `loadSubPackage` 调用。
- 不存在越界或不存在的 `../../subpackages/...` require。
- 不依赖不受支持的主包同步 require 子包代码。
- 动画成功时正常播放。
- 动画失败时稳定 fallback。
- 首次失败不会永久阻止后续合理重试。

------

# 六、P1：修复鉴权和 401 重试状态机

重点检查：

```text
miniprogram/utils/api.js
miniprogram/utils/auth.js
miniprogram/pages/login/
backend 中 access token / refresh token 配置
```

需要建立明确的状态机：

```text
业务请求
    ↓
access token 可用
    ↓
正常请求

首次收到 401
    ↓
只允许一个 in-flight refresh
    ↓
其他并发请求等待同一个 refresh Promise
    ↓
refresh 成功
    ↓
原请求最多重放一次
    ↓
若重放后再次 401
    ↓
清理失效 session
    ↓
只触发一次重新登录流程
```

要求：

1. 单个业务请求最多因 401 自动重试一次。
2. 第二次仍然 401 时：
   - 不允许继续 refresh loop；
   - 原子化清理 access token / refresh token / 用户态；
   - 防止多个请求同时重复跳登录页。
3. 区分：
   - refresh token 无效/过期；
   - HTTP 401/403；
   - 网络断开；
   - timeout；
   - DNS/TLS；
   - 服务器 5xx。
4. 临时网络错误不能直接被标记成“登录已过期”。
5. 保持 single-flight refresh，避免多个并发 401 产生刷新风暴。
6. 检查主动刷新阈值。
7. 读取后端真实 access token TTL：
   - 如果前端当前约 3600 秒的提前刷新阈值大于或接近 token TTL，会造成几乎每次请求刷新；
   - 改成合理阈值，例如固定较短安全窗口，或基于 token 到期时间动态计算。
8. 统一 `ApiError.code` 语义：
   - 不要一部分是字符串，一部分是数字，除非类型定义和调用方明确支持。
9. 保证登录页不会发生 redirect/reLaunch 风暴。

必须补充自动化测试，至少覆盖：

```text
A. 正常请求成功
B. access token 主动刷新成功
C. 首次 401 → refresh 成功 → retry 成功
D. 多请求同时 401 → 只 refresh 一次
E. refresh token 返回 401
F. refresh 网络超时
G. refresh 500
H. retry 后再次 401
I. 没有 refresh token
J. 登录跳转只发生一次
```

验收标准：

- 不存在无限 refresh / retry 循环。
- 并发 401 只产生一次 refresh。
- 第二次 401 会进入稳定的重新登录状态。
- 网络失败不会被误判成凭证失效。

------

# 七、P1：优化刷题页高频大对象 setData

重点检查：

```text
miniprogram/pages/practice/practice.js
miniprogram/components/quiz-runner/
```

当前选择答案或填写答案时，可能会重新构造完整：

```js
questions
```

然后：

```js
this.setData({
  questions,
  answeredCount,
  currentQuestion
})
```

要求：

1. 实际测量或静态分析每次答题交互的 `setData` payload。

2. 不要在每次选择选项时把整批富题目对象重新传给视图层。

3. 优先采用：

   - 精确数据路径更新；
   - 轻量 `questionStates`;
   - 或将完整题目保存在页面实例字段中。

4. 例如：

   ```js
   this.setData({
     [`questionStates[${index}].answered`]: true,
     answeredCount,
     currentQuestion
   })
   ```

5. 如果答题卡需要全部状态，只同步：

   ```text
   id
   answered
   correct/wrong
   current
   ```

   等轻量字段。

6. 保证以下行为完全不回归：

   - 单选；
   - 多选；
   - 填空；
   - 上一题/下一题；
   - 跳题；
   - 答题卡；
   - 已答数量；
   - 提交；
   - 结果页。

7. 避免为了性能优化引入复杂的双状态源失同步。

验收标准：

- 单次答题操作不再 setData 整个重型 `questions` 数组。
- 答题状态和 UI 一致。
- 原有行为测试通过。
- 能输出优化前后的 payload 大小或至少可靠的结构性对比。

------

# 八、P1/P2：检查主包体积并安全减包

重点大文件：

```text
KaTeX CSS/WXSS
katex.min.js
pages/pomodoro/pomodoro.js
dashboard 样式
wrong-book
review-today
practice
mp-html/parser
stem-render
```

要求：

1. 使用真实发布规则统计主包和各分包。
2. 如果微信开发者工具或 CI 可用，以真实构建结果为准。
3. 清理：
   - 发布包测试脚本；
   - 未引用文件；
   - 未使用依赖；
   - 重复资源。
4. 检查 `lottie-miniprogram` npm dependency 是否实际使用：
   - 确认未使用后才能移除。
5. KaTeX 是核心公式能力：
   - 不允许为了减包破坏公式渲染；
   - 不允许未经验证直接删除 CSS、字体映射或 JS。
6. 如果需要进一步拆包：
   - 先分析核心页面是否同步依赖；
   - 使用微信支持的异步组件或分包机制；
   - 添加公式回归测试。
7. 保留足够发布余量，不要只做到“刚好低于限制”。

验收标准：

- 输出真实或可重复计算的主包/分包大小。
- 无测试代码和明显死资源进入正式包。
- 所有公式回归测试通过。

------

# 九、P2：优化番茄钟持续绘制

重点检查：

```text
miniprogram/pages/pomodoro/pomodoro.js
```

要求：

1. 不改变番茄钟的真实时间准确性。

2. 时间计算必须以 wall clock：

   ```js
   Date.now()
   ```

   或等价时间差为准，不能依赖 tick 次数。

3. 检查当前 80–250ms tick 和 Canvas 重绘频率。

4. 缓存不随每帧变化的：

   - gradient；
   - geometry；
   - canvas size；
   - DPR 相关参数。

5. 页面隐藏、暂停、卸载后停止无意义重绘。

6. 页面恢复后根据真实时间重新计算状态。

7. 在不降低明显视觉质量的前提下减少不必要 redraw。

8. 检查：

   - start
   - pause
   - resume
   - complete
   - interrupt
   - 前后台切换
   - 页面销毁
   - session 恢复

验收标准：

- 不存在重复计时器。
- 后台不持续高频绘制。
- 长时间运行没有明显时间漂移。
- UI 动画效果保持正常。

------

# 十、清理与文档同步

检查并处理：

1. 空目录：

   ```text
   components/question-card
   ```

   确认无引用后再删除。

2. README 与真实配置不一致的内容。

3. 当前实际基础库版本与 README 是否一致。

4. 已废弃依赖。

5. 测试文件命名规则和发布 ignore 规则。

6. API 文档与后端实际 route 同步。

不要为了“看起来干净”删除任何不能确认无用的文件。

------

# 十一、安全与生产配置检查

检查：

```text
miniprogram/config.js
project.config.json
project.private.config.json
backend/.env.example
deploy/
```

重点确认：

1. production 不指向：

   ```text
   localhost
   127.0.0.1
   局域网 IP
   测试域名
   ```

2. 小程序源码不存在：

   - WeChat AppSecret；
   - 数据库密码；
   - AI API key；
   - JWT secret；
   - 管理员密码。

3. Token 只通过安全的认证流程发送。

4. 不在日志中打印完整 token、敏感请求体和用户隐私数据。

5. 检查正式环境的：

   - `request` 合法域名；
   - `uploadFile` 合法域名；
   - `downloadFile` 合法域名；
   - HTTPS/TLS。

6. 微信公众平台后台配置无法通过仓库验证的，列入人工上线门禁。

7. 检查小程序隐私协议和实际使用的敏感 API 是否一致。

------

# 十二、最终测试矩阵

修复后执行所有可自动执行的测试。

至少包括：

## 静态

```text
所有 JS 语法检查
所有 JSON 解析
页面注册完整性
usingComponents 路径
相对模块路径
Node builtin 泄漏检查
发布包内容检查
```

## 现有测试

执行仓库已有全部相关测试，尤其公式渲染测试。

## 鉴权

```text
正常登录
token refresh
并发 401
refresh token 失效
断网
timeout
retry 二次 401
退出后重新登录
```

## 核心小程序 smoke test

```text
1. 微信登录
2. 首页
3. 顺序刷题
4. 随机刷题
5. 选择答案
6. 填空题
7. 提交答题
8. 结果页
9. 错题本
10. 错题详情
11. 错题批量操作
12. 今日复习
13. 掌握/未掌握
14. 学习报告
15. Dashboard
16. AI 相关入口的正常和失败 fallback
17. 番茄钟 start
18. pause
19. resume
20. complete
21. interrupt
22. 前后台恢复
23. 数学公式
24. 富文本题干
25. 动画加载
26. 动画加载失败 fallback
```

## API

核心页面不得存在已知：

```text
404
405
前端字段读取 undefined 导致崩溃
错误 method
错误 URL
```

------

# 十三、发布判定标准

只有满足以下条件才允许最终输出：

```text
GO
```

1. 无 P0 未解决问题。
2. 所有前端核心 API 已与真实后端代码核对。
3. 发布包无 Node-only 测试代码。
4. 无明显错误的分包加载 API。
5. 无 401 refresh 无限循环风险。
6. 刷题高频交互不再传输完整重型题目数组。
7. 所有可执行测试通过。
8. 真实构建工具可用时，微信小程序编译通过。
9. 包体积在微信限制内并有合理余量。
10. 没有客户端 secret 泄漏。
11. 剩余人工检查只允许是：
    - 微信公众平台合法域名；
    - 隐私配置；
    - 审核后台配置；
    - 真机专项验证；
      等无法从代码仓库自动完成的事项。

如果任意核心项无法验证，必须输出：

```text
NO-GO
```

或：

```text
CONDITIONAL GO
```

并准确说明缺少什么证据。

------

# 十四、完成后的输出格式

修改完成后，不要只说“已优化”。

按以下格式输出：

## 1. 最终结论

```text
GO / CONDITIONAL GO / NO-GO
```

一句话说明原因。

## 2. 已修复问题

按：

```text
P0
P1
P2
```

列出。

每项必须包括：

```text
问题
根因
修改文件
修复方案
验证方法
结果
```

## 3. API 契约结果

列出所有发现过差异的 endpoint：

```text
frontend method/path
backend method/path
状态：MATCH / FIXED / REMOVED / FEATURE-GATED
```

## 4. 性能结果

至少输出：

```text
主包大小
各分包大小
删除的发布垃圾
刷题 setData 优化前后
番茄钟绘制策略变化
```

无法获得真实微信构建大小时必须明确写：

```text
仅为源码估算，不是微信最终上传包大小
```

## 5. 测试结果

逐条列出：

```text
命令
结果
```

不得伪造未运行的命令。

## 6. 修改文件清单

列出所有修改文件及用途。

## 7. 剩余人工发布检查

只列真正无法自动执行的项目。

------

现在开始：

1. 阅读项目规范。
2. 检查 `git status`。
3. 建立修改前基线。
4. 按 P0 → P1 → P2 顺序直接修复代码。
5. 运行测试。
6. 重新审计。
7. 输出最终发布结论。

不要停留在分析阶段；在确认根因后直接修改仓库代码。