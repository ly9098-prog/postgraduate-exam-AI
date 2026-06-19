# ADR-001: Content Block Phase 2-A — Deferred

- **Status**: Deferred
- **Date**: 2026-06-20
- **Deciders**: AI audit + user confirmation
- **Supersedes**: `prompts/tasks/content_block_phase_2._task.md`

---

## Context

### 当前数据流

```
OCR → code_detector → text_normalizer → AI修复 → pipeline → hybrid_content_builder → DB → Frontend
```

前端有 **三条渲染路径**：

| 路径 | 触发条件 | 支持 code | 支持 math_image |
|------|----------|-----------|-----------------|
| mp-html | `_needsRichRender()` (含 ``` 围栏) | 是 (CSS 降级) | 否 |
| math-question | `render_mode === 'segments'` | 否 | 是 |
| text | fallback | 否 | 否 |

**问题**：含代码块 + 数学公式的题目只能选一条路径，另一条路径的内容退化渲染。

### 为什么最初考虑 Content Block Phase 2-A

目标：给 `math-question` 组件加上 `type=code` 渲染能力，使其成为**唯一的统一结构化渲染组件**，消除路径选择带来的内容退化。

设计：
1. 新建 `unified_content_builder.py`，从 `content.text` 解析代码围栏生成 code segments
2. 与现有 `hybrid_content_builder` 的 math_image segments 合并
3. math-question 组件新增 code 渲染分支（wxml + wxss）

---

## 已完成的前置工作（全部保留可复用）

| 资产 | 位置 | 内容 |
|------|------|------|
| 架构分析与设计报告 | `prompts/tasks/content_block_phase_2._task.md` | 完整数据流分析、Markdown 围栏方案评估、type=code 设计、实施路径 |
| 表格恢复能力审计 | 同上 Appendix A | OCR → Pipeline → DB 全链路表格结构追踪，定位 `formula_normalizer.parse_latex_table()` 为断点 |
| 性能基准 | `backend/tests/benchmarks/bench_unified_content_builder.py` | P50=1.19µs, P95=1.27µs, P99=1.28µs（10000 题） |
| Segment Schema 规范 | `prompts/tasks/segment_schema_v1.md` | 8 种 SegmentType 枚举、JSON Schema、扩展规则、废弃策略 |
| 回归测试套件 | `backend/tests/test_content_block.py` + `backend/tests/content_block_cases.py` | 30 用例 / 150 测试 / 5 类覆盖（正向、负向、边界、混排、异常围栏） |

---

## 阻断原因

### 风险 1：math_image 与 code segment 合并顺序丢失

`hybrid_content_builder._rebuild_text()` 将 math_image 转为 `$alt$` 写入 `content.text`。`unified_content_builder` 以此 text 为输入重新解析围栏时，`$alt$` 被当作普通文本切进 text segment。

合并策略 `_merge_with_existing` 采用简单 append——所有 math_image 移到 segments 末尾：

```
输入 segments: [text:"设函数 ", math_image:E=mc², text:"，代码:\n```c\n...\n```"]
↓ _rebuild_text  →  content.text = "设函数 $E=mc^2$，代码:\n```c\n...\n```"
↓ parse fences   →  [text:"设函数 $E=mc^2$，代码:", newline, code:c]
↓ merge          →  [text:"设函数 $E=mc^2$，代码:", newline, code:c, math_image:E=mc²]
                                                    ↑                      ↑
                                            原始 $latex$ 字面量渲染     公式图片移到末尾
```

**后果**：408 题目同时含公式和代码时，公式双重渲染（raw `$latex$` + 图片）且位置错乱。修复此问题需要放弃简单 append，改为基于原始文本偏移量的交织合并或直接在 `hybrid_content_builder` 内部做 code fence 解析——超出原估算 ~120 行的工程范围。

### 风险 2：当前收益不足以抵消复杂度增加

- 受益题目仅限 408 中同时含公式+代码的题目（估算 5-15%），数学/英语科目为零
- mp-html 降级路径对代码块的 CSS 渲染效果可接受
- 合并 Bug 的修复成本使实际工程量 > 设计估算，并增加回归风险

---

## Decision

**Deferred — 延后实施。**

不做以下工作：
- 新建 `unified_content_builder.py`
- 修改 `math-question` 组件（wxml + wxss）
- 添加 Feature Flag `UNIFIED_CONTENT_ENABLED`
- Pipeline 集成点

保留所有已完成的设计文档、审计报告、性能基准、Schema 规范和测试套件。

---

## Re-activation Criteria

满足以下**任意一个条件**时，重新评估并启动实施：

1. **表格恢复需求启动** — `formula_normalizer.parse_latex_table()` 接入 Pipeline，math-question 需要渲染 `type=table`
2. **代码高亮需求启动** — 前端代码块需要语法高亮（如 Prism.js / highlight.js 集成）
3. **代码搜索需求启动** — 需要按语言类型或代码内容搜索题目
4. **图片 Block 需求启动** — 题目内嵌图片需要结构化管理
5. **Mermaid / 流程图需求启动** — `type=diagram` 需要前端渲染

启动时直接复用以下资产：

| 复用项 | 说明 |
|--------|------|
| `prompts/tasks/content_block_phase_2._task.md` | 架构分析、数据流、设计决策 |
| `prompts/tasks/segment_schema_v1.md` | 8 种 SegmentType + JSON Schema + 扩展规则 |
| `backend/tests/content_block_cases.py` | 30 用例定义 |
| `backend/tests/test_content_block.py` | 150 条回归测试 |
| `backend/tests/benchmarks/bench_unified_content_builder.py` | 性能基准 |

## Consequences

- **Positive**: 避免在窄受益场景下引入合并复杂度；保持 math-question 组件简洁；设计资产全部保留不丢失
- **Negative**: 混合 code+math 题目的渲染退化问题未解决（mp-html 路径下公式显示为 `$latex$` 原文）
- **Neutral**: Segment Schema 规范已建立，未来新增 type 无需重新设计框架
