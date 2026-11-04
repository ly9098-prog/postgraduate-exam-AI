# 冷启动还原进行中的刷题/复习/番茄钟

> 状态：用户已确认刷题/番茄钟真机冷启动恢复成功；刷题系统返回仍被反馈绕过退出确认，本轮统一两种入口的返回拦截，待真机复验（2026-11-05）。本地回归通过不能替代真机结果。
> 范围：`miniprogram/`，不涉及后端与数据库。
> 前置：需求来自用户——打开小程序时若存在未完成的刷题会话或进行中的番茄钟，应回到该页面而不是固定进 home。

## 目标

冷启动（小程序进程被销毁后重新打开）且走默认入口时，按优先级还原用户离开时所在的页面：

1. 刷题页 `subpackages/study/practice/practice`
2. 今日复习 `subpackages/study/review-today/review-today`
3. 番茄钟 `pages/pomodoro/pomodoro`
4. 都没有 → 现有行为，进 `pages/home/home`

刷题页与今日复习互斥：用户离开时只会停留在其中一个页面，因此用单槽位活跃标记表达，不需要在两者之间排优先级。

## 已确认的设计决策

### 触发与时序

- 只在**冷启动**判断。热启动（从后台切回前台，页面栈仍保留）不跳转，不打断用户当前页面。
- 只在**默认入口**生效：没有指定页面、原本会经 `login` 落到 home 的路径。
- 深链接、分享卡片、二维码、订阅消息等显式目标路径优先，不覆盖。
- 登录成功后才判断，不使用未登录状态。状态按用户隔离，换账号不会跳到别人的会话。

### 启动解析顺序

1. 刷题页提交待确认记录：`practice_pending_submission_v1:<userId>`，状态 `pending` 或 `blocked` 时跳刷题页，由现有恢复弹窗接管；`submitted` 不触发。
2. 单槽位活跃标记：`practice` 或 `review-today`，按有效期校验。
3. 番茄钟：请求 `GET /pomodoro/active`，超时 1.5 秒。
4. 无命中 → home。

网络与延迟：第 1、2 步只读本地存储，瞬时完成；仅当前两步未命中时才请求番茄钟。请求失败或超时时，有本地快照按快照跳转，没有则进 home，不阻塞启动。

### 跳转方式

- 直接 `wx.reLaunch` 到目标页，页面栈中只有目标页（不在下面垫 home）。
- 刷题页与今日复习在栈长为 1 时通过控制器回到 home。
  - 刷题页：`subpackages/study/practice/utils/launch-return-controller.js` 的 `navigateWithoutStackTarget` 在 `getCurrentPages().length <= 1` 时 `reLaunch` 到 home；本轮修复 `returnToOrigin` 错把字符串传入微信 API、导致兜底不可达的问题。
  - 今日复习：`subpackages/study/review-today/utils/nav-back-controller.js` 同样有 `reLaunch` 到 home 的兜底。
- 按用户本轮追加要求，三个恢复页面增加单页栈系统返回处理；番茄钟返回 home 时保持运行/暂停会话，详见文末返回导航修复记录。此要求覆盖初版仅依赖原生导航栏的决定。

### 刷题页快照

现状：作答状态只在内存（`page._practiceSession`），进程被回收即丢失；唯一落盘的是提交时的待确认记录。

- 新增本地快照，内容：
  - 精简题目列表（沿用 `utils/recovery-questions-builder.js` 的 `recoveryQuestions` 格式）。
  - `batchToken`、`requestId`、`answerMap`、`answeredFlags`、`currentIndex`、`elapsedSec`、`questionTimeMap`，以及入口上下文（`_launch*`、选中的科目/模式/知识点作用域）。
- 写入时机：作答变化、切题、`onHide`。
- 清除时机：确认退出练习、提交开始（此后由 `practice_pending_submission_v1` 接管）。
- 有效期 24 小时，与服务端 `PRACTICE_BATCH_TOKEN_TTL_SEC`（`backend/app/services/practice/batch_token.py`）以及客户端待确认记录 TTL 对齐；过期视为无效并清除。
- 还原不弹窗，直接回到上次那道题与已答内容。
- 计时：按保存的已用时间接着计，进程被回收期间的时间不计入（与现有 `onHide` 暂停语义一致）。`activeStartedMonoMs` 需按 `monotonicNow() - savedElapsedMs` 重建，`backgroundMs` 归零。
- 还原失败（题目下架、拉取失败、登录过期）：清除标记，静默进 home。只有“网络失败但快照有效”保留快照，下次启动再试。

### 今日复习活跃标记

现状：`review_today_draft_v1:<userId>:<taskDate>` 草稿在确认退出后仍保留（`onUnload` 会再写一次），因此“有草稿”不等于“未退出”。

- 新增按用户隔离的轻量活跃标记，不改草稿现有行为。
- 置位：进入 `phase === 'reviewing'`。
- 清除：确认退出；进入 `group-result`（本组已提交，无未保存内容）。
- 有效期：仅同一天（`taskDate`）有效，跨天不还原。
- 还原方式：`reLaunch` 到 `review-today?autostart=1`，页面照常拉取下一批，由现有草稿逻辑恢复已答内容与位置（含“已恢复 N 题草稿”提示）。不新增题目快照。
- 依据：`POST /review/today/next-batch` 在同一天内、未提交任何内容时是确定性的（排序 `(next_review_at, schedule.id)`，无随机、无预留/锁），返回同一批题，`question_version_id`、`occurrence_seq` 稳定。
- 兜底：题目改版会让 `occurrence_seq` +1、多设备已提交会移出待办，草稿中匹配不上的条目被静默丢弃（现有行为），尽力而为；拉不到批次或今日无待复习时停在页面现有空状态/错误状态。

### 番茄钟判定

- 算作进行中：服务端 `running`、`paused` 会话，包括倒计时与正计时（自由计时）；本地已到点但服务端仍为 `running` 的倒计时也算，跳过去由页面自行结算。
- 不算：休息阶段（仅本地 `pomodoro_break`）、结算庆祝页。

## 改动落点

- 启动解析：新建独立模块（建议 `miniprogram/utils/launch-resume.js`），只负责“解析启动目标”，不持有页面逻辑。`pages/login/login.js` 中 4 处 `wx.reLaunch` 到 home（`_scheduleHomeRedirect` 与 `_autoLogin` 相关路径）统一改为调用该模块。
- `app.js`、`pages/home/home.js` 不改动。
- 三个目标页的钩子优先加在各自现有 `utils/` 控制器中，不改 `Page({})` 字面量（`practice.js` 的 `Page({...})` 被 `scripts/architecture/practice-boundaries.js` 与 `practice-page-templates.json` 按 token 冻结，共 113 个属性）。
- 新存储键：
  - 刷题页快照与活跃标记使用带用户前缀的动态键，加入 `miniprogram/utils/storage-core.js` 的 `SESSION_DYNAMIC_KEY_PREFIXES`，登出时按前缀清除。
  - 同步更新 `tests/test-storage-facade-contract.js` 中对前缀列表的钉死断言。

## 架构守卫影响

已知会受限的检查（必要时做最小更新，并在提交说明中列出理由）：

- `scripts/architecture/page-budgets.js`：`practice.js` 542、`pomodoro.js` 1596、`review-today.js` 645 均已在上限；新增逻辑必须放入 `utils/`，避免抬高页面上限。
- `scripts/architecture/practice-boundaries.js` + `practice-page-templates.json` + `tests/test-practice-module-boundaries.js`：新增页面属性/方法/require 需要同步冻结模板与属性计数。
- `scripts/architecture/review-today-boundaries.js` + `tests/test-review-today-module-boundaries.js`：钉死 `PAGE_MAX_LINES = 645`、24 个控制器、35 个 require。
- `scripts/architecture/learning-controller-budgets.js`：`subpackages/study/practice/utils`、review-today `utils`、pomodoro `utils` 下每个文件 ≤ 300 行、每个函数 ≤ 50 行。
- `tests/test-storage-facade-contract.js`：`SESSION_DYNAMIC_KEY_PREFIXES` 为 `deepEqual` 钉死。
- `miniprogram/utils` 不在通用行数预算内；主包与 study 子包有体积上限（`tests/test-main-package-size.js`）。

## 验收标准

- 冷启动且默认入口时：
  - 存在未提交的刷题会话 → 直接进入刷题页作答视图，题目、答案、位置、已用时间与离开时一致。
  - 存在未完成的今日复习 → 进入 `review-today` 并自动开始，已答内容按草稿恢复。
  - 仅有进行中番茄钟（含暂停）→ 进入番茄钟页。
  - 都没有 → 进入 home，行为与现在一致。
- 热启动不跳转；深链接不覆盖；未登录先登录再判断；换账号不还原他人会话。
- 提交开始、确认退出后，下次冷启动不再还原对应页面。
- 无论冷启动恢复还是从 home 正常进入刷题，作答中使用真机 back 均先弹出退出提示；确认后留在当前 `practice` Page 的刷题配置界面，取消继续作答。配置界面再次返回才离开页面。
- 超过 24 小时的刷题会话、跨天的今日复习标记不再还原。
- 新增 `node:test` 回归测试（风格与 `miniprogram/tests/` 现有用例一致），覆盖：
  - 启动目标解析：刷题页 / 今日复习 / 番茄钟 / 无会话 / 过期 / 换账号 / 深链接不覆盖 / 接口超时降级。
  - 刷题快照的写入、清除、还原与失效。
  - 今日复习活跃标记的置位、清除与日期边界。
- 现有回归脚本与架构守卫检查通过。
- 同步更新 `docs/` 下小程序相关文档。

## 不在范围内

- 套卷（`subpackages/exam/exam-runner`）、错题详情、错题本的冷启动还原。
- 后端接口、数据库、提交校验与批次令牌行为。
- 修改番茄钟计时、暂停及结算业务（返回导航按本轮追加要求修复）。
- 热启动（后台切回）的页面重定向。

## 待实现时核实

- 微信原生导航栏在栈长为 1 时是否显示“回首页”按钮（平台行为，仓库内无法验证）。
- 刷题页顺序模式的服务端预留（reservation）在快照还原后是否仍然有效，是否需要重新取批次凭据。
- `subpackages/study/practice/utils/submit-error-controller.js` 的失败路径与快照清除的衔接。
- 今日复习在题目刚改版或多设备提交时草稿只能部分恢复，需确认用户可接受的表现。
- 功能无法在本地端到端验证，最终需在微信开发者工具模拟器/真机走一遍。

## 手工验证清单（实现后交由用户执行）

1. 刷题进行中 → 杀掉小程序进程 → 重开：回到原题、答案与位置一致，计时接着走。
2. 刷题页确认退出 → 杀掉进程 → 重开：进 home。
3. 刷题提交成功 → 结果页返回/杀掉进程 → 重开：进 home。
4. 提交失败（待确认 `pending`/`blocked`）→ 冷启动：进刷题页并出现现有恢复弹窗。
5. 今日复习作答中 → 杀进程 → 重开：进入复习并提示已恢复 N 题。
6. 今日复习确认退出 → 杀进程 → 重开：进 home，但手动进入复习时草稿仍在。
7. 今日复习跨天（次日）冷启动：不还原。
8. 番茄钟运行中 / 暂停中 → 杀进程 → 重开：进入番茄钟并继续或保持暂停。
9. 番茄钟休息阶段 / 结算页 → 杀进程 → 重开：进 home。
10. 刷题会话与番茄钟同时存在 → 冷启动：进刷题页。
11. 热启动（后台切回）：不跳转。
12. 从分享卡片/深链接进入：目标页优先，无覆盖。
13. 登录过期后冷启动：先登录，登录成功后再按上述规则判断。
14. 换账号登录：不还原上一账号的会话。
15. 超过 24 小时的刷题会话：冷启动进 home。
16. 断网（番茄钟接口失败）但本地有刷题会话：进刷题页。

## 设计确认问答记录（grilling，2026-11-05）

逐轮确认过程与结论。`Q` 为问题，`推荐` 为提问时的建议，`结论` 为用户最终确认的答案。

### 第一轮

- **Q1 两者同时存在时怎么跳**：刷题页与番茄钟都有未结束会话时是否只跳刷题页。
  - 推荐：只跳刷题页，二选一取高优先级，不做页面叠加。
  - 结论：同意。
- **Q2 触发时机**：是否只在小程序冷启动（进程被销毁/后台超时回收后重开）判断，热启动不跳。
  - 推荐：只在冷启动判断，热启动保留原页面栈。
  - 结论：同意。
- **Q3 显式入口优先**：分享卡片、二维码、订阅消息、深链接是否优先于自动跳转。
  - 推荐：尊重显式目标路径，只替换“默认进 home”这一条路径。
  - 结论：同意。
- **Q4 未登录或登录过期**：是否先走正常登录，登录成功后再判断，并按用户隔离状态。
  - 推荐：登录后再判断，换账号不跳到别人遗留的会话。
  - 结论：同意。
- **Q5 “刷题页面”的范围**：除 `study/practice` 外，套卷 `exam/exam-runner`、今日复习 `study/review-today`、错题详情是否纳入。
  - 推荐：只算 `study/practice`，其余后续扩展。
  - 结论：**修正为 `study/practice` + `study/review-today`**；套卷、错题详情不纳入。

### 第二轮

- **Q6 刷题页与今日复习都有未完成会话时跳哪个**（第一轮遗留）。
  - 推荐：跳最近一次有操作的那个；无时间戳时固定 `practice` > `review-today`。
  - 结论：**用户纠正问题前提**——用户离开时只可能停留在其中一个页面，不存在两者同时未完成的情况，因此不需要排优先级。设计改为**单槽位活跃标记**。
- **Q7 刷题页要新增“进行中”持久化**：现状作答状态只在内存，冷启动后无内容可恢复；是否接受为此改动刷题页。
  - 推荐：接受，用本地存储快照，不改后端。
  - 结论：同意。
- **Q8 今日复习怎么判定“未退出”**：草稿在退出后仍保留，是否另加独立活跃标记。
  - 推荐：加独立活跃标记，进入作答置位，确认退出/提交完成清除，草稿行为不变。
  - 结论：同意。
- **Q9 提交失败的待确认记录算不算“未提交”**：`practice_pending_submission_v1` 的 `pending`、`blocked`。
  - 推荐：都算并触发跳转，由现有恢复弹窗接管；`submitted` 不算。
  - 结论：同意。
- **Q10 番茄钟哪些状态算“正在进行”**：是否包含暂停、正计时、休息、结算页、本地已到点但服务端仍 running。
  - 推荐：算 running/paused（含倒计时、正计时、本地已到点）；不算休息阶段和结算庆祝页。
  - 结论：同意。
- **Q11 网络与启动延迟**：先查本地再请求番茄钟，超时 1.5 秒，失败降级。
  - 推荐：先本地后服务端，超时 1.5 秒，失败时按本地快照降级，不阻塞进首页。
  - 结论：同意。
- **Q12 跳转后的返回栈**：A = `reLaunch` 到 home 再 `navigateTo` 目标页；B = 直接 `reLaunch` 到目标页。
  - 推荐：A，保证返回路径一致，接受首页闪烁。
  - 结论：**用户选择 B**，直接 `reLaunch` 到目标页。后续核实确认刷题页与今日复习在栈长为 1 时已有回 home 兜底；番茄钟依赖微信原生导航栏。

### 第三轮

- **Q13 进行中状态的有效期**：刷题快照 24 小时、今日复习标记仅当天、番茄钟不设有效期。
  - 推荐/结论：按此处理，同意。
- **Q14 还原失败时怎么办**：题目下架、拉取失败、登录过期等。
  - 推荐/结论：清标记，静默进 home；仅“网络失败但快照有效”保留快照，下次再试。同意。
- **Q15 还原时的交互**：直接还原还是弹窗询问“继续上次练习”。
  - 推荐/结论：直接还原，不弹窗。同意。
- **Q16 进程被回收期间的用时**：是否计入已用时间。
  - 推荐/结论：不计入，按保存的已用时间接着计，与现有 `onHide` 暂停语义一致。同意。

### 第四轮

- **Q17 刷题页怎么还原题目**：A = 本地存精简题目快照 + 批次令牌/答案/位置/用时；B = 只存题目 id，还原时按 `question_ids` 重新拉题。
  - 推荐：A，快照有效期与 `batchToken` 24 小时对齐，保证还原的会话仍可提交（B 会换发新批次令牌，题目下架/修订会导致整批被拒）。
  - 结论：同意 A。
- **Q18 番茄钟栈长为 1 时的返回**：是否接受不改 `pomodoro.js`，依赖微信原生导航栏“回首页”按钮。
  - 推荐/结论：接受，不动番茄钟页；安卓系统返回键在栈长为 1 时退出小程序为预期行为。同意。
- **Q19 改动落点与架构守卫**：启动判断放独立模块并统一替换 `login.js` 的 `reLaunch`；页面钩子放现有 `utils/` 控制器；必要时最小更新守卫并说明理由。
  - 推荐/结论：同意。
- **Q20 刷题快照与提交待确认记录的关系**：待确认记录优先，提交开始时清除快照，两者不同时存在。
  - 推荐/结论：同意。
- **Q21 测试与文档**：新增 `node:test` 回归测试，同步 `docs/`，真机/模拟器验证清单写入说明且不声称已验证。
  - 推荐/结论：同意。

### 第五轮

- **Q22 今日复习怎么还原**：`reLaunch` 到 `review-today?autostart=1`，由现有草稿恢复已答内容与位置，不新增题目快照；进入 `reviewing` 置位标记，确认退出或进入 `group-result` 清除；草稿匹配不上的条目尽力而为。
  - 推荐：按此处理，`group-result` 视为已完成，冷启动后不再还原。
  - 结论：同意。

### 设计依据（提问前核实的事实）

- `app.json` 首入口为 `pages/login/login`；`login.js` 是唯一的启动路由，4 处 `wx.reLaunch` 回 home；`app.js` 的 `onLaunch` 不做路由；`home.js` 无任何自动跳转。
- 刷题页作答状态仅在内存 `page._practiceSession`，无本地/服务端草稿；唯一落盘的是 24 小时有效的 `practice_pending_submission_v1:<userId>`。
- 今日复习草稿 `review_today_draft_v1:<userId>:<taskDate>` 在确认退出后仍保留，`onUnload` 会再写一次，故不能以草稿作为“未退出”依据。
- 番茄钟以服务端 `GET /pomodoro/active` 为准（`status IN ('running','paused')`）；本地 `pomodoro_running_state` 仅在页面 `onHide` 写入，进程被杀时可能缺失；休息阶段仅本地 `pomodoro_break`。
- `POST /review/today/next-batch` 同一天内未提交任何内容时结果确定（排序 `(next_review_at, schedule.id)`，无随机、无预留/锁），`question_version_id`、`occurrence_seq` 稳定；部分提交后窗口滑动，题目改版会触发重新绑定。
- 刷题页与今日复习在栈长为 1 时已有 `reLaunch` 回 home 兜底；番茄钟页无任何返回处理。
- 架构守卫：`practice.js` 的 `Page({})` 按 token 冻结（113 属性）；`page-budgets.js` 中 `practice.js` 542、`pomodoro.js` 1596、`review-today.js` 645 均在上限；`SESSION_DYNAMIC_KEY_PREFIXES` 被 `deepEqual` 钉死。

## 执行结果（2026-11-05）

- 启动解析：新增 `utils/launch-session-store.js` / `launch-resume.js`，登录后按待确认 `pending|blocked` 提交 → 单槽刷题/复习标记 → 番茄钟 active → home 解析，直接 `reLaunch`。仅默认登录入口、空 query 和普通启动场景生效；未知场景不恢复，热启动、显式入口和其它场景保持原流程。番茄钟请求使用 1500 ms client 网络超时、1500 ms 总等待上限，失败按当前用户有归属的本地快照降级。
- 刷题：`practice?resume=1` 由 `cold-resume-controller.js` 在现有 `onReady` 恢复精简题目、原请求/批次凭据、答案、位置、入口上下文和前台用时；作答/切题/`onHide` 写入，进入页面起固定 24 小时。确认退出、待确认提交成功持久化时清除或接管快照；取消确认继续保留。恢复后保留科目选择、静默加载科目树且禁止自动开新练习。恢复失败清除状态回 home，迟到 `onHide` 不重建。
- 复习：`review-active-state.js` 在初次批次/下一批/重试组/掌握撤销进入 `reviewing` 时置位，本组结果、empty、掌握移除最后一题、跨天、确认退出时清除；普通 overview 加载和瞬时 error 保留标记，草稿和 `onUnload` 行为不变。跨天恢复拒绝；进入时复用现有 `autostart`、next-batch 和草稿匹配。
- 隔离：刷题/复习动态键按用户前缀，显式登出清除；自动鉴权失效保留恢复键但清除身份，迟到回调按启动时 owner 校验。番茄钟快照 `session-storage` 写入 `ownerId`，页面读取与 reconciler 在 storage 边界校验归属，无身份迟到 `onHide` 不覆盖快照。
- 守卫：`practice.js` 542 行/113 属性、`review-today.js` 645 行/24 控制器、`pomodoro.js` 1596 行均未变。practice 守卫仅豁免三个既有责任模块对 `cold-resume-controller` 的直接 require；review 守卫登记四个适配器对 `review-active-state` 的依赖，require 35→39、适配器源预算 +6 行；通用 300/50 与包体预算通过。
- 验证：新增 36 项定向行为测试（含真实 Page 作答/切题/隐藏恢复、退出、交卷失败、科目树、登录隐藏/换身份、番茄钟归属），全量 `node --test tests/test-*.js` 2597/2597 通过；受影响 50 项相邻回归、5 fixture/31 渲染回归、architecture 守卫、主包/分包/媒体预算通过。已新增 5 个测试到 reliability 固定清单。
- 独立脚本 `node --test scripts/test-*.js` 为 25/28；3 个失败（`test-error-diagnosis`、`test-v5-ui-fixes`、`test-v8-fixes`）在未修改的 `HEAD` 归档副本同样失败，属于既有基线而非本任务回归。`codex review --uncommitted` 的两条 P2（跨用户番茄钟旧快照、恢复后科目树为空）均已先复现、修复并加回归测试。
- 文档：新增 `docs/frontend/LAUNCH_RESUME.md`，更新文档索引和相关链接。未改后端、数据库、OpenAPI、提交协议；未提交、推送、部署或同步 Windows 镜像。微信开发者工具编译/模拟器/真机、原生“回首页”、真实网络/预留/多设备场景及编译包质量扫描未验证，不能以 Node 测试替代。

## 复审修复（2026-11-05）

- 自动鉴权失效后重新登录可恢复一次：`api-auth` 增加进程内失效序号，`launch-resume` 在新登录入口检测未消费的失效序号；显式登出及普通热启动仍不恢复。新增真实 refresh 失败路径回归。
- 复习标记不再被普通 overview 加载或瞬时 error 清除；掌握操作移除本组最后一题仍通过显式清除路径回到 overview/empty，组结果、empty 和确认退出继续清除。新增保留与显式清除回归。
- 待确认交卷记录不再因设备时钟回拨产生的未来时间戳被删除，仅按 24 小时 TTL 清理；新增未来时间戳保留回归。
- 修复后全量 `node --test tests/test-*.js` 2601/2601 通过；review-today 架构守卫、practice 守卫、学习控制器预算、渲染 fixture 31/31、主包/分包/媒体预算和包体质量检查通过。微信开发者工具/真机验收仍未执行。

### 内聚与耦合复审修复

- 普通刷题快照也容忍设备时钟回拨，读写保留原始创建时间，原 24 小时过期边界不变；补充答案保留、启动目标、再次保存不续期和到期清理回归。
- 掌握移除最后一题及确认退出复习均通过独立 `clearReviewActivity` 端口清除标记；`clearReviewTimer` 仅负责计时，不再隐藏会话清理副作用。同步适配器固定契约，覆盖保留其他题目、overview/empty 和取消退出边界。
- 本轮先增加回归，6 项失败复现后修复至通过；首次全量检查发现固定端口契约需同步，已按新增的两个业务端口更新。本轮修复连同上一轮未提交修复一起提交；不包含既有无关改动、不推送或部署。
- 最终验证：全量 `node --test tests/test-*.js` 2603/2603 通过；practice/review-today 架构守卫、学习控制器/模块预算、渲染 31/31、主包/分包/媒体预算和包体质量检查通过。微信开发者工具编译及真机验收仍待完成。

## 真机失败排查（2026-11-05）

- 用户反馈已补充：刷题与番茄钟杀进程后重启均停在首页，内容未恢复；通过微信上传代码后在手机上实机测试。尚未取得实际 launch/enter 场景值和运行包版本。
- 已只读核对 Windows 镜像 `D:/workspace/postgraduate-ai/miniprogram`：`pages/login/login.js`、`utils/launch-resume.js`、practice `cold-resume-controller.js` 的 SHA-256 均与当前仓库一致；这只能排除这三个镜像文件落后，不能证明手机安装包版本或真实编译产物一致。
- 已复现的代码缺陷：旧白名单仅含 1001/1089/1090/1103/1104，体验版入口 1017 等默认入口即使有有效快照也直接回 home。已从微信官方 `wechat-miniprogram/api-typings/types/wx/lib.wx.app.d.ts` 核对场景定义，补入 1005/1006/1017/1023/1027；仍要求 login/空路径及空 query，不放宽分享、二维码、显式路径或未知场景。
- 新增 `launch-resume-diagnostics.js`：以 `debug_snapshot:launch_resume:v1` 保存最近 20 条安全元数据，区分入口拒绝、持久化失败/无效、恢复失败、番茄钟接口无活跃/不可用和跳转结果；不记录身份、凭据、题目、答案或 query 值。
- 回归：新增入口用例在修复前失败；修复后真实登录页与真实解析器联合测试覆盖体验版入口的刷题和暂停番茄钟。全量 `node --test tests/test-*.js` 2608/2608 通过，practice/review-today、学习控制器/模块预算、渲染 31/31、包体和媒体预算/质量检查通过。诊断测试已登记 reliability 固定清单。
- 已将本次四个运行源码文件同步到 Windows 上传镜像并逐个验证 SHA-256；同步前确认三个既有文件均与 HEAD 一致，新诊断文件不存在，旧文件备份于 `/tmp/postgraduate-launch-scene-backup-20261105T042354/`。配置和其他文件未改。
- 下一步：从该镜像重新上传后分别验证刷题与番茄钟，必要时读取上述诊断。现场实际 scene 未取得，不能认定白名单遗漏为唯一根因，也不宣称真机已通过。本轮未提交、上传、发布或部署。

## 恢复后返回导航修复（2026-11-05）

- 用户已确认上一轮修复后刷题、番茄钟冷启动成功；新增问题为刷题确认退出后停在选题界面，左上角按钮无反应、系统返回直接退出小程序。冷启动恢复成功与本轮导航复验分开记录。
- 根因：`returnToOrigin` 调用平台端口 `options.navigateBack(returnTo, 0)`，绕开控制器的栈匹配/根页兜底，并传入错误参数。现改为调用控制器内部 `navigateBack`；跳转锁保持至离开页面，home 跳转失败解锁并提示，卸载后延迟任务不导航。
- 系统返回：新增共享 `components/root-back-guard`，仅单页栈启用。刷题选题/已提交界面、练习结果页、复习非作答界面、番茄钟返回 home；复习作答通过事件委托既有确认流程，弹窗期间重复返回与取消后均重新拦截。刷题进行中保留原 guard，并以互斥模板避免双容器。普通多页栈和按钮知识点来源路由保持原策略。
- 高内聚低耦合检查：新组件只封装平台返回，不接触会话存储/计时/提交，不反向引用页面；退出确认继续由领域控制器负责。页面 `Page({})` 不增加方法，主包/分包依赖通过显式组件注册；组件 74 行、最长方法 15 行，无新 npm 依赖，300/50 与原页面预算不抬高。
- 回归先复现真实 Page→适配器→控制器的错误参数、冷恢复确认退出后按钮、普通栈/指定来源、卸载后延迟返回。补充系统返回 home、重复事件、失败重试、确认/取消、弹窗期间重复返回与组件登记覆盖。定向 58/58 通过；首次全量仅组件全局注册遗漏失败，已修复。
- 最终验证：全量 `node --test tests/test-*.js` 2619/2619 通过；practice/review-today/pomodoro/practice-result 边界、学习控制器/模块和页面预算、组件路径、主包/分包/媒体预算、包体质量检查通过；渲染 5 fixture/31 项全部通过。新增组件与诊断模块另按 `inspectSource` 校验 300/50 预算。
- Windows 上传镜像同步：仅新增或更新 14 个导航相关运行文件，与上一轮 4 个场景修复文件一起逐个验证 18 个运行文件 SHA-256 一致；既有目标文件先核对 HEAD 后备份至 `/tmp/postgraduate-root-back-backup-20261104T204650008125/`。未覆盖 `project.config.json` 或其他用户改动。提交范围包含上一轮尚未提交的默认入口/诊断修复，本轮不推送、上传、发布或部署。
- 平台限制：微信官方 `page-container` 文档注明鸿蒙 OS 暂不支持页面返回拦截；Android 物理返回、iOS 手势及原生导航仍需实机复验，不以 Node 模拟事件宣称真机通过。

## 两种入口的刷题系统返回统一修复（2026-11-05）

- 用户真机反馈：冷恢复作答时 back 直接退出小程序，正常进入作答时 back 直接回 home。目标统一为先弹出“退出练习？”，确认后回同一个 `practice` Page 的配置界面，取消保留作答。
- 已确认的结构问题：上一轮让配置阶段的共享 `root-back-guard` 和作答阶段的原生 `page-container` 通过 `wx:if` 交替创建。微信官方文档限定每页最多一个容器，已有时不能新增；本轮去除切换，刷题页只保留一个从首次渲染起一直挂载的原生实例，不再引入共享根页返回组件。现场平台回调仍未采集，不能以本地结构修复认定真机唯一根因。
- 控制器将会话退出确认与页面返回拦截分开：结束会话只清除确认状态，仍保留页面容器；作答 back 走原 `requestExitPractice` 确认和状态重置，配置 back 才委托 `launch-return-controller` 导航。真正导航时使用既有导航锁屏蔽迟到事件及重启回调，不增加页面路由分支或修改提交/计时职责。
- 回归先复现四个失败：两个入口确认后容器丢失、结束会话关闭页面拦截、模板条件创建原生容器。修复后新增真实 Page→适配器→控制器联合用例，覆盖正常 `startPractice` 和冷恢复的确认/取消/重复 back；断言页面栈不变、无路由 API 调用、确认后显示配置且保留科目。固定原生容器结构另有模板回归，不能替代真机操作。
- 验证：定向 95/95、全量 `node --test tests/test-*.js` 2624/2624 通过；增强“配置界面下一次 back 才回 home”断言后真实 Page 文件 10/10 通过。practice/review-today/pomodoro/practice-result 边界、300/50 与页面预算、组件路径、包体/媒体质量检查通过，渲染 5 fixture/31 项通过。刷题入口仍为 542 行/113 属性，无新增页面方法、npm 依赖或跨层引用。
- 已将五个运行文件同步到 Windows 上传镜像，先确认目标均等于本轮 HEAD，再备份于 `/tmp/postgraduate-practice-back-backup-20261104T210947938470/`，逐个校验字节一致；未修改项目配置和其他文件。两种入口的原生 back 弹窗、取消、确认回配置需重新上传后实机复验，本地事件测试不代表已通过。
