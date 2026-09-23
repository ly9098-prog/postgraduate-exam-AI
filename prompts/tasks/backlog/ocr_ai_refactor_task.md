> **不要按本文施工（2026-09-23）。** 这是收进 `backlog/` 的历史任务书，不代表当前工作。现行范围见 `docs/project/ROADMAP.md`。

## 📌 目标：OCR 两层模型重构

我们正在对 OCR pipeline 做一次**模型架构替换（不是新增功能）**，涉及两个关键改动：

------

# 🧱 一、AI 视觉回退层（Vision Fallback Layer）重构

## 📌 原逻辑

```text
PDF → PaddleOCR →（失败）→ DeepSeek Vision API（ocr_service.py fallback）
```

当前问题：

- DeepSeek Vision 不稳定
- OCR质量不可控
- 与后续纠错层职责重复

------

## 📌 新逻辑（替换）

### ❗核心变更：引入 PaddleOCRVLAdapter 替换 DeepSeek Vision

```text
PDF → PaddleOCR →（失败）→ PaddleOCRVLAdapter（external high-precision OCR API）
```

------

## 📌 新视觉回退层结构

```python
features/ocr_service.py

ocr_fallback():
    1. PDF → image render
    2. PaddleOCR primary OCR
    3. if fail → PaddleOCRVLAdapter (NEW)
    4. return structured OCR text
```

------

## 📌 PaddleOCRVLAdapter 职责

```text
input: image bytes
output: OCR text / JSONL result
```

调用流程：

- POST /api/v2/ocr/jobs
- poll job status
- 解析 JSONL OCR result
- 转换为统一 text format

------

## 📌 关键替换点

### ❌ 删除

- DeepSeek Vision API 在 ocr_service.py 中的调用
- `_call_ocr_api()` 发送 image → DeepSeek

### ✅ 替换为

- PaddleOCRVLAdapter（external OCR service）

------

# 🧠 二、AI OCR 纠错层（Multi-Model Correction）重构

## 📌 原逻辑

```text
OCR文本 + 图片 → QwenFixer（多模态纠错）
        ↓
DeepSeekFixer
        ↓
RuleFixer
```

------

## 📌 新逻辑（替换 Qwen）

### ❗核心变更：PaddleOCRVLAdapter 替代 QwenFixer

```text
OCR文本 + 图片 → PaddleOCRVLAdapter（primary correction source）
        ↓
DeepSeekAdapter（text-only repair）
        ↓
RuleAdapter
```

------

## 📌 新 OCRFixRouter chain

```python
OCRFixRouter:

PaddleOCRVLAdapter   (NEW - highest priority / vision correction)
        ↓ (fail)
DeepSeekAdapter      (semantic repair only)
        ↓
RuleAdapter          (safe fallback)
```

------

## 📌 QwenFixer 完全移除

### ❌ 删除内容：

- qwen_adapter.py
- 所有 Qwen-VL 多模态 OCR correction 调用
- OCRFixRouter 中 Qwen 节点

------

# 🧩 三、职责变化

## 📌 新职责划分

| 层              | 模型               | 职责                               |
| --------------- | ------------------ | ---------------------------------- |
| OCR primary     | PaddleOCR          | 基础识别                           |
| OCR fallback    | PaddleOCRVLAdapter | 高精度 OCR（替代 DeepSeek Vision） |
| correction      | PaddleOCRVLAdapter | 视觉级纠错（替代 Qwen）            |
| semantic repair | DeepSeek           | 纯文本语义修复                     |
| fallback        | Rule               | deterministic fallback             |

------

# 🔥 四、架构变化总结

## 📌 这次不是“增加模型”，而是：

> ❗统一视觉能力到 PaddleOCRVLAdapter，并彻底移除 DeepSeek Vision + Qwen-VL

------

## 📌 两个关键迁移点

### ① Vision fallback layer

```
DeepSeek Vision  →  PaddleOCRVLAdapter
```

------

### ② OCR correction layer

```
QwenFixer (multimodal) → PaddleOCRVLAdapter (external OCR correction API)
```

------

# ⚠️ 五、约束条件

## ❗必须遵守

1. 不允许改 pipeline 主流程结构
2. 只允许改：
   - ocr_service.py fallback
   - OCRFixRouter chain
3. 不得引入新的视觉模型（只允许 PaddleOCRVLAdapter）
4. DeepSeek 只能做 text-only repair
5. Qwen 完全删除

------

# 📌 六、成功标准

改造后必须满足：

- DeepSeek Vision API 不再被调用
- QwenFixer 完全消失
- PaddleOCRVLAdapter 成为：
  - fallback OCR
  - correction vision model（统一入口）
- OCRFixRouter 变成 3 层：

```text
PaddleOCRVL → DeepSeek → Rule
```

------

# 🚀 七、一句话版本

> Replace DeepSeek Vision fallback with PaddleOCRVLAdapter, and replace QwenFixer in OCR correction layer with the same PaddleOCRVLAdapter, making it the unified high-precision vision OCR/correction entry point.