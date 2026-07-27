你是一名资深全栈工程师、后端安全审计负责人、微信小程序负责人、测试负责人和发布负责人。

请对当前工作区的“错题导出为试卷”功能执行一次以真实代码为准的修复审计。不要根据历史报告或注释推定功能已经完成。必须检查实际调用链、依赖注入、数据库模型、生成文件、存储对象、小程序运行逻辑和自动化测试。

本次目标是：

1. 修复所有阻断 PDF/DOCX 导出正式开放的问题；
2. 验证后端创建、处理、下载、删除、重试、重新导出、过期清理的真实链路；
3. 修复小程序导出入口、设置页、记录页、下载、分享、WebSocket 和轮询；
4. 补齐能够证明实现有效的自动化测试；
5. 给出是否具备全量开放条件的证据化结论。

开始工作后，先输出不超过 12 条的执行清单，然后直接修改、测试和验证，不要等待再次确认。

# 一、已确认的阻断问题

以下问题已通过静态审计确认。必须逐项复核并修复，不得只更新注释或测试预期。

## 1. 小程序通用请求层运行时错误

文件：

```
utils/api.js
```

当前 `_rawRequest(method, url, data, header, timeout)` 调用 `wx.request` 时传入了未定义变量 `payload`，而不是形参 `data`。

要求：

- 修复所有 GET、POST、PUT、DELETE 请求；
- 增加带 wx mock 的运行时测试；
- 覆盖正常请求、401 刷新、网络失败、结构化错误解析；
- 测试必须实际调用 `_rawRequest` 路径，不能只做语法检查。

## 2. 本地存储生成路径与下载路径不一致

当前：

- `LocalFileStorage.upload()` 基于后端根目录写入；
- `_resolve_local_path()` 基于 `app/api/v1` 向上两级解析，实际会定位到 `app/static/exports`；
- 默认 `EXPORT_DIR` 为 `static/exports`。

要求：

- 建立唯一的导出存储根目录解析函数；
- 上传、存在性检查、下载、删除和 cleanup 必须复用同一解析逻辑；
- 不允许 API 层自行拼接另一套目录；
- 默认导出目录迁移到非公开静态目录，例如 `var/exports` 或项目现有私有数据目录；
- 防止目录穿越、符号链接逃逸和绝对路径泄露；
- 添加真实临时目录测试，验证上传后可下载、删除后不存在。

## 3. COS 对象 key 不一致

当前上传对象实际包含 `static/exports/` 前缀，但任务只保存 `taskId/文件名`。后续签名 URL 和删除使用任务中的相对 key，可能指向不存在的 COS 对象。

要求：

- 明确定义 canonical storage key；
- 上传成功后保存可供下载、删除、exists 使用的 canonical key，而不是忽略上传返回结果；
- COS 上传、签名、删除、exists 必须使用完全相同的 key；
- 签名 URL 必须短时有效；
- 不得返回永久公开 URL；
- COS 未配置或上传失败时，禁止产生“completed 但文件不可访问”的任务；
- 如果保留本地 fallback，必须记录实际 backend，并保证下载分支能识别；否则对导出功能禁用 fallback 并明确失败。

## 4. 重新导出没有真正复用快照

当前 re-export 接口加载原快照并把 `snapshot_id` 写入新任务，但 processor 仍调用 `resolve_range()`、`build_snapshot_data()` 和 `create_snapshot()`，会重新读取当前错题数据并覆盖快照引用。

要求：

- 给任务明确增加“复用快照”处理路径；
- re-export 必须直接加载原快照生成文件；
- 原错题被编辑、停用或删除后，re-export 内容仍应与原快照一致；
- 不得创建无引用的孤儿快照；
- 设计快照生命周期：
  - 可以每个任务复制独立快照；
  - 或实现引用检查/引用计数；
- 删除一个任务不得破坏仍被其他任务使用的快照；
- 增加原任务删除、源错题修改、多个 re-export 并存的测试。

## 5. 删除和 cleanup 虚假成功

当前 API 和 cleanup 只捕获异常，没有检查 `storage.delete()` 返回的布尔值。返回 `false` 时仍会删除数据库记录或增加 `files_deleted`。

要求：

- 统一 StorageBackend 删除契约；
- 返回 `false` 必须视为删除失败；
- 不得在文件删除失败时错误统计为成功；
- 明确数据库记录删除策略：
  - 建议采用软删除或保留可重试清理状态；
  - 至少确保不会失去残留文件的定位信息；
- cleanup 删除失败后应允许下一次重试；
- 添加本地存储、COS、返回 false、抛异常、对象不存在和重复删除测试；
- 所有测试必须 patch 或注入生产代码实际使用的 `get_export_storage()`，不得 mock `get_storage()` 造成假阳性。

## 6. 跨进程 WebSocket 推送缺少 user_id

当前 processor 调用 `build_status_event()` 时未传入 `user_id`。Redis subscriber 根据事件中的 `user_id` 路由，导致 scheduler 与 web 分离部署时无法向用户推送。

要求：

- Redis 事件必须包含正确的用户标识；
- 用户标识只用于内部路由，日志中按项目规范脱敏；
- 测试 scheduler 发布、web 订阅和指定用户连接收到消息；
- 测试其他用户不能收到事件；
- Redis 不可用时轮询仍可正常完成任务状态同步。

## 7. selected IDs 部分越权未拒绝

当前 `_resolve_selected()` 会过滤不属于用户的 ID，只在所有 ID 均无效时失败。

要求：

- 只要请求中存在任意不属于当前用户、已停用或不存在的 ID，整个请求必须拒绝；
- 对外返回统一结构化错误，不透露具体哪个 ID 存在或属于谁；
- 日志不得记录题目正文；
- preview-count 和 create 必须使用相同验证规则；
- 增加“部分合法、部分越权”的测试。

## 8. create 未执行同步范围和数量验证

当前 create 只创建 pending 任务，范围解析、0 道和 100 道上限到 processor 才检查。客户端可以绕过 preview-count。

要求：

- create、retry、re-export 在创建任务前执行适用的同步校验；
- 0 道返回 `no_questions`；
- 超过上限返回 `too_many_questions`；
- 越权返回统一错误；
- 不创建注定失败的 pending 任务；
- preview-count 负责返回真实数量，不应因为超过上限而无法返回 101 等数量；
- 创建接口独立执行上限检查，不能信任前端 preview 结果；
- 最大数量必须来自配置，而不是多处硬编码 100。

## 9. 能力和配置仍未完全统一

要求建立统一能力服务，至少包含：

- `get_export_capability(user_id)`；
- `ensure_new_export_allowed(user_id)`；
- `ensure_format_allowed(format)`；
- `validate_export_range(...)`；
- 已有资源访问校验。

必须区分：

### 新建类权限

适用于：

- preview-count；
- create；
- retry；
- re-export；
- WebSocket 是否启用。

受以下配置控制：

- 总开关；
- allow-all；
- 白名单；
- DOCX 开关；
- 最大题目数；
- 并发限制。

### 已有资源权限

适用于：

- 记录列表；
- 任务详情；
- 下载；
- 文件流；
- 删除。

只校验：

- 当前用户拥有任务；
- 状态允许；
- 未删除；
- 未过期；
- 文件存在。

总开关关闭或用户被移出白名单后：

- 禁止新建；
- 已有记录仍可查看；
- 有效已完成文件仍可下载；
- pending/processing 任务继续处理。

同时修复：

- 总开关关闭应返回 `feature_disabled`；
- 白名单不匹配应返回 `user_not_allowed`；
- 非法白名单字符串不能导致请求 500；
- 白名单解析应处理空格、重复值、空字符串和非法 ID；
- capabilities 中的 max count 和 retention days 必须来自配置；
- 最大题目数和保留天数不得硬编码在 service、resolver 和 schema 多处。

## 10. processor 并发和时间处理

审计并修复：

- 当前 processor 循环是否真正并行处理 `_MAX_CONCURRENT` 个任务；
- PDF/DOCX 并发配置是否实际生效；
- 不得只创建 Semaphore 却仍串行 await 每个任务；
- timeout、heartbeat、zombie recovery 的状态转换必须一致；
- timeout 和异常路径也要发布终态事件；
- DateTime 全部使用项目统一 UTC 规则，避免 aware/naive 混用；
- `completed_at`、`expires_at`、下载过期比较和 cleanup 比较必须一致；
- `retry_count` 和 `source_task_id` 必须正确记录。

## 11. 文件不存在与运维工具

要求：

- completed 但文件不存在时返回 `file_not_found`；
- 记录 `export_file_missing`；
- 明确任务是否转为 failed 或保留 completed 并允许 re-export；
- 管理命令调用的 StorageBackend 方法必须真实存在；
- 当前 orphan-scan 使用 `storage.exists()`，需要补齐接口及本地/COS实现；
- 统计必须来自数据库或持久化日志，不能仅依赖进程重启即清零的内存计数；
- 提供任务总数、PDF/DOCX、completed、failed、timeout、平均/最大耗时和 cleanup 结果查询。

# 二、小程序必须修复的问题

## 1. API 地址错误

`services/export.js` 的 `getFileUrl()` 使用 `config.apiBase`，而当前配置导出的是 `BASE_URL`。

要求统一 API base 命名，并增加 URL 构造测试。

## 2. WXML 非法表达式

当前导出页面 WXML 使用：

- `.find()`；
- 箭头函数；
- optional chaining；
- `.toFixed()`；
- `_taskStatus(item)` 页面方法调用。

要求：

- 所有展示值在 JS 中预计算并写入 data；
- WXML 只使用受支持的属性读取、简单条件和运算；
- `SORT_OPTIONS`、`GROUP_OPTIONS`、`POSITION_OPTIONS`、`SPACE_OPTIONS` 必须放入页面 data；
- 记录列表预先生成 `statusLabel`、`statusTone`、`fileSizeText`、格式文本和日期文本；
- 删除页面 JSON 中不适用于 Page 的 `"component": true`；
- 通过微信开发者工具实际编译验证。

## 3. picker 值处理错误

微信 picker 的 `e.detail.value` 是选项索引，不是业务枚举值。

修复：

- 根据索引读取对应 option.value；
- sort/group/answer/analysis/space 都要修复；
- format 点击使用 `dataset.value` 或正确的 radio-group change；
- 不能向后端提交 `"0"`、`"1"` 等索引；
- 配置切换不得丢失其他字段。

## 4. 能力请求和入口安全降级

当前错题本导出按钮始终显示，只在点击后检查能力；导出设置页同时发起 capabilities 和 preview-count，可能先发送未授权 preview。

要求：

- 错题本 onShow 获取 capabilities；
- 允许时显示导出按钮；
- 不允许或请求失败时隐藏导出按钮；
- 导出记录入口按“已有资源仍可访问”策略保留；
- 设置页先完成 capability 检查，再请求 preview；
- `export_enabled=false` 时禁止所有新建操作并给出简洁提示；
- 直接通过 URL 打开设置页也必须安全；
- DOCX 开关只影响 Word，不能影响 PDF 和纯计数。

## 5. 范围和计数状态

要求：

- selected 模式无 selected IDs 时禁用；
- filtered 模式没有真实 filters 时不能退化为 all；
- all 模式不携带页面 filters；
- preview loading、preview error、count < 1、count > max 时均禁用提交；
- 当前 `previewCount=-1` 仍可能启用按钮，必须修复；
- 最大数量从 capabilities 获取，不要硬编码 100；
- 100 道允许，101 道显示明确错误。

## 6. 结构化错误码映射

建立统一用户提示映射：

- `feature_disabled`；
- `user_not_allowed`；
- `docx_disabled`；
- `too_many_questions`；
- `no_questions`；
- `too_many_concurrent`；
- `file_expired`；
- `file_not_found`；
- `storage_failed`；
- `service_unavailable`。

禁止：

- 直接展示内部异常；
- 在记录页直接显示服务端原始 `error_message`；
- 出现 `[object Object]`。

## 7. WebSocket 和轮询生命周期

当前实现存在：

- 每个任务创建一条 WebSocket；
- fallback 轮询返回的 stop 函数未保存；
- 页面隐藏或卸载后 fallback 轮询仍可能继续；
- WebSocket 正常时 15 秒后仍启动备份轮询；
- 进入 polling 后 `usePolling=true`，后续无法恢复 WebSocket；
- 可能存在重复连接和重复定时器。

要求重构为页面级状态同步管理器：

- 每个页面或用户最多一条 WebSocket；
- 根据 task_id 分发事件；
- WebSocket 关闭配置时直接轮询；
- 断线后启动一个轮询；
- 重连成功后停止轮询；
- 页面隐藏时停止连接和定时器；
- 页面显示时恢复；
- 页面卸载时彻底清理；
- 所有任务终态后停止同步；
- 增加 fake timer 和 wx socket mock 测试。

## 8. 下载、保存和分享

要求：

- 本地流下载 URL 正确；
- 下载携带 Authorization；
- 下载 401 时支持一次 token 刷新并重试；
- PDF/DOCX MIME 和 openDocument fileType 正确；
- 中文文件名可保存；
- 分享改为微信小程序支持的分享机制，例如 `button open-type="share"` 配合 `onShareAppMessage`；
- 分享接收者不能越权访问文件；
- 当前分享页面只高亮任务 ID，不代表接收者获得下载权限，必须明确产品行为。

# 三、测试与验证

当前提交包中没有可见 pytest 测试或迁移目录，因此不得声称“完整测试已通过”。

必须补齐并执行：

1. Python compileall；
2. 后端完整 pytest；
3. 导出 API 测试；
4. capability/preview/create 权限测试；
5. selected IDs 越权测试；
6. 本地和 COS storage contract 测试；
7. 删除、cleanup、重复清理和失败重试测试；
8. snapshot、retry、re-export 生命周期测试；
9. processor timeout、zombie、并发测试；
10. Redis/WebSocket 跨进程路由测试；
11. PDF 真实生成与文本提取测试；
12. DOCX 真实生成、解压 Open XML、`w:tbl` 和 `m:oMath` 测试；
13. 100 道 PDF 和 100 道 DOCX；
14. formula catalog；
15. 数据库迁移测试；
16. lint 和类型检查；
17. 所有小程序 JS 的 node 语法检查；
18. 小程序 API、picker、错误码和同步管理器单元测试；
19. 微信开发者工具构建或可复现的 CLI 构建；
20. 页面隐藏、显示、卸载和终态清理测试。

每条测试必须报告：

- 完整命令；
- collected；
- passed；
- failed；
- skipped；
- xfailed；
- warnings；
- duration。

没有执行的检查必须写“当前环境无法验证”，不得写成已通过。

# 四、端到端验收

使用真实 API、数据库、processor 和存储完成：

## PDF

capabilities → preview → create → pending → processing → completed → 下载 → 打开 → 删除 → 删除后不可下载。

## DOCX

格式开关 → create → processor → 下载 → 打开 → 原生表格 → OMML → 删除 → 过期。

## 权限变化

- 白名单用户可创建；
- 移出白名单后不能新建；
- 原有效文件仍可下载；
- allow-all 后普通用户可创建；
- 总开关关闭后不能新建；
- 原有效文件仍可下载。

## 格式关闭

- DOCX 关闭时 PDF 正常；
- DOCX create 被拒绝；
- preview-count 不依赖 DOCX；
- 已有 DOCX 仍可下载；
- 小程序 Word 选项禁用。

# 五、发布安全

检查并补齐：

- `.env.example`；
- 最大题目数；
- 保留天数；
- processor 间隔；
- task timeout；
- zombie 阈值；
- 每用户并发；
- 私有本地目录；
- COS key 前缀；
- COS 签名有效期；
- allow-all 默认 false；
- 白名单默认空；
- 不硬编码真实用户 ID；
- 配置日志只记录开关和白名单数量；
- 不记录 JWT、openid 明文、签名 URL、COS key、私有路径、题目正文、答案和解析。

# 六、最终回复格式

严格按照以下结构输出：

## 1. 最终结论

只能选择：

- 已具备全量开放条件；
- 已完成全量开放；
- 暂不具备全量开放条件。

没有生产权限时不得使用“已完成全量开放”。

## 2. 执行清单完成情况

逐项对应开始时的执行清单。

## 3. 阻断问题处理

逐项说明本 Prompt 中每个 P0/P1 问题的根因、修改和证据。

## 4. 修改文件

列出路径和用途。

## 5. 完整测试结果

列出每条命令和统计。

## 6. 端到端验证

分别报告 PDF、DOCX、processor、本地存储、COS、删除、过期和权限变化。

## 7. 小程序验证

报告入口、设置、记录、下载、保存、分享、WebSocket、轮询和错误码。

## 8. 内容一致性

列出实际比较字段、题目数量、PDF 提取证据和 DOCX XML 证据。

## 9. 安全验证

报告鉴权、越权、私有路径、签名 URL、删除、过期和日志脱敏。

## 10. 开关演练

报告总开关、DOCX、WebSocket、白名单和 allow-all 的预期及实际结果。

## 11. 发布与回滚

给出可直接执行的步骤。

## 12. 已知限制

只列真实且不阻断核心需求的限制。

## 13. 产物

列出测试报告、PDF、DOCX、日志、SQL、部署文档和回滚文档的相对路径。

## 14. 最终验收表

每项标记：

- 已验证；
- 部分支持；
- 未完成；
- 当前环境无法验证。

所有“已验证”必须附具体测试、日志、文件或实际操作证据。

禁止仅凭代码存在、注释、mock、内存对象或历史报告判定功能完成。
