任务名称：修复 Pomodoro 番茄钟科目关联与科目动态渲染

背景：
当前项目中 pomodoro_sessions 表仍在使用废弃的 subject 字符串字段记录科目，未正确关联 subjects 表中的 subject_id。
同时，小程序 pomodoro 页面存在科目硬编码问题，没有根据 subjects 表中的真实科目结构动态渲染。
现在需要先修复番茄钟科目数据模型、接口和前端渲染逻辑，为后续新增“自由计时 / 正向计时”功能打好数据基础。

重要原则：
1. 本任务只修复 Pomodoro 科目关联和前端科目动态渲染。
2. 暂时不要新增自由计时器功能。
3. 不要删除旧 subject 字段，先作为 legacy fallback 保留。
4. 新数据必须使用 subject_id 关联 subjects.id。
5. 前端 pomodoro 页面必须从后端 subjects 数据动态生成科目选项，不能继续硬编码。
6. 保持现有番茄钟开始、暂停、继续、完成、统计、历史记录等功能不被破坏。
7. 所有修改必须兼容历史数据。

一、需要先检查的现有代码位置

请先全局搜索以下关键词，确认当前实现位置：

- pomodoro_sessions
- PomodoroSession
- PomodoroStartRequest
- PomodoroSessionResponse
- subject
- subject_id
- /pomodoro/start
- /pomodoro/history
- /pomodoro/stats
- /practice/subjects
- pages/pomodoro
- SUBJECTS
- SUBJECT_LABELS
- SUBJECT_COLORS

重点检查以下目录：

- backend/app/models/
- backend/app/schemas/
- backend/app/api/v1/
- backend/app/services/
- backend/alembic/
- miniprogram/pages/pomodoro/
- miniprogram/utils/

二、后端数据库模型修复

目标：
让 pomodoro_sessions 表新增 subject_id 字段，并与 subjects.id 建立外键关联。

要求：
1. 在 PomodoroSession ORM 模型中新增字段：

   subject_id: int | None

2. subject_id 外键关联 subjects.id。
3. subject_id 允许为空，用于兼容历史旧数据。
4. 保留旧 subject 字段，不要删除。
5. 在 ORM 中增加 relationship，例如：

   subject_ref = relationship("Subject")

6. 如果当前 Subject 模型已有 relationship 命名规范，请遵循项目现有风格。
7. 不要影响现有 create_all 开发环境自动建表逻辑。

三、数据库迁移

目标：
新增 Alembic migration，为 pomodoro_sessions 增加 subject_id 字段和外键索引。

迁移要求：
1. 新增字段：

   subject_id INTEGER NULL

2. 建立外键：

   pomodoro_sessions.subject_id -> subjects.id

3. 建立索引：

   ix_pomodoro_sessions_subject_id

4. 迁移中尽量根据旧 subject 字段回填 subject_id。

建议回填映射逻辑：
根据 subjects.code 或 subjects.name 匹配旧 subject 字段。

需要重点兼容这些旧值：

- math -> 数学或 math
- computer -> 计算机或 computer
- english -> 英语或 english
- politics -> 政治或 politics
- advanced_math -> 高数
- linear_algebra -> 线性代数
- data_structure -> ds / 数据结构
- computer_organization -> co / 计算机组成原理
- operating_system -> os / 操作系统
- computer_network -> cn / 计算机网络

注意：
截图中的 subjects 表结构类似：

id
parent_id
code
name
level
path
sort_order
is_active

示例：
数学、计算机是一级科目；
高数、线性代数、数据结构、计算机组成原理、操作系统、计算机网络是二级子科目；
英语、政治可能是一级但没有子级，也应允许被选择。

回填优先级：
1. 优先按 subjects.code 匹配。
2. 其次按 subjects.name 匹配。
3. 对旧硬编码英文值做特殊映射。
4. 找不到匹配时 subject_id 保持 null，历史展示时继续 fallback 到旧 subject。

四、后端 Schema 修复

目标：
Pomodoro 相关请求和响应都支持 subject_id，并逐步废弃 subject 字符串。

请修改或新增以下 schema：

1. PomodoroStartRequest

新增字段：

   subject_id: int | None = None

保留：

   subject: str | None = None

处理规则：
- 新前端必须传 subject_id。
- subject 仅作为旧客户端兼容。
- 如果 subject_id 和 subject 同时传，以 subject_id 为准。
- 如果两者都没有传，返回 400 或 422，提示请选择科目。

2. PomodoroSessionResponse

新增字段：

   subject_id
   subject_code
   subject_name

保留字段：

   subject

响应规则：
- 如果 subject_id 存在，则 subject_name 来自 subjects.name。
- 如果 subject_id 为空，则 subject_name 使用旧 subject fallback 格式化。
- subject 字段继续返回，兼容旧前端，但新前端不应再依赖它。

3. PomodoroSubjectStatsResponse 或类似统计响应

如果存在按科目统计响应，调整为返回：

   subject_id
   subject_code
   subject_name
   sessions
   duration_sec / total_minutes / total_duration

不要再只返回 subject 字符串。

五、后端业务逻辑修复

目标：
番茄钟开始、完成、统计、历史记录全部优先使用 subject_id。

1. start 接口

接口：
POST /api/v1/pomodoro/start

新请求示例：

{
  "subject_id": 7,
  "preset": "standard",
  "work_duration": 25,
  "break_duration": 5
}

处理要求：
- 优先读取 subject_id。
- 校验 subject_id 是否存在。
- 校验 subjects.is_active = true。
- 建议只允许选择叶子科目：
  - 如果该 subject 有 active children，则不允许直接选择该父级科目。
  - 返回 400，提示“请选择具体子科目”。
- 如果一级科目没有子级，例如英语、政治，则允许选择。
- subject 字段仅用于兼容旧客户端。
- 新创建的 pomodoro_sessions 必须写入 subject_id。
- 旧 subject 字段可以同步写入 subjects.code 或 subjects.name，用于兼容旧逻辑，但不能作为主数据来源。

2. active 接口

接口：
GET /api/v1/pomodoro/active

要求：
- 返回 active session 时包含 subject_id、subject_code、subject_name。
- 如果是旧数据 subject_id 为空，则使用 subject 字段 fallback。

3. complete / pause / resume 接口

接口：
POST /api/v1/pomodoro/{session_id}/complete
POST /api/v1/pomodoro/{session_id}/pause
POST /api/v1/pomodoro/{session_id}/resume

要求：
- 不破坏现有状态流转。
- 返回 session 时补充 subject_id、subject_code、subject_name。
- 完成记录后统计数据应能按 subject_id 正确聚合。

4. history 接口

接口：
GET /api/v1/pomodoro/history

要求：
- 返回每条记录的 subject_id、subject_code、subject_name。
- 新记录展示 subjects.name。
- 旧记录如果 subject_id 为空，则使用旧 subject 字段 fallback。
- 不要因为旧记录缺少 subject_id 导致接口报错。

5. stats / trends / subjects 统计接口

接口可能包括：
GET /api/v1/pomodoro/stats
GET /api/v1/pomodoro/trends
GET /api/v1/pomodoro/history

如项目中存在按科目聚合接口，也要调整。

要求：
- 新统计优先按 pomodoro_sessions.subject_id 聚合。
- join subjects 表返回 subject_name。
- 历史旧数据 subject_id 为空时，可以归入“未分类”或 legacy subject 名称。
- 不要再依赖硬编码 subject label map。

六、科目接口复用或新增

当前项目已有 /api/v1/practice/subjects 接口。
请检查该接口是否返回完整 subjects 树，或是否足够 pomodoro 页面使用。

目标：
pomodoro 页面应该根据 subjects 表动态渲染可选科目。

处理方案优先级：
1. 优先复用 GET /api/v1/practice/subjects。
2. 如果该接口只适合练习页，且数据结构不满足番茄钟页面，可新增：

   GET /api/v1/subjects
   或
   GET /api/v1/pomodoro/subjects/options

但不要重复写复杂逻辑，尽量复用已有 Subject service。

科目返回建议结构：

[
  {
    "id": 1,
    "code": "math",
    "name": "数学",
    "level": 1,
    "parent_id": null,
    "is_active": true,
    "children": [
      {
        "id": 5,
        "code": "advanced_math",
        "name": "高数",
        "level": 2,
        "parent_id": 1,
        "is_active": true,
        "children": []
      }
    ]
  }
]

七、前端 pomodoro 页面修复

目标：
移除 pomodoro 页面的科目硬编码，改为接口动态加载。

请检查：

miniprogram/pages/pomodoro/pomodoro.js
miniprogram/pages/pomodoro/pomodoro.wxml
miniprogram/pages/pomodoro/pomodoro.wxss

以及可能存在的：

miniprogram/pages/pomodoro-stats/
miniprogram/pages/report/
miniprogram/utils/

前端修改要求：

1. 删除或停止使用硬编码：

   const SUBJECTS = [...]
   const SUBJECT_LABELS = {...}
   const SUBJECT_COLORS = {...}

2. 页面 onLoad 或 onShow 时请求科目接口：

   GET /api/v1/practice/subjects

或项目已有的封装方法。

3. 将 subjects 树转换为可选择列表。

选择规则：
- active=true。
- 如果一个科目没有 active 子级，则它是可选项。
- 如果一个科目有 active 子级，则父级只作为分组，不作为可选项。
- 一级科目如果没有子级，例如英语、政治，也可以作为可选项。
- 二级子科目如高数、线性代数、数据结构、计算机组成原理、操作系统、计算机网络必须可以被选择。

根据截图，最终 pomodoro 页面应该渲染类似：

高数
线性代数
数据结构
计算机组成原理
操作系统
计算机网络
英语
政治

而不是写死旧数组。

4. 前端状态改造

旧状态可能是：

selectedSubject: 'math'

新状态应改为：

selectedSubjectId: 7
selectedSubject: {
  id: 7,
  code: 'ds',
  name: '数据结构'
}

5. 启动番茄钟时传 subject_id

旧请求：

{
  "subject": "math",
  "preset": "standard",
  "work_duration": 25
}

新请求：

{
  "subject_id": 7,
  "preset": "standard",
  "work_duration": 25,
  "break_duration": 5
}

6. 页面展示名称

所有位置优先显示：

subject.name
subject_name

不要再通过旧 subject 字符串查 label。

7. 加载状态和异常状态

要求：
- 科目加载中显示 loading。
- 科目接口失败时提示“科目加载失败，请稍后重试”。
- 科目为空时提示“暂无可用科目”。
- 没有选择科目时，点击开始应提示“请选择科目”。

八、前端统计页面修复

如果存在番茄钟统计页面，例如：

miniprogram/pages/pomodoro-stats/

请同步修复：

1. 不再用 SUBJECT_LABELS 映射科目名。
2. 使用接口返回的 subject_name。
3. 如果 subject_name 为空，fallback 到 subject 或“未分类”。
4. 图表颜色不要依赖硬编码科目。
5. 可以用 subject_id 做稳定 hash 生成颜色，或使用数组顺序分配颜色。
6. 不要因为历史记录 subject_id 为空导致页面崩溃。

九、兼容性要求

必须兼容三类数据：

1. 新数据：
   subject_id 有值，subject 可有可无。
   展示 subjects.name。

2. 旧数据：
   subject_id 为空，subject 有值。
   展示旧 subject fallback 文案。

3. 异常数据：
   subject_id 为空，subject 也为空。
   展示“未分类”。

十、验收标准

完成后必须满足以下验收项：

1. 数据库
- pomodoro_sessions 表存在 subject_id 字段。
- subject_id 外键关联 subjects.id。
- 旧 subject 字段仍然存在。
- 迁移可以正常执行。
- 旧数据不会丢失。

2. 后端
- POST /api/v1/pomodoro/start 支持 subject_id。
- 使用有效 subject_id 可以成功创建番茄钟。
- 使用不存在的 subject_id 返回错误。
- 使用 inactive subject_id 返回错误。
- 使用有子级的父级 subject_id 返回错误。
- 使用无子级的一级科目 subject_id 可以成功。
- active/history/stats 接口返回 subject_id、subject_code、subject_name。
- 旧 session 不会导致接口报错。

3. 小程序 pomodoro 页面
- 科目列表来自后端 subjects 数据。
- 页面不再硬编码科目。
- 选择“高数 / 线性代数 / 数据结构 / 计算机组成原理 / 操作系统 / 计算机网络 / 英语 / 政治”等可用科目后，可以正常开始番茄钟。
- 请求体传 subject_id。
- 番茄钟暂停、继续、完成功能正常。
- 页面返回、重新进入后 active session 能正常恢复并显示正确科目名。

4. 统计页面
- 统计按 subject_id 聚合。
- 科目名显示 subjects.name。
- 历史旧数据有 fallback，不崩溃。
- 不再依赖旧硬编码 SUBJECT_LABELS。

十一、不要做的事情

1. 不要删除 pomodoro_sessions.subject。
2. 不要直接把 subject 字符串继续作为主关联字段。
3. 不要在前端继续维护硬编码科目数组。
4. 不要为了这次任务新增自由计时器功能。
5. 不要大规模重构无关页面。
6. 不要破坏 practice、review、wrong-detail 等页面的现有科目逻辑。
7. 不要修改 subjects 表结构，除非确实发现现有结构无法满足需求。

十二、推荐实现顺序

1. 全局搜索 pomodoro 和 subject 相关代码。
2. 修改 PomodoroSession ORM，增加 subject_id。
3. 创建 Alembic migration。
4. 修改 Pomodoro 请求和响应 schema。
5. 修改 pomodoro start/active/history/stats 相关 service 或 router。
6. 修改小程序 API 封装，支持 subject_id。
7. 修改 pomodoro 页面，动态加载 subjects 并 flatten 为可选项。
8. 修改 pomodoro 统计页面，使用 subject_name。
9. 跑后端测试或手动接口测试。
10. 使用微信开发者工具测试完整流程。

十三、手动测试用例

测试用例 1：正常二级科目
- 选择“数据结构”
- 点击开始
- 暂停
- 继续
- 完成
- 查看历史记录
- 应显示“数据结构”
- 数据库记录 subject_id 应为 subjects 表中“数据结构”的 id

测试用例 2：一级无子级科目
- 选择“英语”
- 点击开始
- 完成
- 应正常记录并显示“英语”

测试用例 3：父级科目
- 尝试通过接口传“计算机”这个父级 subject_id
- 如果它存在 active 子级，应返回错误
- 错误文案提示请选择具体子科目

测试用例 4：旧数据兼容
- 找一条 subject_id 为空但 subject 有值的旧 pomodoro_sessions 记录
- 调用 history 接口
- 页面应正常显示 fallback 科目名
- 不得报错

测试用例 5：科目接口失败
- 模拟 /practice/subjects 请求失败
- pomodoro 页面应显示加载失败提示
- 点击开始应提示先选择科目或科目不可用

十四、最终输出要求

完成后请输出：
1. 修改过的文件列表。
2. 新增 migration 文件名。
3. 后端接口变更说明。
4. 前端页面变更说明。
5. 旧 subject 字段兼容策略。
6. 手动测试结果。
7. 是否还有遗留问题。