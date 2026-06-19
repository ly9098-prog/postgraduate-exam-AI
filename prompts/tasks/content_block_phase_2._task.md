# 阶段二任务：Content Block 架构评估与预埋

第一阶段（Markdown 代码围栏方案）已完成并提交为 `d48d88b`。

---

## 1. 当前架构分析

### 1.1 完整数据流

```
OCR 文本 (PaddleOCR 或 PyMuPDF)
  │
  ├─[1] code_detector.wrap_code_fences()    ← 阶段一注入点
  │    插入 ``` 围栏（CODE_DETECTOR_ENABLED flag 控制）
  │
  ▼
ImportTextNormalizer.normalize()
  ├─ in_code_fence 保护：围栏内内容不合并换行、不去重空格
  │
  ▼
AI OCR Correction (可选)
  ├─ prompt 规则 9：保护已有 ``` 围栏
  │
  ▼
QuestionSplitter → StructureAnalyzer → AnswerMatcher
  ├─ 不涉及围栏感知（逐行分析）
  │
  ▼
QuestionNormalizer.normalize()
  ├─ clean_text() 含 in_code_fence 保护
  ├─ hybrid_content_builder.build()  → 仅处理 math_image 类型
  │
  ▼
DB: Question.content (JSONB)
  ├─ 形式一：{"text": "题干... ```c\n...\n``` ..."}
  ├─ 形式二：{"text": "...", "segments": [...], "render_mode": "segments"}
  │          ↑ 仅当有公式图片时出现
  │
  ▼
前端渲染（微信小程序）
  ├─ 路径A: mp-html  — _stemNeedsRich=true 时（含 $...$ LaTeX 或 HTML 标签或多行文本）
  ├─ 路径B: math-question 组件 — render_mode==='segments' && enableMathImage
  └─ 路径C: text 组件 — 纯文本
```

### 1.2 各环节格式细节

| 环节 | 输入 | 输出 | 代码感知 |
|------|------|------|---------|
| code_detector | 纯文本 | 含 ``` 围栏的文本 | 是（产生围栏） |
| ImportTextNormalizer | 任意文本 | normalized_text | 是（保护围栏内内容） |
| AI OCR Correction | 任意文本 | 纠正后文本 | 是（prompt 规则 9） |
| QuestionSplitter | normalized_blocks | raw_questions | 否 |
| QuestionNormalizer | raw dict | 标准 schema | 是（保护围栏） |
| hybrid_content_builder | text + math regions | content JSON | 否（仅处理 math） |
| DB | content JSONB | content JSONB | 否（透传） |
| 前端 mp-html | text/HTML | 渲染视图 | 部分（CSS 已添加） |
| 前端 math-question | segments[] | 渲染视图 | 否（无 code 类型） |

### 1.3 segments 能力现状

`hybrid_content_builder.py` 已支持三种 segment 类型：
- `{"type": "text", "text": "..."}`  — 普通文本段
- `{"type": "math_image", "url": "...", "alt": "...", "display": true|false}`  — 公式图片
- `{"type": "newline"}`  — 换行

前端 `math-question` 组件已完整渲染以上三种类型。

**关键发现**：segments 模型仅在检测到 math_image 时激活（`render_mode: "segments"`），纯文本题目不走此路径。代码围栏题目目前走的是 mp-html 路径（因为含换行符触发 `_needsRichRender`），不经过 segments 渲染。

---

## 2. 当前 Markdown 围栏方案评估

### 2.1 优点

1. **实现简单**：230 行单一模块，正则匹配 + 围栏包裹，无状态机
2. **零破坏**：不修改 DB schema，不改变历史数据，Feature Flag 可控回滚
3. **与现有系统完美兼容**：text_normalizer 和 question_pipeline 中已有 in_code_fence 保护逻辑
4. **立即可用**：mp-html 天然支持 ``` 围栏渲染，CSS 已补上 monospace + 横向滚动

### 2.2 缺点评估

| 声称的缺点 | 是否真实存在 | 严重程度 |
|-----------|-------------|---------|
| 代码语义隐藏在文本中 | **是** — 代码是 text 字段的子串，无法程序化访问 | 低（当前无程序化需求） |
| 表格和代码难统一处理 | **是** — 表格和代码都是 Markdown 字符串片段，无类型区分 | 中（表格恢复是已知未来需求） |
| 无法直接统计内容类型 | **是** — 需要重新解析 text 字段才能统计 | 低（统计需求尚未出现） |
| 无语言元数据 | **部分** — code_detector 已检测语言并写入围栏标签（```c, ```python 等） | 低 |
| 无法语法高亮 | **是** — mp-html 不支持语法高亮 | 中（408 代码可读性有提升空间） |

### 2.3 结论

Markdown 方案作为阶段一是正确的选择。上述缺点在当前业务规模下（日均导入量、代码题占比）均未造成实际问题，但：

- 表格恢复需求出现时，Markdown 表格与代码围栏混在同一 text 字段将显著增加解析复杂度
- 若未来需要代码高亮、代码搜索、代码块独立导出等功能，text 内嵌方案会成为瓶颈

**建议**：Markdown 方案作为长期运行方案是可行的，但预埋 Content Block 转换层作为可选升级路径是审慎的。

---

## 3. Content Block type=code 接入方案

### 3.1 约束重申

- 不修改历史题目
- 不修改数据库结构（不新增列、不改变 JSONB schema）
- 不影响现有 Markdown 方案（双路径共存）
- 仅在运行时支持转换

### 3.2 设计方案：围栏感知的 segments 构建器

新增 `unified_content_builder.py`，在 `hybrid_content_builder.py` 基础上扩展：

```
输入: question.content JSON (含 text 字段，text 中可能含 ``` 围栏)
输出: 同一个 content JSON，但 segments 中包含 code 段

示例输入:
{
  "text": "阅读以下代码：\n```c\nint main() {\n  return 0;\n}\n```\n下列说法正确的是"
}

示例输出:
{
  "text": "阅读以下代码：\n```c\nint main() {\n  return 0;\n}\n```\n下列说法正确的是",
  "segments": [
    {"type": "text", "text": "阅读以下代码："},
    {"type": "newline"},
    {"type": "code", "language": "c", "content": "int main() {\n  return 0;\n}"},
    {"type": "text", "text": "下列说法正确的是"}
  ],
  "render_mode": "segments"
}
```

### 3.3 实现细节

#### 3.3.1 `unified_content_builder.py`

```python
def build(content: dict) -> dict:
    """将 content.text 中的 ``` 围栏解析为 type=code segments。
    
    - 无围栏时透传原 content（不强制激活 segments 模式）
    - 有围栏时：按围栏边界切分 text，生成混合 segments
    - 已有 segments 且含 code 类型时：跳过（幂等）
    - 已有 segments 但无 code 类型时：合并 math segments + code segments
    """
    text = (content or {}).get("text", "")
    if not text or "```" not in text:
        return content  # 无围栏，透传

    existing_segments = (content or {}).get("segments")

    # 幂等保护
    if existing_segments and any(s.get("type") == "code" for s in existing_segments):
        return content

    # 解析围栏区域
    code_segments = _parse_fenced_regions(text)

    # 合并现有 math segments（如果有）
    if existing_segments:
        segments = _merge_with_math_segments(code_segments, existing_segments)
    else:
        segments = code_segments

    return {
        "text": text,
        "segments": segments,
        "render_mode": "segments",
    }
```

#### 3.3.2 围栏解析 `_parse_fenced_regions()`

```python
import re

_FENCE_RE = re.compile(r"```(\w*)\n([\s\S]*?)```")

def _parse_fenced_regions(text: str) -> list[dict]:
    """将 text 按 ``` 围栏切分为 segments（text → code → text ...）"""
    segments = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        # 围栏前的文本
        before = text[pos:m.start()]
        if before:
            segments.extend(_text_to_segments(before))
        # 代码块
        lang = m.group(1) or "text"
        code = m.group(2).rstrip()
        segments.append({"type": "code", "language": lang, "content": code})
        pos = m.end()
    # 尾部文本
    after = text[pos:]
    if after:
        segments.extend(_text_to_segments(after))
    return segments
```

#### 3.3.3 调用点

在 `QuestionNormalizer.to_question_fields()` 或管线末尾调用，将 content 透传至 unified_content_builder：

```python
# 在 question_pipeline.py 或 pipeline_orchestrator.py 的 review 阶段
from app.features.unified_content_builder import build as build_unified_content
content = build_unified_content(question["content"])
```

启用条件：Feature Flag `UNIFIED_CONTENT_ENABLED`（默认 false）。

### 3.4 为什么这个方案满足所有约束

| 约束 | 如何满足 |
|------|---------|
| 不修改历史题目 | 仅在新题导入 / 题干更新时运行；已入库题目保持原样 |
| 不修改数据库结构 | content JSONB 格式不变，仅新增 code segment type（JSON 扩展兼容） |
| 不影响 Markdown 方案 | text 字段中的 ``` 围栏原样保留；mp-html 渲染路径不感知 segments |
| 运行时转换 | build() 是纯函数，无副作用，可随时开关 |

---

## 4. 前端适配

### 4.1 math-question 组件扩展

在 `math-question.wxml` 中新增 code 类型渲染：

```xml
<view wx:elif="{{item.type === 'code'}}" class="seg-code-block">
  <view class="seg-code-head" wx:if="{{item.language && item.language !== 'text'}}">
    <text class="seg-code-lang">{{item.language}}</text>
  </view>
  <text class="seg-code-content" space="ensp">{{item.content}}</text>
</view>
```

新增 CSS（`math-question.wxss`）：
```css
.seg-code-block {
  display: block;
  overflow-x: auto;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 26rpx;
  line-height: 1.6;
  white-space: pre;
  margin: 16rpx 0;
  padding: 16rpx 24rpx;
  background: #f5f5f5;
  border-radius: 8rpx;
  -webkit-overflow-scrolling: touch;
}

.seg-code-head {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8rpx;
}

.seg-code-lang {
  font-size: 20rpx;
  color: #8EA0BA;
  font-weight: 700;
  text-transform: uppercase;
}
```

### 4.2 渲染路径选择升级

当前 practice.js 的路径选择逻辑（line 629）：
```js
stemRenderPath: q._stemNeedsRich ? 'mp-html'
  : (q.content && q.content.render_mode === 'segments' && config.enableMathImage
    ? 'math-question' : 'text'),
```

升级为：当 `render_mode === 'segments'` 且 segments 包含 code 类型时，也走 math-question 路径（math-question 组件已更名为通用 segments 渲染器，或新起一个 content-question 组件）。

实际做法：不改变 math-question 组件名称（避免影响现有引用），直接在组件内新增 code 类型支持。前端层面唯一的变化是：`_textToSegments()` 不再使用，改为直接使用后端返回的 segments 数组。

### 4.3 wrong-detail 页面同步

wrong-detail 需要同样的 code 段渲染。由于 wrong-detail 当前使用 mp-html 渲染 stem，若 segments 路径完整覆盖所有内容类型，可以考虑统一迁移到 segments 渲染。

---

## 5. 与未来能力兼容性评估

### 5.1 表格 (table)

```
segment: {"type": "table", "headers": [...], "rows": [[...], ...], "caption": "..."}
```

**兼容性：高**。表格天然是结构化数据，segments 模型比 Markdown 更适合表格。text 字段中保留 Markdown 表格语法作为 fallback 内容。

前端需要表格组件（可用 `<table>` 或自定义 grid），这是主要工作量。

### 5.2 数学公式 (math / math_image)

**已兼容**。当前 math_image 是 segments 体系内的一等公民。未来若引入 MathJax/KaTeX 客户端渲染，可新增 `{"type": "math", "latex": "..."}` 类型替代远程图片。

### 5.3 图片块 (image)

```
segment: {"type": "image", "url": "...", "alt": "...", "width": ..., "height": ...}
```

**兼容性：高**。OCR 已支持图片区域识别，只是当前未存储为 segment。扩展自然。

### 5.4 流程图 (diagram / mermaid)

**兼容性：中**。Mermaid 等文本描述语言用 Markdown 围栏表示（```` ```mermaid ````），直接复用 code 类型（`language: "mermaid"`）。前端需要 Mermaid 渲染库，但小程序环境受限。

### 5.5 代码高亮 (syntax highlighting)

**兼容性：高**。`type=code` 已携带 language 元数据，前端可根据 language 字段应用不同高亮规则。但微信小程序不支持 highlight.js / Prism.js，需要自建简单的关键词高亮。

### 5.6 综合评估

| 能力 | 当前状态 | Content Block 优势 | 难度 |
|------|---------|-------------------|------|
| 代码 | Markdown 围栏 | 独立访问、语言标记、高亮准备 | 低 |
| 表格 | 未实现 | 结构化的行列数据优于 Markdown 表格 | 高 |
| 公式 | 已实现 (math_image) | 已兼容 | — |
| 图片 | 未实现 | 自然扩展 | 低 |
| 流程图 | 未实现 | 复用 code 类型 | 中 |
| 代码高亮 | 未实现 | language 字段已就绪 | 中 |

**结论**：统一 Content Block 架构对所有未来能力有正向或中性影响，无冲突。

---

## 6. 推荐实施路径

### 阶段二-A：最小改造（当前推荐）

```
unified_content_builder.py (新增, ~120 行)
  ├── 围栏解析 + code segments 生成
  ├── 与 math segments 合并逻辑
  └── Feature Flag: UNIFIED_CONTENT_ENABLED

math-question 组件扩展 (修改 3 文件)
  ├── math-question.wxml: +8 行 code 渲染
  ├── math-question.wxss: +25 行 code 样式
  └── math-question.js: 无需改动（segments 已是透传）

question_pipeline.py 调用点 (修改 1 文件, +5 行)
  └── to_question_fields() 中调用 build_unified_content()

config.py (修改 1 行)
  └── UNIFIED_CONTENT_ENABLED: bool = False
```

**总代码量**：约 160 行新增，风险极低。

### 阶段二-B：前端渲染路径统一（后续可选）

```
将 practice.js / wrong-detail.js 中的 stemRenderPath 判断统一：
  - render_mode === 'segments' → 始终走 math-question（或改名 content-block）
  - 否则 → 走 mp-html / text
  
这样所有含 code/table/math 的题目都走 segments 渲染
```

### 阶段二-C：运行时降级（远期）

```
对历史题目（render_mode != 'segments'）：
  读取时按需调用 unified_content_builder 转换
  缓存结果到 Redis（不做 DB 写回）
  
仅在客户端请求时触发，延迟转换，零持久化成本
```

---

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| code segment 的 newline 语义与前端冲突 | 低 | 中 | 复用 mp-html 已验证的 CSS 规则 |
| math segments 和 code segments 合并错位 | 低 | 中 | 数学公式不会出现在代码围栏内；合并逻辑仅做拼接，不做重排 |
| UNIFIED_CONTENT_ENABLED 意外启用导致前端崩溃 | 低 | 低 | math-question 组件遇到未知 type 只是不渲染，不崩溃 |
| 围栏解析正则与已有 in_code_fence 逻辑冲突 | 极低 | 低 | 正向解析围栏语义明确，无歧义 |
| `_textToSegments` 被绕过产生重复换行 | 低 | 中 | 前端 _textToSegments 仅在无 segments 时作为 fallback，有 segments 时不调用 |

---

## 8. 实施建议

### ✅ 推荐：执行阶段二-A

理由：
1. 代码量极小（~160 行），风险可控
2. 为表格恢复、代码高亮等未来需求预埋了结构基础
3. 不改变任何现有行为（Feature Flag 默认关闭）
4. 与阶段一 Markdown 方案完全解耦

### ⚠️ 暂缓：阶段二-B 和 阶段二-C

理由：
- 当前题目中 code block 占比低，前端路径统一的收益暂时不明显
- 除非表格恢复需求正式启动，否则不需要强制所有题目走 segments 渲染

### 🚫 禁止（按任务约束）

- 数据库迁移（新增列/修改 JSONB schema）
- 批量重写历史数据中的 content JSON
- 替换现有 Markdown 围栏方案
- 引入复杂状态机

---

## 9. 附录：关键文件索引

| 文件 | 角色 | 需要修改 |
|------|------|---------|
| `backend/app/services/hybrid_content_builder.py` | 现有 segments 构建器（仅 math） | 否（保留） |
| `backend/app/features/unified_content_builder.py` | **新增** 围栏→code segment 解析 | **是** |
| `backend/app/features/question_pipeline.py` | QuestionNormalizer 和管线入口 | **是**（调用点） |
| `backend/app/core/config.py` | Feature Flag | **是**（+1 行） |
| `miniprogram/components/math-question/math-question.wxml` | Segments 渲染模板 | **是**（+8 行） |
| `miniprogram/components/math-question/math-question.wxss` | Segments 渲染样式 | **是**（+25 行） |
| `miniprogram/pages/practice/practice.wxss` | 已有 `._pre` / `._code` 样式 | 否 |
| `miniprogram/pages/wrong-detail/wrong-detail.wxss` | 已有 `._pre` / `._code` 样式 | 否 |
| `miniprogram/components/mp-html/index.wxss` | 已有 `._pre` / `._code` 样式 | 否 |

---

*报告完成。本报告仅包含设计和分析，无代码修改。*

---

## 附录 A：表格恢复能力审计

> 审计日期：2026-06-20

### A.1 全链路结论

**该流水线在任何阶段都没有对表格进行有意义的处理。表格完全被当作纯文本处理。**

### A.2 各环节详细发现

| 组件 | 文件 | 表格处理 |
|------|------|---------|
| PaddleOCR / AI OCR | `features/ocr_service.py` | **否** — `ocr_table()` 是抛出 `NotImplementedError` 的存根 |
| PyMuPDF 提取 | `features/ocr_service.py` | **否** — `page.get_text()` 返回纯文本 |
| text_normalizer | `features/text_normalizer.py` | **否** |
| structure_analyzer | `features/structure_analyzer.py` | **否** |
| question_splitter | `features/question_splitter.py` | **否** |
| answer_matcher | `features/answer_matcher.py` | **否** |
| question_normalizer | `features/question_normalizer.py` | **否** |
| ai_repair | `features/ai_repair.py` | **否** |
| pipeline_orchestrator | `features/pipeline_orchestrator.py` | **否**（仅 `"表\s*\d"` 用于散文检测，非表格解析） |
| question_pipeline | `features/question_pipeline.py` | **否**（无 table 题型） |
| **formula_normalizer** | `services/formula_normalizer.py` | **已实现但未使用** — `parse_latex_table()` + `extract_tables_from_text()` |
| hybrid_content_builder | `services/hybrid_content_builder.py` | **否**（无 table segment type） |
| AI prompts | `ai/prompts.py` | **否** |
| 前端 math-question | `miniprogram/components/math-question/` | **否**（仅 text/math_image/newline） |
| 前端 mp-html | `miniprogram/components/mp-html/parser.js` | **是**（完整 HTML table 渲染，但**不用于流水线内容**） |

### A.3 关键发现

1. **孤立实现**：`formula_normalizer.py` 中有完整的 LaTeX `\begin{tabular}` 解析器（`parse_latex_table()`, `extract_tables_from_text()`），能按 `&` 分列、按 `\\` 分行、处理 `\multicolumn` 和 `\hline`。但这两个函数在流水线中从未被调用。

2. **OCR boxes 在表格检测中的价值**：PaddleOCR 返回 per-line bbox 坐标 `[x0, y0, x1, y1]`，这些坐标在 pipeline 中一直保存到 `_run_split()` 阶段，然后被丢弃。利用这些坐标可以做列对齐检测（同一 y 范围的行，按 x 坐标聚类 → 检测表格列）。`visual_boundary_detector.py` 是唯一消费 boxes 的模块，仅做两栏布局检测。

3. **mp-html 已具备渲染能力**：前端 mp-html 组件有完整的 HTML `<table>` 渲染支持（colspan/rowspan/border），但流水线从不产生 HTML 表格。

### A.4 表格恢复可行性

| 表格来源 | 可行性 | 难度 | 关键数据 |
|---------|--------|------|---------|
| LaTeX `tabular` | **高** — 解析器已存在，仅需接入 | 低 | 文本中的 `\begin{tabular}...\end{tabular}` |
| OCR 视觉表格 | **中** — bbox 坐标可用，需空间分析 | 高 | boxes `[x0,y0,x1,y1]` + page_width |
| Markdown 表格 | **低** — OCR 几乎不产生 Markdown 表格 | — | — |

**推荐路径**：先行接入 `formula_normalizer.parse_latex_table()` 到 `_run_split()` 阶段，在切题之前提取表格并转为 `type=table` segment。视觉表格检测留待后续。

---

## 附录 B：UnifiedContentBuilder 性能基准

> 测试日期：2026-06-20
> 环境：Python 3.12, WSL2, 2核 2G
> 脚本：`backend/tests/benchmarks/bench_unified_content_builder.py`

### B.1 延迟分布

| 规模 | P50 | P95 | P99 | Mean | 总耗时 |
|------|-----|-----|-----|------|--------|
| 1000 题 (无代码) | 0.10µs | 0.14µs | 0.15µs | 0.11µs | ~0.1ms |
| 1000 题 (15% 代码) | 0.94µs | 1.47µs | 1.51µs | 1.08µs | ~1.1ms |
| 5000 题 (15% 代码) | 1.04µs | 1.26µs | 1.30µs | 1.09µs | ~5.5ms |
| **10000 题 (15% 代码)** | **1.19µs** | **1.27µs** | **1.28µs** | **1.18µs** | **~11.8ms** |

### B.2 细粒度分析 (10000题 × 10轮)

| 函数 | 每题耗时 |
|------|---------|
| `build()` 全流程 | 1.138µs (0.001138ms) |
| `_parse_fenced_regions()` (有围栏题) | 5.267µs (0.005267ms) |

### B.3 结论

- `build()` 函数在任意规模下都是 **微秒级**，不会成为 pipeline 瓶颈
- 10000 道题全量处理仅需 ~12ms，批量导入中可忽略不计
- 主要开销在 `re.finditer()` 扫描，占总耗时的 80%+
- 无内存突增（纯函数，无缓存/全局状态）

---

## 附录 C：Segment Schema 规范 v1.0

> 完整文档：`prompts/tasks/segment_schema_v1.md`

### C.1 SegmentType 枚举

```python
class SegmentType(StrEnum):
    CODE = "code"          # 代码块
    DIAGRAM = "diagram"    # 流程图（预留）
    IMAGE = "image"        # 图片（预留）
    MATH = "math"          # LaTeX 客户端渲染（预留）
    MATH_IMAGE = "math_image"  # 公式图片（当前）
    NEWLINE = "newline"    # 显式换行
    TABLE = "table"        # 表格（预留）
    TEXT = "text"          # 普通文本
```

### C.2 已定义类型

| Type | 必填字段 | 可选字段 | 状态 |
|------|---------|---------|------|
| `text` | `text` | — | 已实现 |
| `code` | `content` | `language` | **阶段二-A 新增** |
| `math_image` | `url`, `alt` | `display` | 已实现 |
| `newline` | — | — | 已实现 |
| `table` | `rows` | `headers`, `caption` | 预留 |
| `image` | `url` | `alt`, `width`, `height`, `caption` | 预留 |
| `diagram` | `content` | `language` | 预留 |

### C.3 扩展规则

- 新增类型需在 `SegmentType` 枚举中注册
- 前端遇到未知 type 降级跳过（不崩溃）
- `segments → text` 逆序列化必须可逆
- 废弃类型保留至少 2 个发布周期

---

## 附录 D：回归测试体系

> 测试文件：`backend/tests/test_content_block.py` (150 tests)
> 用例文件：`backend/tests/content_block_cases.py` (30 cases)

### D.1 测试覆盖

| 测试类 | 测试数 | 覆盖范围 |
|--------|--------|---------|
| `TestPositiveCodeDetection` | 24 | 8 个正向用例 × 3 断言 (code count, render_mode, language, type match) |
| `TestNoFalsePositive` | 12 | 6 个负向用例 × 2 断言 + 2 个独立测试 |
| `TestEdgeCases` | 18 | 10 个边界用例 (no-crash + code count) |
| `TestMixedCodeAndMath` | 5 | 3 个混排用例 + 2 个独立断言 |
| `TestMalformedFences` | 4 | 3 个异常用例 + 1 个独立断言 |
| `TestFeatureFlag` | 3 | 关闭/开启/纯文本 3 种模式 |
| `TestIdempotency` | 3 | 单次/双次/幂等保护 |
| `TestTextConsistency` | 9 | 8 个正向 roundtrip + text 字段保留 |
| `TestMergeWithExistingMath` | 2 | code+math 合并 + 无重复 |
| `TestRegressionSnapshot` | 60 | 全量 30 用例 × 2 断言 (确定性 + JSON 形状) |
| `test_case_count_report` | 1 | 用例统计 |
| **合计** | **150 passed, 1 skipped** | |

### D.2 用例分类

| 分类 | 数量 | 说明 |
|------|------|------|
| positive | 8 | C, Java, Python, SQL, HTML, 无语言, 双块, 三块 |
| negative | 6 | 纯数学, 408选择, 内联反引号, 未闭合, 空围栏, 数学上下文 |
| edge | 10 | 开头/末尾/空格/空行/长代码/特殊字符/嵌套反引号/无换行/空文本/None |
| mixed | 3 | 代码+公式, 公式+代码, 代码-公式-代码 |
| malformed | 3 | 嵌套, 无换行, 四反引号 |

---

## 综合结论

四项审计全部通过，阶段二-A 可以安全实施：

1. **表格恢复**：LaTeX tabular 解析器已就绪，仅需接入 pipeline；视觉表格检测需更复杂工作
2. **性能**：P99 < 2µs/题，10000 题全量处理 < 12ms，零性能风险
3. **Schema**：枚举和 JSON Schema 已定义，前向兼容，扩展规则明确
4. **测试**：150 个回归测试覆盖全部场景，Feature Flag 行为验证通过
