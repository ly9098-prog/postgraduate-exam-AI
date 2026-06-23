## 🧩 任务名称

**OCR Pipeline：新增 Structure Freeze Layer（选项结构冻结层）**

------

## 🎯 背景问题（必须理解）

当前 OCR pipeline 存在一个结构性设计缺陷：

> options（A/B/C/D 或 ①②③④）在多个 stage 被重复解析 + 反复修正

导致：

- VL OCR 输出不稳定
- normalize_schema 会“误修 options”
- AI repair 会再次改写 options
- 最终出现：
  - ❌ 选项丢失
  - ❌ 选项错位
  - ❌ A/B/C/D 不完整
  - ❌ 不同 stage 结果不一致

------

## ❗根本问题

当前 pipeline：

```text
OCR → clean → split → normalize_schema → ai_repair
```

问题是：

> ❌ “options extraction 是分散在多个 stage 中的”

------

## ✅ 正确设计目标

必须改成：

> ✔ options 只能在一个 deterministic stage 中生成
> ✔ 后续所有 stage 只能读取，不能修改

------

## 🧱 新增核心模块（必须实现）

### 📌 新文件

```
features/pipeline_stages/structure_freeze_stage.py
```

------

## 🧠 Stage 职责定义（非常重要）

### ✔ 输入

```python
raw_ocr_blocks: List[OCRBlock]
```

（OCR + clean 之后的文本块）

------

### ✔ 输出（核心结构锁定）

```python
FrozenQuestionStructure:
{
    "question_id": str,
    "stem": str,
    "options": {
        "A": str,
        "B": str,
        "C": str,
        "D": str
    },
    "option_style": "abcd | circled | roman",
    "confidence": float,
    "source_span": list[span]
}
```

------

## 🔥 核心逻辑（必须实现）

### Step 1：option detection（规则优先）

必须支持：

- `A. / B. / C. / D.`
- `A)` / `B)`
- `①②③④`
- `(A)(B)(C)(D)`
- OCR断行（如 B 单独一行）

------

### Step 2：option normalization（强制统一）

统一输出：

```text
A / B / C / D
```

------

### Step 3：option completeness check

必须检测：

- A 是否存在
- B 是否存在
- C 是否存在
- D 是否存在

如果缺失：

```python
confidence -= 0.3
flag = "INCOMPLETE_OPTIONS"
```

------

### Step 4：structure freeze（关键）

输出结构必须：

```python
FrozenQuestionStructure
```

并标记：

```python
is_frozen = True
```

------

## ❗必须修改的 pipeline DAG

### 修改 pipeline_orchestrator.py

把流程改为：

```text
OCR
↓
clean_ocr_text
↓
structure_freeze_stage   ← ⭐新增
↓
question_splitter (light mode)
↓
normalize_schema (NO mutation allowed)
↓
ai_repair (stem only)
↓
review / persist
```

------

## 🚫 强约束（必须实现，否则会回归）

### ❌ 1. 禁止 normalize_schema 修改 options

在 normalize_schema 中加入：

```python
if "options" in diff and diff["options_changed"]:
    raise RuntimeError("OPTIONS ARE FROZEN - mutation not allowed")
```

------

### ❌ 2. 禁止 ai_repair 修改 options

在 ai_repair prompt 中加入：

```
You MUST NOT modify:
- options field (A/B/C/D)

Only allowed to modify:
- stem
- explanation
- formatting
```

------

### ❌ 3. 禁止 question_splitter 做 option extraction

删除 / 禁用 fallback：

- ❌ regex option extraction fallback
- ❌ OCR-based re-detection of options

split 只允许：

```text
question boundary detection
```

------

## 🧠 数据流约束（非常关键）

### ❗必须保证：

```text
OCR → clean → FREEZE → downstream ONLY READ
```

### frozen 数据必须：

- 不可 mutate
- 不可 re-parse
- 不可重新 OCR

------

## 📊 验证标准（必须加 test）

新增测试：

### test_structure_freeze.py

验证：

#### 1️⃣ options 不丢失

- OCR 输入含 A/B/C/D
- freeze 输出必须完整

------

#### 2️⃣ options 不被修改

- inject normalize_schema mutation
- assert options unchanged

------

#### 3️⃣ AI repair 不影响 options

- before/after diff
- options must identical

------

#### 4️⃣ deterministic test

同一 OCR 输入：

```text
must produce identical frozen structure
```

------

## 🔥 成功标准

修复必须满足：

### ✔ 结构稳定性

- options extraction 只发生一次

### ✔ 可预测性

- 同输入 = 同输出

### ✔ 无二次污染

- AI / normalize / split 不再改 options

------

## 🚨 如果不修复会发生什么

当前系统会持续出现：

- OCR 正确 → options 被后处理破坏
- VL 正确 → normalize 改错
- AI 修复“修坏正确结构”

------

## 🧩 本质升级目标

从：

> ❌ best-effort OCR pipeline

升级为：

> ✅ structure-first immutable DAG pipeline

------

## 📌 一句话总结

> 在 OCR pipeline 中新增 structure_freeze_stage，使 options 在 OCR 后立即结构化并冻结，后续所有 stage 仅允许读取不得修改，并强制移除 normalize_schema / ai_repair / splitter 中所有 option mutation 行为。

------

