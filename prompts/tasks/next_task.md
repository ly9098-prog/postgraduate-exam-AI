任务名称：修复 Pomodoro 自由计时的会话状态、暂停时长与前端同步问题

背景：
当前项目已经完成以下基础工作：

1. Pomodoro 科目体系已改为 subject_id。
2. 废弃 subject 字段和 Alembic 迁移问题已在上一轮任务中修复。
3. Pomodoro 页面已新增“自由计时 / 正向计时”模式。
4. 自由计时已能开始、暂停、继续、结束并写入 pomodoro_sessions。
5. 本任务不再处理 Alembic migration，不要重复修改迁移文件。

当前仍需修复的问题：

1. 后端 start_session() 会自动调用 _cancel_running()，导致已有 active session 被静默中断。
2. 暂停状态模型不统一，当前可能存在 status="running" + paused_at 表示暂停的半混用状态。
3. 暂停时长可能被重复扣除。
4. 暂停中直接结束时，当前暂停等待时间可能被错误计入专注时长。
5. total_paused_ms / total_paused_sec 字段名和职责不统一。
6. 前端暂停 / 继续是先改本地状态，再请求后端，接口失败时会造成前后端状态不一致。
7. 取消结束弹窗时可能重复创建 interval。
8. interrupted 记录不应默认计入专注统计。

本任务目标：
在不处理迁移、不新增功能、不重构无关模块的前提下，修复 Pomodoro 自由计时与普通番茄钟共用逻辑中的状态流转、暂停时长计算和前端状态同步问题。

一、重要原则

1. 不要修改 Alembic migration 文件。
2. 不要新增独立 timer 表。
3. 不要恢复 pomodoro_sessions.subject 字段。
4. 不要恢复前端硬编码科目数组。
5. 不要破坏 subject_id 科目关联。
6. 不要破坏标准番茄钟、长时番茄钟、自定义番茄钟。
7. 自由计时继续复用 pomodoro_sessions 表。
8. 暂停时长以后端 total_paused_sec 为权威来源。
9. 前端不得重复参与暂停时长扣除。
10. 已有 active session 时，不允许自动中断旧 session。
11. 前端暂停 / 继续必须以后端成功响应为准再更新本地状态。
12. interrupted 默认不计入统计总时长。

二、需要重点检查的文件

后端重点检查：

- backend/app/services/pomodoro_service.py
- backend/app/schemas/pomodoro.py
- backend/app/models/pomodoro.py
- backend/app/api/v1/pomodoro.py

小程序重点检查：

- miniprogram/pages/pomodoro/pomodoro.js
- miniprogram/pages/pomodoro/pomodoro.wxml
- miniprogram/pages/pomodoro/pomodoro.wxss
- miniprogram/pages/pomodoro-stats/
- miniprogram/utils/api.js 或项目实际 API 封装文件

全局搜索关键词：

- start_session
- _cancel_running
- interrupt_session
- pause_session
- resume_session
- complete_session
- get_active_session
- paused_at
- total_paused_sec
- total_paused_ms
- actual_duration_sec
- status == "running"
- status == "paused"
- preset == "free"
- _pauseFreeTimer
- _resumeFreeTimer
- _cancelEndFreeTimer
- _freeTimerId
- setInterval
- clearInterval

三、修复 1：取消 start_session() 自动 _cancel_running()

当前问题：
start_session() 开始时自动调用 _cancel_running(db, user_id)，会导致用户重复点击开始时，旧 session 被静默标记为 interrupted，然后创建新 session。

这会造成：

1. 用户误点开始会丢失当前进行中的计时。
2. interrupted 记录可能污染历史和统计。
3. 系统可能产生多条异常 session。

修复要求：

1. 删除或停止在 start_session() 中调用：

   await _cancel_running(db, user_id)

2. start_session() 开始时先查询当前用户是否已有 active session。

active session 定义为：

status in ["running", "paused"]

1. 如果已有 active session，直接返回错误，不创建新 session。

推荐错误码：

HTTP 409 Conflict

推荐错误信息：

当前已有进行中的专注，请先结束后再开始

1. 不要自动 interrupt 旧 session。
2. interrupt_session 只能由用户主动“放弃 / 中断”操作触发。
3. 前端收到 409 后，应提示用户当前已有进行中的专注，并尝试调用 active 接口恢复当前 session。

后端伪代码：

existing = await get_active_session(db, user_id)

if existing:
raise HTTPException(
status_code=409,
detail="当前已有进行中的专注，请先结束后再开始"
)

create new session...

验收标准：

1. 已有 running session 时，再调用 start 不会创建第二条记录。
2. 已有 paused session 时，再调用 start 不会创建第二条记录。
3. 旧 session 不会被自动标记为 interrupted。
4. 数据库中不会因为重复点击开始产生多条 active session。

四、修复 2：统一暂停状态模型，采用 status="paused"

当前问题：
pause_session() 可能只设置 paused_at，但 status 仍然是 running，导致状态语义不清晰。部分逻辑按 status 判断，部分逻辑按 paused_at 判断，容易出错。

本任务要求统一使用：

status="paused"

状态定义：

- running：正在计时
- paused：已暂停
- completed：已完成并计入统计
- interrupted：已主动放弃或异常中断，不默认计入统计

pause_session 修复要求：

1. 只能暂停 status="running" 的 session。

2. 设置：

   status = "paused"
   paused_at = now

3. 不修改 start_time。

4. 不修改 actual_duration。

5. 不立即累加 total_paused_sec，累加动作放到 resume 或 complete 时。

resume_session 修复要求：

1. 只能恢复 status="paused" 的 session。

2. 必须存在 paused_at。

3. 计算本次暂停时长：

   paused_sec = max(0, int((now - paused_at).total_seconds()))

4. 累加：

   total_paused_sec = old_total_paused_sec + paused_sec

5. 如果普通倒计时依赖 expected_end_time，则同步顺延：

   expected_end_time = expected_end_time + paused_sec

6. 设置：

   status = "running"
   paused_at = None

complete_session 修复要求：

1. 可以完成 status in ["running", "paused"] 的 session。

2. 如果 status="paused" 且 paused_at 不为空，需要把当前暂停段补入暂停时长计算。

3. 完成后设置：

   status = "completed"
   end_time / completed_at = now
   paused_at = None

interrupt_session 修复要求：

1. 可以中断 status in ["running", "paused"] 的 session。

2. 如果 status="paused" 且 paused_at 不为空，需要补算当前暂停段。

3. 中断后设置：

   status = "interrupted"
   end_time = now
   paused_at = None

get_active_session 修复要求：

1. 查询：

   status in ["running", "paused"]

2. 返回最近一条 active session。

3. active response 中必须包含：

   status
   paused_at
   total_paused_sec
   preset
   start_time
   subject_id
   subject_name
   work_duration
   break_duration
   expected_end_time

history 查询修复要求：

1. history 不应返回 running / paused 记录。

2. 推荐条件：

   status in ["completed", "interrupted"]

3. UI 展示时区分 completed 与 interrupted。

验收标准：

1. 暂停后数据库 status 为 paused。
2. 继续后数据库 status 为 running，paused_at 清空。
3. 暂停中的 session 能被 active 接口查到。
4. 暂停中的 session 不出现在 history 中。
5. 暂停中的 session 可以直接 complete。
6. 暂停中的 session 可以 interrupt。

五、修复 3：暂停时长以后端 total_paused_sec 为权威来源

当前问题：
resume_session 已经把暂停时长累加到 total_paused_sec，但 complete_session 又可能把前端传来的 total_paused_ms 叠加进去，造成重复扣除。

修复要求：

1. 后端 total_paused_sec 是暂停累计时长的唯一权威来源。
2. resume_session 负责累加已经结束的暂停段。
3. complete_session 负责在结束时补算“当前仍处于暂停中的暂停段”。
4. complete_session 不再把前端 total_paused_ms 叠加到 total_paused_sec。
5. 前端 total_paused_ms 只作为 legacy 字段兼容，不参与主计算。
6. 前端 total_paused_sec 可以传，但后端只用于校验或兼容，不作为重复扣除来源。

推荐新增统一工具函数：

def _get_effective_paused_sec(session, now):
paused = session.total_paused_sec or 0
if session.paused_at:
paused += max(0, int((now - session.paused_at).total_seconds()))
return paused

所有计算 actual_duration 的地方都使用这个函数。

普通倒计时完成时：

raw_seconds = int((now - session.start_time).total_seconds())
paused_sec = _get_effective_paused_sec(session, now)
actual_duration_sec = max(0, raw_seconds - paused_sec)

自由计时完成时：

raw_seconds = int((now - session.start_time).total_seconds())
paused_sec = _get_effective_paused_sec(session, now)
server_duration_sec = max(0, raw_seconds - paused_sec)

if request.actual_duration_sec is not None:
actual_duration_sec = request.actual_duration_sec
但必须校验不能明显大于 server_duration_sec
else:
actual_duration_sec = server_duration_sec

建议允许 3 到 5 秒误差：

if actual_duration_sec > server_duration_sec + 5:
actual_duration_sec = server_duration_sec

推荐为了体验，后端自动纠正为 server_duration_sec，而不是直接报错。

验收标准：

1. 运行 10 秒，暂停 20 秒，继续运行 10 秒，完成后 actual_duration 约为 20 秒。
2. 不会出现实际时长被扣成 0 或明显偏小。
3. 前端传 total_paused_ms 不会导致重复扣除。
4. 普通倒计时和自由计时都使用同一套暂停时长计算逻辑。

六、修复 4：暂停中直接结束时的时长计算

当前问题：
如果用户暂停后不点击继续，直接点击结束，当前暂停段 paused_at -> now 可能不会被扣除，导致暂停等待时间被计入专注时长。

修复要求：

1. complete_session 必须支持 status="paused"。

2. 如果 session.paused_at 不为空，complete 时必须补算当前暂停段。

3. 计算 actual_duration 时必须使用：

   _get_effective_paused_sec(session, now)

4. 完成后必须清空 paused_at。

5. 完成后 total_paused_sec 应保存为最终暂停累计值：

   session.total_paused_sec = effective_paused_sec

6. interrupt_session 也必须使用同样逻辑。

7. 如果 _cancel_running 仍被其他场景使用，也必须使用同样逻辑；但 start_session 不能再调用它。

验收测试：

1. 开始自由计时。
2. 运行 10 秒。
3. 暂停。
4. 等待 20 秒。
5. 不点击继续，直接结束。
6. 最终 actual_duration 应约为 10 秒，而不是 30 秒。

七、修复 5：统一 total_paused_ms / total_paused_sec 字段名

当前问题：
前端自由计时发送 total_paused_sec，后端 schema 可能接收 total_paused_ms，字段语义不统一。

修复策略：

1. 主字段统一为：

   total_paused_sec

2. 后端 PomodoroCompleteRequest 修改为：

   actual_duration_sec: int | None = None
   total_paused_sec: int | None = None
   total_paused_ms: int | None = None

3. total_paused_ms 标记为 legacy only。

4. 后端主计算不依赖 total_paused_ms。

5. 如果前端仍传 total_paused_ms，后端可以接收但不重复扣除。

6. 小程序完成自由计时时发送：

   {
   "actual_duration_sec": elapsedSec,
   "total_paused_sec": totalPausedSec
   }

7. 小程序普通番茄钟完成时也尽量改为发送 total_paused_sec，或者不发送暂停字段，由后端计算。

8. 如果保留 total_paused_ms，只用于兼容旧接口，不作为权威计算来源。

Schema 示例：

class PomodoroCompleteRequest(BaseModel):
actual_duration_sec: int | None = Field(default=None, ge=0)
total_paused_sec: int | None = Field(default=None, ge=0)
total_paused_ms: int | None = Field(default=None, ge=0, description="legacy only")

验收标准：

1. 后端不再因为 total_paused_ms 导致重复扣除。
2. 前端自由计时请求体使用 total_paused_sec。
3. 普通番茄钟和自由计时字段语义一致。
4. 老字段 total_paused_ms 即使存在，也不会破坏时长计算。

八、修复 6：前端暂停 / 继续改为 await 后端成功后再更新本地状态

当前问题：
前端自由计时暂停 / 继续时，先改本地状态，再异步请求后端。如果网络失败，前端显示已暂停或已继续，但后端状态没有变化。

修复要求：

1. _pauseFreeTimer 改为 async。

2. 点击暂停后先设置 actionLoading，防止重复点击。

3. 调用后端 pause 接口。

4. 只有后端成功后，才清理本地 interval 并更新本地状态。

5. 如果后端失败，保持原 running 状态，不清理计时。

6. 显示 toast：

   暂停失败，请重试

推荐流程：

async _pauseFreeTimer() {
if (this.data.actionLoading) return
this.setData({ actionLoading: true })

```
   try {
       const session = await api.post(`/pomodoro/${this.data.sessionId}/pause`, {})
       this._clearFreeTimerInterval()
       this.setData({
           activeSession: session,
           isRunning: false,
           isPaused: true,
           pausedAt: session.paused_at,
           totalPausedSec: session.total_paused_sec || 0,
           actionLoading: false
       })
   } catch (err) {
       this.setData({ actionLoading: false })
       wx.showToast({ title: '暂停失败，请重试', icon: 'none' })
   }
```

}

继续流程：

1. _resumeFreeTimer 改为 async。
2. 点击继续后先请求后端 resume。
3. 后端成功后，用返回的 start_time、total_paused_sec、status 重新计算 elapsedSec。
4. 再启动 interval。
5. 如果失败，保持 paused 状态。

推荐流程：

async _resumeFreeTimer() {
if (this.data.actionLoading) return
this.setData({ actionLoading: true })

```
   try {
       const session = await api.post(`/pomodoro/${this.data.sessionId}/resume`, {})
       this.setData({
           activeSession: session,
           isRunning: true,
           isPaused: false,
           pausedAt: null,
           totalPausedSec: session.total_paused_sec || 0,
           actionLoading: false
       })
       this._updateFreeElapsed()
       this._startFreeTimerInterval()
   } catch (err) {
       this.setData({ actionLoading: false })
       wx.showToast({ title: '继续失败，请重试', icon: 'none' })
   }
```

}

普通番茄钟的 pause / resume 如果也存在先改本地再请求的问题，也要同步修复，避免不同模式行为不一致。

验收标准：

1. pause 接口失败时，前端仍保持计时中。
2. resume 接口失败时，前端仍保持暂停中。
3. 不会出现前端 paused、后端 running 的分叉状态。
4. 连续点击暂停 / 继续不会发出重复请求。

九、修复 7：取消结束弹窗重复 interval

当前问题：
用户点击结束自由计时后弹出确认框，如果点击取消，代码可能重新 setInterval，但原 interval 并未清理，导致重复 interval。

修复要求：

1. 统一封装自由计时 interval 方法：

   _startFreeTimerInterval()
   _clearFreeTimerInterval()

2. _startFreeTimerInterval 必须先判断：

   if (this._freeTimerId) return

3. _clearFreeTimerInterval 必须：

   if (this._freeTimerId) {
   clearInterval(this._freeTimerId)
   this._freeTimerId = null
   }

4. 所有地方启动自由计时 interval 时，都调用 _startFreeTimerInterval。

5. 所有地方清理自由计时 interval 时，都调用 _clearFreeTimerInterval。

6. 取消结束弹窗时，如果当前不是 paused，调用 _startFreeTimerInterval 即可，不直接 setInterval。

7. 打开结束确认弹窗时，不一定要清理 interval；如果不清理，取消时不要重复启动。

8. onHide / onUnload / complete 成功 / active session 重置时必须清理 interval。

修复前危险写法：

this._freeTimerId = setInterval(...)

修复后统一写法：

this._startFreeTimerInterval()

验收标准：

1. 多次点击结束 -> 取消，不会创建多个 interval。
2. 页面 setData 频率正常。
3. onHide 后 interval 被清理。
4. 回到页面恢复 active session 时只存在一个 interval。
5. 完成后 interval 清理。

十、修复 8：interrupted 不默认计入统计

当前问题：
如果统计接口把 completed 和 interrupted 都计入，会导致用户放弃或异常中断的 session 也增加专注总时长。

修复要求：

1. completed 计入统计。

2. interrupted 默认不计入统计。

3. history 可以展示 interrupted，但 UI 需要标明“已放弃 / 已中断”。

4. 如果当前统计代码使用：

   status in ["completed", "interrupted"]

请改为：

status == "completed"

涉及：

- get_stats
- get_trends
- get_subject_breakdown
- pomodoro-stats 页面展示逻辑

验收标准：

1. 用户主动放弃的 session 不增加今日专注总时长。
2. completed 自由计时正常计入统计。
3. completed 普通番茄钟正常计入统计。
4. history 仍可查看 interrupted 记录，但不能混入总专注时长。

十一、后端最终期望行为

start：

1. 没有 active session 时创建新 session。
2. 已有 running / paused session 时返回 409。
3. 不自动中断旧 session。

pause：

1. running -> paused。
2. 设置 paused_at。
3. 不立即重复累加 total_paused_sec。

resume：

1. paused -> running。
2. 计算 paused_at 到 now 的秒数。
3. 累加 total_paused_sec。
4. 清空 paused_at。

complete：

1. running / paused 都可以完成。
2. 使用 _get_effective_paused_sec 计算暂停总时长。
3. 暂停中直接完成时，不把暂停等待时间计入专注时长。
4. 完成后 status=completed。
5. 完成后 paused_at=None。
6. 自由计时不进入休息流程。

interrupt：

1. running / paused 都可以中断。
2. 使用 _get_effective_paused_sec。
3. 中断后 status=interrupted。
4. interrupted 默认不计入统计。

active：

1. 返回 running / paused。
2. 返回 status、paused_at、total_paused_sec。
3. 前端能恢复正确状态。

十二、前端最终期望行为

自由计时开始：

1. 选择科目。
2. 选择自由计时。
3. 点击开始。
4. 后端创建成功后开始本地正向计时。
5. 如果已有 active session，提示并恢复当前 session。

自由计时暂停：

1. 点击暂停。
2. 后端成功后前端停止 interval。
3. 显示暂停状态。
4. 后端失败则继续运行，不改变状态。

自由计时继续：

1. 点击继续。
2. 后端成功后前端恢复 interval。
3. 根据后端 total_paused_sec 重新计算 elapsedSec。
4. 后端失败则保持暂停。

自由计时结束：

1. 点击结束弹确认框。
2. 取消时不重复创建 interval。
3. 确认时调用 complete。
4. 成功后清理 interval、刷新统计。
5. 失败后保留当前 session，不丢失记录。

十三、必须执行的测试

后端测试 1：防重复开始

- 创建 running session。
- 再调用 start。
- 应返回 409。
- 数据库仍只有一条 active session。
- 旧 session status 仍为 running，不是 interrupted。

后端测试 2：暂停状态

- start。
- pause。
- 数据库 status=paused，paused_at 不为空。
- active 接口能返回该 session。

后端测试 3：继续状态

- paused session 调用 resume。
- status=running。
- paused_at=None。
- total_paused_sec 增加。

后端测试 4：暂停时长不重复扣除

- 运行 10 秒。
- 暂停 20 秒。
- 继续。
- 运行 10 秒。
- complete。
- actual_duration 约 20 秒。

后端测试 5：暂停中直接结束

- 运行 10 秒。
- 暂停 20 秒。
- 直接 complete。
- actual_duration 约 10 秒。

后端测试 6：字段兼容

- complete 请求带 total_paused_sec。
- complete 请求带 total_paused_ms。
- 都不会导致重复扣除。

后端测试 7：统计口径

- completed 计入统计。
- interrupted 不计入统计。

前端测试 1：暂停接口失败

- 模拟 pause 请求失败。
- 页面仍显示计时中。
- interval 不被清理。

前端测试 2：继续接口失败

- 模拟 resume 请求失败。
- 页面仍显示暂停中。
- 不启动 interval。

前端测试 3：取消结束弹窗

- 自由计时运行中。
- 点击结束。
- 点击取消。
- 重复 3 次。
- 页面只存在一个 interval。
- 时间显示正常。

前端测试 4：后台恢复

- 自由计时运行中切后台。
- 回来后 active 恢复。
- 时长正确。

前端测试 5：暂停后台恢复

- 自由计时暂停中切后台。
- 回来后仍保持暂停。
- 暂停期间不计入时长。

前端测试 6：普通番茄钟回归

- 标准番茄钟开始。
- 暂停。
- 继续。
- 完成。
- 记录正常。
- 暂停时长不重复扣除。

十四、代码检查命令

后端：

python -m py_compile app/models/pomodoro.py
python -m py_compile app/schemas/pomodoro.py
python -m py_compile app/services/pomodoro_service.py
python -m py_compile app/api/v1/pomodoro.py

小程序：

node --check miniprogram/pages/pomodoro/pomodoro.js

如果存在统计页 JS：

node --check miniprogram/pages/pomodoro-stats/pomodoro-stats.js

十五、最终输出要求

完成后请输出：

1. 修改过的文件列表。
2. start_session 防重复开始的修复说明。
3. 暂停状态模型说明：已统一使用 status="paused"。
4. pause / resume / complete / interrupt 的状态流转说明。
5. total_paused_sec 权威计算逻辑说明。
6. total_paused_ms / total_paused_sec 兼容策略。
7. 暂停中直接结束的计算修复说明。
8. 前端 pause / resume await 后端成功的修复说明。
9. interval 防重复修复说明。
10. interrupted 不计入统计的修复说明。
11. 手动测试结果。
12. 是否仍有遗留风险。

十六、禁止事项

1. 不要修改 Alembic migration。
2. 不要在 start_session 中继续调用 _cancel_running。
3. 不要让 start 自动 interrupt 旧 session。
4. 不要继续混用 status="running" + paused_at 表示暂停。
5. 不要重复扣除 total_paused_sec 和 total_paused_ms。
6. 不要在前端请求失败时先改变本地状态且不回滚。
7. 不要直接 setInterval 而不检查旧 interval。
8. 不要重新引入 pomodoro_sessions.subject。
9. 不要恢复前端硬编码 SUBJECTS / SUBJECT_LABELS。
10. 不要让 interrupted 默认计入统计总时长。
