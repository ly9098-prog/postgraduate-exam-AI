# 新增「文本题目识别导入」功能

## 目标

在 Admin 后台新增一种题目录入方式：

- OCR导入（已有）
- PDF导入（已有）
- Excel导入（已有）
- 图片导入（已有）
- **文本导入（新增）**

用户直接粘贴题目文本，系统自动解析并结构化为题目数据。

---

## 修订说明（审计后修正）

| 修正项 | 原方案 | 修正后 |
|--------|--------|--------|
| 前端框架 | `TextImport.vue` | Next.js App Router 页面 `admin-frontend/src/app/(admin)/questions/text-import/page.tsx` |
| 后端模块位置 | `backend/app/services/text_question_parser.py` | `backend/app/features/text_question_parser.py` |
| 解析管线 | 独立解析，直接写入 DB | 扩展 `question_splitter.py`，经 `process_question_pipeline()` 统一处理 |
| 选项结构 | `{"A": "...", "B": "..."}` | `[{"key": "A", "text": "..."}]`（对齐现有标准） |
| 判断题型名 | `judge` | `true_false`（对齐 `QuestionNormalizer` 枚举） |
| source_type | 未定义 | `text` |

---

# 一、新增导入入口

## Admin 页面

文件：`admin-frontend/src/app/(admin)/questions/text-import/page.tsx`

界面包含：

- 多行文本输入框（Textarea）
- 科目选择下拉框（必填，确定 subject 字段）
- 实时字符统计
- 解析按钮
- 解析结果预览区
- 批量确认导入按钮

## API Endpoint

新增：`POST /api/admin/v1/imports/text-parse`

```
权限：import:write
Body: { text: string, subject: string }
Response: { data: { questions: QuestionSchema[], warnings: string[] } }
```

流程：

```
用户粘贴文本 + 选择科目
        ↓
POST /api/admin/v1/imports/text-parse
        ↓
后端：text_question_parser 切分文本 → process_question_pipeline() 标准化/去重/校验
        ↓
返回结构化结果 + warnings
        ↓
前端预览（可编辑、删除单题）
        ↓
确认导入 → 写入 question_imports 表
        ↓
审核工作台审核 → 正式入库 questions
```

---

# 二、支持识别的文本格式

## 格式1：题干、选项、答案、解析连续排列

示例：

```
【题目】
操作系统采用时间片轮转调度算法的主要目的是（）。

【选项】
A. 提高系统吞吐量
B. 提高CPU利用率
C. 保证响应时间
D. 减少进程切换

【答案】
C

【解析】
时间片轮转属于分时系统调度算法，其主要目标是保证系统响应时间。
```

解析结果（对齐现有标准 Schema）：

```json
{
  "question": "操作系统采用时间片轮转调度算法的主要目的是（）。",
  "options": [
    {"key": "A", "text": "提高系统吞吐量"},
    {"key": "B", "text": "提高CPU利用率"},
    {"key": "C", "text": "保证响应时间"},
    {"key": "D", "text": "减少进程切换"}
  ],
  "answer": "C",
  "analysis": "时间片轮转属于分时系统调度算法，其主要目标是保证系统响应时间。",
  "question_type": "single_choice"
}
```

---

## 格式2：上下分栏自测版

示例：

```
【题目】
操作系统采用时间片轮转调度算法的主要目的是（）。

【选项】
A. 提高系统吞吐量
B. 提高CPU利用率
C. 保证响应时间
D. 减少进程切换

------

【答案】
C

【解析】
时间片轮转属于分时系统调度算法，其主要目标是保证系统响应时间。
```

要求：自动识别分隔线 `----` / `====`，自动匹配答案和解析。

---

# 三、支持批量题目识别

允许一次粘贴多道题，用分隔线 `====` 或 `----` 分割。

示例：

```
【题目】
第一题...

【选项】
A...
B...
C...
D...

【答案】
A

【解析】
...

====================

【题目】
第二题...

【选项】
A...
B...
C...
D...

【答案】
B

【解析】
...
```

返回：

```json
[
  { "question": "...", "options": [...], "answer": "...", "analysis": "..." },
  { "question": "...", "options": [...], "answer": "...", "analysis": "..." }
]
```

---

# 四、兼容真实用户输入

不要依赖固定格式。

## 标签变体

支持：

| 题干 | 答案 | 解析 |
|------|------|------|
| 题目 | 答案 | 解析 |
| 【题目】 | 【答案】 | 【解析】 |
| 题干 | 正确答案 | 分析 |
| Question | Answer | Analysis |

---

## 选项变体

支持：

```
A.  B.  C.  D.
A、 B、 C、 D、
A:  B:  C:  D:
A． B． C． D．
(A) (B) (C) (D)
①②③④
```

---

## 多选题

```
答案：ACD
```

解析结果：

```json
{ "answer": ["A", "C", "D"], "question_type": "multiple_choice" }
```

---

## 判断题

```
【题目】
Linux内核属于宏内核架构。

【答案】
正确
```

解析结果：

```json
{ "answer": true, "question_type": "true_false" }
```

兼容：正确/错误、对/错、True/False、√/×、T/F

---

# 五、智能题型识别

根据内容自动判断：

| 条件 | 题型 |
|------|------|
| 存在 A/B/C/D 选项 + 答案为单个 | `single_choice` |
| 存在 A/B/C/D 选项 + 答案为多个 | `multiple_choice` |
| 答案为 正确/错误/对/错/True/False | `true_false` |
| 无选项，只有题干+答案 | `subjective` |

---

# 六、解析容错

## 空行混乱

自动清洗多余空行，规范化换行。

## 中英文符号混用

统一规范化：
- `：` → `:`
- `．` → `.`
- `【】` 保留或转为无标签模式

## OCR残留字符

识别并修复：
- `A . xxx` → `A. xxx`
- `A、 xxx` → `A. xxx`（内部规范化）
- `A  xxx` → `A. xxx`

## 缺失标签

无 `【题目】` 等标签时，依靠位置启发式切分：

```
操作系统采用时间片轮转调度算法的主要目的是（）。

A. 提高系统吞吐量
B. 提高CPU利用率
C. 保证响应时间
D. 减少进程切换

答案：C

解析：xxxx
```

也能识别成功。

---

# 七、后端实现

## 策略：扩展现有模块，不另起炉灶

### 扩展 `backend/app/features/question_splitter.py`

新增能力：
- 分隔线识别（`====` / `----` / `****`）
- 标签变体识别（`题目` / `【题目】` / `Question` 等）
- 缺失标签时基于位置启发式切分

### 新增 `backend/app/features/text_question_parser.py`

职责：
- 文本预处理（符号规范化、空行清洗、OCR残留修复）
- 调用扩展后的 `question_splitter.split_questions()`
- 调用 `QuestionNormalizer` 标准化
- 题型自动判断
- 返回 `list[dict]` 结构化结果 + warnings

### 集成 `process_question_pipeline()`

所有解析结果必须经过 `process_question_pipeline()`：
- 标准化/校验（`QuestionNormalizer`）
- 去重（`question_hash`）
- `import_fields` / `question_fields` 切分
- 可选 AI repair（通过 enrich endpoint 单独触发）

解析器不直接写入 DB，中间结果由 pipeline 统一处理。

### API endpoint

在 `backend/app/api/v1/admin_imports.py` 中新增：

```
POST /api/admin/v1/imports/text-parse
```

解析成功 → 返回结构化数据供前端预览
确认导入 → 走现有 `question_imports` 批量创建流程 → 审核工作台

---

# 八、前端实现

文件：`admin-frontend/src/app/(admin)/questions/text-import/page.tsx`

技术栈：Next.js 16 + React 19 + TypeScript + Tailwind CSS

复用：
- `apiRequest` HTTP 客户端
- 审核工作台的题干/选项渲染逻辑（`review/page.tsx` 中的组件）

功能：
- 粘贴文本
- 科目选择（必填下拉框）
- 实时字符统计
- 点击解析 → 调用 `POST /api/admin/v1/imports/text-parse`
- 解析结果预览（题目列表 + warnings）
- 单题编辑/删除
- 批量确认导入

解析结果预览：

```
题目 1  [single_choice]  [编辑] [删除]
题干：操作系统采用时间片轮转调度算法的主要目的是（）。
选项：
  A. 提高系统吞吐量
  B. 提高CPU利用率
  C. 保证响应时间
  D. 减少进程切换
答案：C
解析：时间片轮转属于分时系统调度算法，其主要目标是保证系统响应时间。
```

---

# 九、数据库

无需新增表。

`source_type` 新增值：`text`

复用现有：
- `questions`
- `question_imports`

导入流程与 OCR 导入保持一致（pipeline → import 记录 → 审核 → 正式入库）。

---

# 十、与 AI 标准化的关系

- 文本解析默认为纯规则解析（不调用 AI）
- 解析结果已写入 `question_imports` 后，可选择性触发 `POST /imports/{batchId}/enrich` 进行 AI 辅助补全
- AI enrich 为可选操作，不影响基本导入流程

---

# 十一、验收标准

以下内容均能正确解析：

1. 标签格式单选题
2. 标签格式多选题（答案如 ACD）
3. 判断题（正确/错误/对/错/True/False）
4. 问答题（无选项，仅题干+答案）
5. 批量题目（分隔线分割）
6. 上下分栏格式（分隔线在答案前）
7. 标签缺失格式（纯文本 + 选项行 + 答案行）
8. OCR 残缺格式（`A .` / `A、` / `A  `）
9. 中英文符号混用（`A．` / `A:` / `【】`）
10. 含 LaTeX 公式的题干不被损坏
11. 空行混乱的文本正确清洗

原则：**宁可返回 warnings 智能恢复，也不直接解析失败。**

若无法完全识别，返回 warning 信息而不是报错中断。

---

# 十二、推荐的实施顺序

| 步骤 | 内容 | 预估 |
|------|------|------|
| Step 1 | 扩展 `question_splitter.py`（分隔线、标签变体、位置启发式） | 1天 |
| Step 2 | 新增 `text_question_parser.py` + 集成 `process_question_pipeline()` | 0.5天 |
| Step 3 | 新增 `POST /api/admin/v1/imports/text-parse` endpoint | 0.5天 |
| Step 4 | 实现 `text-import/page.tsx` React 页面 | 1天 |
| Step 5 | 端到端测试 + 验收标准覆盖 | 0.5天 |
