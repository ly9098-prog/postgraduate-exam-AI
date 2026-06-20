# Render Invariant — 小程序题干渲染架构规范

## Render Invariant 定义

> **同一份题干只能经过一个渲染引擎，产生一个渲染根节点。**

禁止任何形式的双重渲染路径（如 `TEXT + mp-html`、`RICH_TEXT + mp-html`、`SEGMENTS + mp-html`）。

此规范基于三次历史题干重复 Bug 确立（2026-06-02、2026-06-14、2026-06-20），三次 Bug 的共同特征：
- API 数据正常（题目题干仅存一份）
- 数据库内容正常
- 重复发生在渲染层

## RenderModel

`buildRenderModel(question, options)` 是题干渲染的**唯一入口**。页面层禁止自行拼装 `_stemText`、`_stemHtml`、`_richTextNodes`、`_segments`。

返回的 RenderModel 结构：

```js
{
  mode: 'RICH_TEXT' | 'LATEX' | 'SEGMENTS',  // 渲染模式
  richTextNodes: [...],  // RICH_TEXT 模式使用，传入 <rich-text nodes="{{...}}">
  html: '',              // LATEX 模式使用，传入 <mp-html content="{{...}}">
  segments: [],          // SEGMENTS 模式使用，传入 <math-question segments="{{...}}">
}
```

RenderModel 在 DEV 环境下通过 `Object.freeze()` 冻结，页面层修改将静默失败。

## 渲染模式决策树

```
buildRenderModel(question, options)
│
├─ enableMathImage && render_mode === 'segments'
│  └─ SEGMENTS → <math-question>
│
├─ 含 $$...$$ 或 \commands（\frac, \sqrt, \int 等）
│  └─ LATEX → <mp-html> + KaTeX 插件
│
└─ 其他（纯文本、多行文本、代码、简单 $...$ inline math）
   └─ RICH_TEXT → 原生 <rich-text>
```

**决策优先级**：SEGMENTS > LATEX > RICH_TEXT

**关键原则**：非 LaTeX 题干永久绕过 mp-html。纯文本、多行文本、代码题统一走原生 `<rich-text>`。

## 各模式适用范围

| 模式 | 适用 | WXML 组件 | 说明 |
|------|------|-----------|------|
| `SEGMENTS` | `render_mode: 'segments'` 且 `enableMathImage: true` | `<math-question>` | 预渲染公式图片模式，当前 `enableMathImage=false`，实际禁用 |
| `LATEX` | 含 `$$...$$` 或 `\frac`/`\sqrt`/`\int` 等 LaTeX 命令 | `<mp-html>` | 通过 KaTeX 插件渲染，仅用于复杂公式 |
| `RICH_TEXT` | **所有其他情况**（纯文本、多行文本、代码、简单 `$...$` inline math、HTML 标签） | 原生 `<rich-text>` | 程序化构建节点数组，不经过 mp-html 模板链 |

## WXML 模板规范

所有渲染题干的页面必须使用以下 3 分支结构：

```xml
<block wx:if="{{model.mode === 'SEGMENTS'}}">
  <math-question segments="{{model.segments}}" />
</block>
<rich-text wx:elif="{{model.mode === 'RICH_TEXT'}}" nodes="{{model.richTextNodes}}"></rich-text>
<mp-html wx:elif="{{model.mode === 'LATEX'}}" content="{{model.html}}" lazy-load></mp-html>
```

禁止添加第 4 个分支或 `<text>` 回退。所有非 LaTeX 题干统一走 `RICH_TEXT`。

## 页面接入清单

| 页面 | 接入状态 | WXML 分支数 |
|------|----------|-------------|
| `pages/practice` | Phase 1 完成 | 3 (SEGMENTS / RICH_TEXT / LATEX) |
| `pages/wrong-detail` | Phase 2 完成 | 3 (SEGMENTS / RICH_TEXT / LATEX) |
| `pages/review-today` | Phase 2 完成 | 3 (SEGMENTS / RICH_TEXT / LATEX) |
| `pages/wrong-book` | Phase 2 完成 | N/A（列表预览，用 `toPlainInlineMathText` 摘要） |

## 第三方渲染组件准入规则

新增渲染组件（如 markdown、table-render）接入时必须声明：

1. **输入格式**：组件消费什么字符串格式？
2. **适用范围**：哪些题型/科目使用该组件？
3. **回退路径**：组件渲染失败时的降级方案
4. **禁止作为默认全量渲染器**：RICH_TEXT 始终是通用回退。新组件必须有明确、狭窄的适用范围

新增 `RENDER_MODE` 时，必须在同一 commit 中同步修改：

| 必改项 | 文件 |
|--------|------|
| 新增模式常量 + 决策分支 | `utils/stem-render.js` |
| 新增 WXML 分支（所有渲染题干页面） | `pages/*/**.wxml` |
| 新增回归测试用例 | `tests/test-render-invariant.js` |
| 更新决策树与适用范围矩阵 | `docs/render-invariant.md` |

## RenderGuard

开发环境（`config.DEV = true`）下，`buildRenderModel()` 内部自动追踪每次渲染决策：

- 记录 `{page, questionId, stemHash, renderMode}`
- 同一 stemHash 在同一页面生命周期内出现不同 renderMode 时，输出 `[RENDER_INVARIANT_VIOLATION]` 并附带完整上下文
- 页面 `onUnload` 时调用 `resetRenderGuard()` 清理状态

## 历史问题案例

### 2026-06-02 — 简单 inline math 进入 mp-html 链路导致重复

- **触发条件**：OCR 导入题目的 `$...$` 简单公式进入 mp-html 富文本渲染链路
- **根因**：简单公式本可纯文本化，却进入 mp-html 模板链
- **修复**：简单 inline math 做 Unicode 纯文本转换（`$P_1$` → `P₁`），绕过 mp-html

### 2026-06-14 — 多行代码 + inline math 导致重复

- **触发条件**：多行代码题干含 `$P_1$`、`$z$` 简单公式进入 mp-html
- **根因**：多行题干 + 简单公式的组合仍触发 mp-html 渲染
- **修复**：多行题干中的简单 `$...$` 做保守纯文本化

### 2026-06-20 — mp-html 模板链导致非 LaTeX 题干重复

- **触发条件**：mp-html `node.js` 的 `childs` observer diff 算法产生增量更新（`nodes[0].children[N]`），微信小程序虚拟 DOM 在处理 `<template is="el">` 时未正确移除旧元素
- **根因**：mp-html 模板链与微信虚拟 DOM 协调不兼容
- **修复**：非 LaTeX 题干绕过 mp-html，使用原生 `<rich-text>` 直出；`node.js` 增加根节点全量替换守卫
- **测试隔离验证**：`<text>` 无重复 → 原生 `<rich-text>` 无重复 → mp-html 全链路出现重复 → 绕过 mp-html 后重复消失

## 回归测试

### 运行方式

```bash
cd miniprogram

# 单元测试（纯函数，无需微信环境）
node tests/test-render-invariant.js

# 历史回归数据集
node tests/render_regression/run.js

# LaTeX 符号处理（已有测试，确保不退化）
node tests/test-latex-symbols.js
```

### 测试覆盖

- 纯文本题干 → `RICH_TEXT`
- 代码题（多行、含反引号）→ `RICH_TEXT`
- 表格题（多行、含竖线）→ `RICH_TEXT`
- 简单 inline LaTeX（`$a < b$`）→ `RICH_TEXT`（Unicode 转换）
- 复杂 LaTeX（`$$`、`\frac`）→ `LATEX`
- OCR 导入题（`$$\frac{}{}$$`）→ `LATEX`
- 空题干 / null → `RICH_TEXT` 回退
- RenderModel 不可变性
- 同一输入 → 同一模式（一致性）
- 单一渲染根节点（每次只有一个输出字段有效）

### 历史回归数据集规范

`tests/render_regression/` 目录固定每次题干重复 Bug 的题目数据。新增任何重复渲染问题时，**必须先加入回归数据再修复**。

Fixture 格式（JSON）：

```json
{
  "_bug": "日期 — 问题描述",
  "_fix": "修复方式简述",
  "question": {
    "id": 唯一ID,
    "question_type": "题型",
    "content": { "text": "题干文本" },
    "options": { "A": "...", "B": "..." }
  },
  "expected": {
    "mode": "期望的渲染模式",
    "hasHtml": true/false,
    "hasRichTextNodes": true/false
  }
}
```

## 相关文件

| 文件 | 说明 |
|------|------|
| `miniprogram/utils/stem-render.js` | 渲染决策核心模块 |
| `miniprogram/tests/test-render-invariant.js` | 回归测试 |
| `miniprogram/tests/render_regression/` | 历史回归数据集 |
| `miniprogram/components/mp-html/` | 第三方富文本组件（仅用于 LaTeX 路径） |
| `miniprogram/components/math-question/` | 公式图片化组件（SEGMENTS 路径） |
| `docs/BUGS_HISTORY.md` | 完整 Bug 修复记录 |
