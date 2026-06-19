## 🚀 任务：AI Repair 升级为“结构化罗马数字修复决策系统”

当前 OCR 修复链路中：

- rule layer 已完成：
  - 罗马数字序列检测（I–V）
  - 跳号检测（gap detection）
  - 1 ↔ I 混淆检测
  - 结构完整性 warning 标记

但仍存在核心问题：

> ⚠ AI repair 阶段仍然是“自由文本修复”，缺乏结构化输入与决策约束，导致修复结果不可预测、不可回归验证。

------

## 🎯 本次任务目标

请将 **AI repair 阶段升级为“结构化决策系统”**，实现以下能力：

### 1. 引入标准化 Roman numeral error schema

将 rule layer 输出的 warning 转换为统一结构，例如：

```json
{
  "error_type": "roman_numeral_sequence_break",
  "sequence": ["I", "II", "II", "IV", "V"],
  "issues": [
    {
      "type": "duplicate",
      "position": 2,
      "value": "II"
    }
  ],
  "expected_pattern": "monotonic I-V sequence"
}
```

------

### 2. AI repair prompt 改造为“受约束决策模式”

要求 AI 不再自由生成文本修复，而是必须：

- 从候选修复动作中选择
- 或明确标记 uncertain

示例：

```
Given structured OCR anomaly report:

You MUST choose ONE action:

A. Fix position 2: II → III
B. Fix position 3: II → III
C. Keep unchanged
D. Mark as uncertain (no change)

Constraints:
- Must preserve sequence monotonicity
- Must avoid duplicate Roman numerals unless justified
```

------

### 3. 引入 Roman numeral ambiguity resolver 逻辑设计

请定义一套策略，用于处理：

- duplicate sequence（I, II, II, IV）
- missing gap（I, II, IV）
- OCR ambiguity（II vs III）

要求输出：

```json
{
  "ambiguity_detected": true,
  "type": "gap_or_duplicate",
  "strategy": "sequence_completion_or_minimal_edit"
}
```

------

### 4. 明确 rule layer 与 AI layer 边界

请严格定义：

#### rule layer 只允许：

- error detection
- tagging
- safe local fixes（如 1 → I）

#### AI repair 承担：

- sequence inference
- missing numeral inference
- conflict resolution
- final correction decision

------

## 📌 最终交付物

请输出：

1. Roman numeral repair schema（JSON结构定义）
2. AI repair prompt（可直接替换现有 prompt）
3. ambiguity resolver 设计逻辑（规则说明）
4. rule vs AI layer 边界说明（清晰职责划分）

------

# 💡 为什么这样写 Claude 才能“做对”

这个任务描述的关键点是：

### ✔ 不给“实现自由度”

否则 Claude 会继续写工具函数

### ✔ 强制“结构化输入”

否则 AI repair 还是会变成文本修补器

### ✔ 强制“决策式输出”

否则不可回归测试

