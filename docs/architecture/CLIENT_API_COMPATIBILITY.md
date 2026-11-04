# 小程序 API 客户端边界兼容基线

核对日期：2026-10-28。对应重构计划阶段 0；范围仅限小程序 `utils/api.js` HTTP 客户端及其拆分模块（错误映射、相关性 ID、认证续签/重定向、请求与上传输送、服务端时钟）。不表示页面级调用点、真机网络或后端接口完成。

## 1. 入口与消费者

- `utils/api.js` 公开导出顺序固定为 `get`、`post`、`put`、`del`、`resetRedirecting`、`ensureValidToken`、`forceRefreshToken`、`uploadFile`、`request`、`ApiError`、`getErrorMessage`、`normalizeExpiresAt`、`createTraceId`、`createRequestId`、`createClientStartId`、`now`。
- 页面、分包、脚本与测试共 41 个文件引用 `utils/api`（含门禁脚本与新增测试）；`utils/api.js` 仍是唯一入口，拆分后的模块只被它聚合。
- 2026-10-28 拆分：`api-error.js`、`api-correlation.js`、`api-transport.js`、`api-clock.js`、`api-auth.js`、`api-request.js`、`api-upload.js` 与门面 `api.js`；八个文件均不超过 300 行，全部函数不超过 50 行。

## 2. 错误契约

- `ApiError` 继承 `Error`，`name = 'ApiError'`，字段 `code`、`statusCode`、`detail`、`raw`，`requestId`/`traceId` 先取显式参数、后回退 `detail.requestId`/`detail.traceId`。`message` 只允许前端安全文案，禁止透传后端 detail。
- `_safeHttpMessage` 按状态码固定映射（0/400/401/403/404/405/409/413/415/422/429/502/503/504/其它 ≥500/默认），不读取响应体。
- `_extractErrorCode` 依次取 `error.code`、`code`、`detail.error_code`、形如 `^[A-Z][A-Z0-9_]{2,63}$` 的 `detail` 字符串，最后回退状态码（`Number(statusCode) || 'HTTP_ERROR'`）。
- `_safeErrorMeta` 只收集 `error.request_id`、`error.trace_id`、`error.retryable === true`，再用响应头 `X-Request-ID`/`X-Trace-ID` 兜底，空结果返回 `undefined`。
- `getErrorMessage` 对 `ApiError` 返回其安全文案，其它错误统一返回 `请求失败，请稍后重试`。

## 3. 请求契约

- 相关性：`_traceId` 先被剥离，再按 `_normalizeCorrelationId(_extractTraceId(data), 'tr')` 归一（合法正则 `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`，不合法则重新生成），请求头固定带 `X-Trace-ID`、`X-Request-ID`、`Content-Type: application/json`，仅当存在 token 时附加 `Authorization: Bearer <token>`。
- 主动续签：`/auth/login` 跳过（`_skipProactiveRefresh`）；无 token 直接返回 `false`（不发请求）；无过期信息视为有效；剩余有效期 ≤ 3600 秒触发续签，失败时等待 1500ms 再试一次，仍失败返回 `false` 并由 `request` 抛 `AUTH_REQUIRED` 阻止无鉴权请求。
- 401 重试：记录 `API_401_REFRESH`，先 `forceRefreshToken`（并发合并为同一次刷新），成功后改写 `Authorization`、生成新的 `X-Request-ID` 重试原请求一次；续签失败直接抛 `AUTH_REQUIRED`，不重试原请求。
- 网络失败：记录 `API_ERROR`，除非 `options.suppressNetworkToast` 否则 toast「网络异常」，抛 `NETWORK_ERROR`（`statusCode: 0`，`raw` 保留原始错误）。
- 响应：`_updateServerClock` 先更新时钟，再按响应头（回退请求 id）记录 `API_RESPONSE` 与调试快照；`statusCode >= 400` 时抛 `ApiError`（`raw: undefined`，`detail` 为安全 meta），否则返回 `res.data`。
- 重定向：`_clearAuthAndRedirect` 调用 `clearSession({ preservePrivacyAcceptance: true, includeDebugSnapshots: true })`，并用 `_redirecting` 锁保证同一轮只 `reLaunch('/pages/login/login')` 一次；`resetRedirecting()` 供登录成功后解锁。

## 4. 上传递送

- `uploadFile` 与请请求共用续签语义，但请求头只有 `X-Trace-ID`、`X-Request-ID`（有 token 时再加 `Authorization`），不设置 `Content-Type`，由 `wx.uploadFile` 管理 multipart boundary；`name` 默认 `file`、`formData` 默认 `{}`、`timeout` 透传。
- 401 时先 `forceRefreshToken` 再以新 request id 重试一次；网络失败抛 `NETWORK_ERROR`；`statusCode >= 400` 时按文本/JSON 解析后抛安全文案错误。

## 5. 服务端时钟

- 采样优先级：响应体 `server_now` 为 rank 2，`Date` 响应头为 rank 1，其它忽略；RTT 取 `responseReceivedAt - requestStartedAt`，偏移取 `serverMs - (startedAt + rtt/2)`。
- 接受样本条件：首次同步、样本超过 10 分钟、rank 提升，或同 rank 且 RTT 不劣于历史最优 +50ms。`now()` 在有样本时返回 `Date.now() + offset`，否则返回本机时间。

## 6. 可执行基线

- 契约测试 `miniprogram/tests/test-api-client-contract.js` 8 项（导出顺序、ApiError 形状、相关性 ID 与过期时间归一化、401 重试顺序与头部、错误映射/提示/重定向锁、主动续签阈值与并发合并、上传头部与 401/网络/4xx、服务端时钟偏移），在 HEAD 原 `utils/api.js` 与拆分后均通过。
- 差分刻画：15 个隔离进程场景对照 HEAD 原模块与拆分后模块（成功/401/续签失败/无刷新令牌/网络/4xx 文案/主动续签/并发合并/登录跳过/上传三态/过期归一化/时钟采样/方法映射），0 不一致。
- 门禁 `miniprogram/tests/test-api-client-boundaries.js` 14 项：八个模块的 300/50 预算、显式无环依赖图、只有门面可聚合、子模块不得反向引用门面、门面导出与子模块函数同一实例，以及页面/分包/第三方/父目录逃逸/动态 require、超预算与循环依赖负向自检，全部通过且不执行被检源码。
- 按当前 `reliability.yml` 的小程序步骤（263 行命令）本机精确重放：退出码 0、0 个 `not ok`，含新增两项。这是本机重放，不是远端 CI。
- 主包源码由 759.7 KiB / 181 个文件变为 762.2 KiB / 188 个文件（低于 1.4 MiB 阈值）；拆分后 8 个文件合计 22,221 字节，原单文件 19,614 字节 / 554 行，净增 2,607 字节。源码体积不是微信编译或上传体积证据。
- 同步更新 `miniprogram/scripts/test-pomodoro-resilience.js` 的五条服务端时钟断言改读 `utils/api-clock.js`（该脚本在 CI 清单内，106 项通过）。

## 7. 未完成和未验证

- 未执行真实微信开发者工具、模拟器或真机；弱网、超时、`wx.request` 并发上限与真实后端联调未验证。
- 页面级调用点（`pages/home`、`pages/dashboard`、`pages/login`、`pages/pomodoro`、`subpackages/*`）、`utils/debug.js`（313 行）与 `utils/china-time.js` 仍未治理；本次不改任何请求协议、路径或页面行为。
- 本基线不覆盖后端接口、鉴权服务端语义、任务队列、OCR 导入、AI 执行或生产验收；存储侧基线见 `CLIENT_STORAGE_COMPATIBILITY.md`。

## 8. MP-10 保留现有共享传输结构（2026-10-30，§318）

前述2026-10-28数字为原拆分快照。本轮按当前消费者映射及八个运行时模块重新核对，不再按文件长度拆分：门面保留公开导出与函数身份，request/upload负责请求生命周期，auth负责续签适配，transport负责平台调用，clock/correlation/error各自拥有已有规则。八个模块与本轮前逐字一致，均满足300/50预算，无环依赖门禁通过；无需新业务模块或依赖。

边界划分：MP-10核对通用JSON请求、multipart上传、刷新调用、错误/相关ID和时钟适配；MP-12仍负责微信登录/退出、用户资料/头像组合、会话持久化与服务端JWT身份策略，不能据本轮关闭。导出流式文件/下载/WebSocket属于已交付MP-02链，保留专用传输，不强塞进JSON门面。消费者映射的84个可能契约形状是当前调用归属基线，不表示每页实际运行了所有可达导出。

原直接契约/门禁22项通过。发现旧测试标题所称上传401与header时钟分支缺少实际断言后，本轮补四项语义契约：上传401保持trace/生成新request id/换token/不带JSON Content-Type/第二次401停止，普通请求第二次401停止，主动续签网络失败只等1500ms重试一次并阻止原请求，时钟样本过期后允许Date header回退。修正旧标题的覆盖表述；当前26项通过。所有平台、存储、时间和延迟均为测试替身，未发生真实上传/微信请求。

当前reliability小程序步骤有306物理行、185条逻辑命令。初次按序执行在第20条番茄钟韧性脚本失败（105通过/1失败），其源码断言要求旧`active = await`写法；真实后端幂等键查询仍在活跃检查前。本轮将该断言限定在start_session函数并检查await调用顺序，未改后端。继续诊断余下命令后，唯一失败仍为第20条；修复后仅复跑该命令106通过，复用其余184条通过结果。最终相关输入有185条通过证据，**不是修复后重新执行了一次完整shell步骤**。MP-15番茄钟业务仍OPEN，不能据一个门禁修复冒称它已治理完毕。

Node语法和diff检查通过；后端源码/测试/固定CI清单未变，复用§317的465文件8049项静态回归，不重复后端全量。精确命令、首次失败/后续诊断/定向复验、当前源哈希、预算口径与审查/提交状态见[结果清单](refactor-results/miniprogram-transport-retention-2026-10-30.json)。保留结构不表示每个业务缺陷或真实微信网络都已验收；真实环境仍ENV-01..06最终阶段，生产验收最后，授权边界不变。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
