# 冷启动还原刷题、今日复习与番茄钟

更新：2026-11-05（Asia/Shanghai）。用户已确认刷题、番茄钟冷启动恢复成功；本轮返回导航修复仍待真机复验。后端、数据库及提交协议未改动。

## 启动边界

`pages/login/login.js` 完成现有登录与协议校验后，通过 `utils/launch-resume.js` 解析默认冷启动目标，直接 `wx.reLaunch`，不在目标页下方垫 home。`app.js`、`pages/home/home.js` 和三个目标页的 `Page({})` 均未修改。

仅默认登录入口、空 query 且识别为普通启动场景时启用。白名单为 `1001/1005/1006/1017/1023/1027/1089/1090/1103/1104`，其中 `1017` 为体验版入口，搜索和安卓桌面默认入口也可恢复。场景定义按微信官方 `wechat-miniprogram/api-typings` 的 `types/wx/lib.wx.app.d.ts` 核对；实际真机场景以诊断记录为准。显式路径、带参数入口及分享/二维码等其他场景沿用原有入口流程；未知场景不自动恢复。解析期间再次出现显式入口会取消本轮恢复。成功跳转后，普通热启动和登录页重入不再恢复；自动鉴权失效会记录进程内序号，重新登录后可再恢复一次，成功跳转即消费该序号。页面隐藏时延迟跳转，卸载或登录身份变化时拒绝迟响应跳转。

优先级：

| 顺序 | 条件 | 目标 |
| --- | --- | --- |
| 1 | 当前用户 24 小时内的待确认交卷为 `pending` / `blocked` | `practice?resume=1`，由原有恢复弹窗接管 |
| 2 | 单槽活跃标记为 `practice`，快照有效 | `practice?resume=1`，直接还原作答 |
| 2 | 单槽活跃标记为 `review-today`，`taskDate` 为北京时间当天 | `review-today?autostart=1`，沿用草稿恢复 |
| 3 | `GET /pomodoro/active` 返回 `running` / `paused` | 番茄钟页，含倒计时和正计时 |
| 4 | 未命中 | home |

前两步仅访问本地存储。番茄钟查询使用统一 API client，传入 1500 ms 网络超时及静默网络错误选项，并以独立的 1500 ms 总等待上限覆盖鉴权等待等情形。失败或超时仅在有当前用户归属的有效本地运行快照时进入番茄钟。本地休息/结算标记不触发番茄钟恢复，即使服务端仍返回进行中；但不会压过更早命中的刷题/复习本地状态。服务端成功返回无会话时以服务端为准。

## 用户隔离与持久化

| 键 | 用途 | 生命周期 |
| --- | --- | --- |
| `practice_resume_v1:<userId>` | 精简题目、批次凭据、答案、位置、前台用时及入口上下文 | 从进入刷题页开始固定 24 小时，作答/恢复不会续期 |
| `study_active_v1:<userId>` | 单槽 `practice` 或 `review-today` | 刷题依赖有效快照；复习仅同一北京时间自然日 |
| `practice_pending_submission_v1:<userId>` | 原有待确认交卷 | 保持原有版本、TTL 与恢复流程；`submitted` 不触发自动跳转 |
| `review_today_draft_v1:<userId>:<taskDate>` | 原有复习草稿 | 保持原有恢复和提交清理逻辑 |
| `pomodoro_running_state` | 原有番茄钟离线快照 | 写入时附加 `ownerId`；启动解析不采用无归属的旧快照 |

新动态键已登记到 `SESSION_DYNAMIC_KEY_PREFIXES`。显式登出按原会话清理流程移除；自动鉴权失效仅保留上述恢复键，重新登录后按用户身份重新匹配，不能使用其他账号的数据。番茄钟全局快照在启动解析和页面存储读取边界都校验归属；其他账号或无归属的旧快照不用于恢复，仍可通过服务端 active 查询恢复当前账号的会话。尚未重新登录时的迟到 `onHide` 不会覆盖已有归属快照。

旧页面的迟响应不能给新账号写入/清除活跃状态。

## 刷题恢复

`cold-resume-controller.js` 复用 `buildRecoveryQuestions()` 的精简题目格式，保存原始 `batchToken`、`requestId`、推荐请求 ID、答案/已答标记、当前位置、逐题用时与 `_launch*` 上下文；不保存渲染模型，在恢复时重新经过现有题目渲染控制器。快照在批次加载成功、作答变化、切题和 `onHide` 写入。

恢复时以 `monotonicNow() - savedElapsedMs` 重建起点，后台累计时间归零，逐题用时维持整数秒契约。进程被回收期间和确认弹窗暂停期间不计时。既有快照损坏、过期、缺少登录态或渲染失败时清除相应状态并返回 home。

设备时钟回拨后，刷题快照和待确认交卷不因时间戳暂时处于未来而被删除；读写仍保留原始创建时间，不续期。客户端 TTL 按设备时间计算，不能据此延长服务端批次凭据的有效期。

确认普通练习退出时清除快照/练习活跃标记，随后 `onHide` 不能重建；恢复成功后以保留选中科目、禁止自动开新练习的方式静默加载科目树，供退出后重新选题。交卷确认后生成提交对象时立即移交给原待确认存储，网络失败和确定性拒绝继续使用 `pending` / `blocked`。取消交卷确认保留快照；取消待确认恢复弹窗继续原有选题流程。原有“交卷仍在确认中，退出后可下次继续确认”的语义保留，未确认提交不会因退出而丢失。

顺序模式服务端预留和批次 token 均为 24 小时，见 `backend/app/services/practice/sequential_service.py` 和 `batch_token.py`；恢复复用原有凭据，不重新发起取题或延长服务端预留。恢复本身读取本地题目，不额外查询题目发布状态；题目撤下、版本变化、多设备提交或预留重置引起的服务端拒绝继续走既有提交边界，不能将本地恢复成功视为服务端已接受提交。

## 今日复习

初次批次、远端下一批、失败重试组、掌握撤销进入 `reviewing` 时写入单槽标记；进入 `group-result`/empty、掌握操作清除本组最后一题或确认退出时清除。掌握和退出控制器在相应业务分支显式调用 `clearReviewActivity`，`clearReviewTimer` 仅负责计时，不附带活跃状态清理。普通 overview 加载、瞬时网络错误不清除标记，便于下次冷启动继续重试；标记与草稿独立，`onUnload` 继续保存草稿也不会重建活跃标记。

恢复沿用 `autostart=1` 与现有 `/review/today/next-batch` / 草稿匹配。相同日期、未提交的待办排序不因本功能变化；题目改版或其他设备已提交导致匹配变化时，继续使用原有尽力恢复行为。无题/请求失败保留现有空态或错误态，不新增题目快照。

## 恢复后的返回导航

仍直接 `reLaunch` 到目标页，不预先加载 home。刷题确认退出后留在选题界面；
左上角按钮经过 `launch-return-controller` 解析返回来源，向微信 `navigateBack` 传入标准选项对象。
有匹配来源时返回原页面，无匹配时保留原跳转规则；单页栈无来源时 `reLaunch` 回 home。
跳转期间保留锁，失败时提示并解锁，延迟回调在页面卸载后不再导航。

刷题页从首次渲染起只保留一个不带 `wx:if` 的原生 `page-container`，配置、作答和已提交阶段共用同一个实例。
正常从 home 进入和冷启动单页栈恢复采用同一策略：作答时系统返回先弹出“退出练习？”；
取消保留题目、答案和计时，确认后只重置当前 Page 的刷题状态并显示配置界面，不调用路由 API。
配置界面再执行系统返回或点击左上角时，才通过原返回控制器离开页面；单页栈回 home，多页栈保留原来源规则。

`exit-guard-controller` 分开维护“会话需要退出确认”和“页面仍需拦截返回”：
确认结束会话不再关闭原生容器，避免配置到作答时销毁/重建返回容器；
只有真正离开页面时，由导航锁配合隐藏容器，屏蔽程序关闭产生的迟到回调。
原生容器重启期间的重复返回继续沿用确认锁，不重复弹窗；卸载或导航开始后不再重新显示容器。

`components/root-back-guard` 处理练习结果页、今日复习非作答阶段和番茄钟的单页栈系统返回，回到 home。
今日复习作答阶段通过事件调用既有退出确认并重新启用拦截；弹窗期间重复返回和取消后仍受保护，确认后仍由原控制器清除活跃标记和计时。
番茄钟只导航，不结束运行/暂停会话，保存仍由既有页面生命周期负责。
普通多页栈不启用该共享组件的拦截；刷题页不再使用该组件，避免与页面内原生容器交替创建。

组件只负责平台返回与 home 兜底，不读取业务存储、不依赖学习控制器；页面通过属性与事件提供退出确认策略。
组件在 `app.json` 和三个使用页面登记，避免 `requiredComponents` 配合上传时遗漏依赖。
页面的 `Page({})`、预算和计时/提交逻辑不变。新增组件为 74 行，最长方法 15 行，符合 300/50 预算。

系统拦截依赖微信 `page-container`；微信官方组件文档注明鸿蒙 OS 暂不支持拦截页面返回。
Android 物理返回、iOS 返回手势及原生导航栏的实际行为仍需真机验证。

## 验证与守卫

新增行为测试：

```bash
cd miniprogram
node --test tests/test-launch-resume.js tests/test-login-launch-resume.js \
  tests/test-launch-resume-diagnostics.js \
  tests/test-root-back-guard.js tests/test-practice-launch-return-controller.js \
  tests/test-practice-cold-resume.js tests/test-practice-cold-resume-page.js \
  tests/test-review-active-resume.js
node --test tests/test-*.js
node tests/render_regression/run.js
node tests/test-main-package-size.js
```

新测试已加入 reliability 固定清单。刷题边界守卫仅允许三个既有责任模块直接引入 `./cold-resume-controller`，其他依赖和平台访问继续受限。复习边界守卫增加四个适配器对 `review-active-state` 的依赖，require 总数 35→39，适配器总预算增加 6 行（新增四个 import、确认退出和掌握移除的两个显式活跃清理端口）；两个端口已登记到适配器契约测试。页面 645 行、24 个控制器及 300/50 通用预算保持不变。刷题页面 542 行、113 个属性与冻结模板未变。

### 手工验收

本地 Node 测试不替代微信平台验收。请在开发者工具及真机验证：

1. 刷题作答、切题后杀进程重开，题目/答案/位置一致，计时接着走。
2. 普通练习确认退出后重开进 home。
3. 提交成功后重开进 home。
4. `pending` / `blocked` 交卷重开进入原有恢复弹窗。
5. 复习作答后杀进程重开，自动开始且提示恢复草稿。
6. 确认退出复习后重开进 home，手动进入仍可恢复草稿。
7. 跨北京时间自然日不自动恢复昨日复习。
8. 倒计时/正计时运行或暂停后重开，进入番茄钟。
9. 番茄钟休息/结算页重开进 home。
10. 刷题和番茄钟同时存在时先进入刷题。
11. 后台切回不重定向。
12. 分享、二维码、订阅消息等显式目标不被覆盖。
13. 登录过期先登录，再按同一身份恢复。
14. 换账号不恢复上一账号数据。
15. 超过 24 小时的刷题快照不恢复。
16. 断网仍可直接恢复有效刷题快照；仅番茄钟时验证 1.5 秒超时及有/无本地快照两种降级。

另需确认：冷恢复及从 home 正常进入刷题后，系统返回均先确认，再停留在同一个 Page 的配置界面；
取消及弹窗期间重复返回不丢答案、不返回 home。配置界面再点击左上角或执行系统返回才回 home；
今日复习系统返回的确认/取消、结果页返回、番茄钟系统返回后会话仍可继续；
普通多页返回及知识点指定来源不回归。跨设备/顺序预留重置后的服务端拒绝、
多空题/图片/公式题真实渲染与编译包质量扫描仍待平台验收。

### 真机恢复诊断

`utils/launch-resume-diagnostics.js` 在 `debug_snapshot:launch_resume:v1` 保留最近 20 个事件。
诊断独立于开发环境开关，仅记录事件类型、时间、已知页面路径、场景值、query 数量和目标页；
未知路径统一写为 `other`，不记录参数值、身份、Token、批次凭据、题目或答案。
诊断写入失败只输出固定警告，不阻断恢复。沿用现有 debug snapshot 清理规则。

可在连接真机的调试控制台读取：

```js
wx.getStorageSync('debug_snapshot:launch_resume:v1')
```

- `entry_skipped`：入口或进程内消费条件不满足，可结合 scene/path/queryCount 排查。
- `entry_changed`：解析期间出现显式入口，取消恢复。
- `practice_saved` → `target_practice` → `practice_restored`：快照保存、启动选择和作答恢复完成。
- `practice_invalid` / `practice_save_failed` / `practice_missing` / `practice_restore_failed`：分别对应无效快照、落盘失败、恢复时快照缺失或页面恢复失败。
- `target_pomodoro` / `pomodoro_local`：服务端活跃或离线快照命中。
- `pomodoro_inactive` / `pomodoro_unavailable` / `pomodoro_terminal`：服务端无活跃会话、请求失败且无有效本地快照或处于休息/结算。
- `navigation_success`：登录页目标跳转成功；不代表目标页已完成渲染。

2026-11-05 首轮真机反馈刷题与番茄钟重开均进入首页；补入体验版等默认入口后，
用户确认冷启动恢复成功。现场实际 scene 仍未取得；本地真实登录页与解析器联合测试
覆盖体验版入口的刷题/暂停番茄钟跳转。本轮新发现的返回导航问题另行修复、复验。

## 相关链接

- [[docs/frontend/COMPONENT_RULES.md|COMPONENT_RULES]] — 小程序页面与组件规则
- [[docs/frontend/render-invariant.md|render-invariant]] — 题干渲染边界
- [[docs/architecture/REVIEW_WRONG_BOOK_COMPATIBILITY.md|REVIEW_WRONG_BOOK_COMPATIBILITY]] — 复习兼容边界
