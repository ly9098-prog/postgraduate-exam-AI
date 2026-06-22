# 🚀 OCR Pipeline RC Final Task（优化完整版）

------

# 🧭 0. 系统状态声明（STATE MACHINE）

```text
SYSTEM_NAME: postgraduate-exam-AI-main
VERSION: v1.0-rc
STATE: FREEZE
MODE: RELEASE_CANDIDATE
```

------

## ✔ 状态规则

### allowed actions

- bug fix（仅修复明确缺陷）
- performance optimization（不改逻辑）
- test expansion（新增测试，不改pipeline）

### forbidden actions

- ❌ 新增 pipeline stage
- ❌ 新增 AI 路由 / 模型
- ❌ 修改 skip / gate 核心逻辑
- ❌ 引入新业务流程

------

# 🎯 1. 系统目标（不变）

系统为：

> OCR + AI 驱动的题库自动导入 pipeline

已具备：

- OCR（PaddleOCR + VL fallback）
- code integrity 检测
- OCR quality gate
- AI repair / enrich / complete
- pipeline orchestrator
- review + DB 入库

------

# 🧪 2. 核心任务（必须执行）

------

## 🥇 Task 1：全链路真实数据压测

执行完整 pipeline：

```text
PDF → OCR → normalize → quality_gate → code_gate → AI correction → split → match → review → DB
```

------

## ✔ 测试覆盖必须包括：

- C / C++ 代码题（结构体 / 指针 / 递归）
- 数学公式题
- 普通选择题
- watermark污染样本
- OCR截断样本
- 双栏排版样本

------

## ✔ 验证规则（CRITICAL）

```text
✔ code_block_incomplete → 必须 BLOCK
✔ code_structure_regression → 必须 BLOCK
✔ confidence_score ≠ override structure error
✔ low_risk_high_confidence → 不能 bypass code gate
✔ vision fallback → code error 必须触发
✔ parsed vs raw mismatch → 必须检测
```

------

## 🚨 PASS / FAIL 判定

### PASS

必须同时满足：

- 无 code gate bypass
- 无 skip override
- 所有 decision_trace 完整
- pipeline 输出稳定一致

------

### FAIL

满足任一：

- code error 被放行
- skip bypass gate
- confidence override structure error
- decision_trace 缺失关键节点

------

### BLOCK

满足任一：

- code结构错误未被识别
- fallback 未触发
- gate逻辑不执行

------

# 📊 3. Task 2：决策可观测性（decision_trace）

------

## ✔ 必须输出 schema（强制结构化）

```json
decision_trace: [
  {
    "stage": "ocr_quality_gate",
    "result": "pass",
    "reason": "score=0.91"
  },
  {
    "stage": "code_gate",
    "result": "blocked",
    "reason": "code_block_incomplete"
  },
  {
    "stage": "ai_repair",
    "result": "skipped",
    "reason": "structure_error"
  }
]
```

------

## ✔ 必须包含字段

| 字段      | 必须     |
| --------- | -------- |
| stage     | ✔        |
| result    | ✔        |
| reason    | ✔        |
| timestamp | optional |

------

## ❗要求

> 必须能够解释“每一个题为什么通过或失败”

------

# 🧱 4. Task 3：系统冻结验证（RC Freeze）

------

## ✔ 冻结目标

确认系统进入：

> 🚨 production release candidate（v1.0 RC）

------

## ✔ freeze验证规则

系统必须满足：

- pipeline行为不可变
- 不存在隐藏 bypass
- code gate 无例外路径
- skip机制不可绕过

------

## ❌ 禁止行为（强约束）

- 新增 AI pipeline
- 新增 OCR路径
- 新增 fallback策略
- 修改 gate逻辑
- 引入实验性模型

------

# 🧠 5. 验收标准（最终判定）

------

## ✔ SYSTEM PASS 条件

```text
1. code损坏题不会进入 passed
2. skip机制无法绕过 code gate
3. 所有 decision_trace 完整
4. pipeline 输出稳定一致
5. 无 bypass路径
```

------

## ❌ SYSTEM FAIL 条件

```text
1. 任意 code error 被放行
2. confidence override structure error
3. missing decision_trace
4. fallback未触发但仍pass
```

------

## 🚨 SYSTEM BLOCK 条件

```text
1. code gate未执行
2. code结构未检测
3. OCR错误未进入修复链
```

------

# 📦 6. 输出要求（Claude Code CLI）

------

## 必须输出：

### 1. 回归测试结果

- 各类样本通过率
- code类样本是否100%拦截

------

### 2. bypass检测结果

```text
是否存在任何：
- skip bypass
- confidence override bypass
- gate绕过路径
```

------

### 3. decision_trace 示例（至少3条）

必须覆盖：

- code题
- 普通题
- OCR污染题

------

### 4. freeze结论

必须明确：

```text
CAN FREEZE: YES / NO
```

------

# 🧭 7. 最终一句话定义系统目标

> 本系统必须保证：任何“代码结构损坏”都不会被误判为有效题目，并且所有放行路径必须可解释、可追踪、不可绕过。

