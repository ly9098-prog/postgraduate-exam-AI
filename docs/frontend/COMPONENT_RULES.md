# 组件规则

> 2240AI 前端组件命名、使用规范。基于小程序原生框架。

---

## 命名约定

- 页面路由：小写 + 连字符（`wrong-book`、`practice-result`）
- WXML class：小写 + 连字符（`action-card`、`subject-row`）
- JS 变量：小驼峰（`wrongStats`、`practiceCount`）
- 事件处理：`handleXxx` 或 `onXxx` 命名

---

## 组件类

### Card (`.card`)

- `background: #FFFFFF`
- `border-radius: 20rpx`
- `padding: 30rpx`
- `margin: 20rpx 30rpx`
- `box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06)`

### Button

| 类名 | 用途 |
|------|------|
| `.btn-primary` | 主色实心，主要操作 |
| `.btn-secondary` | 主色浅底，次要操作 |
| `.btn-text` | 纯文字 |
| `.btn-danger` | 红色实心，危险操作 |
| `.btn-block` | 宽度 100%，全宽 |

所有按钮高度统一 88rpx，圆角 12rpx。

### Tag

| 类名 | 用途 |
|------|------|
| `.tag` | 默认标签 |
| `.tag-success` | 正确/已掌握 |
| `.tag-warning` | 待复习 |
| `.tag-danger` | 错误 |
| `.tag-primary` | 主色标签 |

内联块，padding 6rpx 16rpx，圆角 6rpx，字号 22rpx。

---

## 布局约定

- 页面背景：`#F7F5F0`
- 导航栏背景：`#5B7B9A`，文字白色
- 内容最大宽度：750rpx
- 卡片间距：垂直 12-20rpx，水平 30rpx
- 列表项高度：88rpx（含 padding）
- 底部操作栏：padding 20rpx 30rpx 40rpx
- 页面使用 Flexbox 布局

---

## 交互规则

- **练习模式**：随机抽题 → 作答 → 提交判分 → 显示结果 → 自动记错题本
- **复习模式**：今日待复习题 → 作答 → 质量评分 → 更新 SM-2
- **导入流程**：上传 → 解析 → 暂存区 → 逐题审核 / 批量审批 → 正式入库
- **AI 分析**：用户主动触发，结果缓存，不自动调用
- **加载态**：下拉刷新 + 上拉加载更多
- **空态**：友好提示，如"还没有错题，继续加油！"
- **错误态**：显示重试按钮

---

## 全局样式引用

```wxss
/* 页面 wxss 顶部 */
@import '../../styles/tokens.wxss';
/* 只写页面独有样式 */
```

全局组件样式在 `styles/components.wxss` 中定义。

---

## 跨分包共享组件注册

主包共享组件 `app-dialog` 和 `premium-nav` 在 `miniprogram/app.json` 的
`usingComponents` 中全局注册，分别指向 `/components/app-dialog/index` 和
`/components/premium-nav/premium-nav`；页面已有的局部声明保留。

- 当前配置使用 `lazyCodeLoading: requiredComponents` 和 `ignoreDevUnusedFiles: true`；
  全局注册与组件路径由 `cd miniprogram && node tests/test-component-paths.js` 检查。
- `app-dialog` 使用显式闭合标签（`<app-dialog ...></app-dialog>`），不使用自闭合写法。
- 修改共享组件注册后，仍需在微信开发者工具编译并验证分包页面；
  Node 检查不代表开发者工具打包、模拟器或真机已验证。

---

## 组件契约：quiz-runner（统一答题 UI）

`miniprogram/subpackages/study/components/quiz-runner/` 是 practice、review-today、wrong-detail 共用的统一答题组件。

- **属性**：`theme`（`default` / `premium-review`）、`mode`（`practice` / `review` / `wrong-detail`）、`flowLayout`（页面内嵌不用自身滚动）、`compactReviewMode`（隐藏深色 hero）、`externalSwitchAnimation`（外层统一动画切题时组件只上报事件不自己加动画类）、`readonly`（只读复盘高亮正确/错误）、`heroCollapseEnabled`（滚动折叠 header 开关）
- **状态分离**：可变答题状态通过 `answerState` 属性传入，与不可变的 `currentQuestion`/渲染负载分离；兼容旧调用方在 `currentQuestion._optionList/_blankOptionGroups` 上提供作用域字段
- **渲染**：复用题干渲染不变性——`SEGMENTS / RICH_TEXT / CODE / LATEX / MIXED` 分支见 `render-invariant.md`；`CODE` 走 `scroll-view` + `<text>`（零 HTML），`MIXED` 内部按块独立渲染
- **事件**：`selectoption` / `selectblankoption` / `prev` / `next` / `jump` / `submit` / `master` / `exit` / `toggleanswercard`
- **滑动切题**：`onTouchStart/End` 识别横向滑动（`absDx >= 44 && absDx > absDy*1.1`），`data-swipe-block` 标记的图片/选项可单独拦截滑动，防止阅读代码/公式时误切题

### 页面动画约定（externalSwitchAnimation）

wrong-detail 使用此模式：题目区 + AI 学习建议放在同一个父容器，由页面统一控制一次淡出/淡入（`QUESTION_SWITCH_OUT_MS=150` / `QUESTION_SWITCH_IN_MS=170`），quiz-runner 内部不再计时，避免两个区域各自动画不同步。

---

## 组件契约：formula-card（公式卡）

`subpackages/formulas/components/formula-card/` 渲染公式卡内容（title / 公式块 / 条件 / 符号表 / 错误提示 / 示例）。

- 所有混合文字 + LaTeX 内容经 `formula-content.normalizeMixedContent` → HTML → `mp-html-parser` + KaTeX 插件渲染，链路见 `render-invariant.md`
- **行内公式横向滚动**：`shouldScrollInlineFormula`——仅当行内公式真正超长（估算可视宽度 > 34 字符）或为 array/matrix 等块环境时才加 `overflow-x:auto` 滚动容器；短公式保持 `overflow:visible`，避免 Android/微信下原生滚动条像灰色下划线出现在短公式下方
- 公式块复杂度阈值（`prepareFormulaBlocks`）：`complexity > 200` 才 `isScrollable`；`> 185` `is-dense`、`> 120` `is-compact`
