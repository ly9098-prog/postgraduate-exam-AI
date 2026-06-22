# 🐞 BUG-001：OCR 导入后题干结构被破坏（代码题混入乱码）

###### |来源：docs/BUGS.md

## 一、问题标题

OCR 导入后代码题题干结构异常，出现代码片段截断与乱码混合

------

## 二、问题描述

在处理包含**二叉树/代码结构定义的选择题**时，OCR 导入流程会破坏原始题干结构，导致题目内容被截断或混入乱码字符，从而影响题目解析与后续结构化处理。

具体表现为：

- 原始题干包含完整 C 语言结构体定义
- 导入后代码块被截断为不完整片段
- 混入 OCR 噪声字符（如 `1typu* p1tysI* apo11ta aonu2s`）
- 导致题干语义不完整，结构解析困难

------

## 三、复现步骤

1. 上传包含代码题的图片（如二叉树结构定义题）
2. OCR 系统执行识别
3. 进入导入审核流程
4. 查看解析后的题干内容

------

## 四、实际结果（Actual Result）

OCR 输出结果：

```
```text
typedef struct BiTNode {
char data;
``` (1typu* p1tysI* apo11ta aonu2s
```

- 代码结构被截断
- 花括号及完整 struct 定义丢失
- 出现乱码 token（OCR noise）
- 题干无法完整还原

------

## 五、预期结果（Expected Result）

应完整保留原始题干结构：

```c
typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;
```

并确保：

- 代码块完整
- 不出现 OCR 噪声字符
- 题干结构不被截断
- 题目语义完整可解析

------

## 六、影响范围

- OCR 识别模块（PaddleOCR）
- 文本清洗模块（clean_ocr_text / normalizer）
- 题目结构解析器（question_splitter）
- AI 修复模块（ai_repair）
- 题库入库流程（review_service）

------

## 七、严重程度

🟥 高（High）

原因：

- 直接影响题目正确解析
- 导致结构化失败
- 会污染后续 AI 修复输入

------

## 八、可能原因分析

### 1. OCR 层问题

- PaddleOCR 对代码结构识别能力弱
- 代码换行/缩进丢失
- 特殊字符误识别

### 2. 文本清洗层问题

- `clean_ocr_text()` 误删结构符号
- 正则过滤过度激进
- 未区分“代码区 vs 普通文本”

### 3. 结构恢复缺失

- 未做 code block boundary detection
- 未保留原始 OCR bbox 顺序

### 4. 噪声字符混入

- OCR 置信度过滤不足
- watermark noise 未完全清除

------

## 九、建议修复方案

### 方案 1：代码区识别增强（推荐）

在 OCR 后增加：

- code block detection
- C/C++ pattern recognition
- struct / typedef / pointer pattern 识别

------

### 方案 2：清洗规则分层

将 `clean_ocr_text()` 改为：

- 普通文本清洗
- 代码文本清洗（弱过滤）
- 禁止对代码区做字符替换（如 0→O）

------

### 方案 3：OCR 置信度保护

- confidence < threshold → 不进入清洗
- 低置信度代码块标记为 `needs_review`

------

### 方案 4：结构重建策略

- 使用 bbox + reading order 重建代码块
- 防止结构体跨行断裂

------

## 十、关联日志

- OCR 原始输出存在明显 noise token：

  ```
  (1typu* p1tysI* apo11ta aonu2s
  ```

- pipeline 标记：

  ```
  code_garbled_text
  code_block_truncated
  watermark_noise_detected
  ```

------

## 十一、备注

该问题属于典型：

> **“OCR + 代码结构识别失败 + 清洗过度” 复合型问题**

建议优先在 OCR 后增加 **code-aware parsing layer**，否则后续 AI 修复会持续放大错误。

------

如果你需要，我可以继续帮你把 `BUGS.md` 里的**所有 bug 自动拆成 Jira backlog（带优先级 + 修复工时 + owner 建议）**。