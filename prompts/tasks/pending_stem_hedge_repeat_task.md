# 任务：建立刷题页渲染架构约束，防止题干重复显示问题再次出现

**状态**：Phase 1 完成，Phase 2 完成，待真机验证

## 背景

历史已发生三次不同形式的题干重复显示：

| 日期 | 触发条件 | 根因 |
|------|----------|------|
| 2026-06-02 | 简单 `$...$` inline math 进入 mp-html 链路 | 简单公式本可纯文本化，却进入 mp-html 模板链 |
| 2026-06-14 | 多行代码 + `$P_1$`/`$z$` inline math | 多行题干 + 简单公式仍触发 mp-html 渲染 |
| 2026-06-20 | 多行纯文本（无 LaTeX） | mp-html `node.js` diff 与 `<template>` 协调问题导致旧 `<rich-text>` 未移除 |

共同特点：
1. API 数据正常
2. 数据库内容正常
3. 题干仅存一份
4. 重复发生在渲染层

后续禁止再通过文本去重补丁解决此类问题。

## 目标

建立 **Render Invariant（渲染不变量）**：同一份题干只能经过一个渲染引擎。

## 实施记录

### Phase 1 ✅ 完成（2026-06-20）

**核心模块** — `miniprogram/utils/stem-render.js`

```js
buildRenderModel(question, options) → { mode, richTextNodes, html, segments }
```

- 三模式：`RICH_TEXT` / `LATEX` / `SEGMENTS`
- `Object.freeze()` 在 DEV 环境冻结输出
- RenderGuard 追踪 `{page, questionId, stemHash, renderMode}`，冲突时 `console.error`
- 所有文本处理函数从 practice.js 收敛到此处（~270 行 → 单一 require）
- 顶部注释含第三方组件准入规则

**回归测试**

| 测试套件 | 用例数 | 说明 |
|----------|--------|------|
| `tests/test-render-invariant.js` | 35 | 单元测试：6 种题干类型 + 不可变性 + 一致性 + 单渲染根 |
| `tests/render_regression/run.js` | 12 | 3 个历史 fixture（2026-06-02/14/20） |
| `tests/test-latex-symbols.js` | 115 | 已有测试，确认不退化 |

**practice 页面重构**

- `practice.js`：删除 ~20 个本地函数定义；`_showQuestion()` 中题干渲染替换为 `buildRenderModel(q, opts)` 单次调用；`onLoad`/`onUnload` 加入 RenderGuard 生命周期
- `practice.wxml`：4 分支 → 3 分支（按 `_renderModel.mode` 字符串判断），移除 `<text>` 回退

**架构文档** — `docs/render-invariant.md`
- Render Invariant 定义与决策树
- 各模式适用范围矩阵
- WXML 模板规范（3 分支）
- 第三方组件准入规则（输入格式、适用范围、回退路径、禁止默认全量渲染）
- 3 个历史案例详述
- 回归测试要求与 fixture 格式

### Phase 2 ✅ 完成（2026-06-20）

| 页面 | 文件 | 变更 |
|------|------|------|
| wrong-detail | `.js` + `.wxml` | 接入 `buildRenderModel()`，WXML 改为 3 分支（SEGMENTS / RICH_TEXT / LATEX） |
| review-today | `.js` + `.wxml` | 接入 `buildRenderModel()`，WXML 改为 3 分支（刷题视图 + 组结果视图两处） |
| wrong-book | `.js` | `_toCleanText()` 替换为 `toPlainInlineMathText`，移除 `formatInlineMathText` 依赖 |

## 验收标准

- [x] 统一 `buildRenderModel()` 决策函数
- [x] 三模式枚举（RICH_TEXT / LATEX / SEGMENTS），消除 TEXT 模式
- [x] DEV 环境 `Object.freeze()` 冻结 RenderModel
- [x] DEV 断言：同一题干满足多个渲染条件时告警
- [x] RenderGuard：追踪 `{page, questionId, stemHash, renderMode}`
- [x] 历史回归数据集（3 个 fixture）
- [x] 回归测试：6 种题干类型全部覆盖
- [x] 第三方组件准入规则文档化
- [x] `docs/render-invariant.md` 架构文档
- [x] practice 页面完成接入
- [x] wrong-detail 页面接入
- [x] review-today 页面接入
- [x] wrong-book 页面接入
- [ ] 真机/DevTools 验证

## 扩展规则

未来新增 RenderMode（TABLE、MARKDOWN、CODE_BLOCK 等）时，必须在同一 commit 中同步修改：

| 必改项 | 文件 |
|--------|------|
| 新增模式常量 + 决策分支 | `utils/stem-render.js` |
| 新增 WXML 分支（所有渲染题干页面） | `pages/*/**.wxml` |
| 新增回归测试用例 | `tests/test-render-invariant.js` |
| 新增历史 fixture（如为 Bug 驱动） | `tests/render_regression/*.json` |
| 更新决策树与适用范围矩阵 | `docs/render-invariant.md` |
