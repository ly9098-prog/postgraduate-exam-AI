# UI Rules

> 2240AI 前端设计规范。包含 Design System Token、组件库、页面结构、交互规则。

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

### 语义对照

| 场景 | 色值 | Token |
|------|------|-------|
| 导航栏 | `#5B7B9A` | primary |
| 答案正确 | `#6B9B6B` | success |
| 待复习 | `#C49A6B` | warning |
| 答错 | `#C47A7A` | danger |

---

## 2. Spacing Scale (8pt base)

| Token | Value | 场景 |
|-------|-------|------|
| `--space-xs` | `8rpx` | 极小间距、标签内边距 |
| `--space-sm` | `12rpx` | 元素间小间距、标签间距 |
| `--space-md` | `16rpx` | 内边距、选项间距 |
| `--space-lg` | `20rpx` | 区块间距、卡内边距 |
| `--space-xl` | `24rpx` | 卡内边距、选项内边距 |
| `--space-2xl` | `30rpx` | 卡边距、区块标题底部 |
| `--space-3xl` | `40rpx` | 大区块间距 |
| `--space-4xl` | `60rpx` | 页面顶部、底部留白 |

---

## 3. Border Radius

| Token | Value | 场景 |
|-------|-------|------|
| `--radius-sm` | `8rpx` | 小标签、进度条 |
| `--radius-md` | `12rpx` | 按钮、输入框 |
| `--radius-lg` | `20rpx` | 卡片、大区块 |
| `--radius-xl` | `28rpx` | 弹窗、首屏卡片 |
| `--radius-full` | `50%` | 圆形头像 |

---

## 4. Typography

| Token | Size | Weight | 场景 |
|-------|------|--------|------|
| `--text-h1` | `36rpx` | 700 | 页面标题 |
| `--text-h2` | `32rpx` | 600 | 区块标题、结果数字 |
| `--text-body` | `28rpx` | 400 | 正文、选项、列表项 |
| `--text-caption` | `24rpx` | 400 | 辅助信息、标签文字 |
| `--text-small` | `22rpx` | 400 | 极简标注、徽标文字 |
| `--text-stat` | `48rpx` | 700 | 统计数字 |
| `--text-stat-sm` | `40rpx` | 700 | 小号统计数字 |

---

## 5. Shadow

| Token | Value | 场景 |
|-------|-------|------|
| `--shadow-card` | `0 2rpx 12rpx rgba(0,0,0,0.06)` | 卡片阴影 |
| `--shadow-card-hover` | `0 4rpx 16rpx rgba(0,0,0,0.08)` | 卡片按压态 |

---

## 6. Component Classes

### Card (`.card`)

- `bg: #FFFFFF`, `border-radius: 20rpx`, `padding: 30rpx`, `margin: 20rpx 30rpx`
- `box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06)`

### Button

| 类名 | 样式 | 用途 |
|------|------|------|
| `.btn-primary` | 主色（`#5B7B9A`）实心 | 主要操作 |
| `.btn-secondary` | 主色浅底 | 次要操作 |
| `.btn-text` | 纯文字 | 文字按钮 |
| `.btn-danger` | 红色实心 | 危险操作 |
| `.btn-block` | 宽度 100% | 全宽按钮 |

所有按钮高度统一 88rpx（padding 24rpx），圆角 12rpx。

### Tag

| 类名 | 用途 |
|------|------|
| `.tag` | 默认标签 |
| `.tag-success` | 正确/已掌握 |
| `.tag-warning` | 待复习 |
| `.tag-danger` | 错误 |
| `.tag-primary` | 主色标签 |

内联块，padding 6rpx 16rpx，圆角 6rpx，字号 22rpx。

### List Item (`.list-item`)

左右布局，padding 28rpx 30rpx，border-bottom 分割线，支持箭头指示可点击。

### Stat Number (`.stat-num`)

字号 40-48rpx，字重 700，主色。

---

## 7. 布局约定

- 页面背景：`#F7F5F0`
- 导航栏背景：`#5B7B9A`，文字白色
- 内容最大宽度：750rpx
- 卡片间距：垂直 12-20rpx，水平 30rpx
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

**分包预下载**（`app.json` `preloadRule`）：首页→study、数据看板→study、番茄钟→productivity；formulas / animation / export 按需加载。

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
- **所有 API 调用**走 `utils/api.js` 封装，自动携带 token、统一错误处理（例外：practice-result 内嵌独立 `requestApi`，为兼容多环境 API 基址 / token 来源）

---

## 11. 命名约定

- 页面路由：小写 + 连字符（`wrong-book`、`practice-result`）
- WXML class：小写 + 连字符（`action-card`、`subject-row`）
- JS 变量：小驼峰（`wrongStats`、`practiceCount`）
- 事件处理：`handleXxx` 或 `onXxx` 命名
