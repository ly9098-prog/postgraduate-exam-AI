# 设计系统 (Design System)

> 2240AI 设计令牌，从 `UI_RULES.md` 中提取，方便前端开发快速查阅。

---

## Color Tokens

| Token | Value | 用途 |
|-------|-------|------|
| `--color-primary` | `#5B7B9A` | 主色：按钮、链接、激活态 |
| `--color-primary-dark` | `#357ABD` | 主色深：渐变、按压态 |
| `--color-primary-light` | `#EDF1F5` | 主色浅：背景、标签 |
| `--color-success` | `#6B9B6B` | 正确、已掌握、通过 |
| `--color-success-light` | `#EFF5EF` | 正确态背景 |
| `--color-warning` | `#C49A6B` | 注意、待复习 |
| `--color-warning-light` | `#F5F1EB` | 注意态背景 |
| `--color-danger` | `#C47A7A` | 错误、有风险 |
| `--color-danger-light` | `#F5EFEF` | 错误态背景 |
| `--color-wechat` | `#07C160` | 微信品牌绿 |
| `--color-text-primary` | `#2D3E50` | 主文字 |
| `--color-text-secondary` | `#6B7B8D` | 次要文字 |
| `--color-text-hint` | `#9AABBA` | 辅助文字 |
| `--color-text-placeholder` | `#BCC8D4` | 占位文字 |
| `--color-border` | `#E8E5E0` | 分割线、边框 |
| `--color-bg` | `#F7F5F0` | 页面背景（暖白米色） |
| `--color-bg-card` | `#FFFFFF` | 卡片背景 |
| `--color-bg-input` | `#F3F2EF` | 输入框背景 |

---

## Spacing (8pt base)

| Token | Value | 场景 |
|-------|-------|------|
| `--space-xs` | `8rpx` | 极小间距 |
| `--space-sm` | `12rpx` | 小间距 |
| `--space-md` | `16rpx` | 内边距 |
| `--space-lg` | `20rpx` | 区块间距 |
| `--space-xl` | `24rpx` | 卡内边距 |
| `--space-2xl` | `30rpx` | 卡边距 |
| `--space-3xl` | `40rpx` | 大区块间距 |
| `--space-4xl` | `60rpx` | 页面顶部留白 |

---

## Border Radius

| Token | Value | 场景 |
|-------|-------|------|
| `--radius-sm` | `8rpx` | 小标签 |
| `--radius-md` | `12rpx` | 按钮 |
| `--radius-lg` | `20rpx` | 卡片 |
| `--radius-xl` | `28rpx` | 弹窗 |
| `--radius-full` | `50%` | 圆形 |

---

## Typography

| Token | Size | Weight | 场景 |
|-------|------|--------|------|
| `--text-h1` | `36rpx` | 700 | 页面标题 |
| `--text-h2` | `32rpx` | 600 | 区块标题 |
| `--text-body` | `28rpx` | 400 | 正文 |
| `--text-caption` | `24rpx` | 400 | 辅助信息 |
| `--text-small` | `22rpx` | 400 | 极简标注 |
| `--text-stat` | `48rpx` | 700 | 统计数字 |

---

## Shadow

| Token | Value | 场景 |
|-------|-------|------|
| `--shadow-card` | `0 2rpx 12rpx rgba(0,0,0,0.06)` | 卡片阴影 |
| `--shadow-card-hover` | `0 4rpx 16rpx rgba(0,0,0,0.08)` | 卡片按压态 |

---

## 主题变体（premium-review）

学习流程页（review-today、wrong-detail、practice-result、`quiz-runner theme="premium-review"`）使用深墨绿 + 荧光绿主题，独立于上方基础 token：

| 语义 | 色值 | 用途 |
|------|------|------|
| 深墨绿 | `#0C2A1F` / `#123A2B` / `#0F2D22` | 顶部深色区、导航、主操作按钮 |
| 荧光绿 | `#B8FF13` / `#A9D800` / `#B7E82A` | 强调色、进度点、箭头、正确标记 |
| 暖米背景 | `#F4F4EE` / `#F7F7F2` / `#F4F2EC` | 页面背景 |

关键布局事实：

- review-today 概览：记忆轨迹弧线装饰（`trail-arc`）+ 独立操作 dock（主按钮不放入带 transform 动画的容器，避免 iOS/微信 WebView 对 `position: fixed` 按动画容器定位）+ `page-meta` 锁定 overview 阶段 100vh
- practice-result：深绿 hero（conic-gradient 正确率环 + 荧光绿进度条）、成长卡 `level-orb`
- wrong-detail：深色导航 + 荧光绿当前题进度点、底部主操作胶囊


## 刷题主题变体（practice-mint）

`subpackages/study/practice` 的练习设置/结果、今日复习与 study 完整
`quiz-runner mode="practice"/"review"/"exam"` 按“清新简约 · 专注刷题”薄荷方案实现。
紧凑错题详情以及考试列表/结果页保持独立布局；exam 答题组件与 study 同步，但依赖留在各自分包。共享答题样式集中在组件内的
`practice-theme.wxss`，由 `quiz-runner.wxss` 导入，使用 `runner-reference` 作用域。

| 语义 | 色值 | 用途 |
|------|------|------|
| 薄荷绿 | `#7ED8B5` | 进度、选项状态、强调 |
| 浅薄荷绿 | `#EAF9F4` | 次操作、选中项、辅助背景 |
| 白色 | `#FFFFFF` | 独立题卡、计时器 |
| 深绿 | `#3A6F5B` | 文字、主操作；按钮由薄荷深绿渐变过渡 |

已实现的布局与行为：

- 顶部保留返回和答题卡入口，移除刷题模式的英文重复题号；导航行通过
  `navigationBarHeight`（默认 44px）接收页面计算的微信胶囊导航高度。
- 科目标题下方将题号、总题量和带时钟图标的计时器同排，保留分段进度。
- 题卡按内容自然高度排版，不再通过 `min-height: 100%` 填满屏幕；翻题/交卷按钮
  固定于页面底部（含安全区），不属于题目滚动区；题目滚动区预留按钮高度，长题干、代码、图片末行不会被遮挡。
- 切题底板保持完全不透明且不移动；仅题卡内部内容以 100ms 轻淡至 0.88、沿翻题方向移出 12rpx；父页面更新题目时将本地 `_displayQuestion` 快照、选项、必要的滚动复位与入场类一次提交，以 220ms、36rpx 定向滑入并恢复不透明。移除全透明准备帧与 `wx.nextTick` 二次提交，入场不叠加 opacity transition。
  动画结束事件负责解锁，300ms 定时器仅作缺失事件的兜底；父页面未更新时超时恢复显示。动画期间锁定重复翻题与选项点击。 底部上一题/下一题/交卷按钮保持固定视觉壳，不绑定瞬时 `_animating` class 或 opacity，避免按钮在切题时闪烁。
  顶部始终完整显示，已删除自动折叠状态、开关属性、展开方法、折叠模板与对应样式；已在顶部时不重复复位滚动；题头、计时器与底部导航不参与位移动画。紧凑复习与自行处理动画的父页面保持原流程。
  滚动只记录题目区位置，不修改顶部高度；答题卡跳题、手势翻题、选项与多空选择、
  末题交卷、提交禁用和加载状态使用既有组件事件，不改答题与提交协议。
- 设置选中项采用浅薄荷底、深绿文字；箭头以相对图标框的百分比定位作光学居中，
  科目展开向下，收起向上。
- 保持题干五种渲染模式互斥，不另建题干渲染路径；模板只读取组件本地已提交的 `_displayQuestion`，防止父属性先刷新题干、随后才启动动画。
- CODE / MIXED 渲染块按题目 ID 重建，避免沿用上一题的代码横向滚动偏移。切题时题干与选项一起移动，底板、题头、计时器和固定操作条不参与。
- study 与 exam 的 runner JS/WXML/WXSS/主题样式保持一致；exam 本地注册 mp-html / math-question，并拥有本地 code-block 模板、样式、行分割工具与同步的 stem-render 渲染契约，不跨分包引用组件。exam 普通题干与 MIXED 文本块输出真实富文本节点，修复旧 plainText-only 契约造成的空白题干；结构化题干的文字与附加代码段不会被误判为过时片段。
- exam 保留倒计时、只读到时保护、标记、交卷与草稿恢复业务；导航行通过页面计算的 `navBarHeight` 留出微信胶囊空间，计时器辅助标签区分“剩余时间”与“已用时”。标记题用暖色虚线边框，当前题边框优先。
- 答题卡入口使用联网取得的 Lucide `notebook-tabs` SVG，路径保持官方源几何，仅固定薄荷描边色；来源及许可证见 `miniprogram/assets/icons/practice/README.md` 和 `LUCIDE-LICENSE.txt`。
- 底部上一题/下一题（末题为交卷）共用一个稳定的主操作节点，由 `onPrimaryNavigation` 分派下一题或交卷；切题锁定只在 JS 方法层生效，不切换按钮的视觉禁用态，避免固定操作条闪烁。

- 最近科目采用 96rpx 高的单行横向滚动胶囊：深绿选中态、48rpx 科目图标与小箭头；移除重复状态文案、呼吸光点、装饰背景和阴影。继续使用现有最近科目缓存与选择逻辑，长科目名截断显示，辅助标签保留完整名称及选中状态。
- 退出练习提示采用薄荷主题的极简文字与双按钮布局，无警告图标或红色退出按钮；确认后回到当前 `practice` 页面设置界面，保留科目选择。
  提交进行中、提交已接受和待确认快照仍走既有保护分支，不因视觉调整丢弃待确认交卷记录。
- 错题本和练习结果的无错题状态共用 `study/components/wrong-book-empty` 插画组件；结果页显式使用 `variant="compact"`，插画宽 224rpx、标题 30rpx、说明 22rpx；错题本保持原默认尺寸。结果页面保留全对、跳过或部分作答对应文案。
- 首页底部 TODAY’S NOTE 使用浅薄荷描边、18rpx 标签和 23rpx 正文，收紧为 22/26/24rpx 内边距；继续绑定真实 `dailyBoostText`，不写死参考图中的题量。
- 切题动画与最近科目按压反馈支持 `prefers-reduced-motion: reduce`，关闭视觉运动；减少动态效果下仍保留切题状态与输入保护。

验证入口：`cd miniprogram && node tests/test-practice-reference-ui.js`。
新增行为回归：`node tests/test-study-ui-refinements.js`，检查淡出/数据更新/滑入时序、重复操作锁、异常恢复与退出保护分支；同样支持传入 WXML 编译产物，验证极简确认框、最近科目、共享空状态与首页便签的真实模板分支。同步回归入口：`node tests/test-quiz-runner-sync.js`，可传入 WXML 编译产物，检查两套组件一致性、原子渲染、长题滚动复位、动画期间作答/标记/交卷保护、五种渲染模式与本地分包导入。
该脚本检查布局约束、选中态、箭头方向与组件导航/提交/折叠行为；可选地传入
微信 WXML 编译器的 JS 产物路径，额外验证实际模板的首题、末题及非练习模式。
2026-10-07 使用本机微信原生 WXML/WXSS 编译器验证上述页面与组件（含模板和样式导入），编译及模板分支测试通过；源码体积和打包质量脚本通过。
单文件编译不等同于真机验收。
2026-10-07 已打开微信开发者工具，并将本轮 10 个修改文件定向同步到 Windows 项目镜像（未做全量同步）。
使用临时合成数据、运行时请求 mock 验证首页 NOTE、最近科目、结果错题复盘空状态，以及完整 runner 的下一题、上一题、答题卡跳题与重复点击锁定；截图确认题头和底部导航保持稳定。
模拟器记录的三个切题序列约 0.3s 完成并解锁，未出现重复点击多跳题；此为状态时序取证，不是帧率或真机流畅度测试。过滤 console 中的 SyntaxError / TypeError / ReferenceError 与动画事件错误，无命中。
验证后恢复请求 API，并重新进入练习设置页清除临时页面状态；未交卷、未写入学习记录。真机动画与系统减少动态效果设置仍需验证。
同日追加切题闪烁修复：去掉整张题卡淡至透明与隐藏准备帧，将运动隔离到 `runner-question-motion`；动画结束监听绑定在运动层自身。模拟器对下一题、上一题与跳题采样，题卡底板 opacity 始终为 1、transform 为 none，内容 opacity 最低 0.92；重复点击没有额外跳题，最终输入已解锁。此为运行时样式采样，不是逐帧录像或真机帧率验证。

练习模式图标使用 Lucide 原始 `shuffle` / `list-ordered` / `target`，计时器使用 `clock`；
本地 SVG 仅设置薄荷主题描边色，来源与许可证保留在 `miniprogram/assets/icons/practice/`。
顶部摘要按参考图方案二使用图标圆底、摘要文字、浅薄荷“调整”胶囊。
科目选择弹层、练习确认框、结果复盘弹层、今日复习题量/决策弹层使用同一色调；
正确/错误/警告保留语义色，不把错误状态强行变绿。
今日复习通过 `reviewNavigationHeight` 设置可用视口高度，使用共享 runner 的内部滚动布局。


2026-10-07 runner 同步收尾：study/exam 的普通题、CODE 长题、答题卡与新图标已经在模拟器中检查；两套切题样式采样均检测到实际位移，底板 opacity 始终为 1、内容最低 0.88，下一题重复点击/上一题/跳题后正常解锁。视觉检查发现 exam 旧渲染契约的空白普通题干，已同步 stem-render 并再次确认题干可见；标记按钮显式覆盖旧荧光边框，标记答题卡移除旧内描边叠加。
同步回归、13 项独立 Node 检查（含渲染 fixture）、study/exam 及相邻页面的原生 WXML/WXSS 编译和编译模板回归通过；Windows 镜像仅定向同步本轮相关源码，未全量 rsync。测试使用合成题目，exam 运行时网络同步与草稿持久化临时禁用，未交卷或写入真实学习记录。
内部 scroll-view 的自动化 scrollTo 未能命中嵌套元素；滚动事件不改题头高度与新题原子复位由 Node 回归覆盖，实际手势滚动、真机主观流畅度与系统减少动态效果设置仍待验证。

### 今日复习提交约束（2026-10-08）

- 今日复习复用 `submit-confirm` 的 `theme="mint"` 与 `layout: 'minimal'`：白色卡片、深绿主按钮、浅薄荷次按钮，不显示顶部装饰条、圆形图标、英文标签或按钮箭头。
- 保留现有分组复习流程，每次提交要求当前复习组的所有题目完成作答，多空题每一空均需填写；不再提供“仅提交已答”或“按不会处理”。标记掌握后移出当前组的题目沿用既有处理。
- 未完成提示只有“继续作答”按钮，点击后定位当前组第一道未完成题；点击遮罩关闭提示也不会提交。全部完成后才显示“继续检查 / 提交复习”。
- 提示期间拦截重复提交；确认后再次校验组与答案，避免异步弹窗期间状态变化导致不完整提交。新增 `tests/test-review-submit-completion.js` 覆盖上述行为与多空完成判断。本轮模拟器/真机视觉验证未执行。
