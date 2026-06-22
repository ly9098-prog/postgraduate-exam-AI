# ✅ [IMPLEMENTED] Code Integrity Gate — All Acceptance Criteria Met (2026-06-22)

> **Status: ✅ 已实现，功能冻结中。**
> 实现 commits: `f877db7` (gate), `80728f3` (refactor), `8a82d90` (quality fixes)
> 测试: 85/85 code_integrity tests + 112/112 ai_repair tests + 1688 full suite

<!-- Original task prompt preserved below for reference. The code integrity gate
     is now live in ai_repair.py:_should_repair() as the topmost check. -->

## 实现总结

- `code_integrity.py`: `detect_code_block_integrity`, `is_code_question`, `contains_code`, `detect_code_regression`
- `ai_repair.py`: code integrity gate in `_should_repair` + `_is_low_risk_skip_candidate` enhancement
- `ocr_quality_gate.py`: integrated `detect_code_block_integrity`
- `vision_fallback.py`: `needs_vision_fallback`, `apply_vision_fallback`
- `ai_safety.py`: code symbol protection in `safe_accept_ai_result`

------

## 🚨 问题背景（更新版 — 已修复，留档参考）

当前 OCR 导入流程在处理**代码类题目（C/C++/数据结构/算法题）**时存在严重风险：

即使存在以下结构性损坏：

- 代码块截断
- brace 不平衡（{ }）
- fenced code block 不闭合
- 代码混入乱码
- 行级断裂（if (n <= \n 1)）

系统仍可能因为：

- confidence_score 高
- option/answer 成功解析
- parsed_success == true

👉 直接进入 `skip repair` 或 `validation passed`

------

## ❗ 核心问题（已升级定义）

### ❌ 错误决策来源（必须废弃）

- confidence_score > threshold
- parsed_success == True
- answer_found == True
- option_extracted == True

👉 以上 **不能作为 skip repair 的依据**

------

## 🎯 新目标（系统级规则）

建立新原则：

> 🔥 **Code integrity 优先级高于 OCR confidence**

------

# 🧩 1. 代码题识别（必须新增）

```python
def is_code_question(text: str) -> bool:
    code_signals = [
        "typedef", "struct", "class",
        "public:", "private:",
        "return", "void ", "int ", "char ",
        "{", "}", "(", ")"
    ]

    score = sum(1 for s in code_signals if s in text)
    return score >= 4
```

------

# 🧱 2. Code Integrity Score（必须新增核心模块）

```python
def compute_code_integrity_score(text: str) -> dict:
```

## 检测维度：

### (1) code fence 完整性

- ```是否成对
  
  ```

### (2) brace 平衡

- `{` vs `}`

### (3) bracket 平衡

- `(` vs `)`

### (4) 截断检测

识别：

- 行断裂（if (n <= \n 1)）
- struct/function 未闭合
- code block 未结束

### (5) OCR 乱码检测

典型特征：

- `1typu`
- `p1tysI`
- `aonu2s`
- 非语义字符混入代码段

------

## 输出结构：

```python
return {
    "score": 0~5,
    "flags": [
        "code_block_incomplete",
        "code_block_truncated",
        "code_brace_unbalanced",
        "code_garbled_text",
        "code_fence_unclosed"
    ]
}
```

------

# 🚨 3. Skip 逻辑（关键修复点）

## ❌ 删除旧逻辑

```python
if confidence_score > 0.95:
    repair_skipped = True
```

------

## ✅ 替换为新逻辑

```python
if is_code_question(text):

    integrity = compute_code_integrity_score(text)

    if integrity["score"] <= 3:

        repair_skipped = False
        validation_status = "needs_repair"
        risk_level = "high"

        route_to = [
            "vision_fallback",
            "ocr_correction",
            "ai_repair"
        ]

        add_risk_flags(integrity["flags"])
```

------

# 🚫 4. 强制禁止规则（必须执行）

当 `is_code_question == True`：

## ❌ 禁止 skip 条件：

- confidence_score
- parsed_success
- answer_found
- option_extracted

👉 这些字段**全部失效于 skip 决策**

------

# ⚠️ 5. 风险升级机制

满足任意条件：

- code_block_truncated
- code_block_incomplete
- code_brace_unbalanced
- code_garbled_text

👉 必须：

```python
risk_level = "high"
requires_manual_review = True
```

------

# 🔁 6. Pipeline 插入位置（必须）

```text
OCR Output
   ↓
OCR Quality Gate
   ↓
🔥 CODE INTEGRITY CHECK（新增）
   ↓
Skip Decision Engine（已修改）
   ↓
Repair / Vision fallback / AI repair
```

------

# 📌 7. Case 验证规则

## Case A（必须 repair）

~~~c
typedef struct BiTNode {
char data;
``` (truncated / missing brace)
~~~

👉 结果：

- ❌ 不允许 skip
- ✔ 必须进入 repair pipeline

------

## Case B（允许通过）

```c
int f(int n){
    return n;
}
```

👉 integrity score = 5
👉 ✔ allow pass

------

# 🚀 8. 成功验收标准

系统必须保证：

## ✔ Code Question

- 100% 触发 code integrity check
- 100% 阻止错误 skip
- 所有结构损坏进入 repair / fallback

------

## ✔ Non-code Question

- 不受影响
- 原 OCR pipeline 行为保持不变

------

# 🎯 一句话总结（系统级定义）

> OCR confidence 不能再决定代码题是否 skip，必须由 code integrity gate 接管所有结构安全判断。**