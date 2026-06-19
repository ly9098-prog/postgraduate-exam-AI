请先对当前 OCR 导题链路进行全面审计，再根据实际实现情况设计并实施「代码块识别与渲染能力」，不要直接假设当前架构。

> **状态：✅ 审计完成 → 方案已定 → 待实施**
> 
> 审计日期：2026-06-19
> 审计范围：OCR 链路（10 阶段）、数据结构（Question.content JSON）、前端渲染（miniprogram 三道展示路径）

## 任务背景

当前系统支持：

```text
图片
→ OCR识别
→ AI纠错
→ 题目结构化
→ 前端题目展示
```

在导入计算机类题目时，题干、选项、解析中可能包含：

- C/C++代码
- Java代码
- Python代码
- JavaScript代码
- SQL语句
- HTML/XML片段
- 伪代码

目前发现：

- OCR导入后代码内容可能被当作普通文本处理
- 前端展示时代码可能被压缩成一行
- 缩进、换行、连续空格可能丢失
- 代码可读性较差
- 影响用户做题体验

------

# 第一阶段：审计（必须先完成）

请先审计当前实现，不要立即修改代码。

重点分析：

## 1. OCR链路

检查：

- OCR原始结果如何保存
- AI纠错层是否会破坏代码格式
- text_normalizer 是否会修改代码内容
- 是否存在代码相关特殊处理
- 是否会丢失换行
- 是否会丢失缩进
- 是否会压缩连续空格

输出：

```text
代码格式在哪个环节丢失
代码是否已被部分支持
有哪些潜在风险
```

------

## 2. 数据结构

检查：

当前题目存储结构是否支持：

```json
{
  "type": "code",
  "content": "..."
}
```

或类似内容块结构。

分析：

- 当前是否只有纯文本字段
- 是否已有 markdown 支持
- 是否已有富文本支持
- 扩展成本如何

------

## 3. 前端渲染

检查：

题干、选项、解析页面。

分析：

- 是否支持 Markdown
- 是否支持 pre/code 标签
- 是否支持代码高亮
- 是否支持横向滚动
- 是否存在 CSS 导致代码被压缩成一行

给出具体问题定位。

------

# 第二阶段：设计方案

基于审计结果设计方案。

原则：

## 优先兼容现有数据

不要破坏已有题库。

优先考虑：

### 方案A（推荐）

OCR阶段输出 Markdown 代码块：

~~~markdown
```c
for(i=0;i<n;i++)
{
    printf("%d",i);
}
```
~~~

前端自动识别并渲染。

分析：

- 实现成本
- 风险
- 对现有系统影响

------

### 方案B

结构化内容块：

```json
{
  "type": "code",
  "language": "c",
  "content": "..."
}
```

分析：

- 优势
- 劣势
- 数据迁移成本

------

请结合当前项目实际情况选择最合适方案，而不是机械实现。

------

# 第三阶段：代码识别能力

如果当前系统缺少代码识别能力，请实现。

要求：

识别：

```text
C
C++
Java
Python
JavaScript
SQL
HTML
XML
伪代码
```

重点识别：

```text
for(...)
while(...)
if(...)
switch(...)
class
public static void
def
SELECT
INSERT
UPDATE
<html>
```

避免误判普通文本。

------

# 第四阶段：前端代码块组件

如果系统尚未支持代码块展示，请实现。

要求：

- 保留原始换行
- 保留缩进
- 保留连续空格
- 横向滚动
- 移动端适配
- 支持复制代码
- 不影响普通题目显示

如果项目已存在 Markdown 渲染能力，则优先复用现有能力。

不要重复造轮子。

------

# 第五阶段：回归测试

新增测试用例：

## C语言

```c
for(i=0;i<n;i++)
{
    printf("%d",i);
}
```

## Python

```python
for i in range(10):
    print(i)
```

## SQL

```sql
SELECT * FROM student;
```

## HTML

```html
<div>Hello</div>
```

验证：

- OCR后是否保留结构
- AI纠错后是否保留结构
- 前端是否正确渲染
- 复制后内容是否一致

------

# 输出要求

先输出审计报告：

```text
当前实现情况
问题定位
推荐方案
影响范围
实施计划
```

待审计完成后再开始修改代码。

禁止直接跳过审计进入开发阶段。这样可以避免在当前架构已经支持 Markdown 或部分代码渲染的情况下重复建设。

------

# 审计报告（2026-06-19 完成）

## 1. OCR 链路全貌（10 阶段）

```
PaddleOCR → clean_ocr_text() → ImportTextNormalizer → AI OCR纠错
→ QuestionSplitter → StructureAnalyzer → QuestionNormalizer
→ AI Repair → QuestionNormalizer.clean_text() → DB存储 → 前端展示
```

## 2. 代码格式丢失的精确位置（7 处）

### Loss A — `clean_ocr_text()` 粉碎缩进
**文件：** `backend/app/services/ocr_service.py` L619
```python
text = re.sub(r" {2,}", " ", text)  # 在清洗第一步就破坏了所有代码缩进
```

### Loss B — `_normalize_spaces()` 压缩连续空格
**文件：** `backend/app/features/text_normalizer.py` L303-306
```python
return "".join(
    part if part.startswith("```") else re.sub(r" {2,}", " ", part)
    for part in parts
)
```
保护了 ``` 围栏内内容，但 OCR 输出从不含围栏 → 保护机制对 OCR 路径完全无效。

### Loss C — `_should_merge_lines()` 无代码感知
**文件：** `backend/app/features/text_normalizer.py` L269-279
仅尊重结构标记（题号/选项/罗马数字）和句末标点。无代码行检测 → 相邻代码行被合并为单行。

### Loss D — OCR 纠错 AI Prompt 无代码保护指令
**文件：** `backend/app/ai/prompts.py` OCR correction system prompt
仅指示"修复换行错乱"，无代码保留相关指令。

### Loss E — 全角符号转半角
**文件：** `backend/app/features/text_normalizer.py` L554-556
`_RE_FULLWIDTH_ASCII` 转换对代码符号影响小但存在。

### Loss F — `clean_text()` 中 \xa0 → 空格
**文件：** `backend/app/features/question_pipeline.py` L343-344

### Loss G — 哈希去重中 \n → 空格
**文件：** `backend/app/features/question_pipeline.py` L417
仅影响去重哈希计算，不影响显示。

## 3. 已有代码部分支持（9 处）

| # | 位置 | 机制 | OCR路径有效？ |
|---|------|------|:---:|
| 1 | `text_normalizer.py:211-223` | `in_code_fence` 围栏内保护 | ❌ OCR 不产围栏 |
| 2 | `text_normalizer.py:303-306` | 按围栏切分跳过空格压缩 | ❌ 同上 |
| 3 | `text_normalizer.py:476` | C 指针箭头 `->` 修复 | ✅ |
| 4 | `text_normalizer.py:516-548` | 编程上下文感知 LaTeX 还原 | ✅ 行级判断 |
| 5 | `question_pipeline.py:588-603` | `_should_merge()` 代码行检测 | ✅ 缩进/Brace/关键词 |
| 6 | `question_pipeline.py:646-666` | `_normalize_code_newlines()` | ✅ 修复运算符断裂 |
| 7 | `prompts.py:95-98` | AI 修复规则 9：保留代码格式 | ⚠️ 输入已损 |
| 8 | `practice.js:6-12` | `_formatHtmlTextSegment()` 代码行检测 | ✅ `{};=//` → `&nbsp;` |
| 9 | `fix_code_newlines.py` | 生产修复脚本 | ⚠️ 仅已知指纹 |

**前端渲染现状：**
- `.q-text` → `white-space: pre-wrap` ✅
- `mp-html` 组件 → 支持 `<pre><code>` HTML 标签 ✅
- `math-question` 组件 → text/math_image/newline 三类，无 code 类型 ⚠️
- **无 Markdown 解析器**，**无代码高亮**

## 4. 数据结构

```python
# Question.content — JSONB 列，两种现有形态
{"text": "..."}                                             # 纯文本
{"text": "...", "segments": [...], "render_mode": "segments"}   # 含数学公式

# segments 支持的类型
{"type": "text", "text": "..."}
{"type": "math_image", "url": "...", "alt": "...", "display": bool}
{"type": "newline"}
# ❌ 无 type: "code"
```

## 5. 根因总结

```
OCR 原始输出（缩进完好）
    │
    ▼ Loss A: clean_ocr_text() 压缩连续空格 → 缩进粉碎
    ▼ Loss C: _should_merge_lines() 无代码感知 → 行合并
    ▼ Loss B: _normalize_spaces() 压缩空格 → 进一步压缩
    ▼ AI修复收到已损坏输入 → 规则9无力恢复
    ▼ 前端 pre-wrap + 代码行检测 → 尽力渲染但输入已损
```

**关键矛盾：** 围栏保护 (`in_code_fence`) 基础设施完备，但 OCR 从不输出 ``` 围栏，所有保护对 OCR 路径是死代码。

------

# 方案设计（两阶段策略）

## 第一阶段：Markdown 围栏快速落地

### 目标
修复 OCR 导题代码格式丢失问题，以最低成本在一周内上线。

### 核心思路
在 OCR 文本入库前，用规则检测代码块并插入 ``` 围栏。激活 pipeline 中已存在但从未生效的 `in_code_fence` 保护机制。

### 为什么选 Markdown 围栏作为第一阶段

| 理由 | 细节 |
|------|------|
| 激活已有保护 | `text_normalizer` 已有 `in_code_fence` 逻辑，只需插入围栏即可全部激活 |
| 前端零开发 | `mp-html` 原生支持 `<pre><code>`，已有 CSS `white-space: pre-wrap` |
| 零 DB 变更 | 围栏是纯文本，存在现有 `content.text` 字段中 |
| 零风险 | 纯文本题不受影响，围栏只在检测到代码时插入 |
| 可回滚 | 删除围栏还原为原始文本即可 |

### 关键约束

> 以下约束为实施前的硬性设计决策。

#### 约束 1：双重判断 — 关键词不能单独触发

代码检测器必须采用 **"结构信号 + 关键词信号"双重判断**。
单行**仅命中关键词**（如孤立的 `for`、`if`）**不触发**代码块识别。

```
防止误判：
  "下列选项中正确的是（ ）" ← 含 "if"？不，这是中文"的是"
  "对于以下说法，正确的有"   ← 含 "for"？不，这是中文
  "A. 选择排序"              ← 含 "int"？不，这是 "print" 的一部分

只有结构信号（缩进、braces、分号）与关键词信号同时出现时才触发。
```

#### 约束 2：基于 OCR 原始文本检测

代码检测必须在**任何空格压缩、换行合并操作之前**完成。
OCR 原始文本保留了缩进、换行等**关键结构信号**。

检测时机：`clean_ocr_text()` 的**最前面**，在所有清洗操作之前。

#### 约束 3：AI 不负责代码块发现

- 代码围栏由**规则层**（`code_detector.py`）生成
- AI（OCR Corrector / Repair）仅负责：**保持已有围栏** + **保持围栏内格式**
- AI prompt 不要求 AI 识别或生成代码围栏

#### 约束 4：OCR 回归数据集

新建目录 `tests/ocr_regression/code/`，至少覆盖 6 种语言：

```
tests/ocr_regression/code/
├── c.c          // C 代码样本
├── cpp.cpp      // C++ 代码样本
├── java.java    // Java 代码样本
├── python.py    // Python 代码样本
├── sql.sql      // SQL 代码样本
└── html.html    // HTML 代码样本
```

每个样本包含：原始 OCR 文本（模拟含噪声的代码片段） + 预期输出（带围栏的文本）。

#### 约束 5：回归测试门禁

后续所有修改 `clean_ocr_text`、`text_normalizer`、`question_pipeline` 时，必须通过代码回归测试。

#### 约束 6：Feature Flag — 关闭后行为与线上一致

代码检测器必须受 Feature Flag 控制。Flag 关闭时，`wrap_code_fences()` 为**透传（no-op）**，系统行为与当前线上版本完全一致。

```python
# backend/app/core/config.py — 追加
CODE_DETECTOR_ENABLED: bool = os.environ.get("CODE_DETECTOR_ENABLED", "false").lower() == "true"
```

默认 `false`，上线后逐步开启。灰度策略：
1. 部署 → Flag 关闭，验证无回归
2. 开启 Flag → 新导入题目走代码检测
3. 观察日志 → 调整阈值后全量

```python
# backend/app/features/code_detector.py
def wrap_code_fences(text: str) -> str:
    if not settings.CODE_DETECTOR_ENABLED:
        return text  # 透传，行为与线上完全一致
    return _detect_and_wrap(text)
```

#### 约束 7：命中日志 — 可观测性

每次调用 `wrap_code_fences()` 输出一行结构化日志，统计识别结果。

```python
# backend/app/features/code_detector.py

import logging
logger = logging.getLogger(__name__)

def wrap_code_fences(text: str, *, trace_id: str = "") -> str:
    if not settings.CODE_DETECTOR_ENABLED:
        return text

    result, stats = _detect_and_wrap(text)
    logger.info(
        "[CodeDetector] trace_id=%s questions=%d blocks=%d avg_lines=%.1f "
        "languages=%s",
        trace_id,
        stats.question_count,     # 识别到的题目数（含代码的题）
        stats.block_count,        # 识别到的代码块总数
        stats.avg_code_lines,     # 平均每块代码行数
        stats.languages or "none",  # 检测到的语言分布，如 "c:2,python:1"
    )
    return result
```

日志示例：
```
[CodeDetector] trace_id=ocr_batch_20260619_001 questions=3 blocks=5 avg_lines=4.2 languages=c:2,java:1,sql:1
[CodeDetector] trace_id=ocr_batch_20260619_002 questions=0 blocks=0 avg_lines=0.0 languages=none
```

便于监控：误判率、漏检率、性能影响。

#### 约束 8：CSS 最小化 — 暂不引入主题

第一版 CSS 仅实现三要素：**monospace 字体 + 保留格式 + 横向滚动**。不引入深色主题、语法高亮、行号等。

```css
/* miniprogram/components/mp-html/index.wxss — 追加 */
._pre {
  display: block;
  overflow-x: auto;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 26rpx;
  line-height: 1.6;
  white-space: pre;
  -webkit-overflow-scrolling: touch;
  margin: 16rpx 0;
  padding: 16rpx 24rpx;
  background: #f5f5f5;
  border-radius: 8rpx;
}

._code {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 0.92em;
}
```

后续第二阶段可引入深色主题，但第一版本仅保证可读性。

### 修正后的数据流

```
OCR 原始文本（缩进、换行完好）
    │
    ▼ (新增) code_detector.wrap_code_fences()  ← 第一步：基于原始文本检测
    │   └ 结构信号（缩进/braces/分号）+ 关键词信号 → 双重判断
    │   └ 命中 → 插入 ``` 围栏
    │
    ▼ clean_ocr_text()  ← 围栏已在位
    │   └ L619 空间压缩 → 修改为跳过围栏内容
    │   └ 其余步骤（去乱码、箭头修复、CJK 合并）→ 不触及围栏内
    │
    ▼ ImportTextNormalizer.normalize()
    │   └ _clean_newlines()     → in_code_fence=True → 跳过合并
    │   └ _normalize_spaces()   → 按围栏切分 → 跳过压缩
    │   └ _filter_watermark()   → in_code_fence=True → 跳过过滤
    │
    ▼ AI OCR Corrector / AI Repair
    │   └ 仅保持已有围栏和格式，不负责发现代码块
    │
    ▼ DB: Question.content.text = "题干...\n```text\nfor(...) {\n    ...\n}\n```"
    │
    ▼ 前端: _textToHtml() → mp-html 自动解析 <pre><code>
    │   └ CSS: ._pre 深色背景 + monospace + 横向滚动
```

### 第一阶段实施清单

#### A. 代码检测器 — `backend/app/features/code_detector.py`（新建）

单一职责：在 OCR 原始文本上检测代码块区域，插入 ``` 围栏。
必须在任何空格压缩、换行合并之前调用。

**检测算法 — 结构信号 + 关键词信号双重判断：**

```
FOR each line:
  struct_score  = 0
  keyword_score = 0

  ── 结构信号检测 ──
  IF line 含缩进 ≥2 空格 (行首)     → struct_score += 1
  IF line 含行尾分号 ;               → struct_score += 1
  IF line 为独立 brace 行 { 或 }     → struct_score += 1
  IF line 含 C 风格运算符 (->, ::, ++, --, &&, ||, ==, !=, <=, >=)
                                     → struct_score += 1

  ── 关键词信号检测 ──
  IF line 含编程关键词               → keyword_score += 1

  ── 行标记 ──
  line._is_code = (struct_score >= 1 AND keyword_score >= 1)
                  OR struct_score >= 2
```

**关键约束：keyword_score 单独 ≥1 不触发。** 必须 struct_score ≥1。

**连续行判定：**

```
连续 ≥2 行且每行 _is_code = True → 标记为代码块边界

例外：单行不触发（避免 "A. 选择排序算法的时间复杂度是 O(n)" 误判）
```

**编程关键词集合**（覆盖 9 种语言，通过行级 token 匹配，非子串匹配）：

```
# C / C++
\b(for|while|if|else|switch|case|return|break|continue|do|goto)\b
\b(int|float|double|char|void|long|short|struct|enum|union|typedef|const|static|sizeof|unsigned|signed)\b
\b(printf|scanf|malloc|free|NULL|true|false|include|define)\b

# Java
\b(class|public|private|protected|new|extends|implements|interface|abstract|final|throws)\b
\b(String|boolean|System\.out|System\.in)\b

# Python
\b(def|import|from|print|lambda|yield|raise|except|try|finally|with|as|elif|pass)\b
\b(self|__init__|__name__)\b
\b(range|len|list|dict|set|tuple|str|int|float|bool)\b(?=\s*\()

# JavaScript
\b(function|var|let|const|console|document|window|async|await|export|default)\b

# SQL
\b(SELECT|FROM|WHERE|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\b
\b(ORDER\s+BY|GROUP\s+BY|HAVING|JOIN|LEFT\s+JOIN|INNER\s+JOIN|UNION|DISTINCT|COUNT|SUM|AVG)\b

# HTML / XML
<(html|div|span|table|tr|td|th|body|head|p|a|ul|ol|li|script|style|meta|link)\b
```

**结构信号集合**（语言无关）：

```
# 缩进
^[ ]{2,}\S          — 行首 ≥2 空格（不是 tab 转空格，OCR 原文即空格缩进）

# 语句终止/分隔符
;\s*$                — 行尾分号
[{}]\s*$             — 行尾 brace
^\s*[{}]\s*$         — 独立 brace 行

# 运算符（C 家族）
->                   — 指针成员访问
::                    — C++ 作用域
\bnew\s+\w+\s*[({]   — C++/Java new
\b\w+\s*[<>]=?\s*\w+ — 比较/赋值运算符
\+\+|--               — 自增/自减

# Python 特有结构
^\s*def\s+\w+\s*\(    — 函数定义行
^\s*class\s+\w+       — 类定义行
:\s*$                 — 以冒号结尾（Python 块开始）
```

**围栏插入函数签名：**

```python
from dataclasses import dataclass

@dataclass
class CodeDetectStats:
    """代码检测统计"""
    question_count: int = 0     # 识别到的含代码题目数
    block_count: int = 0        # 识别到的代码块总数
    total_code_lines: int = 0   # 代码行总数
    languages: dict[str, int]   # {language: count}

    @property
    def avg_code_lines(self) -> float:
        return self.total_code_lines / self.block_count if self.block_count else 0.0


def wrap_code_fences(text: str, *, trace_id: str = "") -> str:
    """在 OCR 原始文本上检测代码块并插入 ``` 围栏。

    约束：
    - 关键词不能单独触发（必须 struct_score ≥ 1）
    - 单行不触发（必须连续 ≥2 行命中）
    - 已有围栏区域不重复处理
    - 检测到的代码块标记为 ```text（规则层不给语言推断）
    - Flag 关闭时透传，行为与线上完全一致（约束 6）
    - 调用后输出结构化命中日志（约束 7）
    """
```

**误判防护测试场景：**

```
不含代码的题干 → 不插入围栏：
  "下列选项中正确的是（ ）"          — 无结构信号
  "对于以下说法，正确的有"            — 无结构信号
  "A. O(n) B. O(n²) C. O(log n)"  — 单行，不触发
  "设函数 f(x)=x²+1，求 f'(x)"     — 含 'f' 但不是 for

含代码的题干 → 正确插入围栏：
  "以下程序段的时间复杂度是（ ）\nint i=1;\nwhile(i<=n)\n    i=i*2;"
  → 检测到 int/while 关键词 + 缩进/分号结构 → 包裹代码部分

边界情况：
  "已知程序段如下：\nfor(i=0;i<n;i++)\n    a[i]=i;\n则其时间复杂度为（ ）"
  → "for" + ";" + 缩进 → 两行代码，插入围栏
  → "已知程序段如下：" 和 "则其时间复杂度为（ ）" 保持纯文本
```

#### B. `clean_ocr_text()` 修改 — `backend/app/services/ocr_service.py`

两处改动：

```python
# L585: 函数第一步 — 在最前面调用代码检测（基于原始文本）
from app.features.code_detector import wrap_code_fences
text = wrap_code_fences(text)

# L619: 空间压缩保护围栏
# 原: text = re.sub(r" {2,}", " ", text)
# 改:
parts = re.split(r"(```[\s\S]*?```)", text)
text = "".join(
    part if part.startswith("```") else re.sub(r" {2,}", " ", part)
    for part in parts
)
```

注意：`wrap_code_fences` 必须在 `clean_ocr_text()` 的**第一步**调用，在所有清洗操作之前，以保证代码检测基于保留缩进/换行的原始文本。

#### C. AI Prompt 修改 — `backend/app/ai/prompts.py`

**约束：AI 不负责发现代码块。围栏由规则层生成。AI 仅保持已有围栏和代码格式。**

OCR 纠错 prompt 末尾追加：

```
代码块保护规则：
- 原文中的 ``` 代码围栏是结构标记，必须原样保留
- 围栏内的所有缩进、换行、空格不得修改
- 不要在围栏外新增围栏（代码块边界由预处理管线决定）
- 围栏内 C/Java 代码中 printf("\\n") 等字符串字面量的 \\n 是转义序列，
  不应被解释为文本换行符
```

Question repair prompt 规则 9 保持原样（已正确）。

#### E. OCR 回归数据集 — `backend/tests/ocr_regression/code/`（新建目录）

**约束：覆盖至少 6 种语言，模拟真实 OCR 噪声。**

目录结构：

```
backend/tests/ocr_regression/code/
├── __init__.py
├── cases.py          # 测试用例定义（{name, raw_text, expected_fenced}）
├── c.c               # C 代码样本
├── cpp.cpp           # C++ 代码样本
├── java.java         # Java 代码样本
├── python.py         # Python 代码样本
├── sql.sql           # SQL 代码样本
└── html.html         # HTML 代码样本
```

`cases.py` 结构：

```python
"""OCR 代码回归测试用例。每个用例模拟真实 OCR 输出（含噪声）。"""

REGRESSION_CASES: list[dict] = [
    {
        "name": "c_for_loop",
        "language": "c",
        "description": "C for 循环 — 基础语法检测",
        "raw_text": (
            "以下程序段的时间复杂度是（ ）\n"
            "int i=1;\n"
            "while(i<=n)\n"
            "    i=i*2;\n"
            "A. O(n) B. O(n²) C. O(log n) D. O(nlog n)"
        ),
        "expected_has_fence": True,
        "expected_code_lines": 3,
    },
    {
        "name": "c_pointer",
        "language": "c",
        "description": "C 指针与链表 — 箭头运算符检测",
        ...
    },
    {
        "name": "java_class",
        "language": "java",
        "description": "Java 类定义 — 关键词+结构双重判断",
        ...
    },
    {
        "name": "python_def",
        "language": "python",
        "description": "Python 函数 — 冒号+缩进结构检测",
        ...
    },
    {
        "name": "sql_select",
        "language": "sql",
        "description": "SQL SELECT — 大写关键词检测",
        ...
    },
    {
        "name": "html_div",
        "language": "html",
        "description": "HTML 标签 — 尖括号结构检测",
        ...
    },
    # 负向测试：不应触发围栏
    {
        "name": "negative_math_choice",
        "language": None,
        "description": "数学选择题 — 含数学符号但非代码",
        "raw_text": "设函数 f(x)=x²+1，求 f'(x)\nA. 2x B. x² C. 2x+1 D. x",
        "expected_has_fence": False,
    },
    {
        "name": "negative_cjk_text",
        "language": None,
        "description": "中文题干 — 含 'if'/'for' 子串但不触发",
        "raw_text": "下列选项中正确的是（ ）\n对于以下说法，正确的有",
        "expected_has_fence": False,
    },
]
```

#### F. 回归测试脚本 — `backend/tests/test_code_detector.py`（新建）

```python
"""代码检测器回归测试。验证 code_detector 的行为符合约束 1-5。"""

import pytest
from app.features.code_detector import wrap_code_fences
from tests.ocr_regression.code.cases import REGRESSION_CASES

class TestCodeDetectorRegression:
    @pytest.mark.parametrize("case", [c for c in REGRESSION_CASES if c["expected_has_fence"]])
    def test_detects_code_blocks(self, case):
        """正例：应正确插入围栏"""
        result = wrap_code_fences(case["raw_text"])
        assert "```" in result
        # 围栏内代码行数正确
        ...

    @pytest.mark.parametrize("case", [c for c in REGRESSION_CASES if not c["expected_has_fence"]])
    def test_no_false_positive(self, case):
        """负例：不应误插围栏"""
        result = wrap_code_fences(case["raw_text"])
        assert "```" not in result

class TestCodeFormatPreservation:
    """验证 clean_ocr_text / text_normalizer / question_pipeline 链路"""

    def test_ocr_clean_preserves_fenced_code(self):
        """clean_ocr_text 不破坏围栏内的缩进和空格"""
        ...

    def test_text_normalizer_preserves_fenced_code(self):
        """ImportTextNormalizer 不合并/压缩围栏内内容"""
        ...

    def test_pipeline_end_to_end(self):
        """完整链路：原始 OCR → 围栏插入 → normalize → 格式完好"""
        ...
```

**回归测试门禁规则：**

后续所有修改 `clean_ocr_text`、`text_normalizer`、`question_pipeline` 时，
必须运行：

```bash
pytest backend/tests/test_code_detector.py -v
pytest backend/tests/ocr_regression/ -v
```

两个套件全部通过方可合并。

#### D. 前端 CSS（最小化）— `miniprogram/components/mp-html/index.wxss`（追加）

**约束：第一版仅实现 monospace + 保留格式 + 横向滚动。不引入主题。**

```css
/* 代码块 — 最小化：等宽 + 保留格式 + 横向滚动 */
._pre {
  display: block;
  overflow-x: auto;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 26rpx;
  line-height: 1.6;
  white-space: pre;
  -webkit-overflow-scrolling: touch;
  margin: 16rpx 0;
  padding: 16rpx 24rpx;
  background: #f5f5f5;
  border-radius: 8rpx;
}

._code {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 0.92em;
}
```

同步追加到 `practice.wxss` 和 `wrong-detail.wxss`。

------

## 第二阶段：统一内容块架构设计（评估与预留）

### 目标

在不破坏第一阶段的前提下，评估 `hybrid_content_builder` + `segments` 架构，为后续 `type=code` / `type=table` 等内容块统一演进预留扩展能力。

### 关键原则

1. **不进行数据库迁移** — 复用现有 JSONB `content` 列
2. **不破坏现有题库** — `render_mode` 缺失时回退为纯文本路径
3. **不增加复杂度** — 扩展而非重写

---

### 现有 segments 架构分析

**当前 `hybrid_content_builder.build()` 签名：**

```python
# backend/app/services/hybrid_content_builder.py
def build(text: str, regions: list[MathRegion]) -> dict:
    """返回 {"text": "...", "segments": [...], "render_mode": "segments"}"""
```

**调用链路：**

```
import_service._run_math_pipeline()          # 后台任务
    → math_region_detector.detect_page()     # 检测数学区域
    → formula_image_cropper.crop_and_upload() # 截图上传
    → hybrid_content_builder.build()         # 构建内容 JSON
    → qi.parsed_content = content            # 存到 QuestionImport
    → qi.math_regions = [regions]            # 额外字段
```

**当前 segments 类型体系：**

```python
# 已实现
{"type": "text",       "text": str}
{"type": "math_image", "url": str, "alt": str, "display": bool}
{"type": "newline"}

# 第一阶段（Markdown 围栏）不产生新 segment 类型
# --- 数据以 ``` 围栏嵌入 content.text 中，render_mode 可保持 "text"
```

**前端渲染分发逻辑（`practice.js:629`）：**

```javascript
stemRenderPath:
  q._stemNeedsRich ? 'mp-html'
  : (q.content.render_mode === 'segments' && config.enableMathImage ? 'math-question'
  : 'text')
```

三条路径：`mp-html`（富文本）> `math-question`（分段）> `text`（纯文本）

---

### 第二阶段：统一演进为 `type=code` 的设计

#### 扩展后的 segments 类型体系（目标）

```python
# 文本（现有）
{"type": "text",       "text": str}

# 数学公式图片（现有）
{"type": "math_image", "url": str, "alt": str, "display": bool}

# 换行（现有）
{"type": "newline"}

# 代码块（新增）
{"type": "code",       "language": str, "content": str}
# language: "c"|"cpp"|"java"|"python"|"javascript"|"sql"|"html"|"text"

# 表格（预留）
{"type": "table",      "headers": [str], "rows": [[str]]}

# 图片（预留）
{"type": "image",      "url": str, "alt": str}
```

#### 统一内容构建器设计

**新建 `unified_content_builder.py`，在 `hybrid_content_builder` 基础上扩展：**

```python
# backend/app/services/unified_content_builder.py

from dataclasses import dataclass
from app.services.math_region_detector import MathRegion

@dataclass
class CodeRegion:
    """代码区域（从 Markdown 围栏解析得到）"""
    language: str       # "c" | "python" | "sql" | ...
    content: str        # 围栏内的代码文本
    start_pos: int      # 在原始 text 中的起始位置

def build_unified(
    text: str,
    math_regions: list[MathRegion] | None = None,
) -> dict:
    """统一内容构建器。

    1. 从 text 中解析 Markdown 围栏 → CodeRegion 列表
    2. 合并 math_regions → MathRegion 列表
    3. 按在 text 中的位置排序所有 region
    4. 切分 text 为 segments 数组

    Returns:
        {"text": str, "segments": [...], "render_mode": "segments"}
    """
    code_regions = _parse_fence_regions(text)
    regions = _merge_regions(code_regions, math_regions or [])
    segments = _build_segments(text, regions)
    return {
        "text": _rebuild_text(segments),
        "segments": segments,
        "render_mode": "segments",
    }

def _parse_fence_regions(text: str) -> list[CodeRegion]:
    """从文本中解析 ``` 围栏，提取为 CodeRegion。"""
    pattern = re.compile(r"```(\w*)\n([\s\S]*?)```")
    regions = []
    for m in pattern.finditer(text):
        regions.append(CodeRegion(
            language=m.group(1) or "text",
            content=m.group(2).rstrip(),
            start_pos=m.start(),
        ))
    return regions
```

#### 从第一阶段到第二阶段的过渡路径

```
第一阶段（当前实施）：
  content = {"text": "题干...\n```c\nfor(...) {\n    ...\n}\n```"}
  render_mode = "text"（或不存在）
  前端路径 → mp-html 自动渲染 <pre><code>

第二阶段（后续升级）：
  content = {
    "text": "题干...\n```c\nfor(...) {\n    ...\n}\n```",
    "segments": [
      {"type": "text", "text": "题干...\n"},
      {"type": "code", "language": "c", "content": "for(...) {\n    ...\n}"},
    ],
    "render_mode": "segments"
  }
  前端路径 → math-question 组件（扩展了 code 渲染）

过渡：已入库的第一阶段题目，可通过 unified_content_builder.build_unified()
      重新构建 segments，无需修改原始 content.text
```

#### 前端 math-question 扩展为 code 类型

```xml
<!-- miniprogram/components/math-question/math-question.wxml 追加 -->
<view wx:elif="{{item.type === 'code'}}" class="seg-code-wrap">
  <scroll-view scroll-x class="seg-code-scroll">
    <text class="seg-code" space="ensp">{{item.content}}</text>
  </scroll-view>
</view>
```

```css
/* 追加样式 */
.seg-code-wrap {
  margin: 16rpx 0;
  border-radius: 12rpx;
  overflow: hidden;
}
.seg-code-scroll {
  background: #1e1e1e;
  padding: 24rpx;
  white-space: nowrap;
}
.seg-code {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 26rpx;
  line-height: 1.6;
  color: #d4d4d4;
  white-space: pre;
}
```

#### 兼容性保证

```
content.render_mode 不存在？
  → 回退到 text 路径，mp-html 或纯文本渲染

content.segments 存在但含未知 type？
  → 忽略未知 type 的 segment，渲染其余

第一阶段题目（仅有围栏，无 segments）？
  → mp-html 渲染围栏，行为正确
  → 可在后台任务中调用 build_unified() 重新处理，产生 segments
```

---

### 统一内容块模型的可行性评估

| 维度 | 评估 |
|------|------|
| **架构契合度** | ✅ `hybrid_content_builder` 的模式直接可扩展，新类型只需追加 segment case |
| **数据库** | ✅ JSONB 列无 schema 约束，`segments` 数组任意扩展 |
| **向后兼容** | ✅ `render_mode` 缺失时走现有 text/mp-html 路径 |
| **前端扩展成本** | 低 — `math-question` 每新增一种 type 只需加一个 `wx:elif` 分支 |
| **第一阶段不产生技术债** | ✅ 围栏是纯文本，`build_unified()` 可随时从围栏解析出 code segments |
| **AI 输出适配** | AI 产出的 ``` 围栏可直接被 `_parse_fence_regions()` 解析，无需改 AI JSON schema |

### 结论

第一阶段（Markdown 围栏）不是临时方案——它是第二阶段（统一 segments）的**数据准备层**。围栏在文本中提供了结构信号，`unified_content_builder` 在渲染层解析这些信号，两个阶段的数据模型完全兼容。

------

# 实施计划

## 第一阶段实施清单

| # | 文件 | 操作 | 内容 |
|---|------|------|------|
| 1 | `backend/app/core/config.py` | **修改** | 追加 `CODE_DETECTOR_ENABLED` Feature Flag（默认 false） |
| 2 | `backend/app/features/code_detector.py` | **新建** | `wrap_code_fences()` 双重判断 + Flag 透传 + 命中日志 |
| 3 | `backend/app/services/ocr_service.py` | **修改** | `clean_ocr_text()` 第一步调用检测 + L619 围栏保护 |
| 4 | `backend/app/ai/prompts.py` | **修改** | OCR纠错 prompt：AI 仅保持已有围栏，不发现代码块 |
| 5 | `backend/tests/ocr_regression/code/cases.py` | **新建** | 6 语言回归用例（含正例+负例） |
| 6 | `backend/tests/ocr_regression/code/` | **新建** | 6 语言代码样本文件（c/cpp/java/python/sql/html） |
| 7 | `backend/tests/test_code_detector.py` | **新建** | 检测器 + Flag 透传 + 链路回归测试 |
| 8 | `miniprogram/components/mp-html/index.wxss` | **修改** | 最小化 CSS：monospace + 保留格式 + 横向滚动 |
| 9 | `miniprogram/pages/practice/practice.wxss` | **修改** | 同步最小化 `._pre` `._code` 样式 |
| 10 | `miniprogram/pages/wrong-detail/wrong-detail.wxss` | **修改** | 同步最小化 `._pre` `._code` 样式 |

## 第二阶段设计（本次不实施，仅文档化）

| # | 文件 | 操作 | 内容 |
|---|------|------|------|
| 11 | `backend/app/services/unified_content_builder.py` | **新建** | 从 text+math_regions 构建含 code 的 segments |
| 12 | `miniprogram/components/math-question/math-question.wxml` | **修改** | 追加 `type="code"` 渲染分支 |
| 13 | `miniprogram/components/math-question/math-question.wxss` | **修改** | 追加 `.seg-code` 样式 |

------

# 实施状态

- [x] 阶段一：审计 — 完成（2026-06-19）
- [x] 阶段二：方案设计 — 完成（两阶段策略 + 8 项约束）
- [x] 第一阶段 A：Feature Flag — `CODE_DETECTOR_ENABLED` 配置项（2026-06-19）
- [x] 第一阶段 B：`code_detector.py` — 双重判断 + Flag 透传 + 命中日志（2026-06-19）
- [x] 第一阶段 C：`clean_ocr_text()` — 第一步调用检测 + L619 围栏保护（2026-06-19）
- [x] 第一阶段 D：AI Prompt — 仅保持围栏，不发现代码块（2026-06-19）
- [x] 第一阶段 E：前端 CSS — 最小化 monospace + 保留格式 + 横向滚动（2026-06-19）
- [x] 第一阶段 F：OCR 回归数据集 — 13 用例（8 正例 + 5 负例）（2026-06-19）
- [x] 第一阶段 G：回归测试 — 49 tests passed（2026-06-19）
- [ ] 第二阶段（预留）：统一内容块模型 `unified_content_builder`

### 第一阶段交付物

| 文件 | 状态 |
|------|------|
| `backend/app/core/config.py` | +2 行 `CODE_DETECTOR_ENABLED` |
| `backend/app/features/code_detector.py` | 新建 230 行 |
| `backend/app/services/ocr_service.py` | 修改 +14 行 |
| `backend/app/ai/prompts.py` | 修改 +16 行 |
| `backend/tests/ocr_regression/code/__init__.py` | 新建 |
| `backend/tests/ocr_regression/code/cases.py` | 新建 13 用例 |
| `backend/tests/test_code_detector.py` | 新建 49 tests |
| `miniprogram/components/mp-html/index.wxss` | +20 行 CSS |
| `miniprogram/pages/practice/practice.wxss` | +20 行 CSS |
| `miniprogram/pages/wrong-detail/wrong-detail.wxss` | +20 行 CSS |

### 部署

```bash
# 默认关闭，行为与线上一致
export CODE_DETECTOR_ENABLED=true   # 灰度开启
```