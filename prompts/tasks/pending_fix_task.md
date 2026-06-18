# PENDING_FIXED_TASK

> **状态：✅ 已完成** (2026-06-18)
>
> 详见 commit `fix(ocr): add quality gate, option completeness validation, anti-false-success, parse cache`

##### 原题(原题选项区域存在半透明水印)

```tex
在一个单链表，已知 q所指结点是p所指结点的前驱结，若在 q和p之间插入结点s,则执行()。

A. s − >next = p − >next;p − >next = s;			B. p − >next = s − >next;s − >next = p;
C. q − >next = s; s − >next = p;				D. p − >next = s − >next;s − >next = q;
```

##### 前端内容显示

```tex
在一个单链表，已知 q所指结点是p所指结点的前驱结，若在 q和p之间插入结点s,则执行()。

A. s − >next = p − >next;p − >next = s;
B. p − >next = s − >next;s − >next = p;
C. q − >next = s; s − >next = p;	
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "在一个单链表，已知 q所指结点是p所指结点的前驱结，若在 q和p之间插入结点s,则执行()。"
  },
  "parsed_options": {
    "A": "s->next=p->next;p->next=s;",
    "B": "p->next=s->next;s->next=p;",
    "C": "q->next=s; s->next=p;"
  },
  "parsed_answer": "C",
  "parsed_analysis": null
}
```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "在一个单链表，已知 q所指结点是p所指结点的前驱结，若在 q和p之间插入结点s,则执行()。",
    "options": [
      {
        "key": "A",
        "text": "s->next=p->next;p->next=s;"
      },
      {
        "key": "B",
        "text": "p->next=s->next;s->next=p;"
      },
      {
        "key": "C",
        "text": "q->next=s; s->next=p;"
      }
    ],
    "blank_option_groups": [],
    "answer": "C",
    "analysis": "",
    "raw_text": "06.在一个单链表，已知 \\alpha所指结点是p所指结点的前驱结，若在 \\alpha和p之间插入结点\ns,则执行()。\nA. s->next=p->next;p->next=s; B. p->next=s->next;s->next=p;\nC. q->next=snexP主Apxt-s-ext=q;\nCIS",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "1.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "incomplete_options: missing D",
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "3094f505",
    "confidence_score": 0.85,
    "risk_flags": [],
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "incomplete_options: missing D",
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "3094f505",
    "risk_flags": null
  }
}
```

## 🎯 任务目标

请你在不破坏现有 OCR/解析链路的前提下，对当前系统进行增强修复，重点解决以下问题：

- OCR 结果中**选项缺失（尤其 D 选项）**
- parsed 结果与 raw OCR 不一致
- 前端展示与后端 parsed 不一致
- OCR 水印/噪声导致文本污染
- 解析器“看似成功但实际信息不完整”的问题未被拦截

------

## 🧩 当前问题本质（必须理解）

现有链路存在“假成功”问题：

```
OCR raw_text → parsed_content → frontend
```

问题在于：

- OCR raw_text 已经损坏（水印/乱码/字符替换）
- parsed_content 仍然“强行解析成功”
- missing option（如 D）不会阻断流程，只是 warning
- 前端依赖 parsed_content，导致错误数据被展示

------

## 🛠️ 修复目标（必须实现）

### ✅ 目标1：选项完整性强校验（核心）

对所有单选题必须执行：

- 标准选项集合必须完整（A / B / C / D）
- 不允许“部分选项通过”

#### 校验规则：

```ts
REQUIRED_OPTIONS = ["A", "B", "C", "D"]

if question_type === "single_choice":
    assert all REQUIRED_OPTIONS exist in parsed_options
```

如果缺失：

- ❌ 不允许 is_valid = true
- ❌ 不允许进入 frontend
- ✅ 必须进入 retry 或 fallback pipeline

------

### ✅ 目标2：OCR污染检测机制（新增）

在 parsed 前增加一层：

#### 检测规则：

- 是否出现异常字符替换（如 α 替代 q）
- 是否出现乱码模式（如 `snexP`, `Apxt`, `ext=q`）
- 是否出现“next指针语义断裂”
- 是否存在 option 结构破损（A/B/C 不完整）

#### 输出：

```json
"ocr_quality_flags": [
  "watermark_noise_detected",
  "symbol_substitution_detected",
  "option_structure_corrupted"
]
```

如果 flags >= threshold：

👉 直接禁止 parsed 进入正常流程

------

### ✅ 目标3：解析一致性校验（raw vs parsed）

新增 cross-check：

```ts
assert parsed_options ⊆ extract_options(raw_text)
```

如果：

- raw_text 中存在 D
- parsed_options 缺 D

👉 判定为 **解析丢失（CRITICAL）**

------

### ✅ 目标4：防“假成功机制”（非常关键）

当前最大问题是：

> parsed_content is_valid = true 但其实数据不完整

必须修改：

### ❌ 禁止逻辑：

```ts
is_valid = true 只基于 stem 成功
```

------

### ✅ 新逻辑：

```ts
is_valid = (
  stem_valid &&
  options_complete &&
  no_critical_ocr_corruption
)
```

任何一项失败：

👉 整体 is_valid = false

------

### ✅ 目标5：防重发 / 防重复解析机制（新增）

避免同一张 OCR 图：

- 多次进入解析 pipeline
- 多次生成不同版本 parsed

#### 实现机制：

对 stem_hash + raw_text hash 建立缓存：

```ts
cache_key = hash(stem_hash + raw_text)
```

规则：

- 如果 cache hit：
  - 直接返回第一次“validated result”
  - 不允许重新解析覆盖
- 如果检测到 OCR correction retry：
  - 必须标记 version +1
  - 并记录 diff

------

### ✅ 目标6：失败必须可追踪（不可静默失败）

如果发生以下情况：

- 选项缺失
- OCR污染
- raw/parsed 不一致

必须输出：

```json
{
  "validation_status": "failed",
  "failure_reason": [
    "missing_option_D",
    "ocr_corruption_detected"
  ],
  "retry_recommended": true
}
```

------

## 🧱 建议架构改造（允许你调整代码结构）

建议增加一层：

```
OCR Raw
  ↓
OCR Quality Gate（新增）
  ↓
Parser
  ↓
Validation Engine（增强）
  ↓
Frontend
```

------

## 🚨 本次修复必须覆盖的 case

必须确保以下情况不会通过：

### ❌ case 1：缺 D 选项

- parsed 只有 A/B/C → ❌ 必须失败

### ❌ case 2：raw_text 有 D，但 parsed 丢失

- → ❌ CRITICAL FAILURE

### ❌ case 3：OCR 乱码污染

- α / snexP / next断裂 → ❌ reject

------

## 🎯 成功标准

修复后系统必须满足：

- parsed 100% 选项完整性
- OCR 污染不会进入解析层
- frontend 不可能展示不完整单选题
- is_valid 不再“误判成功”
- 同一输入不会产生多个 parsed 版本

------

## ⚠️ 强约束

- 不允许仅靠 warning 修复
- 不允许”默认补齐选项”
- 不允许 silent fallback
- 必须 fail-fast 或 retry

------

## ✅ 实施记录 (2026-06-18)

### 变更文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/features/ocr_quality_gate.py` | 新增 | OCR 污染检测 + 解析一致性 cross-check |
| `backend/app/features/question_normalizer.py` | 修改 | 核心验证增强 + 缓存机制 + 失败追踪 |
| `backend/app/features/question_pipeline.py` | 修改 | `validate()` 增加选项完整性强校验 |
| `backend/app/features/batch_validation.py` | 修改 | 单选题缺选项从 warning 升级为 error |

### 各目标实现

| 目标 | 状态 | 实现位置 |
|------|------|----------|
| Goal 1: 选项完整性强校验 | ✅ | `question_normalizer.py:_check_option_completeness()` |
| Goal 2: OCR 污染检测 | ✅ | `ocr_quality_gate.py:detect_ocr_contamination()` |
| Goal 3: 解析一致性 cross-check | ✅ | `ocr_quality_gate.py:cross_check_consistency()` |
| Goal 4: 防假成功 is_valid | ✅ | `question_normalizer.py:normalize_question()` 复合判定 |
| Goal 5: 防重发缓存 | ✅ | `question_normalizer.py:parse_cache_*()` |
| Goal 6: 失败追踪 | ✅ | `validation_status` / `failure_reason` / `retry_recommended` 字段 |

### 测试覆盖

- 缺 D 选项 → `is_valid=False`, `retry_recommended=True`
- 完整 A/B/C/D → `is_valid=True`, `validation_status=”passed”`
- OCR 乱码 (α/snexP/Apxt) → `is_valid=False`, `ocr_critical_corruption`, confidence 封顶 0.30
- raw 有 D 但 parsed 丢失 → `parse_loss: raw_has_D_parsed_missing` (CRITICAL)
- 现有测试套件 398 passed（无回归）


