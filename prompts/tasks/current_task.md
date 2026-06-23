### 🎯 目标

定位为什么 options detection 未触发（runtime级）

------

## 🧪 Step 1：增加全链路 trace log

在以下节点加 log：

- raw input
- after normalize
- after text-detection
- classifier result
- selected pipeline branch
- final extracted options

输出格式：

```
[TRACE] stage=xxx value=xxx reason=xxx
```

------

## 🧪 Step 2：验证关键触发条件

重点检查：

### ① classifier 输入

```
question_type_classifier(input_text)
```

确认：

- 是否真的包含 option pattern
- 是否被 pre-normalize 改写

------

### ② text-detection gate

检查：

- is_question == True 的判定条件
- 是否误判为 “paragraph / instruction / OCR noise”

------

## 🧪 Step 3：对 10 条失败样本做反推

要求：

- 把“没有识别选项”的真实输入贴出来
- 标注失败原因分类：

```
A. 未识别为 single_choice
B. options pattern 未命中
C. normalize 清洗掉选项
D. splitter 未执行
```

------

## 🧪 Step 4：做一个“强制探测模式”（debug only）

新增：

```
force_options_probe(input_text)
```

规则：

> 不依赖 classifier，直接扫描所有 option pattern

用于验证：

- 是 classifier 问题
- 还是 extractor 问题

------

# 🧠 最关键的一句话（你现在的核心问题）

> ❗ pipeline 是好的，但 runtime 输入“没有被归类为 options”
