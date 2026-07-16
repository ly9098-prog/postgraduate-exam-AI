# MemoGrad 多空选择题支持：Claude Code 分阶段执行 Prompt

> 适用项目：FastAPI 后端 + Next.js 管理端 + 原生微信小程序。
>
> 目标示例：
>
> 题干：一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 vᵢ 的入度是（ ）；若图为无向图，顶点 vᵢ 的度是（ ）。
>
> 公共选项：A / B / C / D
>
> 原始答案：`①B、②D`
>
> 当前错误结果：被导入成 `single_choice`，只能选一个答案。
>
> 目标结果：识别为 `multi_blank_choice`，第 1 空选 B、第 2 空选 D。

---

## 一、开始前必须遵守的原则

你正在 MemoGrad 项目中工作。先阅读：

- `CLAUDE.md`
- `README.md`
- 与本任务相关的后端、管理端、小程序代码
- 当前 `git status`

不要直接重写现有答题系统。项目中已经存在部分 `multi_blank_choice` 支持，应以补齐和统一为主。

已知相关位置可能包括：

### 后端

- `backend/app/features/question_splitter.py`
- `backend/app/features/question_normalizer.py`
- `backend/app/features/question_pipeline.py`
- `backend/app/features/answer_matcher.py`
- `backend/app/features/text_question_parser.py`
- `backend/app/features/question_import_writer.py`
- `backend/app/features/question_publish_service.py`
- `backend/app/utils/answer_normalizer.py`
- `backend/app/services/practice_service.py`
- `backend/app/schemas/practice.py`
- `backend/app/schemas/admin_imports.py`
- `backend/app/api/v1/practice.py`
- `backend/app/api/v1/admin_imports.py`
- `backend/app/ai/prompts.py`

### 管理端

- `admin-frontend/src/app/(admin)/imports/review/page.tsx`
- `admin-frontend/src/app/(admin)/imports/questions/page.tsx`
- `admin-frontend/src/app/(admin)/questions/page.tsx`
- `admin-frontend/src/lib/api/types.ts`

### 微信小程序

- `miniprogram/utils/answer.js`
- `miniprogram/utils/question-runner-adapter.js`
- `miniprogram/components/quiz-runner/quiz-runner.js`
- `miniprogram/components/quiz-runner/quiz-runner.wxml`
- `miniprogram/pages/practice/practice.js`
- `miniprogram/pages/practice/practice.wxml`
- `miniprogram/pages/review-today/review-today.js`
- `miniprogram/pages/wrong-detail/wrong-detail.js`
- `miniprogram/pages/practice-result/practice-result.js`

要求：

1. 不改无关功能。
2. 尽量不新增数据库列。本功能可以利用现有 JSON `content`、`parsed_content` 和文本 `answer` 字段实现。
3. 保持旧单选、多选、判断、填空、主观题完全兼容。
4. 保持已有“每个空有独立选项组”的多空题兼容。
5. 所有答案判定必须以后端为最终事实来源。
6. 规则解析优先，AI 只做结构化兜底，不允许 AI 猜答案。
7. 每个阶段完成后停止，输出：
   - 修改文件
   - 核心设计
   - 测试命令及结果
   - 尚未处理的问题
8. 不自动提交 Git commit。

---

## 二、统一数据契约

不要为这类题继续使用 `single_choice`。

统一题型：

```json
{
  "question_type": "multi_blank_choice"
}
```

正式题目建议存储为：

```json
{
  "content": {
    "text": "一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 vᵢ 的入度是（ ）；若图为无向图，顶点 vᵢ 的度是（ ）。",
    "blank_option_groups": [
      {
        "id": "①",
        "options": [
          {"key": "A", "text": "..."},
          {"key": "B", "text": "..."},
          {"key": "C", "text": "..."},
          {"key": "D", "text": "..."}
        ]
      },
      {
        "id": "②",
        "options": [
          {"key": "A", "text": "..."},
          {"key": "B", "text": "..."},
          {"key": "C", "text": "..."},
          {"key": "D", "text": "..."}
        ]
      }
    ]
  },
  "options": null,
  "answer": "①:B;②:D"
}
```

说明：

- 即使原题只展示一次 A-D 公共选项，也将公共选项复制到每个 `blank_option_groups` 中。
- 这是为了兼容项目中已有的小程序多空选项渲染模型，避免新增数据库结构。
- `blank_option_groups` 顺序就是空位顺序。
- `id` 优先保留原题显式标记，例如 `①`、`②`、`(1)`、`(2)`。
- 题干只有多个匿名 `（ ）` 时：
  - 优先使用答案中的标记，如原答案 `①B、②D`，则生成 `①`、`②`；
  - 没有标记时生成 `"1"`、`"2"`。
- 正确答案必须序列化为稳定格式：
  - `①:B;②:D`
  - 分隔符固定为英文分号；
  - 槽位和值之间固定为英文冒号；
  - 顺序严格跟随 `blank_option_groups`。
- 数据库存储的 `options` 字段对 `multi_blank_choice` 设为 `null`，分组选项放在 `content.blank_option_groups`。
- 审核暂存区对应放在 `parsed_content.blank_option_groups`。
- 不允许只存 `A,B` 作为最终标准答案，因为这会丢失槽位含义；但导入兼容层可以在已知槽位顺序时接受 `A,B`。

---

# 阶段 1 Prompt：后端数据契约、答案解析与判题

请只完成后端基础能力，不修改管理端和小程序 UI。

## 任务目标

建立多空选择题的唯一后端工具层，使导入、发布、练习判题共用相同规则。

## 1. 新建或整理统一工具模块

优先新增：

```text
backend/app/features/multi_blank_choice.py
```

提供纯函数，至少包括：

```python
extract_blank_slots(stem: str, answer: str | None = None) -> list[str]
parse_multi_blank_answer(
    answer: str | list | dict | None,
    slot_ids: list[str] | None = None,
    allow_positional: bool = True,
) -> dict[str, str]
serialize_multi_blank_answer(
    answer_map: dict[str, str],
    slot_ids: list[str],
) -> str
build_blank_option_groups(
    slot_ids: list[str],
    shared_options: list[dict] | dict,
) -> list[dict]
validate_multi_blank_question(
    groups: list[dict],
    answer: str | dict | None,
) -> tuple[bool, list[str]]
detect_shared_option_multi_blank(
    stem: str,
    options: list[dict] | dict,
    answer: str | None,
    explicit_question_type: str | None = None,
) -> dict
```

函数名可以根据项目风格调整，但职责必须集中，不能继续在多个文件复制正则。

## 2. 答案兼容格式

解析器至少兼容：

```text
①:B;②:D
①B、②D
① B，② D
(1)B、(2)D
1:B,2:D
第1空B，第2空D
A,B
B,D
```

规则：

- `A,B` 这种位置型答案只有在已经知道 `slot_ids` 且答案数等于空位数时才接受。
- 答案字母统一大写。
- 过滤重复槽位、未知槽位和非法选项时不能静默吞错，应返回可用于审核的错误。
- 禁止从题目知识内容推测答案。
- 只解析明确给出的答案文本。
- 支持 A-H，不只限定 A-D。

## 3. 精确判题

修改：

```text
backend/app/utils/answer_normalizer.py
```

让 `multi_blank_choice` 使用统一工具。

正确判定必须满足：

- 用户答案包含所有要求槽位；
- 不能缺少槽位；
- 不能多出未知槽位；
- 每个槽位答案完全一致；
- 槽位顺序不影响判定；
- 大小写及中英文标点不影响；
- 空答案或解析失败返回错误。

以下结果必须正确：

```text
标准：①:B;②:D

①:B;②:D       => true
②:D;①:B       => true
①B、②D         => true
①:B            => false
①:B;②:C        => false
①:B;②:D;③:A    => false
B,D             => true（仅在题目槽位顺序已知的调用路径中）
```

检查并删除或复用 `practice_service.py` 中重复的多空答案处理逻辑，保证只有一处事实来源。

## 4. 后端校验规则

修复当前多空题可能“无答案也通过”的问题。

`multi_blank_choice` 发布前必须满足：

- 至少 2 个空；
- `blank_option_groups` 存在；
- group id 非空且唯一；
- 每组至少 2 个选项；
- 每组选项 key 唯一；
- 正确答案覆盖所有 group id；
- 无额外答案槽位；
- 每个答案字母存在于对应组的选项中。

导入暂存可以允许缺答案，但必须：

- `answer_status = missing`；
- `is_valid` 或发布校验不能误判为可直接发布；
- 审核页显示明确风险；
- 发布接口拒绝缺答案或槽位不匹配的数据。

## 5. Hash 与去重

当前多空题可能把普通 `options` 清空，因此 question hash 可能遗漏分组选项。

修改 hash 逻辑：

- 对 `multi_blank_choice` 将 `blank_option_groups` 的 id、option key、option text 按稳定顺序加入 hash；
- 答案使用规范化后的槽位映射加入 hash；
- 相同题目不同分组选项不能产生相同 hash；
- 旧题型 hash 行为不改变。

## 6. Schema/API 兼容

保持现有 `AnswerSubmit.user_answer: str`，不要强制数据库迁移。

在服务层规范化字符串即可。

检查：

- `/api/v1/practice/questions`
- `/api/v1/practice/submit`
- `/api/v1/practice/batch-submit`
- 复习提交
- 错题详情
- AI 讲解上下文

确保 `content.blank_option_groups` 不会被序列化丢失。

## 7. 测试

新增单元测试，覆盖：

- 所有兼容答案格式；
- 缺槽位、多槽位、错选项；
- 顺序变化；
- shared options 构造；
- hash 包含 group options；
- 旧单选、多选判题不回归。

先运行最小测试，再运行后端相关测试集。

完成后停止，不做阶段 2。

---

# 阶段 2 Prompt：导入识别、审核与发布

阶段 1 已完成。现在只实现导入链路和管理端审核，不修改小程序答题 UI。

## 任务目标

让下面这种“多个空共用一套选项”的题目自动识别为 `multi_blank_choice`：

```text
一个有 n 个顶点的图用邻接矩阵 A 表示，
若图为有向图，顶点 vᵢ 的入度是（ ）；
若图为无向图，顶点 vᵢ 的度是（ ）。

A. ...
B. ...
C. ...
D. ...

答案：①B、②D
```

## 1. 调查现有导入链路

先追踪并记录实际入口，不要凭文件名猜测：

- 图片/OCR 导入；
- PDF 导入；
- 文本导入；
- AI/VL 结构化；
- `question_imports` 写入；
- 审核更新；
- 发布到 `questions`。

找到所有可能绕过统一 normalizer 的路径，并统一接入阶段 1 的 helper。

## 2. 识别“公共选项多空题”

在普通 A-D 选项已被提取后、最终题型落定前，执行共享选项多空检测。

强信号：

- 题干部分存在至少两个空位；
- 已提取一套至少两个普通选项；
- 答案能解析出至少两个槽位答案；
- 或输入显式标注“多空选择题”。

需要支持的空位：

```text
（ ）
( )
____
___
①（ ）
②（ ）
(1)（ ）
(2)（ ）
```

注意：

- 只扫描题干，不扫描选项文字、解析、代码块。
- 避免把数学区间 `(0,1)`、函数调用、代码括号当成空。
- 匿名 `（ ）` 的数量必须与答案数量一致，否则进入人工审核。
- 只有多个空但没有结构化选择答案时，不要武断改成多空选择题，可能是普通填空题。
- 有两空 + 一套选项 + `①B、②D` 是确定的多空选择题。

识别成功后：

```python
question_type = "multi_blank_choice"
options = []
blank_option_groups = build_blank_option_groups(slot_ids, shared_options)
answer = serialize_multi_blank_answer(...)
```

## 3. 保留现有“每空独立选项组”

现有如下结构必须继续工作：

```text
① A... B... C... D...
② A... B... C... D...
```

不要因为新增共享选项检测而破坏它。

两类输入最终统一成相同 `blank_option_groups` 数据契约。

## 4. 答案提取

修改答案匹配逻辑，使：

```text
答案：①B、②D
```

不会被旧正则截成单个 `B` 或识别失败。

重点检查：

- `answer_matcher.py`
- OCR 内联答案提取；
- 分离答案页按题号匹配；
- `_ANSWER_LETTERS` 一类只允许字母的正则；
- 文本导入答案规范化；
- AI 输出校验。

AI prompt 可以要求输出结构，但必须：

- 原文没有答案时输出空，不得猜测；
- 输出 `question_type=multi_blank_choice`；
- 输出完整 `blank_option_groups`；
- 答案输出 canonical string 或结构化 map；
- 后端再次规则校验 AI 输出。

## 5. 修复审核区数据

审核暂存应为：

```json
{
  "question_type": "multi_blank_choice",
  "parsed_content": {
    "text": "...",
    "blank_option_groups": [...]
  },
  "parsed_options": null,
  "parsed_answer": "①:B;②:D"
}
```

风险场景：

- 空位数与答案数不一致；
- 某个答案不在选项中；
- 只有部分空有答案；
- 识别到多个空但没有答案；
- OCR 把 `①` 识别成 `1`。

这些记录保留在审核池，增加明确 `risk_flags` / `warnings`，禁止静默降级为单选题。

## 6. 管理端审核 UI

修改管理端审核页面。

当前多空题不能只显示一个自由文本答案框，也不能提示“用 A,B 表示”。

实现结构化编辑：

- 显示每个空位；
- 每个空位展示对应选项；
- 每个空只能选择一个选项；
- 不同空可以选择相同字母；
- 支持新增/删除空位；
- 支持编辑 group id；
- 支持编辑选项文本；
- 对共享选项提供“复制到所有空”或自动同步能力；
- 保存时生成 canonical answer；
- 保存 `parsed_content.blank_option_groups`；
- `parsed_options` 对该题型设为 null；
- 切换题型时避免意外丢失数据，应二次确认或保留草稿。

答案展示应为：

```text
①：B
②：D
```

而不是普通多选标签。

## 7. 发布链路

验证审核通过和发布后：

- `questions.question_type = multi_blank_choice`
- `questions.content.blank_option_groups` 完整
- `questions.options IS NULL`
- `questions.answer` 为 canonical string
- 发布前再次严格校验
- 版本记录和审计日志保留结构变化

## 8. 回归样例

添加一个精确回归测试，文本至少包含：

```text
一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 vᵢ 的入度是（ ）；若图为无向图，顶点 vᵢ 的度是（ ）。
A. ∑...
B. ∑...
C. ∑...
D. ...
答案：①B、②D
```

断言：

```text
question_type == multi_blank_choice
len(blank_option_groups) == 2
两个 group 都有 A-D
parsed_options is None
parsed_answer == "①:B;②:D"
```

完成后停止，不做阶段 3。

---

# 阶段 3 Prompt：微信小程序答题、复习和错题模式

阶段 1、2 已完成。现在只完善小程序多空答题体验及相关结果页。

## 任务目标

复用现有 `quiz-runner` 和 adapter，不新建一套独立答题页面。

项目中已有部分：

- `multi_blank_choice` 类型标签；
- `_blankOptionGroups`；
- `selectBlankOption`；
- `serializeBlankAnswer`；
- 只读正确/错误状态。

先验证现有代码，再补缺口。

## 1. 数据适配

保证以下响应可以直接渲染：

```json
{
  "id": 352,
  "question_type": "multi_blank_choice",
  "content": {
    "text": "...",
    "blank_option_groups": [
      {"id": "①", "options": [...]},
      {"id": "②", "options": [...]}
    ]
  }
}
```

兼容：

- options 为数组；
- options 为对象；
- group id 为数字、普通字符串、圈号；
- 旧数据 answer 为 `①B、②D`；
- 新数据 answer 为 `①:B;②:D`。

## 2. 答题交互

每个空位显示独立选项组：

```text
① 请选择该空答案
A ...
B ...
C ...
D ...

② 请选择该空答案
A ...
B ...
C ...
D ...
```

要求：

- 每个空单选；
- 两个空可以同时选 B；
- 点击当前已选项可以取消；
- 选择某空时不影响其他空；
- 页面返回上一题后选择状态恢复；
- 切换题目、横滑、答题卡跳转不丢状态；
- 选项中的公式和富文本继续正常渲染；
- 无障碍/点击区域与普通选项一致。

## 3. “已作答”定义

多空题只有所有空都选择后才算已作答。

检查并修复类似以下错误逻辑：

```js
const answered = !!newAnswer
```

它会在只答一个空时错误地标为已作答。

统一使用：

```js
adapter.isQuestionAnswered(question, answerMap, keyField)
```

检查：

- practice 页面；
- review-today；
- 答题卡；
- answeredCount；
- 提交按钮；
- 未答题确认弹窗；
- 进度条。

## 4. 提交格式

提交仍使用字符串：

```json
{
  "question_id": 352,
  "user_answer": "①:B;②:D"
}
```

序列化顺序严格跟随 group 顺序。

不直接把临时 JS 对象发送给后端。

## 5. 本地答案工具一致性

修改 `miniprogram/utils/answer.js`：

- 解析规则和后端保持一致；
- `isAnswerCorrect` 必须精确比较槽位集合；
- 当前仅检查标准槽位是否都存在、但不拒绝多余槽位的逻辑要修复；
- 旧答案格式兼容；
- 位置型 `B,D` 只有在传入 slot ids 时才能解析。

本地判题只用于展示，最终结果以后端返回为准。

## 6. 结果展示

提交后逐空展示：

- 用户选项；
- 正确选项；
- 选对：绿色；
- 选错：用户选项红色，正确选项绿色；
- 未选：正确选项绿色，并标记“未作答”；
- 页面顶部显示整题正确/错误；
- 可选地显示“答对 1/2 空”，但不要改变当前整题计分规则。

整题规则：

```text
所有空都正确 => 正确
任一空错误或缺失 => 错误
```

## 7. 错题本和复习

验证：

- 错题记录保存 canonical user_answer；
- wrong-detail 能逐空回显；
- 今日复习能重新作答；
- 复习结果按整题正确性统计；
- AI 错因分析收到易读答案，例如：
  - 用户答案：①B、②C
  - 正确答案：①B、②D

## 8. 小程序测试

若项目无正式测试框架，至少增加 Node 可运行的纯函数测试脚本，覆盖：

- parse / serialize；
- 部分作答不算已作答；
- 选择/取消；
- 同一选项可用于多个空；
- 多余槽位判错；
- 旧格式兼容。

完成后停止，不做阶段 4。

---

# 阶段 4 Prompt：历史数据修复、端到端测试与收尾

阶段 1～3 已完成。现在做历史数据修复和完整回归，不新增功能。

## 1. 历史数据修复脚本

新增一个幂等脚本，例如：

```text
backend/scripts/backfill_multi_blank_choice.py
```

默认 dry-run，只有显式 `--apply` 才写库。

扫描：

- `question_imports`
- `questions`

候选条件：

- 当前题型为 `single_choice`、`choice` 或 `unknown`；
- 题干存在至少两个可靠空位；
- 有一套至少两个选项；
- 答案能解析为多个槽位答案。

例如数据库中可能存在：

```text
question_type = single_choice
stem = "...入度是（ ）；...度是（ ）。"
answer = "①B、②D"
```

转换为统一数据契约。

要求：

- 不处理有歧义记录；
- 输出候选 id、原类型、新类型、空位数、答案映射、风险；
- 每条修改可追踪；
- `--apply` 前提示备份；
- 事务失败整体回滚或按安全批次提交；
- 重复执行不产生二次变化；
- 正式题库修改时同步版本/审计机制，不能绕开项目既有治理逻辑；
- 修复后重算 question hash 和 duplicate status。

## 2. 管理端维护入口（可选）

若项目已有导入维护页面，可以增加：

- “扫描疑似多空题”
- dry-run 结果列表
- 人工勾选
- 执行转换

不要为了这个可选功能新建复杂系统；脚本优先。

## 3. 端到端测试

至少覆盖：

### 导入

```text
OCR/文本
→ question_imports
→ 管理端审核
→ 发布
→ questions
```

### 答题

```text
GET practice questions
→ 小程序选择两个空
→ submit
→ 后端判题
→ practice_records
→ 错题/复习
```

### 用例矩阵

1. 两空共用 A-D，答案 `①B、②D`。
2. 两空共用 A-D，答案 `B,D`。
3. 两空各自不同选项组。
4. 两空答案顺序交换输入。
5. 只答一个空。
6. 多提交一个不存在的空。
7. 答案字母不在选项中。
8. 三空题。
9. 普通单选含多个数学括号，不应误判。
10. 普通填空有两个空但无选择答案，不应误判。
11. 旧单选、多选、判断题完整回归。

## 4. 文档

补充项目文档：

- 题型枚举；
- JSON 数据结构；
- 答案 canonical 格式；
- 导入识别规则；
- 审核规则；
- API 提交示例；
- 历史数据修复方式。

## 5. 最终验收输出

最后输出：

- 完整变更文件清单；
- 数据契约；
- 后端测试结果；
- 管理端构建结果；
- 小程序纯函数测试结果；
- dry-run 修复统计；
- 尚存风险；
- 建议人工验收步骤。

