# Segment Schema 规范 v1.0

> 统一 Content Block 体系的核心类型定义。
> 所有 segment 类型共享相同的 JSON 结构约束，保证向前兼容。

---

## SegmentType 枚举

```python
from enum import StrEnum


class SegmentType(StrEnum):
    """Content Block Segment 类型枚举。

    新增类型时遵循规则：
    - 值必须唯一
    - 新增类型不能改变已有类型的语义
    - 前端遇到未知类型时降级渲染（skipped, not crashed）
    - 枚举以字母顺序排列便于查找
    """

    CODE = "code"              # 代码块（围栏包裹的源码）
    DIAGRAM = "diagram"        # 流程图/图表（预留）
    IMAGE = "image"            # 图片块（预留）
    MATH = "math"              # LaTeX 数学公式（预留，客户端渲染）
    MATH_IMAGE = "math_image"  # 数学公式远程图片（当前方案）
    NEWLINE = "newline"        # 显式换行
    TABLE = "table"            # 表格数据（预留）
    TEXT = "text"              # 普通文本段
```

---

## 通用约束

所有 segment 对象必须满足：

1. **`type` 字段必填**，值必须为 SegmentType 枚举成员
2. **无额外顶层字段**：除 type 外，仅允许各类型定义的字段
3. **不变量**：segments 数组内的文本拼接 + type=code 的 content 必须与 content.text 语义等价
4. **向前兼容**：旧版前端遇到未知 type 时跳过该 segment（不崩溃）
5. **幂等性**：同一 content JSON 多次调用 build() 结果一致

---

## 各 Segment JSON Schema

### 1. `text` — 普通文本

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type", "text"],
  "properties": {
    "type": { "const": "text" },
    "text": {
      "type": "string",
      "description": "纯文本内容，不含换行符（换行由 newline segment 表示）"
    }
  },
  "additionalProperties": false
}
```

**约束**：
- `text` 不得包含 `\n` 字符
- `text` 可以为空字符串（表示空白行，但与 newline 配合使用）

**示例**：
```json
{"type": "text", "text": "设函数 $f(x)=x^2+1$，则 $f'(x)=$（ ）。"}
```

---

### 2. `code` — 代码块

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type", "content"],
  "properties": {
    "type": { "const": "code" },
    "language": {
      "type": "string",
      "description": "编程语言标识符，小写。未检测到语言时为 'text'。常用值：c, cpp, java, python, javascript, sql, html",
      "default": "text"
    },
    "content": {
      "type": "string",
      "description": "源代码原文，保留换行和缩进"
    }
  },
  "additionalProperties": false
}
```

**约束**：
- `content` 保留原始格式（换行、缩进、空格）
- `language` 来自 ``` 围栏的语言标签，未指定时为 "text"
- 前端渲染时必须 monospace + preserve whitespace + horizontal scroll

**示例**：
```json
{
  "type": "code",
  "language": "c",
  "content": "int main() {\n    return 0;\n}"
}
```

---

### 3. `math_image` — 数学公式图片（当前方案）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type", "url", "alt"],
  "properties": {
    "type": { "const": "math_image" },
    "url": {
      "type": "string",
      "description": "公式图片的远程 URL"
    },
    "alt": {
      "type": "string",
      "description": "LaTeX 源码（图片加载失败时的 fallback 文本）"
    },
    "display": {
      "type": "boolean",
      "description": "true = 块级公式（独占一行），false = 行内公式",
      "default": false
    }
  },
  "additionalProperties": false
}
```

**与 `math` 的关系**：`math` 是预留类型用于未来客户端 KaTeX/MathJax 渲染。`math_image` 和 `math` 不应同时存在 — 当客户端渲染可用时，`math_image` 降级为 `math`。

**示例**：
```json
{
  "type": "math_image",
  "url": "https://cdn.example.com/math/abc123.png",
  "alt": "x^2 + y^2 = 1",
  "display": true
}
```

---

### 4. `table` — 表格（预留）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type", "rows"],
  "properties": {
    "type": { "const": "table" },
    "headers": {
      "type": "array",
      "items": { "type": "string" },
      "description": "表头行（可选）"
    },
    "rows": {
      "type": "array",
      "items": {
        "type": "array",
        "items": { "type": "string" }
      },
      "description": "数据行，每行为字符串数组"
    },
    "caption": {
      "type": "string",
      "description": "表格标题（可选）"
    }
  },
  "additionalProperties": false
}
```

**约束**：
- 所有行的列数应一致（前端可自行处理不规则表格）
- `headers` 和 `rows[0]` 可能语义等价—由后端决定是否去重

**示例**：
```json
{
  "type": "table",
  "headers": ["算法", "最好时间", "平均时间", "最坏时间"],
  "rows": [
    ["冒泡排序", "O(n)", "O(n²)", "O(n²)"],
    ["快速排序", "O(n log n)", "O(n log n)", "O(n²)"],
    ["归并排序", "O(n log n)", "O(n log n)", "O(n log n)"]
  ],
  "caption": "常见排序算法时间复杂度对比"
}
```

---

### 5. `image` — 图片块（预留）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type", "url"],
  "properties": {
    "type": { "const": "image" },
    "url": {
      "type": "string",
      "description": "图片远程 URL"
    },
    "alt": {
      "type": "string",
      "description": "替代文本"
    },
    "width": {
      "type": "integer",
      "description": "图片宽度（像素）"
    },
    "height": {
      "type": "integer",
      "description": "图片高度（像素）"
    },
    "caption": {
      "type": "string",
      "description": "图片说明文字"
    }
  },
  "additionalProperties": false
}
```

---

### 6. `diagram` — 流程图/图表（预留）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type", "content"],
  "properties": {
    "type": { "const": "diagram" },
    "language": {
      "type": "string",
      "description": "图表语言：mermaid, plantuml, graphviz",
      "default": "mermaid"
    },
    "content": {
      "type": "string",
      "description": "图表源码文本"
    }
  },
  "additionalProperties": false
}
```

---

### 7. `newline` — 显式换行

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["type"],
  "properties": {
    "type": { "const": "newline" }
  },
  "additionalProperties": false
}
```

**约束**：
- `newline` 表示渲染时的显式断行，不为 `<br>` 的语义别名
- 连续两个 `newline` 表示空行（段落分隔）
- 不应有额外的 `text` 字段

---

## Content JSON 顶层结构

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["text"],
  "properties": {
    "text": {
      "type": "string",
      "description": "题目内容的纯文本表示（保留 Markdown 围栏）"
    },
    "segments": {
      "type": "array",
      "items": {
        "oneOf": [
          { "$ref": "#/defs/text" },
          { "$ref": "#/defs/code" },
          { "$ref": "#/defs/math_image" },
          { "$ref": "#/defs/table" },
          { "$ref": "#/defs/image" },
          { "$ref": "#/defs/diagram" },
          { "$ref": "#/defs/newline" }
        ]
      },
      "description": "结构化内容段列表（可选）"
    },
    "render_mode": {
      "type": "string",
      "enum": ["text", "segments"],
      "description": "前端渲染模式：'text' 使用 mp-html 纯文本渲染，'segments' 使用 math-question 结构化渲染",
      "default": "text"
    }
  },
  "additionalProperties": false,
  "defs": {
    "text": { "$ref": "#/segment-text" },
    "code": { "$ref": "#/segment-code" },
    "math_image": { "$ref": "#/segment-math-image" },
    "table": { "$ref": "#/segment-table" },
    "image": { "$ref": "#/segment-image" },
    "diagram": { "$ref": "#/segment-diagram" },
    "newline": { "$ref": "#/segment-newline" }
  }
}
```

---

## 扩展规则

### 新增类型 checklist

1. [ ] 在 `SegmentType` 枚举中新增值
2. [ ] 定义 JSON Schema（本节格式）
3. [ ] 在 `_rebuild_text()` 中添加逆序列化逻辑
4. [ ] 在 `math-question.wxml` 中添加渲染分支
5. [ ] 在 `math-question.wxss` 中添加样式
6. [ ] 添加回归测试 case（`test_content_block_cases.py`）
7. [ ] 确保旧版前端遇到新 type 时跳过不报错
8. [ ] 更新本规范文档

### 废弃类型规则

- `math_image` → `math` 迁移路径：后端同时输出两种 type 一段时间，前端优先使用 `math`，降级到 `math_image`
- 废弃类型保留至少 2 个发布周期后移除

---

## 与 content.text 的一致性保证

```
不变量：
  segments_to_text(segments) == 规范化(text)
  
其中 segments_to_text(s):
  text + newline → text.text + "\n"
  code         → "```" + code.language + "\n" + code.content + "\n```"
  math_image   → "$" + math_image.alt + "$"
  table        → Markdown table 表示（未来定义）
  image        → ""（不参与 text 重建）
  diagram      → "```" + diagram.language + "\n" + diagram.content + "\n```"
```

---

*規範 v1.0 — 实施阶段二-A 时快照*
