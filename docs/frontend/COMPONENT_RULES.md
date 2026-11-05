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
- 极简确认框可传 `hideIcon`、`hideAccent`、`hideEyebrow`；登录提示复用该模式，不得在页面中另写原生 `wx.showModal`。
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

---

## 小程序代码质量：包体与媒体预算

2026-10-04 在微信开发者工具 RC `2.02.2607271`、基础库 `3.6.6` 上验证：

- 扫描界面的「主包大小」项实际检查每个编译包，不仅检查主包。修复前超限的是
  `study` 分包（约 1597 KiB），而不是主包；修复包体与上传语法后约 1440 KiB，两项大小检查均通过。
- 「图片和音频资源」项按全包媒体文件合计检查 200 KiB，而非检查单文件大小。
  本次按现有 `packOptions.ignore` 统计的媒体从约 500 KiB 降至约 165 KiB。
- 仅对 `study/components/mp-html/latex/` 中六个已预构建的 `katex*.js` 文件设置
  `babelSetting.ignore`，避免增强编译将已压缩 vendor 二次展开。
  不忽略 `latex/index.js` 或其他业务文件，不关闭 ES6/增强编译或代码质量检查。
- 跳过 Babel 的 vendor 必须预先满足上传语法要求。2026-10-04 的上传错误
  `katex-core.js:1:16623 Unexpected token .` 对应 `i?.type`：现代 Node 与模拟器能运行，
  不代表上传校验能接受。三份 vendor 的 `katex-core.js`、`katex-part-64.js`、
  `katex-part-970.js` 已仅对可选链/空值合并做标准语法降级，保留空值判断、单次求值语义，
  没有对整个 vendor 做 ES5 重编译。升级 vendor 时必须同步三份文件并再次运行语法检查。
- `katex-part-64.js` 的数组单元格分配使用标准 JS `new Array(a.length)`；
  `study`、`exam` 与 `formulas` 三份 vendor 保持该行为一致。矩阵和 array 公式必须纳入回归，
  不能只验证简单公式就认定 vendor 可以直接运行。
- 图片保留 PNG/JPEG 格式、原路径与宽高比，按现有显示尺寸缩小并优化编码；
  PNG 保留透明通道。它们是有损体积优化，后续替换资源需做视觉检查。

回归入口：

```bash
cd miniprogram
npm ci  # 安装测试专用 Acorn；node_modules 不参与小程序打包
node tests/test-main-package-size.js
node tests/test-package-quality.js
node tests/test-katex-vendor-runtime.js
node tests/test-katex-upload-syntax.js
node tests/test-component-paths.js
```

大小脚本按实际 `packOptions.ignore` 排除文件，对主包/分包设置保守源码预算，
并将媒体源码合计预算限制为 190 KiB，为开发者工具的 200 KiB 阈值留余量。
该脚本不是编译器，不能用源码统计替代开发者工具的「重新扫描」；
本次另在模拟器实际 JS 上下文验证了 11 个公式的 HTML/DOM-tree 渲染。
`test-katex-upload-syntax.js` 使用 Acorn 的保守 ES2015 语法检查 exam/formulas 的 12 个 vendor JS，
并校验两份文件字节一致；`test-package-quality.js` 同时调用此语法检查。
Node 回归在独立进程测试 33 个公式案例，包含重音、上下标、矩阵、带分隔线数组和 aligned；
本次临时对比确认修复前后 HTML 完全一致。语法回归与质量扫描不能代替微信服务器实际上传，
本次未执行新的版本上传或发布。
Android/iOS 真机渲染仍未验证。

### 2026-10-27：study 运行时迁入主包（历史）

该次把 study 的六个预构建文件迁到主包 `vendor/katex/`；2026-11-01 已按微信工具“主包未使用JS”提示移除，study 恢复本地全量副本。以下文本是历史状态，不代表当前结构。

study、exam 的 `latex/index.js`、Parser、组件模板和样式保留各自实现。study 的 DOM-tree
转 rich-text 与 exam 的 HTML 解析存在语义差异，不能合并包装器或替换整套组件。
2026-11-01 当前规则：普通分包不得把主包 vendor 作为运行时依赖；如再次提取主包 vendor，必须保持至少一个主包直接消费者，并重新验证微信打包扫描。
这次曾把 study 源码降至 1,124,220 字节；2026-11-01 恢复本地副本后 study 为 1,485,461 字节，源码预算按当前结构调整为 1.45 MiB（容差到 1,484,800 字节）仍不足，实际测试输入显示需 1.48 MiB 量级，后续应以新消费链或真实微信验证驱动调整。

历史测试曾有主包 vendor 哈希与六转发入口检查；2026-11-01 改为 exam/formulas 2份副本语法/一致性检查，vendor runtime 覆盖 study/exam/formulas 3份副本，`test-katex-main-vendor.js` 已删除。
比较包括默认/natural 布局、复杂矩阵、无效 LaTeX 和中文；不要求 study 与 exam 节点相同。
质量与运行时回归已接入 reliability；加载顺序对照脚本保留，但其主包 vendor 专用边界测试已删除。

当前迁移仅有 Node 与源码体积证据；微信开发者工具重新编译、编译包扫描、模拟器、
Android/iOS 真机及服务器上传尚未验证，不能复用历史结果作为本次验收。

---

## 冷启动会话还原

冷启动默认入口还原规则见 `docs/frontend/LAUNCH_RESUME.md`：只在登录后替换默认首页跳转，
复用现有作答/草稿/番茄钟控制器；微信编译、真机及原生“回首页”行为仍待手工验收。

## 相关链接

- [[docs/frontend/UI_RULES.md|UI_RULES]] — 小程序 UI 规则
- [[docs/frontend/DESIGN_SYSTEM.md|DESIGN_SYSTEM]] — 设计系统
- [[docs/frontend/render-invariant.md|render-invariant]] — 渲染不变性
- [[docs/frontend/LAUNCH_RESUME.md|LAUNCH_RESUME]] — 冷启动会话还原
