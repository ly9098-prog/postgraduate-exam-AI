# OCR解析管道增强（第二阶段）

## 背景

已完成 OCR 质量门控、污染检测、选项完整性校验、缓存机制等基础能力建设。

最新审计结果显示当前系统功能正确、测试全部通过（398 Passed，0 Regression），不存在阻塞上线的问题。

但审计发现若干影响长期可维护性的架构问题，需要进行一次增强优化。

本次任务目标不是修复 Bug，而是提升系统一致性、可维护性和未来扩展能力。

------

# 任务一：实现解析缓存版本化失效机制（P0）

## 当前问题

question_normalizer.py 中的 `_parse_cache` 会永久缓存解析结果。

当前缓存只有：

```python
{
    "version": 1,
    "cached_at": ...
}
```

但读取时并不会校验 version。

因此：

1. 某道题被缓存
2. 后续修复了解析规则
3. 用户再次导入同一道题
4. 仍然返回旧缓存结果

导致规则修复无法生效。

------

## 改造目标

建立自动缓存失效机制。

禁止依赖：

```python
parse_cache_clear()
```

进行人工清理。

------

## 实现要求

### 1. 引入缓存版本常量

例如：

```python
PARSER_CACHE_VERSION = "2026.06.18"
```

------

### 2. 写入缓存时记录版本

例如：

```python
{
    ...
    "cache_version": PARSER_CACHE_VERSION
}
```

------

### 3. 读取缓存时校验版本

逻辑：

```python
if cache_version != PARSER_CACHE_VERSION:
    cache miss
```

自动重新解析。

------

### 4. 向后兼容

对于历史缓存：

```python
{
   ...
}
```

不存在：

```python
cache_version
```

字段时：

自动失效并重新生成。

------

### 5. 补充测试

覆盖：

- 同版本命中缓存
- 新版本自动失效
- 无版本字段自动失效

------

# 任务二：统一所有导题链路的 Question Schema（P0）

## 当前问题

系统存在两条标准化路径：

### 路径A

question_normalizer.py

主要用于：

- OCR导题
- PDF导题

------

### 路径B

question_pipeline.py

主要用于：

- 文本导题
- AI解析导题

------

两条路径返回字段不一致：

| 字段              | question_normalizer | question_pipeline |
| ----------------- | ------------------- | ----------------- |
| validation_status | ✓                   | ✗                 |
| failure_reason    | ✓                   | ✗                 |
| retry_recommended | ✓                   | ✗                 |
| ocr_quality_flags | ✓                   | ✗                 |

导致下游逻辑需要区分来源处理。

增加未来维护成本。

------

## 改造目标

无论题目来源：

- OCR
- PDF
- AI解析
- 文本导入

最终都返回统一结构。

------

## 实现要求

### 建立统一 Validation Schema

例如：

```python
QuestionValidationResult
```

或等价结构。

------

### 所有导题入口统一输出

```python
{
    ...
    "validation_status": "...",
    "failure_reason": "...",
    "retry_recommended": false,
    "ocr_quality_flags": []
}
```

------

### 非OCR来源

统一返回：

```python
ocr_quality_flags = []
```

------

### 校验通过

统一返回：

```python
validation_status = "passed"
failure_reason = None
retry_recommended = False
```

------

### 校验失败

统一返回：

```python
validation_status = "failed"
failure_reason = "..."
retry_recommended = True/False
```

------

### 补充测试

验证：

OCR路径与文本路径输出字段完全一致。

确保未来新增导题方式时也遵循统一契约。

------

# 任务三：优化 OCR 污染检测中的 LaTeX 误报（P1）

## 当前问题

污染检测规则会将：

```latex
\alpha
\beta
\gamma
```

识别为：

```python
symbol_substitution_detected
```

例如：

```latex
设\alpha,\beta为3维列向量
```

被标记为污染。

虽然目前只是 Warning，不影响通过，但属于误报。

未来如果叠加其他轻微问题，可能导致合法数学题被误阻断。

------

## 目标

提升污染检测准确率。

降低数学题误报率。

------

## 重要原则

不要继续采用：

```python
if "\\alpha" in text:
    skip
```

或类似黑名单/白名单补丁方案。

禁止继续堆积特殊规则。

------

## 实现方向

从“符号匹配”升级为“上下文感知判断”。

------

### 数学上下文示例

```text
向量
矩阵
行列式
特征值
积分
导数
极限
α β γ连续出现
```

应倾向于认为是合法数学内容。

------

### 程序设计上下文示例

```text
链表
结点
指针
next
prev
p
q
r
->
NULL
```

若出现：

```text
\alpha
\beta
```

则更可能属于 OCR 污染。

------

## 实现目标

优先降低误报率。

允许少量漏报。

避免合法数学内容被污染检测误伤。

------

# 任务四：代码清理（可选）

本次不要求立即修复。

仅请评估并给出后续重构建议：

1. option completeness 检查逻辑重复
2. stem_hash 参数命名不准确
3. 缓存中的 version / cached_at 元数据利用率不足

无需为了清理而修改稳定逻辑。

仅在重构收益明确时处理。

------

# 验收标准

必须满足：

1. 所有现有测试继续通过
2. 不降低 OCR 导题成功率
3. 不增加误阻断率
4. 缓存版本升级后自动失效
5. 所有导题入口输出统一 Schema
6. 合法数学 LaTeX 内容不再被误判为污染
7. 新增测试覆盖上述场景

交付内容：

1. 修改说明
2. 架构说明
3. 风险评估
4. 新增测试清单
5. 回归测试结果