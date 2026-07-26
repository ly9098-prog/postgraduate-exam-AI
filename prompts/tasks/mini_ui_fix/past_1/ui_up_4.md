任务名称：为 pomodoro 页面新增“自由计时 / 正向计时”功能

背景：
当前项目已经完成 Pomodoro 科目体系修复：
1. pomodoro_sessions 已使用 subject_id 关联 subjects.id。
2. pomodoro 页面已根据 subjects 表动态渲染可选子级科目。
3. 小程序启动番茄钟时已经传 subject_id。
4. 后端 active / history / stats 等接口已经支持 subject_id、subject_code、subject_name。
5. 废弃 subject 字符串字段不应再作为主数据来源。

现在需要在现有 pomodoro 页面中新增“自由计时 / 正向计时”模式：
用户点击开始后，从 00:00:00 开始递增计时；
允许暂停、继续；
点击结束时弹窗确认；
用户确认后，记录本次实际计时时长；
该记录进入现有 pomodoro_sessions、历史记录和统计体系。

重要原则：
1. 不要新建独立 timer 表，复用现有 pomodoro_sessions。
2. 不要破坏现有标准番茄钟、长时间番茄钟、自定义番茄钟、暂停、继续、完成、统计、历史记录逻辑。
3. 自由计时必须继续使用 subject_id 记录科目。
4. 自由计时不进入休息倒计时流程。
5. 自由计时不需要订阅提醒或到点提醒。
6. 正向计时显示必须使用 HH:MM:SS。
7. 暂停时长不得计入最终 actual_duration。
8. 小程序页面隐藏、锁屏、返回后再次进入，应能从 active session 恢复正确计时状态。
9. 如果存在 active session，不允许重复开始新的计时。
10. 完成后必须进入现有历史和统计数据。

一、需要先检查的代码位置

请先全局搜索以下关键词，确认当前实现：

- pomodoro
- PomodoroSession
- PomodoroStartRequest
- PomodoroCompleteRequest
- PomodoroSessionResponse
- preset
- work_duration
- break_duration
- actual_duration
- pause
- resume
- active
- complete
- pages/pomodoro
- startPomodoro
- pausePomodoro
- resumePomodoro
- completePomodoro
- selectedSubjectId
- subject_id

重点检查目录：

- backend/app/models/
- backend/app/schemas/
- backend/app/api/v1/
- backend/app/services/
- backend/alembic/
- miniprogram/pages/pomodoro/
- miniprogram/pages/pomodoro-stats/
- miniprogram/utils/

二、功能定义

新增模式名称：

中文：自由计时
英文标识：free
计时方式：正向递增
目标时长：无
休息时长：无
是否触发完成提醒：否
是否进入休息阶段：否
是否进入统计：是
是否进入历史：是

建议 preset：

preset = "free"

如果后端当前 preset 使用枚举，需要新增 free。
如果当前 preset 只是字符串校验，也要补充 free 的合法校验。

三、后端 Schema 修改

1. PomodoroStartRequest

需要支持：

{
  "subject_id": 7,
  "preset": "free",
  "work_duration": 0,
  "break_duration": 0
}

要求：
- subject_id 必填。
- preset 支持 free。
- preset=free 时：
  - work_duration 可以为 0 或 null。
  - break_duration 可以为 0 或 null。
  - 不要校验 work_duration 必须大于 0。
- preset 非 free 时，保留原有 work_duration 校验逻辑。

建议规则：

if preset == "free":
    work_duration = 0
    break_duration = 0
else:
    work_duration 必须大于 0

2. PomodoroCompleteRequest

检查当前 complete 接口是否支持传实际时长。
如果没有，请新增字段：

actual_duration_sec: int | None = None
total_paused_sec: int | None = None

自由计时完成时，前端传：

{
  "actual_duration_sec": 1832,
  "total_paused_sec": 120
}

处理规则：
- preset=free 时，优先使用 actual_duration_sec。
- 后端仍需做安全校验：
  - actual_duration_sec 必须 >= 0。
  - actual_duration_sec 不应明显大于 server_now - started_at。
  - 如果前端未传 actual_duration_sec，则后端根据 started_at、paused_at、total_paused 计算。
- 对于普通倒计时番茄钟，保持现有 complete 行为。

3. PomodoroSessionResponse

确保响应包含：

id
subject_id
subject_code
subject_name
preset
work_duration
break_duration
status
started_at
completed_at
paused_at
actual_duration
actual_duration_sec
total_paused_sec
is_free_timer 或 mode

如果不想新增 is_free_timer，可以由前端通过 preset === "free" 判断。

四、后端模型 / 数据库

优先复用现有字段。

请先检查 pomodoro_sessions 是否已有以下字段或等价字段：

- preset
- work_duration
- break_duration
- actual_duration
- started_at
- completed_at
- paused_at
- status
- total_paused_time / total_paused_sec / paused_duration

如果已有字段足够支持自由计时，不要新增字段。

如果没有累计暂停时长字段，建议新增：

total_paused_sec INTEGER DEFAULT 0

作用：
- 记录累计暂停秒数。
- pause 时记录 paused_at。
- resume 时计算 now - paused_at，并累加到 total_paused_sec。
- complete 时 actual_duration = now - started_at - total_paused_sec。

如果当前项目已经有暂停累计字段，请复用现有字段，不要重复新增。

五、后端业务逻辑

1. POST /api/v1/pomodoro/start

新增支持 preset=free。

请求示例：

{
  "subject_id": 7,
  "preset": "free",
  "work_duration": 0,
  "break_duration": 0
}

处理要求：
- 校验当前用户是否已有 active / running / paused session。
- 如果已有未完成 session，返回错误或返回现有 active session，避免重复创建。
- 校验 subject_id 存在且 is_active=true。
- 如果 subject_id 是有 active children 的父级科目，应返回错误：“请选择具体子科目”。
- 创建 session：
  - preset = "free"
  - work_duration = 0
  - break_duration = 0
  - status = running
  - started_at = now
  - total_paused_sec = 0
  - actual_duration = null 或 0
- 返回 session response。

2. POST /api/v1/pomodoro/{session_id}/pause

自由计时和普通番茄钟都应可暂停。

处理要求：
- session 必须属于当前用户。
- session 状态必须是 running。
- 设置 status = paused。
- 设置 paused_at = now。
- 不要修改 started_at。
- 返回 session response。
- 对 free 模式不做额外限制。

3. POST /api/v1/pomodoro/{session_id}/resume

处理要求：
- session 必须属于当前用户。
- session 状态必须是 paused。
- 如果 paused_at 存在：
  - paused_delta = now - paused_at
  - total_paused_sec += paused_delta
- 设置 paused_at = null。
- 设置 status = running。
- 返回 session response。

4. POST /api/v1/pomodoro/{session_id}/complete

自由计时完成逻辑：

- session 必须属于当前用户。
- session 状态必须是 running 或 paused。
- 如果状态是 paused 且 paused_at 存在：
  - 完成时不要把暂停后的等待时间计入 actual_duration。
  - 可先累加截至完成时的暂停时长，也可以直接使用前端 actual_duration_sec。
- 如果 request.actual_duration_sec 存在：
  - 使用该值作为实际专注时长。
  - 但需要做合理校验。
- 如果 request.actual_duration_sec 不存在：
  - actual_duration_sec = now - started_at - total_paused_sec
- 如果 actual_duration_sec < 0，归零。
- 设置 status = completed。
- 设置 completed_at = now。
- 设置 actual_duration / actual_duration_sec。
- preset=free 时不进入 break 状态，不触发休息倒计时。
- 返回完成后的 session response。

5. GET /api/v1/pomodoro/active

要求：
- 如果存在 preset=free 且 status=running 的 session，返回完整 started_at、total_paused_sec、paused_at。
- 如果存在 preset=free 且 status=paused 的 session，也返回。
- 前端需要根据返回值恢复计时：
  - running：继续正向递增。
  - paused：显示暂停时刻的已计时时长，不继续递增。

6. GET /api/v1/pomodoro/history

要求：
- 自由计时记录应该正常出现在历史列表。
- 返回 preset=free。
- 返回 subject_name。
- 返回 actual_duration_sec。
- 前端展示为：
  - 类型：自由计时
  - 时长：xx小时xx分xx秒
  - 科目：subject_name

7. GET /api/v1/pomodoro/stats / trends

要求：
- 自由计时记录应纳入总专注时长。
- 自由计时记录应纳入科目统计。
- 如果有“完成番茄数”统计：
  - 建议自由计时不计入传统番茄个数，或单独显示为“自由计时次数”。
  - 如果当前统计结构暂时无法区分，可以先将 free session 计入 sessions 数，但 UI 文案应避免叫“番茄数”。
- 不破坏原有统计。

六、小程序页面 UI 改造

目标：
在 pages/pomodoro 页面增加自由计时入口，并保持页面简洁。

建议 UI 结构：

1. 科目选择区
- 继续使用修复后的动态科目列表。
- 必须先选择科目才能开始计时。

2. 模式选择区
当前可能有：
- 标准
- 长时间
- 自定义

新增：
- 自由计时

建议文案：
- 标准 25分钟
- 长时 50分钟
- 自定义
- 自由计时

3. 计时显示区

普通番茄钟：
- 保持原倒计时显示。

自由计时：
- 显示 HH:MM:SS。
- 初始显示 00:00:00。
- 开始后每秒递增。
- 暂停时停止递增。
- 继续后恢复递增。

4. 状态文案

未开始：
- 选择科目后显示“准备开始自由计时”

运行中：
- “自由计时中”

暂停中：
- “已暂停”

完成后：
- “本次自由计时已记录”

5. 按钮文案

未开始：
- 开始计时

运行中：
- 暂停
- 结束

暂停中：
- 继续
- 结束

结束按钮：
- 不要直接结束，必须弹窗确认。

七、小程序前端状态设计

建议 data 中增加或调整：

timerMode: 'pomodoro' | 'free'
selectedPreset: 'standard' | 'long' | 'custom' | 'free'
isFreeTimer: false
elapsedSec: 0
actualElapsedSec: 0
totalPausedSec: 0
freeTimerStartedAt: null
freeTimerPausedAt: null
timerInterval: null
activeSession: null
isRunning: false
isPaused: false

如果已有状态字段，请尽量复用，避免大规模重构。

八、自由计时前端计算规则

不要只依赖 setInterval 的累加值。
正确做法是基于 started_at 和 total_paused_sec 计算，这样锁屏、后台、页面隐藏后恢复不会错。

运行中 elapsedSec 计算：

elapsedSec = floor((Date.now() - startedAtMs) / 1000) - totalPausedSec

暂停中 elapsedSec 计算：

elapsedSec = floor((pausedAtMs - startedAtMs) / 1000) - totalPausedSecBeforeCurrentPause

如果后端 totalPausedSec 已经包含当前暂停前的累计暂停时长，则暂停中保持 lastElapsedSec 不变。

简单实现方案：
1. start 后记录 started_at。
2. 每秒调用 updateFreeElapsed。
3. updateFreeElapsed 中：
   - 如果 running：
     elapsed = now - started_at - total_paused_sec
   - 如果 paused：
     elapsed 保持暂停时的值。
4. resume 成功后，以后端返回的 total_paused_sec 重新计算。

九、自由计时启动流程

前端点击“开始计时”：

1. 如果未选择科目：
   wx.showToast({ title: '请选择科目', icon: 'none' })
   return

2. 请求：

POST /api/v1/pomodoro/start

{
  "subject_id": selectedSubjectId,
  "preset": "free",
  "work_duration": 0,
  "break_duration": 0
}

3. 请求成功：
- 保存 activeSession。
- 设置 isFreeTimer=true。
- 设置 isRunning=true。
- 设置 isPaused=false。
- elapsedSec=0。
- 启动本地 interval，每秒更新显示。

4. 请求失败：
- 如果提示已有 active session：
  - 调用 /pomodoro/active 尝试恢复。
- 其他错误正常 toast。

十、自由计时暂停流程

点击“暂停”：

1. 调用：

POST /api/v1/pomodoro/{session_id}/pause

2. 成功后：
- 清理 interval。
- 设置 isPaused=true。
- 设置 isRunning=false。
- 保存 paused_at。
- 保持 elapsedSec 不变。
- 更新按钮为“继续 / 结束”。

注意：
- 暂停按钮不要仅做本地暂停，必须同步后端。
- 如果网络失败，提示“暂停失败，请重试”。

十一、自由计时继续流程

点击“继续”：

1. 调用：

POST /api/v1/pomodoro/{session_id}/resume

2. 成功后：
- 根据后端返回的 started_at、total_paused_sec 重新计算 elapsedSec。
- 设置 isRunning=true。
- 设置 isPaused=false。
- 启动 interval。
- 更新按钮为“暂停 / 结束”。

十二、自由计时结束流程

点击“结束”时，不要立即 complete。

弹窗：

标题：结束计时？
内容：本次已专注 18分32秒，确认后将计入学习统计。
取消按钮：继续计时
确认按钮：确认结束

如果时长超过 1 小时，内容显示：
本次已专注 1小时05分20秒，确认后将计入学习统计。

确认后调用：

POST /api/v1/pomodoro/{session_id}/complete

{
  "actual_duration_sec": elapsedSec,
  "total_paused_sec": totalPausedSec
}

完成成功后：
- 清理 interval。
- 重置运行状态。
- activeSession = null。
- 显示成功 toast：“已记录本次专注”
- 刷新今日统计。
- 可跳转或停留在 pomodoro 页面。
- 历史记录应能看到本次自由计时。

取消后：
- 如果原来是 running，继续计时。
- 如果原来是 paused，保持暂停状态。
- 不调用 complete。

十三、页面生命周期处理

1. onShow

- 调用 /pomodoro/active。
- 如果返回 active session：
  - 如果 preset=free：
    - 恢复自由计时 UI。
    - running 状态重新启动 interval。
    - paused 状态保持暂停显示。
  - 如果 preset 非 free：
    - 走原倒计时恢复逻辑。
- 如果没有 active session：
  - 保持未开始状态。

2. onHide / onUnload

- 清理本地 interval。
- 不自动完成计时。
- 不自动暂停计时。
- 因为实际时长由 started_at 和 total_paused_sec 计算，后台时间应继续计入 running 状态。

3. 页面重新进入

- 必须能恢复 active free session。
- 不应从 0 重新开始，除非后端没有 active session。

十四、时间格式工具函数

新增或复用工具函数：

formatDuration(sec)

规则：
- 小于 1 小时：MM:SS 或 00:MM:SS，建议统一 HH:MM:SS。
- 大于等于 1 小时：HH:MM:SS。
- 弹窗文案可以使用中文格式：
  - 32秒
  - 18分32秒
  - 1小时05分20秒

建议：
计时器主视觉统一显示：

00:18:32
01:05:20

十五、统计和历史展示要求

1. history 列表

自由计时记录显示：

类型：自由计时
科目：数据结构
时长：37分20秒
完成时间：2026-xx-xx xx:xx

不要显示：
- 25分钟番茄钟
- 休息时间

2. stats 页面

自由计时纳入：
- 今日专注总时长
- 本周专注总时长
- 科目专注时长
- 趋势图

如果页面有“番茄数”：
- 文案建议改为“专注次数”。
- 或将 free session 单独统计为“自由计时次数”。
- 不要把 5 分钟自由计时强行显示为一个 25 分钟番茄钟。

十六、异常处理

必须处理：

1. 未选择科目点击开始：
提示“请选择科目”。

2. 已有 active session 再点击开始：
提示“当前已有进行中的专注，请先结束后再开始”。

3. 开始请求失败：
提示“开始计时失败，请重试”。

4. 暂停请求失败：
提示“暂停失败，请重试”。

5. 继续请求失败：
提示“继续失败，请重试”。

6. 完成请求失败：
提示“结束计时失败，请重试”。
不要清空本地 activeSession，避免记录丢失。

7. elapsedSec 小于 1 秒：
可以允许保存，也可以提示“计时时长过短，是否结束？”
推荐简单处理：允许保存，但 actual_duration_sec 最小为 1。

8. subject_id 不可用：
提示“科目不可用，请重新选择”。

十七、兼容现有倒计时番茄钟

必须保证：

1. 标准番茄钟仍然倒计时。
2. 长时间番茄钟仍然倒计时。
3. 自定义番茄钟仍然倒计时。
4. 普通番茄钟完成后如果原本会进入休息流程，继续保持原逻辑。
5. 自由计时完成后不进入休息流程。
6. 普通番茄钟 active 恢复逻辑不被 free 模式影响。
7. 普通番茄钟统计不被破坏。
8. 历史记录中普通番茄钟仍显示原来的 preset / duration。

十八、推荐实现顺序

1. 全局阅读现有 pomodoro 后端和前端实现。
2. 后端 preset 校验增加 free。
3. 如有必要，数据库增加 total_paused_sec 字段。
4. 修改 PomodoroStartRequest，允许 preset=free 且 work_duration=0。
5. 修改 start service，支持创建 free session。
6. 修改 pause / resume / complete，确保 free 模式实际时长正确。
7. 修改 active / history / stats 返回，确保 free 模式字段完整。
8. 小程序 pomodoro 页面新增“自由计时”模式选项。
9. 新增 HH:MM:SS 正向计时显示。
10. 实现自由计时开始、暂停、继续、结束确认。
11. 实现 onShow 恢复 active free session。
12. 修改历史和统计页面展示 free session。
13. 完整手动测试普通番茄钟和自由计时。
14. 清理无用代码和 console log。

十九、验收标准

后端验收：
1. POST /api/v1/pomodoro/start 支持 preset=free。
2. preset=free 时 work_duration=0 不报错。
3. free session 可以 pause。
4. free session 可以 resume。
5. free session complete 后 actual_duration_sec 正确。
6. free session 不进入 break 状态。
7. active 接口能返回 running free session。
8. active 接口能返回 paused free session。
9. history 接口能显示 free session。
10. stats 接口能统计 free session。
11. 普通 pomodoro 模式不受影响。

前端验收：
1. pomodoro 页面出现“自由计时”模式。
2. 选择科目后点击“开始计时”，时间从 00:00:00 开始递增。
3. 点击暂停后时间停止。
4. 点击继续后时间继续递增。
5. 点击结束后弹出确认框。
6. 取消结束后保持原状态。
7. 确认结束后记录时长。
8. 页面隐藏再回来，计时仍正确。
9. 小程序锁屏/切后台一段时间后回来，running 状态的自由计时包含后台时间。
10. paused 状态下切后台，暂停期间不计入时长。
11. 历史记录显示“自由计时”和正确科目名。
12. 统计页面包含该自由计时时长。
13. 普通标准番茄钟仍可正常使用。

二十、手动测试用例

测试 1：基础自由计时
- 进入 pomodoro 页面
- 选择“数据结构”
- 选择“自由计时”
- 点击开始计时
- 等待 10 秒
- 点击结束
- 确认结束
- 历史记录显示 10 秒左右
- 数据库 actual_duration_sec 约为 10

测试 2：暂停不计时
- 开始自由计时
- 运行 10 秒
- 暂停
- 等待 20 秒
- 继续
- 再运行 10 秒
- 结束
- 最终记录应约为 20 秒，不应是 40 秒

测试 3：后台恢复
- 开始自由计时
- 运行 10 秒
- 切后台 30 秒
- 回到页面
- 显示时长应约为 40 秒

测试 4：暂停后台恢复
- 开始自由计时
- 运行 10 秒
- 暂停
- 切后台 30 秒
- 回到页面
- 显示仍应约为 10 秒
- 继续后再递增

测试 5：active session 恢复
- 开始自由计时
- 退出 pomodoro 页面
- 再进入 pomodoro 页面
- 页面应恢复自由计时状态
- 不应重新从 0 开始

测试 6：已有 session 防重复
- 已经有 running free session
- 再点击开始
- 不应创建第二条 session
- 应提示已有进行中的专注或恢复当前 session

测试 7：普通番茄钟回归测试
- 选择标准番茄钟
- 开始
- 暂停
- 继续
- 完成
- 原有逻辑正常
- 不被 free 模式影响

测试 8：统计回归
- 完成一条自由计时
- 打开统计页面
- 今日专注时长增加
- 科目统计增加
- 历史列表正确展示

二十一、最终输出要求

完成后请输出：
1. 修改文件列表。
2. 是否新增 migration，以及 migration 文件名。
3. 后端接口变更说明。
4. 前端 pomodoro 页面变更说明。
5. 自由计时实际时长计算逻辑说明。
6. 暂停时长如何排除的说明。
7. active session 恢复逻辑说明。
8. 历史和统计页面适配说明。
9. 手动测试结果。
10. 是否还有遗留问题或风险。