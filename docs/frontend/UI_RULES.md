# UI Rules

> 2240AI 前端设计规范。包含 Design System Token、组件库、页面结构、交互规则。
> 2026-11-04：Token 表按 `miniprogram/styles/tokens.wxss` 当前实现修订；现行 Token 以工具类形式提供，不再使用 CSS 自定义属性。

---

## 设计原则

- **简洁**：去除冗余装饰，信息层级清晰
- **稳定**：统一的 token 体系，避免风格漂移
- **高效**：减少重复样式定义，优先使用全局 token
- **学习感**：蓝色主调传递专注与信任，绿色/橙色/红色对应状态
- **刷题参考主题**：练习设置/结果、今日复习与 study 完整 `quiz-runner mode="practice"/"review"/"exam"` 使用薄荷绿 + 白色主题，题卡自然高度、题号与计时器同排、导航固定底部，切题先淡出旧题、再随新题数据滑入，详细实现见 DESIGN_SYSTEM.md「刷题主题变体」。
- **主题化**：错题详情与考试列表/结果等独立流程保留既有 premium 主题；练习/结果/今日复习/考试答题使用薄荷绿主题，与基础蓝调并存（色值见 DESIGN_SYSTEM.md「主题变体」）

---

## 1. Color Tokens

现行颜色 Token 定义在 `miniprogram/styles/tokens.wxss`，以工具类提供。页面通过引入该文件后直接使用 `.color-*` / `.bg-*` 等类。

| 类 | 值 | 用途 |
|---|---|---|
| `.color-primary` / `.bg-primary` | `#4F7FFF` | 主色：文字、按钮、激活态 |
| `.bg-primary-gradient` | `135deg, #4F7FFF → #6EC1FF` | 主色渐变 |
| `.bg-primary-light` | `#EEF4FF` | 主色浅背景 |
| `.color-success` / `.bg-success` | `#22C55E` | 成功、已掌握、通过 |
| `.bg-success-light` | `#ECFDF3` | 成功浅背景 |
| `.color-warning` / `.bg-warning` | `#F59E0B` | 注意、待复习 |
| `.bg-warning-light` | `#FFF7E8` | 警告浅背景 |
| `.color-danger` / `.bg-danger` | `#EF4444` | 错误、有风险 |
| `.bg-danger-light` | `#FEF2F2` | 危险浅背景 |
| `.bg-wechat` | `#07C160` | 微信品牌绿 |
| `.color-text-primary` | `#18233A` | 主文字 |
| `.color-text-secondary` | `#617089` | 次要文字 |
| `.color-text-hint` | `#8EA0BA` | 辅助文字 |
| `.color-text-placeholder` | `#B7C4D8` | 占位文字 |
| `.color-border` | `#E2EAF7` | 分割线、边框 |
| `.bg-page` | `#F8FAFF → #EEF5FF` 渐变 | 页面背景 |
| `.bg-card` / `.bg-input` / `.bg-surface` / `.bg-glass` | `#FFFFFF` / `#F3F7FF` / `#F6F9FF` / `rgba(255,255,255,.72)` | 卡片、输入、表面与毛玻璃背景 |

### 语义对照

| 场景 | 色值 | Token |
|------|------|-------|
| 导航栏/主色 | `#4F7FFF` | primary |
| 答案正确 | `#22C55E` | success |
| 待复习 | `#F59E0B` | warning |
| 答错 | `#EF4444` | danger |

---

## 2. Spacing Scale (8pt base)

间距同样以工具类提供，`.p-*` 控制四向 padding，`.m*-*` 控制方向性 margin，`.gap-*` 控制 flex/grid 间距。

| 后缀 | 值 | 场景 |
|---|---|---|
| `xs` | `8rpx` | 极小间距、标签内边距 |
| `sm` | `12rpx` | 元素间小间距、标签间距 |
| `md` | `16rpx` | 内边距、选项间距 |
| `lg` | `20rpx` | 区块间距、卡内边距 |
| `xl` | `24rpx` | 卡内边距、选项内边距 |
| `2xl` | `30rpx` | 卡边距、区块标题底部 |
| `3xl` | `40rpx` | 大区块间距 |
| `4xl` | `60rpx` | 页面顶部、底部留白 |

---

## 3. Border Radius

| 类 | 值 | 场景 |
|---|---|---|
| `.radius-sm` | `12rpx` | 小标签、按钮 |
| `.radius-md` | `16rpx` | 输入框、中型卡片 |
| `.radius-lg` | `24rpx` | 卡片、大区块 |
| `.radius-xl` | `32rpx` | 弹窗、首屏卡片 |
| `.radius-2xl` | `40rpx` | 超大圆角面板 |
| `.radius-full` | `999rpx` | 胶囊、圆形元素 |

---

## 4. Typography

| 类 | Size | Weight | 场景 |
|---|---|---|---|
| `.text-h1` | `36rpx` | 800 | 页面标题 |
| `.text-h2` | `32rpx` | 700 | 区块标题 |
| `.text-body` | `28rpx` | 400 | 正文、选项、列表项 |
| `.text-caption` | `24rpx` | 400 | 辅助信息、标签文字 |
| `.text-small` | `22rpx` | 400 | 极简标注、徽标文字 |
| `.text-stat` | `48rpx` | 800 | 统计数字（`tabular-nums`） |
| `.text-stat-sm` | `40rpx` | 800 | 小号统计数字（`tabular-nums`） |

---

## 5. Shadow

| 类 | 值 | 场景 |
|---|---|---|
| `.shadow-card` | `0 8rpx 24rpx rgba(42,84,160,.08)` | 卡片阴影 |
| `.shadow-card-hover` | `0 14rpx 36rpx rgba(42,84,160,.12)` | 卡片按压/悬停增强态 |

---

## 6. Component Classes

### Card (`.card`)

- `bg: #FFFFFF`, `border-radius: 24rpx`, `padding: 30rpx`, `margin: 16rpx 24rpx`
- `box-shadow: 0 8rpx 24rpx rgba(42,84,160,.08)`，带 `1rpx solid rgba(226,234,247,.92)` 边框

### Button

| 类名 | 样式 | 用途 |
|------|------|------|
| `.btn-primary` | 主色渐变（`#4F7FFF → #6EC1FF`）实心 | 主要操作 |
| `.btn-secondary` | 主色浅底（`#EEF4FF`） | 次要操作 |
| `.btn-text` | 纯文字 | 文字按钮 |
| `.btn-danger` | 红色实心 | 危险操作 |
| `.btn-block` | 宽度 100% | 全宽按钮 |

所有按钮最小高度 88rpx，圆角 999rpx。

### Tag

| 类名 | 用途 |
|------|------|
| `.tag` | 默认标签 |
| `.tag-success` | 正确/已掌握 |
| `.tag-warning` | 待复习 |
| `.tag-danger` | 错误 |
| `.tag-primary` | 主色标签 |

内联块，padding 6rpx 16rpx，圆角 999rpx，字号 22rpx。

### List Item (`.list-item`)

左右布局，padding 28rpx 30rpx，border-bottom 分割线，支持箭头指示可点击。

### Stat Number (`.text-stat` / `.text-stat-sm`)

字号 48rpx / 40rpx，字重 800，主色，启用 `tabular-nums`。

---

## 7. 布局约定

- 页面背景使用 `.bg-page`：`#F8FAFF → #EEF5FF` 渐变；需要纯色滚动底色时同步设置页面级 `background-color`
- 主色导航/主操作使用 `#4F7FFF` 系；具体导航栏背景以页面 JSON 为准
- 内容最大宽度：750rpx
- 卡片间距：垂直 12-16rpx，水平 24rpx
- 标题与内容间距：24rpx
- 列表项高度：88rpx（含 padding）
- 底部操作栏：padding 20rpx 30rpx 40rpx
- 页面使用 Flexbox 布局

---

## 8. 使用方式

所有页面通过 `@import` 引入全局 token：

```wxss
/* 页面 wxss 顶部 */
@import '../../styles/tokens.wxss';

/* 只需写页面独有的样式 */
.page-specific-class { ... }
```

全局组件样式在 `styles/components.wxss` 中定义。

---

## 9. 页面结构

> 页面已迁入分包。主包仅保留登录/协议/首页/看板/番茄钟；学习类页面在 `subpackages/study` 下。

| 页面 | 路由 | 说明 |
|------|------|------|
| 登录 | pages/login/login | 微信授权登录 |
| 协议 | pages/agreement/{user,privacy,ai} | 用户/隐私/AI 协议 |
| 首页 | pages/home/home | 学习概览 + 快捷入口 |
| 数据看板 | pages/dashboard/dashboard | 学习统计与分析 |
| 番茄钟 | pages/pomodoro/pomodoro | 专注计时 |
| 练习 | subpackages/study/practice/practice | 刷题页（选择题/填空题） |
| 练习结果 | subpackages/study/practice-result/index | 三 Tab：结果概览 / 错题分析 / 成长记录 |
| 错题本 | subpackages/study/wrong-book/wrong-book | 错题列表 |
| 错题详情 | subpackages/study/wrong-detail/wrong-detail | 单题详情 + AI 学习建议 |
| 今日复习 | subpackages/study/review-today/review-today | 分组复习 + 组结果 |
| 公式库 / 阅读器 | subpackages/formulas/{library,reader}/index | 公式卡库与阅读 |
| 专注统计 | subpackages/productivity/pomodoro-stats/index | 番茄钟统计 |
| 导出配置 / 记录 | subpackages/export/{export-config,export-records}/ | 数据导出 |

**分包预下载**（`app.json` `preloadRule`）：首页→study + knowledge、数据看板→study + knowledge、番茄钟→productivity；formulas / animation / export 按需加载。

**动画资源**：`subpackages/animation/lottie-loader.js` 保留加载动画、番茄钟使用的 `excellent` / `award` / `thumbsUp` 庆祝动画，以及组件默认的 `steady`（与 `practice` 共用成功动画）。未使用的 `final` / `combo` / `group` / `focus` 动画数据和 `assets/animation` 中无引用的 1×1 占位图片已清理；无图片来源时仍使用组件内置静态降级。图标保留运行时使用的格式、主题及诊断选中态变体，已被 PNG 或共享图标替代的旧 SVG 不再打包。

---

## 10. 交互规则

- **练习模式**：随机抽题 → 用户选择 → 提交判分 → 练习结果页（结果概览 / 错题分析 / 成长记录）→ 答错自动记入错题本
- **复习模式（review-today）**：今日概览 → 分组作答（每组 5/10/20/30 道，可自定义）→ 组结果（正确率 / 错题）→「复盘错题 / 继续练习」；跳过题重新入队
- **导入流程**：上传 → 解析 → 暂存区 → 人工逐题审核 / 批量审批 → 正式入库
- **错题详情 AI 学习建议**：加载时自动展示已存在解析——`wrong_questions.ai_analysis` 非空优先，否则回退 `questions.analysis`，两个来源走同一套标准化/富文本渲染（错因诊断 / 补漏重点 / 复练任务三段）；AI 生成与「重新生成解析」需用户点击按钮手动触发，生成进行中/超时通过短轮询恢复持久化结果
- **错题详情切题**：题目区 + AI 学习建议作为同一父容器统一淡出/淡入过渡，支持横向滑动与答题卡跳题；切题预取相邻题（页面实例缓存，TTL 300s）
- **成长体系**：练习结果页展示等级（Lv1~Lv5）/ 经验值 / 连续学习天数 / 徽章；数据源优先级：练习结果内嵌成长 → `/api/v1/stats/growth` → 看板聚合 → overview 公式兜底
- **专注统计扇区详情**：点击扇形图扇区时，遮罩通过 `visibility` 即时显示/隐藏，父层不做 `opacity` 动画，也不参与主题通用过渡，避免背景模糊在淡入结束后才生效；仅详情卡片保留入场动画。浅/深色遮罩与点击遮罩关闭、点击卡片不关闭的交互保持不变。自动回归：`cd miniprogram && node tests/test-pomodoro-stats-detail.js`；微信开发者工具/真机上的首帧模糊效果仍需人工验证。
- **加载态**：所有列表页支持下拉刷新 + 上拉加载更多（分页）
- **空态**：无数据时显示友好提示，如"还没有错题，继续加油！"
- **错误态**：网络错误显示重试按钮，API 错误显示错误信息
- **错题本日期筛选**：筛选控件封装在主包共享组件 `components/question-filter-panel`，通过 `app.json` 注册供 study 分包使用；页面保留筛选条件与请求逻辑，维持分包源码预算。筛选面板提供“不限 / 今天 / 近7天 / 近30天 / 自定义”，按加入错题本日期（`created_at`）和北京时间筛选。近7天、近30天均包含今天；快捷范围使用 API 同步时钟计算，跨午夜继续加载时从第一页重新查询。自定义开始/结束日期点击“应用日期”后生效，反向范围在页面内提示；重置会清除日期条件和草稿。日期条件与学科、错因、知识点组合，并同步传给 `/wrong-questions` 和 `/wrong-questions/task-flow`；无匹配结果可重置，加载失败可重试。日期作为一个筛选维度计入角标。顶部全局统计仍表示完整错题本，列表/任务流表示筛选结果。回归：`node tests/test-wrong-book-date-filter.js`（在 `miniprogram/` 执行）。
- **章节诊断学科选择**：`pages/dashboard/dashboard` 的章节学习诊断模块使用“推荐学科 + 当前学科名称”单行点击入口，打开轻磨砂半透明底部弹层；四个 408 叶子学科按两行两列排列，使用本地 Lucide 线性图标和全称，去除独立卡片描边与厚底色，当前学科仅使用淡绿背景、绿色图标和文字表达选中，不显示勾号。图标来源与许可保存在 `assets/icons/diagnosis-subject/`。模糊限定在弹层区域，不支持时使用较高不透明度浅色底。点选后立即反馈选中态，并用 180ms 退场动画收起弹层，退场期间阻止重复点选；推荐请求并行发起，入口与正文保持原学科直到退场完成，再一起更新。退场期间已返回或命中缓存时直接展示结果，跳过骨架；仍在请求时显示等高加载态，骨架延迟 100ms 后用 120ms 淡入，降低短请求闪现。点击当前学科仅收起弹层，即使缓存过期也不触发刷新；点击遮罩和关闭按钮同样平滑收起，页面隐藏/卸载时取消退场计时并使未完成切换失效。减弱动态效果偏好下移除空间动画。全屏弹层通过 `catchtouchmove` 阻止背景触摸滚动，不切换页面级 `overflow`。诊断正文保留已测得的最小高度，未缓存学科使用不闪动的等高静态骨架，加载失败与空态同样保留高度；30 秒内切回已查看学科直接复用本页缓存，缓存命中也使旧请求失效。业务 ID 来自 `/practice/subjects` 的有效目录，包含尚无练习历史的学科，未启用或缺失学科隐藏，不将 408 根学科作为章节推荐对象。初次优先使用路由指定学科或薄弱学科，用户选择在本页刷新与练习返回后保留；切换后以所选 `subject_id` 请求 `/study-hub/knowledge-diagnosis`。加载时清除其他学科的旧推荐，旧请求不能覆盖新选择；学科加载、推荐失败和暂无推荐分别提供恢复入口。专项练习、返回地址和知识图谱使用当前推荐学科。回归：`node tests/test-dashboard-diagnosis-subject.js`（在 `miniprogram/` 执行）。2026-10-15 微信开发者工具已通过 WXML/WXSS 编译与截图检查；本轮快速切换未进入 loading 状态，延迟接口响应 3 秒的 180 个采样覆盖切换前、退场、加载和完成阶段，正文高度均为 251px，正文顶部和页面滚动位置保持不变。真机效果待验证。
- **学习计划保存日期**：`subpackages/study/study-plan/index` 使用 `utils/api.js` 同步的服务端时钟计算北京时间日期下限，在页面进入、重新显示、概览加载后和提交前刷新。提交前校验日期格式、真实日历日期及是否过期；过期目标提示“目标日期已过期，请重新选择”，改选当天或未来日期后可继续保存，不放宽后端 `PUT /api/v1/study-plan` 的日期校验。未设置目标日期时仍只保存本地四科策略；远端保存失败不回滚本地策略。自动回归：`cd miniprogram && node tests/test-study-plan-save.js`；后端接口边界：`cd backend && python -m pytest tests/test_features/test_study_plan_save.py`。微信开发者工具/真机上的日期选择与保存仍需人工验证。
- **所有 API 调用**走 `utils/api.js` 封装，自动携带 token、统一错误处理（例外：practice-result 内嵌独立 `requestApi`，为兼容多环境 API 基址 / token 来源）

---

## 11. 命名约定

- 页面路由：小写 + 连字符（`wrong-book`、`practice-result`）
- WXML class：小写 + 连字符（`action-card`、`subject-row`）
- JS 变量：小驼峰（`wrongStats`、`practiceCount`）
- 事件处理：`handleXxx` 或 `onXxx` 命名
