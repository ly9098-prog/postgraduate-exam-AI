你现在是一名资深后端工程师，请基于我上传的项目代码，检查并修复 SM-2 间隔重复算法及其调度集成问题。

项目背景：
这是一个考研 AI 错题与复习系统。项目中已经实现了 SM-2 算法和复习调度逻辑，相关文件重点包括：

1. backend/app/services/sm2_service.py
2. backend/app/services/review_scheduler.py
3. backend/app/services/wrong_question_service.py
4. backend/app/api/v1/review.py
5. 与 ReviewSchedule、WrongQuestion、Question 相关的模型文件
6. 相关测试文件，例如 tests 中 review、wrong_question、scheduler 相关测试

请你不要只做表面修改，要完整阅读相关调用链，确保数据库字段、API、服务层、测试之间逻辑一致。

需要修复的问题如下：

一、修复已有复习记录再次做错时 ease_factor 被重置的问题

当前问题：
在 backend/app/services/review_scheduler.py 的 auto_schedule_wrong_question() 中，如果某道题已经有 ReviewSchedule，再次做错时，代码会直接执行类似逻辑：

schedule.interval = 1
schedule.ease_factor = 2.5
schedule.repetitions = 0
schedule.next_review_at = utcnow()

这会导致一个严重问题：反复做错的题原本 ease_factor 已经下降，但再次做错后又被重置为默认 2.5，相当于把难题重新变成“普通题”。

修复要求：
1. 如果 schedule 已存在，不要把 ease_factor 重置为 2.5。
2. 应调用 SM-2 算法，把这次做错视为一次 quality=0 或较低评分的复习。
3. 保留已有 schedule.ease_factor、schedule.interval、schedule.repetitions 作为输入。
4. 更新后的 interval、ease_factor、repetitions 应来自 calc_sm2()。
5. next_review_at 可以设为当前时间，表示立即进入复习队列；如果项目现有逻辑更适合明天复习，也可以使用 calc_sm2 返回的 next_review_date，但请保持接口行为一致并说明理由。
6. mastered 应重置为 False。

参考逻辑：

sm2_result = calc_sm2(
    quality=0,
    efactor=schedule.ease_factor or 2.5,
    interval=schedule.interval or 1,
    repetitions=schedule.repetitions or 0,
    review_date=date.today(),
)

schedule.interval = sm2_result["interval"]
schedule.ease_factor = sm2_result["efactor"]
schedule.repetitions = sm2_result["repetitions"]
schedule.next_review_at = utcnow()
schedule.mastered = False

但请你根据项目实际字段名称和时间工具函数调整。

二、检查并统一 WrongQuestion 与 ReviewSchedule 的调度逻辑

当前风险：
项目里同时存在两套 SM-2 调度数据：

WrongQuestion 中可能有：
- efactor
- interval
- repetitions
- next_review_date

ReviewSchedule 中可能有：
- ease_factor
- interval
- repetitions
- next_review_at

这会导致两个入口的复习结果不同步：
- /review/due 可能基于 WrongQuestion
- /review/today、/review/schedule-submit、/review/grade-batch 可能基于 ReviewSchedule

修复要求：
1. 阅读完整调用链，确认哪些接口使用 WrongQuestion 调度，哪些接口使用 ReviewSchedule 调度。
2. 优先以 ReviewSchedule 作为统一复习调度来源。
3. WrongQuestion 应主要记录错题属性，例如 wrong_answer、error_type、ai_analysis、mastered、created_at 等。
4. 如果暂时不能彻底移除 WrongQuestion 中的 SM-2 字段，请至少保证两个表在更新时不会产生明显矛盾。
5. 对外接口行为不能破坏现有前端调用。
6. 如果需要保留兼容逻辑，请在代码注释中说明：ReviewSchedule 是主调度来源，WrongQuestion 的调度字段仅为兼容或历史字段。
7. 检查 /review/due、/review/submit、/wrong-questions/{id}/quality 等接口是否仍然使用旧调度字段。如果是，请重构为调用 ReviewSchedule 或统一服务层。

三、优化自动批改评分映射

当前问题：
review.py 中自动批改可能使用：

rating = 5 if is_correct else 0

这会导致 SM-2 评分过于极端：
- 答对直接按最熟悉处理
- 答错直接按完全不会处理

修复要求：
1. 检查 /review/grade-submit 和 /review/grade-batch 等接口。
2. 如果接口没有用户自评 rating，只能根据 is_correct 自动生成 rating，则建议改为：
   - is_correct=True  => rating=4
   - is_correct=False => rating=1
3. 如果前端已经传入 rating，则优先使用用户传入的 rating。
4. rating 必须限制在 0 到 5。
5. 对主观题、AI 批改题、客观题保持兼容。
6. 不要破坏现有 API 返回结构。

四、修复 SM-2 中 round() 的不稳定舍入问题

当前问题：
sm2_service.py 中可能有：

new_interval = round(interval * efactor)

Python 的 round() 是银行家舍入，例如 round(22.5) == 22，这可能导致复习间隔不符合预期。

修复要求：
1. 改为稳定的四舍五入：
   import math
   new_interval = max(1, math.floor(interval * efactor + 0.5))
2. 保证 interval 最小为 1。
3. 保持 SM-2 核心公式不变：
   EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
   EF 最低不低于 1.3。
4. quality < 3 时 repetitions 归零，interval 设为 1。
5. quality >= 3 时：
   - repetitions == 0 => interval = 1
   - repetitions == 1 => interval = 6
   - repetitions >= 2 => interval = interval * ease_factor 后四舍五入

五、修复 /review/today 的 subject 筛选顺序问题

当前问题：
review_scheduler.py 中 get_today_review_questions() 可能先查询 ReviewSchedule 并 limit，然后再用 Python 根据 Question.subject 过滤。这样会导致 subject 筛选漏题。

错误模式大致是：
先查 due schedules limit 20
再加载 questions
再 if subject 过滤
这样如果前 20 条都不是目标 subject，就会返回空，即使后面还有目标 subject 的待复习题。

修复要求：
1. subject 筛选必须在 SQL 查询阶段完成，而不是 limit 之后再过滤。
2. 如果传入 subject，应 join Question 表并 where Question.subject == subject。
3. limit 应在 subject 筛选之后生效。
4. 保证 total 统计与返回列表一致。
5. 保持不传 subject 时行为不变。
6. 注意 SQLAlchemy async 写法和已有项目风格。

六、增加或修改测试

请新增或修改测试，至少覆盖以下场景：

1. calc_sm2 基础行为：
   - quality=5, repetitions=0 => interval=1, repetitions=1
   - quality=5, repetitions=1 => interval=6, repetitions=2
   - quality=5, repetitions=2, interval=6, efactor=2.7 => interval 约为 16
   - quality<3 => repetitions=0, interval=1
   - efactor 不低于 1.3

2. 已有 ReviewSchedule 再次做错：
   - 原 ease_factor 低于 2.5，例如 1.6
   - 调用 auto_schedule_wrong_question()
   - 修复后 ease_factor 不应重置为 2.5
   - repetitions 应根据 SM-2 失败逻辑归零
   - interval 应为 1
   - mastered 应为 False

3. 自动批改 rating 映射：
   - is_correct=True 且未传 rating 时，默认 rating 应为 4
   - is_correct=False 且未传 rating 时，默认 rating 应为 1
   - 如果传入 rating，应优先使用传入值
   - rating 超出 0-5 时应被拒绝或裁剪，按项目现有风格处理

4. /review/today subject 筛选：
   - 创建多个不同 subject 的待复习题
   - 设置 limit 小于总数
   - 请求某个 subject
   - 返回结果必须只包含该 subject
   - 不应因为 limit 先截断而漏掉该 subject 的题

七、代码质量要求

1. 不要大面积重写无关代码。
2. 保持现有接口返回格式。
3. 保持异步 SQLAlchemy 风格一致。
4. 修改后运行项目现有测试。
5. 如果测试环境缺少依赖，请说明缺少哪些依赖，并尽量运行能够运行的单元测试。
6. 修复完成后，请输出：
   - 修改了哪些文件
   - 每个文件改了什么
   - 修复了哪些 bug
   - 新增/修改了哪些测试
   - 测试运行结果
   - 是否有兼容性风险

八、最终交付格式

请按以下格式汇报：

## 修复摘要

## 修改文件清单

## 关键代码变更说明

## 测试覆盖情况

## 测试结果

## 仍需注意的问题

请直接修改代码，不要只给建议。
