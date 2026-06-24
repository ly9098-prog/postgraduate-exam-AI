# 📌 Production Governance Upgrade

## 🎯 任务名称

**Code Language Noise Layer v2：生产可观测性 + 漂移检测 + 治理体系升级**

------

## 🧠 背景说明

你已经完成 `code_language_noise_layer.py` v1 版本，实现了：

- C/C++/Java/Python/HTML/JS 语言标识噪声清洗
- transition zone detection
- safe removal rules
- cross-pipeline consistency validation
- stress test 15/15 passed
- false positive = 0
- production integration completed

当前模块已经是：

> ✅ Production Stable Component（生产稳定可用）

------

## 🚨 现在的问题（v1 已完成，但系统不完整）

当前系统缺少“生产级能力”：

### ❗1. 无运行时可观测性

无法回答：

- C/C++ 噪声发生率是多少？
- 哪类OCR最容易产生语言标识污染？
- 是否出现新噪声模式？

------

### ❗2. 无噪声分布漂移检测

无法检测：

- PaddleOCR-VL版本变化导致的噪声变化
- 新语言/新模式出现（Go / Rust / Kotlin）
- C/C++噪声比例上升

------

### ❗3. 无治理与回滚机制

无法控制：

- 某类规则误伤扩大时自动降级
- safe_mode / normal_mode 自动切换
- A/B策略验证不同规则效果

------

## 🎯 本阶段目标

将当前 v1 模块升级为：

> 🚀 **Production-grade OCR Code Language Noise Governance System**

不是改算法，而是构建：

✔ 可观测性
✔ 漂移检测
✔ 规则治理
✔ 运行时控制

------

# 🧩 任务拆解

------

## 🟦 Phase 1：Noise Metrics Observability Layer（可观测性层）

在 `code_language_noise_layer.py` 外新增：

### 📌 文件：

```
code_language_noise_metrics.py
```

### 📊 必须统计以下指标：

#### 1. 噪声发生统计

- total_noise_detected
- c_cpp_noise_count
- html_noise_count
- python_noise_count
- generic_noise_count

------

#### 2. transition zone 统计

- total_transition_zones
- noise_density_per_zone

------

#### 3. removal stats

- removed_lines_count
- protected_lines_count
- false_positive_suspected_count

------

#### 4. per-document profiling

输出：

```json
{
  "doc_id": "...",
  "noise_ratio": 0.12,
  "c_cpp_noise_ratio": 0.08,
  "risk_level": "low|medium|high"
}
```

------

## 🟨 Phase 2：Noise Drift Detection（漂移检测）

新增模块：

```
noise_drift_detector.py
```

### 🎯 功能：

检测 OCR 噪声分布是否发生变化

------

### 📌 必须支持：

#### 1. baseline distribution

```json
{
  "c_cpp_noise_ratio": 0.15,
  "html_noise_ratio": 0.05
}
```

------

#### 2. runtime distribution

实时统计

------

#### 3. drift score

计算：

```
drift_score = KL_divergence(baseline, runtime)
```

------

#### 4. 输出：

```json
{
  "drift_detected": true,
  "drift_score": 0.32,
  "top_changed_noise": "c_cpp_noise"
}
```

------

## 🟩 Phase 3：Adaptive Rule Governance（自适应治理）

新增：

```
noise_rule_governor.py
```

------

### 🎯 功能：

根据 noise stats 自动调整策略

------

### 📌 必须支持：

#### 1. 自动降级 safe_mode

```text
if false_positive_rate > threshold:
    enable safe_mode
```

------

#### 2. 自动调节 removal threshold

- normal_mode → threshold 0.6
- safe_mode → threshold 0.9

------

#### 3. per-language weighting

```text
C/C++ noise weight ↑
HTML noise weight ↓
Python noise medium
```

------

## 🟪 Phase 4：Pipeline Integration Hook（接入层）

必须集成到：

```
pipeline_orchestrator.py
```

### 📌 要求：

在以下位置插入：

```text
normalize_schema → code_language_noise_layer → structure_freeze
```

并确保：

- metrics 自动记录
- drift detector 每 batch run
- governor 每 batch update policy

------

## 🟥 Phase 5：Safety Guarantees（必须）

必须保证：

### ❌ 禁止误删：

- C / C++ code logic
- operators: ++ -- -> == <= >=
- HTML tags (, )
- Java class structure

------

### ✔ 必须保护：

- code blocks `{ }`
- expressions inside loops
- function signatures

------

## 📤 最终交付物

必须输出：

```
code_language_noise_metrics.py
noise_drift_detector.py
noise_rule_governor.py
updated_pipeline_integration.patch
```

------

## 🧠 成功标准

### ✔ 系统级要求：

- 可以统计噪声分布
- 可以检测 OCR model drift
- 可以自动调整策略
- 可以安全回滚规则
- 不影响 existing pipeline correctness

------

## 🔥 核心原则

> v1 解决“怎么清噪声”
> v2 解决“如何治理噪声系统”

------

## 🚀 一句话总结任务

把现有 OCR code language noise layer 从：

> **rule-based cleaning system**

升级为：

> **self-observing + self-adjusting production governance system**

