### 🎯 目标

修复 PaddleOCR-VL 输出被错误 confidence gate 丢弃的问题，导致选项文本在进入 classifier 前丢失。

------

## 🧩 Step 1：修复 OCR-VL confidence gate（必须优先）

在 `pipeline_orchestrator.py:2443`：

### 当前问题：

- PaddleOCR-VL 返回 confidence=0.0
- 被当作 invalid result 丢弃
- 导致完整 237 chars 被忽略

### 修复要求：

- VL OCR 结果必须默认接受
- confidence 不得作为丢弃条件

### 推荐实现：

```
if is_vl_result:
    accept_result = True
```

或：

```
confidence=0.0 → treat as valid (VL override)
```

------

## 🧩 Step 2：保留现有 fallback（不改）

- 不修改 classifier
- 不修改 detect_options_from_text
- 不修改 splitter

------

## 🧩 Step 3：验证目标

修复后必须满足：

- VL OCR 237 chars 进入 classifier
- force_options_probe(237 chars) → detect=True
- options = {A, B, C, D}

------

## ⚠️ 禁止事项

- ❌ 不允许先改 VL_REBUILD PDF 限制
- ❌ 不允许动 classifier logic
- ❌ 不允许增加新 OCR path
- ❌ 不允许删除 confidence 字段（只调整使用方式）

------

## 🎯 最终目标

> VL OCR 结果不能因为 confidence=0.0 被丢弃

