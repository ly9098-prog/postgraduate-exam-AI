# 任务目标

升级当前OCR识别流程中的「AI纠错层」。

当前架构：

```text
图片
 ↓
PaddleOCR
 ↓
OCR原始文本
 ↓
DeepSeek纠错层（文本纠错）
 ↓
最终识别结果
```

升级为：

```text
图片
 ↓
PaddleOCR
 ↓
OCR原始文本
 ↓
Qwen-VL视觉纠错层
（图片 + OCR文本）
 ↓
最终识别结果
```

目标是利用Qwen-VL的视觉能力，根据原始图片重新校验OCR识别结果，提高公式、代码、符号、数学表达式、英文变量、特殊字符等内容的识别准确率。

------

# 实现原则

## 1. 不允许硬编码模型配置

当前系统已有完整AI模型配置体系：

- 模型名称
- API Key
- Base URL
- Model Name
- 是否启用
- Provider

均通过：

```text
Admin后台UI
↓
数据库
↓
后端动态读取
```

进行配置。

本次Qwen-VL接入必须复用现有配置体系。

禁止：

```python
QWEN_API_KEY=...
os.getenv(...)
```

形式硬编码配置。

必须通过当前系统已有AI配置读取逻辑获取：

```python
provider
api_key
base_url
model_name
```

并动态创建客户端。

请先分析现有DeepSeek模型是如何读取配置的，再按照同样方式实现Qwen-VL。

------

# 2. 保持AI纠错层可插拔

不要把Qwen-VL写死。

将AI纠错层重构为可插拔架构：

```python
BaseOCRCorrector
├── DeepSeekCorrector
├── QwenVLCorrector
```

或者类似设计。

要求：

```python
OCR_CORRECTOR_PROVIDER
```

可切换：

```text
deepseek
qwen-vl
```

后续新增模型无需修改OCR主流程。

------

# 3. 新增Qwen-VL视觉纠错器

新增：

```python
QwenVLCorrector
```

输入：

```python
image
ocr_text
```

输出：

```python
corrected_text
```

接口设计参考：

```python
correct_text(
    image_bytes,
    ocr_text
)
```

或当前项目已有风格。

------

# 4. Qwen-VL调用方式

请参考阿里云DashScope兼容OpenAI接口的Qwen-VL调用方式实现。

要求支持：

```python
image_url
```

以及

```python
base64 image
```

优先采用当前项目最容易集成的方案。

图片无需再次OCR。

直接发送：

- 原始图片
- PaddleOCR结果

给Qwen-VL。

------

# 5. 优化Prompt

不要让Qwen-VL重新做OCR。

应该采用：

```text
OCR校验模式
```

Prompt参考：

你是专业OCR校验助手。

我会提供：

1. 原始图片
2. PaddleOCR识别结果

你的任务不是重新OCR，而是：

- 根据图片核对OCR结果
- 修正识别错误
- 保持原有结构
- 保持换行
- 保持题目格式
- 保持选项顺序

重点检查：

- 数学公式
- 编程代码
- 英文变量名
- 特殊符号
- 括号
- 箭头符号
- 运算符
- OCR常见错字

规则：

1. 图片与OCR一致时不要修改
2. 不允许补充图片中不存在内容
3. 不允许解释
4. 不允许输出Markdown
5. 只输出最终修正后的文本

OCR结果如下：

{ocr_text}

```
---

# 6. 降级策略

若Qwen-VL失败：

```python
API异常
超时
限流
```

不要导致OCR整体失败。

按当前项目风格实现：

```python
返回原始OCR结果
```

或：

```python
自动降级到DeepSeek纠错器
```

请评估现有架构后选择更合理方案。

------

# 7. 性能要求

不要影响批量导题。

实现：

- 超时控制
- 重试机制
- 图片大小限制
- 图片压缩（如已有）

避免：

```text
大图直接发送Qwen
```

导致响应过慢。

------

# 8. Admin后台适配

在现有AI模型配置页面基础上扩展。

支持新增：

```text
Provider:
- DeepSeek
- Qwen-VL
```

如果当前Provider已支持扩展，则直接复用。

无需新增独立配置页面。

------

# 9. 保持向后兼容

现有DeepSeek纠错功能不能被破坏。

要求：

```text
切换为Qwen-VL → 使用视觉纠错
切换为DeepSeek → 使用原逻辑
```

保证旧配置升级后仍可正常运行。

------

# 最终交付

请完成：

1. 架构分析
2. AI纠错层重构
3. Qwen-VL接入
4. Prompt设计
5. 配置中心接入
6. 容错与降级
7. Admin配置适配
8. 完整代码修改

修改前先阅读当前OCR流程、AI模型配置体系、DeepSeek纠错器实现，再基于现有架构进行改造，不要另起一套配置系统。