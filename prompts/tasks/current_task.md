## 🎯 任务名称

OCR Pipeline v3 — Anti-Mutation DAG Architecture (ZERO TRUST OCR SYSTEM)

------

# 🚨 一、核心目标（必须理解）

当前系统的根本问题不是：

- ❌ OCR 精度
- ❌ code detection 规则
- ❌ clean text 逻辑

而是：

# 🚨 数据在 pipeline 中“被允许随意变形（mutation）”

------

## ✔ 本次升级目标：

建立一个系统：

> ✔ 任意 stage 不能修改不属于它的 region
> ✔ code 永远不可被 mutation
> ✔ 每一步输入输出必须可验证
> ✔ pipeline 必须 DAG 化（不可串行污染）

------

# 🧱 二、系统架构（必须实现）

------

## 🔷 1. DAG Pipeline（核心结构）

📄 新增：

```id="dag_core"
app/pipeline/ocr_dag.py
```

------

### ✔ Pipeline 定义（必须实现）

```python
PIPELINE = DAG(
    nodes=[
        "OCR_RAW",
        "NOISE_FILTER",
        "CODE_LOCK_DETECTION",
        "REGION_SPLIT",
        "TEXT_CLEAN",
        "CODE_VERIFY",
        "OPTION_EXTRACT",
        "TEXT_REPAIR",
        "SCHEMA_BUILD"
    ],
    edges=[
        ("OCR_RAW", "NOISE_FILTER"),
        ("NOISE_FILTER", "CODE_LOCK_DETECTION"),
        ("CODE_LOCK_DETECTION", "REGION_SPLIT"),
        ("REGION_SPLIT", "TEXT_CLEAN"),
        ("REGION_SPLIT", "CODE_VERIFY"),
        ("TEXT_CLEAN", "TEXT_REPAIR"),
        ("TEXT_REPAIR", "SCHEMA_BUILD"),
        ("CODE_VERIFY", "SCHEMA_BUILD"),
        ("OPTION_EXTRACT", "SCHEMA_BUILD")
    ]
)
```

------

# 🔒 三、Zero Mutation Core（核心机制）

------

## 🚨 2. 全局不可变数据结构（必须实现）

📄 新增：

```id="immutable1"
app/core/immutable_regions.py
```

------

### ✔ Region 定义

```python
@dataclass(frozen=True)
class Region:
    id: str
    type: Literal["code", "text", "option"]
    content: str
    hash: str
```

------

### ❗关键原则：

> 一旦 region 创建，**绝不允许修改 content**

------

# 🚨 四、Mutation Guard（核心防线）

------

## 🔥 3. runtime mutation blocker

📄 新增：

```id="guard1"
app/core/mutation_guard.py
```

------

### ✔ 强制校验：

```python
def assert_no_mutation(before: Region, after: Region):
    if before.hash != after.hash:
        raise RuntimeError(
            f"MUTATION DETECTED: {before.id}"
        )
```

------

## ✔ 所有 stage 必须通过 guard

```python
def run_stage(stage_fn, input_regions):
    output = stage_fn(input_regions)

    for b, a in zip(input_regions, output):
        if b.type == "code":
            assert_no_mutation(b, a)

    return output
```

------

# 🧠 五、Code Lock（升级版）

------

## 🔷 4. Code region 必须进入 LOCKED state

```python
@dataclass(frozen=True)
class CodeRegion(Region):
    locked: bool = True
```

------

## ❌ 所有 stage 禁止：

- replace
- normalize
- regex rewrite
- whitespace fix
- brace fix
- arrow fix

------

## ✔ 只允许：

```python
READ ONLY ACCESS
```

------

# 🧹 六、Stage 责任分离（关键升级）

------

## ❌ 禁止“混合 stage”

------

### TEXT_CLEAN

✔ only text
❌ cannot see code

------

### CODE_VERIFY

✔ only validation
❌ cannot modify

------

### OPTION_EXTRACT

✔ independent from OCR pipeline
✔ uses raw + text only

------

# 🧪 七、数据流约束（非常关键）

------

## 🚨 每个 stage 必须声明 contract

```python
class StageContract:
    input_types: list
    output_types: list
    mutation_allowed: bool
```

------

## ✔ example

```python
TEXT_CLEAN = StageContract(
    input_types=["text"],
    output_types=["text"],
    mutation_allowed=True
)

CODE_VERIFY = StageContract(
    input_types=["code"],
    output_types=["report"],
    mutation_allowed=False
)
```

------

# 🧪 八、强制测试（必须全部通过）

------

## ✔ regression suite

```bash
pytest tests/ocr_regression/ -k "bugs"
```

------

## ✔ invariant checks

必须验证：

### ✔ 1. code hash before == after

### ✔ 2. no stage modifies code region

### ✔ 3. options extraction independent

### ✔ 4. schema build never fallback

### ✔ 5. pipeline DAG has no cycles

------

# 🚨 九、禁止行为（非常重要）

Claude **必须禁止**：

❌ patch rule addition
❌ regex tuning
❌ heuristic scoring
❌ “improving detection accuracy”
❌ modifying clean OCR logic for code

------

# 🧠 十、本质升级说明

------

## 这是一个系统级变化：

| 旧系统                 | 新系统                |
| ---------------------- | --------------------- |
| linear pipeline        | DAG pipeline          |
| mutable text           | immutable regions     |
| heuristic rules        | contract enforcement  |
| best-effort processing | zero-trust processing |

------

# 📌 一句话总结

> 你现在不能再“修 OCR”，必须构建一个“不可变 + DAG + zero-mutation”的处理系统，否则 code contamination 永远无法根除。

------

