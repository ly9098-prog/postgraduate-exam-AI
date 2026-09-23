> **不要按本文施工（2026-09-23）。** 这是收进 `backlog/` 的历史任务书，不代表当前工作。现行范围见 `docs/project/ROADMAP.md`。

# 🚀 AI Repair v2（Admin导入题库前字段补全 + 结构修复）

------

# 🧭 0. 任务定位（必须先纠正）

## ❗本模块的真实定位

> 🧩 Admin「待导入题目」页面的 AI 补全系统
> ❗不是 OCR pipeline
> ❗不是系统级 repair engine
> ❗不是 final gate / quality gate

------

## ✔ 作用边界（非常重要）

```text
输入：OCR/Excel/PDF/文本导入后的“待入库题目”
输出：结构完整 + 字段补全后的标准题目
```

------

## ✔ 核心约束

- ❌ 不参与 pipeline 决策
- ❌ 不控制 skip / confidence / gate
- ❌ 不影响系统是否通过
- ✔ 只负责“入库前规范化”

------

# 🧠 1. 审计总结（基于你提供报告）

------

## 🧨 当前AI Repair本质问题（已确认）

### ❌ 问题1：职责混合

- 字段补全（complete）
- 结构修复（repair）
- 代码修复
  👉 全部混在一个 LLM体系

------

### ❌ 问题2：answer 被污染风险

- 无硬约束
- 无 diff rollback
- 无独立保护层

------

### ❌ 问题3：code修复能力弱但被误当能力

> 实际只是 token-level 文本修复，不是结构恢复

------

### ❌ 问题4：batch 与 single repair 行为不一致

- code protection 在 batch 中缺失
- prompt规则不统一

------

### ❌ 问题5：字段责任不清

- difficulty / knowledge_points
  - 有时 AI生成
  - 有时直接继承
    👉 行为不一致

------

# 🧭 2. 新架构设计（去耦合版本）

------

# 🧱 AI Repair v2 = 三模块拆分（关键）

```text
┌──────────────────────────────┐
│ 1. Field Completer            │
│ 2. Structure Normalizer       │
│ 3. Code Structure Fixer       │
└──────────────────────────────┘
```

------

# 🧩 2.1 Field Completer（字段补全模块）

## ✔ 职责（唯一职责）

补全：

- subject
- knowledge_points
- difficulty
- question_type

------

## ❌ 禁止行为

- 不允许修改 stem
- 不允许修改 options
- 不允许修改 answer

------

## ✔ 输出

```json
{
  "subject": "...",
  "knowledge_points": [...],
  "difficulty": 1-5,
  "question_type": "single_choice"
}
```

------

## 🧠 规则

- knowledge_points 必须基于题干
- 不允许外推知识体系
- 不允许 hallucination

------

# 🧱 2.2 Structure Normalizer（结构标准化模块）

------

## ✔ 职责

统一结构：

- 题干断行修复
- A/B/C/D选项规范化
- JSON结构标准化

------

## ✔ 不做：

- 不做知识补全
- 不做语义扩展
- 不做答案修改

------

## ✔ 输出保证

```text
题干 + 选项结构完整
但语义不变
```

------

# 🧱 2.3 Code Structure Fixer（仅代码结构）

------

## ✔ 触发条件

仅当：

```text
enable_code_fix = true
```

------

## ✔ 修复范围

- if / for / while 断行
- <= >= == 运算符拆分
- struct / function 结构恢复
- code fence修复

------

## ❌ 禁止

- 不允许重写逻辑
- 不允许补代码
- 不允许优化代码

------

## ✔ 本质

> 🧠 token-level structural repair engine

------

# ⚠️ 3. 强制安全规则（来自审计）

------

## 🚨 3.1 Answer保护（必须）

```text
如果原始 answer 非空：

AI 不允许修改 answer
```

------

## 🚨 3.2 code修复后必须二次检查

```text
Code Fix → 必须重新执行结构检查
```

------

## 🚨 3.3 字段隔离原则

```text
Field Completer ≠ Structure Fixer ≠ Code Fixer
```

------

# 🧪 4. 输入输出定义

------

## ✔ 输入

```json
{
  "stem": "...",
  "options": "...",
  "answer": "...",
  "analysis": "...",
  "source": "ocr/pdf/excel/text"
}
```

------

## ✔ 输出

```json
{
  "stem": "...",
  "options": [],
  "answer": "...",
  "analysis": "...",
  "subject": "...",
  "knowledge_points": [],
  "difficulty": 1-5,
  "question_type": "single_choice"
}
```

------

# 🧠 5. AI行为边界（最关键）

------

## ❌ AI不能做的事

- 不能改答案
- 不能改题意
- 不能推理补全缺失代码
- 不能扩展知识体系

------

## ✔ AI可以做的事

- 补字段（subject / kp / difficulty）
- 修结构（断行 / 格式）
- 修代码（token-level）

------

# 📏 6. 成功标准（验收）

------

## ✔ 字段层

- subject准确率 ≥ 90%
- knowledge_points合理性 ≥ 85%

------

## ✔ 结构层

- options完整率 = 100%
- JSON结构合法率 = 100%

------

## ✔ 代码层

- 运算符修复率 ≥ 95%
- code fence恢复率 ≥ 99%

------

## ✔ 安全层

- answer 零污染
- 无 hallucinated knowledge
- 无结构越权修改

------

# 🚀 7. 与 final_task 的区别（关键）

| 模块         | 职责                           |
| ------------ | ------------------------------ |
| final_task   | 系统级验收 / pipeline / freeze |
| AI Repair v2 | 入库前数据规范化               |
| OCR pipeline | 数据生成                       |
| admin AI补全 | 人工审核前增强                 |

------

# 🧠 8. 一句话定义

> 🧩 AI Repair v2 是“入库前题目标准化与字段补全引擎”，只负责结构与字段，不参与系统决策。

