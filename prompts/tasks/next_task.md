任务名称：修复 Pomodoro 自由计时与 Alembic 迁移链路问题

背景：
当前项目已经完成 Pomodoro 科目体系改造和自由计时功能初步开发：

1. pomodoro_sessions 已改为使用 subject_id 关联 subjects.id。
2. pomodoro_sessions.subject 废弃字段已经准备删除。
3. Pomodoro 页面已经支持“自由计时 / 正向计时”模式。
4. Alembic 补充包中新增了以下 Pomodoro 相关迁移：
   - r3g4h5i6j7k8_add_pomodoro_subject_id.py
   - s4g5h6i7j8k9_drop_pomodoro_subject.py
   - t5g6h7i8j9k0_add_pomodoro_total_paused_sec.py

但当前代码和迁移仍存在问题：

1. Alembic 存在多 head 风险。
2. Pomodoro 历史 subject 回填映射和当前 subjects 表实际 code 不完全匹配。
3. env.py 没有导入 PomodoroSession。
4. start_session 会自动中断已有 session，可能污染数据。
5. pause / resume / complete 的暂停时长计算存在重复扣除或漏扣风险。
6. 小程序自由计时暂停 / 继续存在前后端状态不同步风险。
7. total_paused_ms / total_paused_sec 字段命名不统一。

本任务目标：
在不破坏现有标准番茄钟、长时番茄钟、自定义番茄钟、历史记录、统计页面、科目动态渲染的前提下，彻底修复 Pomodoro 自由计时和 Alembic 迁移问题，使数据库迁移、后端接口、前端计时逻辑、历史统计全部稳定可用。

一、先检查当前代码和迁移状态

请先执行以下检查：

1. 检查 Alembic heads：

   alembic heads

当前补充包中大概率会出现两个 head：

- t5g6h7i8j9k0
- v7_import_review_source_metadata

必须修复到最终只有一个 head。

1. 检查 Alembic history：

   alembic history --verbose

确认以下 Pomodoro 迁移链路：

- o0e1f2a3b4c5_add_pomodoro_sessions_table.py
- q2g3h4i5j6k7_add_pomodoro_paused_at.py
- r3g4h5i6j7k8_add_pomodoro_subject_id.py
- s4g5h6i7j8k9_drop_pomodoro_subject.py
- t5g6h7i8j9k0_add_pomodoro_total_paused_sec.py

1. 全局搜索：

   PomodoroSession
   pomodoro_sessions
   total_paused_sec
   total_paused_ms
   paused_at
   _cancel_running
   status == "running"
   preset == "free"
   subject_id
   subject
   selectedSubject
   SUBJECTS
   SUBJECT_LABELS

2. 重点检查文件：

后端：

- backend/app/models/pomodoro.py
- backend/app/schemas/pomodoro.py
- backend/app/services/pomodoro_service.py
- backend/app/api/v1/pomodoro.py
- backend/app/core/database.py
- backend/alembic/env.py
- backend/alembic/versions/

小程序：

- miniprogram/pages/pomodoro/pomodoro.js
- miniprogram/pages/pomodoro/pomodoro.wxml
- miniprogram/pages/pomodoro/pomodoro.wxss
- miniprogram/pages/pomodoro-stats/
- miniprogram/utils/

二、修复 Alembic 多 head 问题

当前补充的 Pomodoro 新迁移从较早的 q2g3h4i5j6k7 分支接出，而主线已经发展到 v7_import_review_source_metadata，导致可能出现双 head。

必须保证最终：

alembic heads

只返回一个 head。

处理策略：

如果这些新增迁移还没有在任何共享环境、测试库、生产库执行过，推荐直接线性化：

1. 将 r3g4h5i6j7k8_add_pomodoro_subject_id.py 的 down_revision 从：

   q2g3h4i5j6k7

   改为当前主线最新 head：

   v7_import_review_source_metadata

2. 保持后续链路：

   r3g4h5i6j7k8 -> s4g5h6i7j8k9 -> t5g6h7i8j9k0

3. 最终 head 应为：

   t5g6h7i8j9k0

如果这些迁移已经在某个环境执行过，不要改历史 revision 的 down_revision。改用新增 merge migration：

merge_pomodoro_timer_heads

down_revision 设为：

("v7_import_review_source_metadata", "t5g6h7i8j9k0")

merge migration 不做 DDL，只负责合并 heads。

验收要求：

1. alembic heads 只剩一个 head。
2. alembic upgrade head 可以正常执行。
3. alembic downgrade -1 可以正常回退最近一次迁移。
4. 不允许保留多个 head 让部署脚本自行处理。

三、修复 env.py 模型导入

当前 alembic/env.py 导入了很多模型，但需要确认是否导入了 PomodoroSession。

如果没有，请新增：

from app.models.pomodoro import PomodoroSession

要求：

1. target_metadata = Base.metadata 能包含 pomodoro_sessions。
2. 后续 autogenerate 不会漏掉 PomodoroSession。
3. 不要删除其他已有 model import。

四、修复 r3g4h5i6j7k8_add_pomodoro_subject_id.py

当前迁移会为 pomodoro_sessions 新增 subject_id，并尝试从旧 subject 字符串回填。但当前回填映射不完全匹配实际 subjects 表。

当前 subjects 体系应以 p5_5_1_fix_subjects.py 中的实际种子为准：

- math2：数学二
- math2-calculus：高等数学
- math2-linalg：线性代数
- exam408：408计算机综合
- exam408-ds：数据结构
- exam408-os：操作系统
- exam408-co：计算机组成原理
- exam408-cn：计算机网络
- english：英语
- pol：政治

请修改 Pomodoro subject 回填逻辑。

必须兼容旧值：

旧 subject 字符串到当前 subject code 的推荐映射：

math -> math2
数学 -> math2
数学二 -> math2

computer -> exam408
计算机 -> exam408
408 -> exam408
408计算机综合 -> exam408

english -> english
英语 -> english

politics -> pol
political -> pol
pol -> pol
政治 -> pol

advanced_math -> math2-calculus
calculus -> math2-calculus
math2-calculus -> math2-calculus
高数 -> math2-calculus
高等数学 -> math2-calculus

linear_algebra -> math2-linalg
linalg -> math2-linalg
math2-linalg -> math2-linalg
线代 -> math2-linalg
线性代数 -> math2-linalg

data_structure -> exam408-ds
ds -> exam408-ds
exam408-ds -> exam408-ds
数据结构 -> exam408-ds

operating_system -> exam408-os
os -> exam408-os
exam408-os -> exam408-os
操作系统 -> exam408-os

computer_organization -> exam408-co
co -> exam408-co
exam408-co -> exam408-co
组成原理 -> exam408-co
计算机组成原理 -> exam408-co

computer_network -> exam408-cn
cn -> exam408-cn
exam408-cn -> exam408-cn
计网 -> exam408-cn
计算机网络 -> exam408-cn

回填优先级：

1. 先按上述旧值映射到目标 code。
2. 再用目标 code 查询 subjects.id。
3. 如果旧值本身就是 subjects.code，直接匹配。
4. 如果旧值本身是 subjects.name，直接匹配。
5. 如果仍无法匹配，记录 unmatched。

迁移安全要求：

1. r3 migration 添加 subject_id 前要检查 pomodoro_sessions 是否存在。
2. 添加 subject_id 前要检查列是否已经存在。
3. 创建 index 前要检查 index 是否已经存在。
4. 创建 FK 前要检查 FK 是否已经存在。
5. FK 推荐使用 ondelete="SET NULL"，因为 subject_id 允许为空。
6. SQLite 下不要直接创建外键 constraint；保持当前跳过策略即可。
7. 回填完成后，必须输出 matched / unmatched 数量。
8. 如果存在 subject 非空但 subject_id 仍为空的记录，不要直接静默进入 drop subject 阶段。

五、修复 s4g5h6i7j8k9_drop_pomodoro_subject.py

当前 s4 migration 会直接 drop pomodoro_sessions.subject。这样如果 r3 回填遗漏，旧 subject 信息会永久丢失。

请修改为更安全的删除策略：

删除 subject 前执行检查：

SELECT subject, COUNT(*)
FROM pomodoro_sessions
WHERE subject_id IS NULL
AND subject IS NOT NULL
AND subject != ''
GROUP BY subject;

处理要求：

1. 如果查询结果为空，可以删除 subject。

2. 如果仍有非空 subject 未回填，必须中止迁移，并抛出清晰错误，例如：

   Cannot drop pomodoro_sessions.subject: unmatched legacy subject values remain: ...

3. 不允许在未匹配数据存在时直接删除 subject。

4. 如果业务决定未匹配数据统一归为“未分类”，请先把这些记录 subject_id 保持 NULL，并在日志中明确列出 unmatched 值，然后再由人工确认是否允许删除。

5. 本任务推荐优先修正映射，尽量让旧数据都回填成功。

SQLite 兼容：
如果 SQLite 环境 drop_column 不稳定，请使用 batch_alter_table：

with op.batch_alter_table("pomodoro_sessions") as batch_op:
batch_op.drop_column("subject")

PostgreSQL 可以继续 op.drop_column。

downgrade：

1. downgrade 可以恢复 subject 字段结构。
2. 不要求恢复历史 subject 值。
3. subject 字段 nullable=True。

六、修复 t5g6h7i8j9k0_add_pomodoro_total_paused_sec.py

当前 t5 migration 直接 add_column，没有检查表和列是否存在。为了兼容已有开发库、手动补过字段的库、或 create_all 先创建新模型后的场景，需要改成幂等安全写法。

要求：

1. 如果 pomodoro_sessions 表不存在，直接 return。

2. 如果 total_paused_sec 已存在，不重复添加。

3. 如果不存在，添加：

   total_paused_sec INTEGER NOT NULL DEFAULT 0

4. 对已有数据，默认值必须补齐为 0。

5. PostgreSQL 下添加后可以移除 server_default。

6. SQLite 下可以保留 server_default 或使用 batch_alter_table，避免迁移失败。

7. downgrade 前检查列是否存在，再 drop。

七、确认数据库最终结构

迁移完成后，pomodoro_sessions 应该至少包含：

- id
- user_id
- subject_id
- chapter_id
- preset
- work_duration
- break_duration
- start_time
- end_time
- expected_end_time
- actual_duration
- status
- paused_at
- total_paused_sec
- notification_enabled
- notification_sent
- notification_sent_at
- notification_error
- openid_snapshot
- created_at

最终不应再包含：

- subject

执行检查：

SELECT column_name
FROM information_schema.columns
WHERE table_name = 'pomodoro_sessions'
ORDER BY ordinal_position;

确认：

1. subject_id 存在。
2. total_paused_sec 存在。
3. subject 不存在。
4. subject_id FK 存在。
5. ix_pomodoro_sessions_subject_id 存在。

八、修复开发环境 runtime DDL 风险

当前 app/core/database.py 中 _ensure_pomodoro_table 只在 pomodoro_sessions 不存在时创建表；如果本地旧 dev.db 已经存在旧表，它不会自动补 subject_id、paused_at、total_paused_sec。

处理要求：

1. 生产环境必须依赖 Alembic，不要在 runtime 自动改生产库。
2. 开发环境可以二选一：
   - 推荐：明确要求开发者删除旧 dev.db 或执行 Alembic upgrade head。
   - 或者：在 _ensure_pomodoro_table 中仅对非 production 环境做轻量 repair，补 subject_id / paused_at / total_paused_sec 缺失列。
3. 不要让生产环境使用 create_all 或 runtime DDL 替代 Alembic。
4. README 或开发说明中补充：Pomodoro schema 变更后必须执行 alembic upgrade head。

九、修复后端 start_session 自动中断问题

当前 start_session 开头调用了：

await _cancel_running(db, user_id)

这会导致用户重复点击开始时，旧 session 被静默标记为 interrupted，然后创建新 session。

这是错误行为。

请改为：

1. start_session 开始时查询当前用户是否已有 active session。

2. active session 包括：

   - status = running
   - 或 status = paused，如果你采用 paused 状态
   - 或 paused_at is not null 的 running session，如果你保留当前设计

3. 如果存在 active session，不要自动中断。

4. 返回 409 或 400，提示：

   当前已有进行中的专注，请先结束后再开始

5. 只有用户主动点击“结束 / 放弃”时，才调用 interrupt。

注意：
不要删除 interrupt_session 接口，它仍然可以作为用户主动放弃本次专注的能力。

十、统一暂停状态模型

当前后端 pause_session 只设置 paused_at，不修改 status。这样接口返回 status 仍是 running，语义不清晰。

请选择一种方案，不能混用。

推荐方案 A：真正使用 status="paused"

修改规则：

pause_session：

1. 查询 status="running" 的 session。
2. 设置：
   - status = "paused"
   - paused_at = now

resume_session：

1. 查询 status="paused" 的 session。
2. 根据 paused_at 计算 paused_sec。
3. total_paused_sec += paused_sec。
4. 如果 expected_end_time 存在，expected_end_time += paused_sec。
5. 设置：
   - status = "running"
   - paused_at = None

complete_session：

1. 查询 status in ["running", "paused"]。
2. 如果 status="paused" 且 paused_at 存在，补算当前暂停段。
3. 设置 status="completed"。

interrupt_session：

1. 查询 status in ["running", "paused"]。
2. 如果 paused_at 存在，补算当前暂停段。
3. 设置 status="interrupted"。

get_active_session：

1. 查询 status in ["running", "paused"]。
2. 返回最近一条 active session。

history：

1. 排除 status in ["running", "paused"]。
2. 不要只写 status != "running"，否则 paused 可能进入历史。

如果你不想引入 status="paused"，则方案 B 是继续使用 status="running" + paused_at 表示暂停。但必须：

1. 所有地方都用 paused_at 判断暂停。
2. 前端不要仅依赖 status。
3. history 必须排除 paused_at 不为空且 status=running 的 session。
4. 文档中明确该状态模型。

本任务推荐方案 A。

十一、修复暂停时长重复扣除问题

当前 resume_session 已经将暂停时长累加到 total_paused_sec。

因此 complete_session 不应再把前端 total_paused_ms 叠加进去。

请把后端时长计算统一为“后端为准”。

推荐新增工具函数：

def _effective_paused_sec(session, now):
paused = session.total_paused_sec or 0
if session.paused_at is not None:
paused += max(0, int((now - session.paused_at).total_seconds()))
return paused

普通倒计时完成：

1. 如果没有 actual_duration_sec：
   raw_seconds = now - start_time
   paused = _effective_paused_sec(session, now)
   actual_duration = max(0, raw_seconds - paused)
2. 不要再叠加 total_paused_ms。

自由计时完成：

1. 如果前端传 actual_duration_sec：
   可以优先使用它。
2. 但后端必须校验：
   - actual_duration_sec >= 0
   - actual_duration_sec <= raw_seconds - paused + 合理容忍值
3. 如果未传 actual_duration_sec：
   用后端公式计算。
4. 保存 actual_duration。

interrupt_session 和 _cancel_running 也必须使用同一个 _effective_paused_sec，避免暂停中被中断时把暂停等待时间计入专注时长。

十二、统一 complete 请求字段

当前前端自由计时发送：

actual_duration_sec
total_paused_sec

但后端 PomodoroCompleteRequest 接收：

actual_duration_sec
total_paused_ms

需要统一。

推荐方案：

1. 后端 PomodoroCompleteRequest 新增 total_paused_sec，可选字段。
2. 保留 total_paused_ms 一段时间作为兼容字段，但不作为主计算来源。
3. 对普通番茄钟和自由计时，最终暂停累计以数据库 total_paused_sec 为准。
4. 前端发送：
   - actual_duration_sec
   - total_paused_sec
5. 后端可以把 total_paused_sec 用于校验或兼容，但不要重复扣除。

Schema 建议：

class PomodoroCompleteRequest(BaseModel):
actual_duration_sec: int | None = Field(default=None, ge=0)
total_paused_sec: int | None = Field(default=None, ge=0)
total_paused_ms: int | None = Field(default=None, ge=0, description="legacy only")

十三、修复统计口径

当前统计把 completed 和 interrupted 都计入：

PomodoroSession.status.in_(["completed", "interrupted"])

这会导致被自动中断或主动放弃的 session 进入总专注时长。

请明确产品口径：

推荐口径：

1. completed 计入统计。
2. interrupted 默认不计入统计。
3. 如果业务希望“放弃但保留时长”，需要单独字段或单独状态，例如 abandoned_recorded，不要混在 interrupted。
4. 历史记录可以显示 interrupted，但统计总时长默认只统计 completed。

请修改：

- get_stats
- get_trends
- get_subject_breakdown

默认只统计：

status == "completed"

history 可以返回 completed 和 interrupted，但 UI 应区分“已完成 / 已放弃”。

十四、修复前端自由计时暂停 / 继续同步问题

当前小程序自由计时暂停和继续是先改本地状态，再异步请求后端。如果网络失败，前后端状态会不一致。

请改为：

暂停：

1. 点击暂停。
2. 设置 loading，防止重复点击。
3. await POST /pomodoro/{session_id}/pause。
4. 请求成功后：
   - 清理 interval。
   - 使用后端返回的 paused_at、total_paused_sec 更新本地状态。
   - isPaused=true。
   - isRunning=false。
5. 请求失败：
   - 不改变本地运行状态。
   - toast：暂停失败，请重试。

继续：

1. 点击继续。
2. 设置 loading。
3. await POST /pomodoro/{session_id}/resume。
4. 请求成功后：
   - 使用后端返回的 start_time、total_paused_sec 重新计算 elapsedSec。
   - isPaused=false。
   - isRunning=true。
   - 重新启动 interval。
5. 请求失败：
   - 保持暂停状态。
   - toast：继续失败，请重试。

十五、修复取消结束弹窗重复 interval 问题

当前取消“结束自由计时”时可能重复创建 interval。

修复要求：

1. 启动新 interval 前必须检查旧 interval 是否存在。

2. 建议封装：

   _startFreeTimerInterval()
   _clearFreeTimerInterval()

3. _startFreeTimerInterval 内部先判断：

   if (this._freeTimerId) return

4. onHide / onUnload 必须 clear interval。

5. active session 恢复前也要先 clear interval，避免重复定时器。

十六、修复 active session 恢复逻辑

后端 active 接口必须返回：

- id
- preset
- status
- start_time
- paused_at
- total_paused_sec
- actual_duration
- subject_id
- subject_code
- subject_name
- work_duration
- break_duration
- expected_end_time

前端恢复规则：

如果 preset="free"：

1. status="running"：
   elapsedSec = now - start_time - total_paused_sec
   启动正向计时 interval。
2. status="paused"：
   elapsedSec = paused_at - start_time - total_paused_sec_before_current_pause
   不启动 interval。
3. 如果后端 total_paused_sec 不包含当前 paused_at 这段，前端暂停中不要额外扣当前 paused_at 后的时间。

如果 preset!="free"：

1. 保持原倒计时恢复逻辑。
2. 但也必须使用 total_paused_sec。
3. paused 状态下不要让剩余时间继续减少。
4. resumed 后按 expected_end_time 或 start_time + work_duration + total_paused_sec 重新计算。

十七、自由计时完成逻辑

点击结束时：

1. 不要立即 complete。
2. 弹出确认框：

标题：结束计时？
内容：本次已专注 xx小时xx分xx秒，确认后将计入学习统计。
取消按钮：继续计时
确认按钮：确认结束

确认后：

1. 调用 POST /pomodoro/{session_id}/complete。
2. 请求体：

{
"actual_duration_sec": elapsedSec,
"total_paused_sec": totalPausedSec
}

1. 完成成功后：
   - 清理 interval。
   - activeSession = null。
   - isRunning=false。
   - isPaused=false。
   - 刷新统计。
   - toast：已记录本次专注。

失败时：

1. 不要清空 activeSession。
2. 不要清空本地 elapsedSec。
3. toast：结束计时失败，请重试。

十八、普通番茄钟回归要求

修复自由计时不能破坏普通番茄钟。

必须验证：

1. 标准番茄钟仍然倒计时。
2. 长时番茄钟仍然倒计时。
3. 自定义番茄钟仍然倒计时。
4. 普通番茄钟暂停后剩余时间停止。
5. 普通番茄钟继续后剩余时间继续。
6. 普通番茄钟完成后仍按原逻辑记录。
7. 如果原来有休息流程，不被自由计时影响。
8. 自由计时完成后不进入休息流程。

十九、接口错误码建议

后端建议使用：

1. 已有 active session：
   HTTP 409
   detail: 当前已有进行中的专注，请先结束后再开始
2. 科目不存在：
   HTTP 400
   detail: 科目不存在
3. 科目不可用：
   HTTP 400
   detail: 科目不可用
4. 选择父级科目：
   HTTP 400
   detail: 请选择具体子科目
5. pause/resume/complete 找不到 active session：
   HTTP 404
   detail: No active session found

二十、迁移和测试命令

完成修复后执行：

后端语法检查：

python -m py_compile app/models/pomodoro.py
python -m py_compile app/schemas/pomodoro.py
python -m py_compile app/services/pomodoro_service.py
python -m py_compile app/api/v1/pomodoro.py

Alembic 检查：

alembic heads
alembic history --verbose
alembic upgrade head
alembic downgrade -1
alembic upgrade head

数据库检查：

SELECT COUNT(*) FROM pomodoro_sessions WHERE subject_id IS NULL;

SELECT column_name
FROM information_schema.columns
WHERE table_name = 'pomodoro_sessions'
ORDER BY ordinal_position;

确认：

1. subject_id 存在。
2. total_paused_sec 存在。
3. subject 不存在。
4. alembic heads 只有一个。

小程序检查：

1. node --check miniprogram/pages/pomodoro/pomodoro.js
2. node --check miniprogram/pages/pomodoro-stats/pomodoro-stats.js

二十一、手动测试用例

测试 1：Alembic 单 head

- 执行 alembic heads。
- 只能看到一个 head。
- alembic upgrade head 成功。

测试 2：旧 Pomodoro subject 回填

- 准备旧数据 subject=data_structure。
- 执行迁移。
- subject_id 应回填为“数据结构”的 id，即 exam408-ds 对应 id。
- 删除 subject 字段后 history 仍显示“数据结构”。

测试 3：advanced_math 回填

- 准备旧数据 subject=advanced_math 或 高数。
- 执行迁移。
- 应回填到“高等数学”对应 id，即 math2-calculus。

测试 4：politics 回填

- 准备旧数据 subject=politics。
- 执行迁移。
- 应回填到“政治”对应 id，即 pol。

测试 5：已有 active session 防重复

- 开始一个自由计时。
- 不结束，再点击开始。
- 不应创建第二条 session。
- 后端返回 409 或 400。
- 旧 session 不应被自动 interrupted。

测试 6：自由计时基础流程

- 选择“数据结构”。
- 选择“自由计时”。
- 开始计时。
- 等待 10 秒。
- 结束并确认。
- history 显示自由计时约 10 秒。
- stats 今日时长增加约 10 秒。

测试 7：暂停不计时

- 开始自由计时。
- 运行 10 秒。
- 暂停。
- 等待 20 秒。
- 继续。
- 再运行 10 秒。
- 结束。
- 最终 actual_duration 约 20 秒，不应是 40 秒。

测试 8：暂停中直接结束

- 开始自由计时。
- 运行 10 秒。
- 暂停。
- 等待 20 秒。
- 不继续，直接结束。
- 最终 actual_duration 约 10 秒。
- 暂停等待的 20 秒不能计入。

测试 9：后台恢复

- 开始自由计时。
- 运行 10 秒。
- 切后台 30 秒。
- 回到页面。
- running 状态应显示约 40 秒。

测试 10：暂停后台恢复

- 开始自由计时。
- 运行 10 秒。
- 暂停。
- 切后台 30 秒。
- 回到页面。
- 仍显示约 10 秒。

测试 11：普通番茄钟回归

- 标准番茄钟开始。
- 暂停。
- 继续。
- 完成。
- 记录正常。
- 暂停时长不重复扣除。

测试 12：统计口径

- 完成一条自由计时。
- 今日专注时长增加。
- 科目统计增加。
- interrupted 记录不计入统计，除非产品明确要求计入。

二十二、最终输出要求

完成后请输出：

1. 修改过的文件列表。
2. Alembic heads 修复方式：
   - 是改 down_revision 线性化；
   - 还是新增 merge migration。
3. 最终 Alembic head revision。
4. r3g4h5i6j7k8 的 subject 回填映射修复说明。
5. s4g5h6i7j8k9 删除 subject 前的数据保护策略。
6. t5g6h7i8j9k0 total_paused_sec 幂等修复说明。
7. env.py 是否已导入 PomodoroSession。
8. 后端 start / pause / resume / complete 的逻辑修复说明。
9. total_paused_sec 的权威计算来源说明。
10. total_paused_ms / total_paused_sec 兼容策略说明。
11. 小程序自由计时暂停、继续、结束、恢复逻辑修复说明。
12. 历史和统计页面适配说明。
13. 手动测试结果。
14. 是否还有遗留风险。

不要做的事情：

1. 不要重新引入 pomodoro_sessions.subject。
2. 不要恢复前端硬编码科目数组。
3. 不要新建独立 timer 表。
4. 不要把自由计时记录写到其他表。
5. 不要让 start_session 自动中断旧 session。
6. 不要让 interrupted 默认进入统计总时长。
7. 不要保留多个 Alembic head。
8. 不要在生产环境依赖 runtime DDL 替代 Alembic。
