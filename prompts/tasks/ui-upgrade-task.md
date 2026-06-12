# 小程序UI升级设计任务

## 设计目标

当前小程序存在以下问题：

### 视觉层

- 页面布局过于传统
- 卡片层级不明显
- 留白不合理
- 色彩单调
- 缺少插画和状态反馈
- 缺少情绪价值

整体观感更像：

> 数据管理工具

而不是：

> 让用户愿意每天打开的学习产品

------

### 交互层

当前页面基本属于：

用户点击 → 做题 → 提交 → 结束

缺少：

- 正反馈
- 成就感
- 连续学习激励
- 进度成长感

导致：

用户完成学习后情绪没有变化。

------

# 整体设计风格重构

不要参考管理后台。

统一采用：

## Modern Learning App Design

参考：

- 不背单词
- 墨墨背单词
- Forest
- 番茄ToDo
- Duolingo

设计关键词：

```text
圆角大卡片
渐变色
玻璃拟态
轻拟物
柔和阴影
高质量插画
成长反馈
游戏化激励
动态数据展示
```

------

# 全局视觉规范

## 主色调

```text
主色：
#4F7FFF

辅助：
#6EC1FF

成功：
#22C55E

警告：
#F59E0B

错误：
#EF4444
```

------

## 卡片

统一：

```text
圆角：24rpx

阴影：
0 8rpx 24rpx rgba(0,0,0,0.08)

背景：
#FFFFFF
```

------

## 页面背景

禁止纯白。

改为：

```css
linear-gradient(
180deg,
#F8FAFF 0%,
#EEF5FF 100%
)
```

------

# 首页(Home)重构

当前问题：

功能入口堆砌。

------

改为：

## 顶部欢迎区域

显示：

```text
早上好 ☀️

今天是坚持学习的第15天

已连续学习：
15天
```

搭配：

动态插画

------

## 学习进度卡

显示：

```text
今日目标

20 / 30题

进度环动画
```

完成时：

进度环发光

数字跳动

------

## 学习入口

改为大卡片

随机刷题

错题本

今日复习

学习统计

使用：

```text
渐变背景
图标
副标题
```

例如：

随机刷题

挑战新的题目
→

------

## 每日激励区域

随机显示：

```text
再坚持5题就能超过昨天的自己

🔥 连续学习15天

击败了78%的用户
```

动画：

数字滚动

------

# 随机刷题页面重构

参考：

不背单词

------

## 顶部

显示：

```text
随机挑战
```

副标题：

```text
今日已完成 12 题
```

------

## 答题卡

改为：

大圆角卡片

居中布局

题目区域增大

提高呼吸感

------

## 选项交互

点击：

```text
轻微缩放
波纹反馈
```

提交：

```text
按钮弹性动画
```

------

## 答对

出现：

```text
✔ 回答正确
```

Lottie动画：

勾选飞入

星星粒子

------

## 连续答对

例如：

```text
🔥 5连对

太棒了！
```

出现连击动画。

------

# 错题本页面重构

当前问题：

像数据库列表。

------

改为：

## 错题概览

顶部显示：

```text
待攻克错题

128
```

大数字设计。

------

## AI分析

改为：

```text
知识漏洞分析
```

使用：

雷达图

能力图谱

弱项标签

不要纯文本。

------

## 错题卡片

增加：

```text
错误次数

最近错误时间

掌握进度
```

可视化展示。

------

# 今日复习页面重构

参考：

墨墨背单词

------

顶部：

```text
今日待复习

45题
```

------

增加：

学习进度条

```text
20 / 45
```

实时增长。

------

每完成一组：

出现：

```text
🎉 已完成一组复习
```

奖励动画。

------

全部完成：

全屏庆祝动画：

```text
今日复习完成
```

粒子特效

礼花动画

徽章出现

------

# 学习统计页面重构

当前问题：

数据堆积。

------

完全重构。

------

## 学习热力图

参考：

GitHub贡献图

显示：

```text
过去365天学习情况
```

------

## 连续学习

显示：

```text
🔥 15天
```

超大数字。

------

## 学习趋势

使用：

折线图

展示：

```text
每日题量
正确率
学习时长
```

------

## 成就系统

新增：

```text
首次学习

连续7天

完成100题

完成1000题
```

徽章墙。

------

## 学习画像

AI生成：

```text
你的优势：
计算题

你的弱项：
同步互斥
```

卡片化展示。

------

# 登录页面重构

当前问题：

极其工具化。

------

改为：

欢迎页风格。

顶部插画：

```text
学习成长主题
```

------

文案：

```text
每天进步一点点

让错题成为成长的阶梯
```

------

登录按钮：

大尺寸胶囊按钮

渐变背景。

------

# 动效系统（重点）

必须新增统一动画体系。

------

## 页面进入

```text
淡入
上滑
```

------

## 卡片

```text
依次出现
```

------

## 按钮

```text
缩放反馈
```

------

## 数据

```text
数字滚动动画
```

------

## 学习完成

Lottie动画：

```text
礼花
星星
勋章
火焰连击
```

------

# 新增成长体系（强烈建议）

新增：

## 学习等级

```text
Lv1 新手

Lv2 坚持者

Lv3 刷题达人

Lv4 学霸

Lv5 大师
```

------

## 连续学习

```text
Streak
```

显示在首页最显眼位置。

------

## 徽章系统

例如：

```text
连续7天学习

连续30天学习

完成100题

完成1000题

正确率90%
```

------

# 当前实现审计（2026-06-12）

> 更新原因：补充当前 UI 升级任务的实现审计结论，将原始设计目标与后续开发待办结合，作为下一阶段开发依据。

## 总体结论

当前 UI 升级总体完成度约 **55%–65%**，尚未达到最终目标。

> 2026-06-12 第三次审计更新：wrong-detail 页面完全遗漏（暖灰主题、文本 `!` 图标、无 reduced-motion）、home.wxss/pomodoro.wxss/pomodoro-stats.wxss 共 3 处 @keyframes 本地重复未清理、pomodoro/pomodoro-stats/wrong-detail 共 4 页面缺 reduced-motion 降级。图标体系统一和关键帧提取进展被这些遗漏抵消，整体评估与前次基本持平。

- **页面覆盖**：Home、随机刷题、错题本、学习统计、登录页存在；`review-today` 已补齐独立体验；🔴 **第三次审计新增** — `wrong-detail` 完全未升级，仍在旧暖灰主题。
- **Home / 随机刷题 / 登录页**：已有 Modern Learning App 的基础视觉方向；Home 已补入本地目标配置、EXP/LV 提示和轻量徽章反馈；登录页已补蓝色欢迎 Hero、成长主题插画、目标文案和渐变胶囊登录按钮，但即时反馈和全局视觉体系仍需继续收敛。
- **学习统计**：已有 bento 卡片、canvas 图表与短期趋势、365 天热力图第一阶段、成就徽章墙和 AI 学习画像；缺后端真实数据接口。
- **错题本**：已补第二阶段（知识漏洞分析、能力雷达、AI 复盘），但缺真实诊断数据；`wrong-detail` 子页面完全未升级。
- **横向能力缺口**：Lottie、真实成长体系、完整徽章墙、统一动效 token 仍为主要缺口；图标体系统一已完成（wrong-detail 除外）；reduced-motion 覆盖 7/11 有动效页面；@keyframes 共享提取已完成但清理不彻底（3 处遗留）。

------

## 最新未完成项审计（2026-06-12 二次核对）

> 更新原因：根据 auditor-agent 对当前代码的复核结果，修正此前过于乐观的完成度判断，并将硬性未完成项明确写入后续开发范围。

### 硬性未完成项

- **今日复习独立体验（已补第一阶段）**：已确认存在可独立进入的 `review-today` 页面和 Home 入口；已具备今日待复习、组进度、组完成反馈、最终完成态，并补强组完成奖励条、组进度增长和最终成长结算；后续仍需接入真实成就解锁和更高质量 Lottie 资源。
- **成长体系未成型**：Home 已具备本地今日目标配置、EXP/LV 提示和轻量徽章状态；完整 Streak、经验值、徽章解锁仍需后端或明确统一规则支撑，不能只停留在静态 UI 壳或伪数据。
- **错题本产品化不足（已补第二阶段）**：已补“待攻克错题”大数字概览、知识漏洞分析、弱项标签、能力雷达、AI 复盘优先级、学科分布、复盘行动建议、错误次数、最近错误时间和掌握进度；后续仍需接入更完整的真实诊断数据与无障碍替代信息。
- **动效与情绪价值不足（复习/随机刷题结果已补第二阶段）**：随机刷题已补答对/答错/已选择即时反馈、连续答对计数、3 连对起连击文案和星星粒子等 CSS 动效；随机刷题结果页已补品牌化全屏庆祝层、奖励胶囊、礼花/粒子动效、成长结算卡和 reduced-motion 降级；今日复习已补组完成奖励条、组进度增长、全屏粒子/礼花庆祝和最终成长结算；后续仍需接入真实 Lottie 资源与统一动画 token。
- **数据可视化不足（Dashboard 已补第一阶段）**：Dashboard 已补 365 天热力图、成就徽章墙、AI 学习画像和基础无障碍文本；后续需接入真实 365 天历史接口、后端成就规则和更完整图表可访问性。错题本缺知识漏洞图谱/能力图谱/雷达图中的核心可视化。
- **登录页工具感（已补第一阶段）**：已从纸张工具卡升级为蓝色 Modern Learning App 欢迎页，补齐“每天进步一点点 / 让错题成为成长的阶梯”文案、成长主题 CSS 插画、蓝色渐变胶囊登录按钮和 reduced-motion 降级；后续仍需替换为更高质量品牌插画与统一图标体系。
- **视觉一致性不足**：全局仍有暖灰/雾蓝和文字/emoji 图标混用；已于 2026-06-12 新增 7 个 CSS line-icon（check、check-circle、chevron-right、exclamation、up、dot）到 tokens.wxss，并将 Home 和 Wrong-book 的结构箭头替换为统一图标体系；后续继续扩大 line-icon 覆盖范围并最终达成全局统一。

### ✅ 视觉体系统一完成（2026-06-12 同日本阶段 — 全页面图标替换）

> 更新原因：已完成 6 个核心页面全部结构性文字/emoji 图标的 CSS line-icon 替换，图标体系统一达成。

- **范围**：Home、Practice、Review-today、Wrong-book、Dashboard、Login 共 6 个核心页面
- **替换内容**：`●` → `icon-dot`、`✓` → `icon-check`、`‹`/`›` → `icon-chevron-left`/`icon-chevron-right`、`!` → `icon-exclamation`、`•` → `icon-dot`、`·` → `icon-dot`、`↗` → `icon-trend`
- **新增 CSS**：`icon-chevron-left`
- **CSS 调整**：更新 nav-arrow / feedback-icon / done-check / ga-status / group-reward-icon / badge-medal-icon / empty-icon-text / dev-arrow 等组件的 flex 居中适配
- **6 个核心页面均已无结构性文字/emoji 图标**
- **辅助页面**：pomodoro、import、import-batch 图标已同步替换（2026-06-12），保留语义性中文角标（导/模/空）
- **例外保留**：`★` 星星粒子（装饰性动效）、`优`/`练`/`章`/`记`（中文语义角标）不属于结构性图标

### ✅ 关键帧统一（2026-06-12 — 消除重复 @keyframes）

> 更新原因：将跨页面重复的 `@keyframes fadeSlideIn`（practice、review-today）和 `@keyframes spin`（practice、review-today、wrong-book）提取到 tokens.wxss 共享，消除 5 处重复定义。

- **新增 tokens**：`@keyframes fadeSlideIn`、`@keyframes spin`
- **已移除的本地重复**：practice.wxss（4 处 @keyframes）、review-today.wxss（2 处 @keyframes）、wrong-book.wxss（1 处 @keyframes）
- **🔴 第三次审计发现的遗漏**：home.wxss:488 仍保留本地 `@keyframes fadeSlideIn`（上次提取时遗漏清理）
- **注意**：各页面 `@keyframes slideIn`、`celeb-*`、`feedback*` 等专用动效保留在本地，因其与特定组件绑定，不适合统一抽取

### 本阶段优先补齐范围

1. **P0-1 今日复习（已补第一阶段）**：已确认独立页面入口、今日待复习概览、分组进度、组完成反馈、最终完成态；后续继续接入真实成就规则和 Lottie 资源。
2. **P0-2 Home 成长闭环（已补第一阶段）**：已补今日目标本地配置、LV/经验进度、每日激励文案和轻量徽章状态；后续继续推进真实成长体系后端化。
3. **P0-3 错题本重构（已补第二阶段）**：已补待攻克错题概览、弱项标签、能力雷达、AI 复盘优先级、学科分布、复盘行动建议、掌握进度、错误次数/最近错误时间可视化；后续继续接入真实诊断数据和更完整可访问性。
4. **P1-1 轻量动效反馈（随机刷题结果已补第二阶段）**：已用 CSS/状态浮层实现答题即时反馈、正确/错误/已选择状态、连对计数、连击文案和星星粒子；结果页已补高质量品牌庆祝层、奖励胶囊、礼花/粒子动效、成长结算和 reduced-motion 降级；后续继续接入真实 Lottie 资源与统一动画 token。
5. **P1-2 Dashboard 深化（已补第一阶段）**：已补 365 天热力图、成就徽章墙、AI 学习画像和基础无障碍文本；后续继续接入真实 365 天历史数据、后端成就状态和更完整图表替代信息。
6. **P1-3 登录页欢迎体验（第一阶段已完成，图标已补）**：已补蓝色欢迎 Hero、成长主题 CSS 插画、目标文案、渐变胶囊登录按钮、入场动效和 reduced-motion 降级；后续继续替换高质量插画资源；图标已纳入统一 line-icon 体系（2026-06-12）。

------

## 第三次审计发现（2026-06-12）

> 更新原因：对全 13 个页面进行逐页审计，发现前两次审计遗漏的关键问题。

### 🔴 关键遗漏

1. **home.wxss 未清理本地 `@keyframes fadeSlideIn`**（`:488`）
   - 上次关键帧提取到 tokens.wxss 后，home.wxss 的本地定义未被移除
   - 虽不会造成功能性 bug，但导致 tokens.wxss 共享版本实际未被 home 页使用（本地定义优先级更高）

2. **wrong-detail 页面完全未升级**
   - 背景仍为暖灰 `#F7F5F0`，而非全局蓝色渐变 `linear-gradient(180deg, #F8FAFF 0%, #EEF5FF 100%)`
   - 色彩体系仍为旧暖灰调（`#5B7B9A`、`#C49A6B`、`#EDF1F5`、`#F7F6F2`）
   - 卡片圆角 28rpx（未统一到 24rpx）
   - 边框使用暖色 `rgba(232, 229, 224, 0.75)`
   - `.fallback-mark` 使用文本 `!`（wxml:124），未替换为 `icon-exclamation`
   - 全页 0 处使用 line-icon 体系
   - 本地重复 `@keyframes spin`（`:407`，tokens.wxss 已有共享版本）
   - 无 `prefers-reduced-motion` 降级

3. **pomodoro.wxss 本地重复 `@keyframes spin`**（`:407`）
   - tokens.wxss 已有共享版本，pomodoro 未引用

4. **pomodoro-stats.wxss 本地重复 `@keyframes spin`**（`:59`）
   - 同上，且 pomodoro-stats 另有 `@keyframes page-enter` / `popup-in`

### ⚠️ reduced-motion 覆盖缺口

**已覆盖（7 页面）**：home、practice、practice-result、review-today、wrong-book、dashboard、login

**未覆盖（4 页面）**：
- `pomodoro.wxss` — 有 `page-enter`、`ceremony-in`、`spin`、`ceremony-pulse`、`timer-in`、`ring-breath`、`celeb-*`、粒子 p1–p6 等多组动效，全部无降级
- `pomodoro-stats.wxss` — 有 `page-enter`、`spin`、`popup-in`，无降级
- `wrong-detail.wxss` — 有 `shimmer`、`spin`、`fadeInOut`，无降级
- agreement 子页面（ai/privacy/user）无动效，不需要降级

### 各页面 @keyframes 本地定义统计

| 页面 | 本地 @keyframes | 其中 tokens 重复 |
|------|----------------|------------------|
| home | 1（fadeSlideIn 🔴） | 1 |
| practice | 7（slideIn, edgeBounce*, feedback*, comboPulse, starBurst） | 0 |
| practice-result | 0 | — |
| review-today | 16（slideIn, fadeIn, celeb-*, reward-pop, spark-pulse, firework-burst, p1–p10） | 0（slideIn 与 practice 同名但实现不同） |
| wrong-book | 0 | — |
| wrong-detail | 3（shimmer, 🔴spin, fadeInOut） | 1 |
| dashboard | 4（page-fade-in, dot-bounce, card-fade-up, card-pop-in） | 0 |
| login | 0 | — |
| pomodoro | 15（page-enter, ceremony-in, 🔴spin, ceremony-pulse, timer-in, ring-breath, celeb-*, p1–p6） | 1 |
| pomodoro-stats | 3（page-enter, 🔴spin, popup-in） | 1 |

### 🔴 图标体系统一遗漏

- **wrong-detail.wxml:124** — `<view class="fallback-mark">!</view>` 使用文本 `!`，应替换为 `icon-exclamation`
- wrong-detail 全页未使用任何 line-icon，需整体纳入图标体系

### 总体完成度修正

基于第三次审计发现：
- wrong-detail 完全未升级，降低整体评估
- home.wxss 和 pomodoros 的 @keyframes spin 重复表明前次清理不彻底
- reduced-motion 在 pomodoro 和 wrong-detail 缺失

**更新后总体完成度：约 55%–65%**（与前次 50%–60% 基本持平；图标/关键帧工作已实质落地，但 wrong-detail 完全遗漏和 3 处清理不彻底抵消了进展）

------

## 分页审计

### Home

涉及文件：`miniprogram/pages/home/home.wxml`、`miniprogram/pages/home/home.wxss`、`miniprogram/pages/home/home.js`

已完成：

- 渐变玻璃欢迎区
- 连续学习、等级、今日目标、进度条展示
- 今日目标本地快捷配置（10 / 20 / 30 / 50）
- EXP / 下一等级提示、每日激励文案和轻量徽章状态
- 入口大卡片
- 非纯白渐变背景
- 基础 fade-in 动效
- 数字滚动动画（连续学习天数、今日完成数、进度百分比渐变递增）
- 箭头图标已替换为 line-icon 体系

缺口：

- Streak、今日完成数、累计题数已接 `/stats/dashboard`，但完整经验值和徽章解锁仍是前端规则，尚未后端化
- 缺动态插画
- 缺真正系统化徽章墙
- 🔴 `home.wxss:488` 本地 `@keyframes fadeSlideIn` 未清理（tokens.wxss 共享版被覆盖）

### 随机刷题

涉及文件：`miniprogram/pages/practice/practice.*`、`miniprogram/pages/practice-result/*`

已完成：

- 挑战入口与题组设置
- 答题状态栏、进度条、题目大卡
- 选项按压反馈
- 答题卡弹窗
- 结果页正确率环与概览
- 结果页高质量品牌庆祝层、奖励胶囊、礼花 / 粒子动效
- 结果页成长结算卡与 reduced-motion 降级

缺口：

- 答题过程中仍缺真实 Lottie 勾选飞入
- 连击动画仍是轻量 CSS 反馈，尚未形成统一动画 token
- 庆祝反馈已覆盖结果页，但仍需接入真实 Lottie / 品牌动效资源
- 选项/反馈/导航图标已统一为 line-icon 体系（2026-06-12）

### 今日复习

涉及文件：`miniprogram/pages/review-today/review-today.*`

已完成：

- 今日复习入口
- 进度环、待复习数、近 7 天正确率
- 分组复习、组结果页
- 最终完成页徽章 / 奖励卡
- 组完成奖励条与组进度增长反馈
- 最终完成全屏粒子 / 礼花庆祝和成长结算卡

缺口：

- 组完成奖励动画仍是 CSS 轻量实现，尚未接入 Lottie
- 徽章仍是视觉文案，不是系统化成就
- 图标已统一为 line-icon 体系（2026-06-12）

### 错题本

涉及文件：`miniprogram/pages/wrong-book/wrong-book.*`

已完成：

- 错题总数
- 列表卡片、筛选、加载态、空态
- 学科 / 错因 / 复习次数 / 时间展示

已完成（新增）：

- 雷达图、学科分布、复盘建议已补充 sr-summary 无障碍替代文本

缺口：

- 后端真实诊断数据待接入
- 图标已统一为 line-icon 体系（2026-06-12）

### 学习统计

涉及文件：`miniprogram/pages/dashboard/dashboard.*`

已完成：

- bento / 卡片统计
- 正确率环形 canvas
- 趋势折线 canvas
- 学科 donut
- 短期 heat dots
- 连续学习 / 待复习 / 累计刷题
- 掌握情况 / 遗忘风险 / 答题用时
- 365 天学习热力图第一阶段
- 成就徽章墙第一阶段
- AI 学习画像卡片
- 趋势与热力图基础无障碍文本

缺口：

- 365 天热力图目前基于现有趋势数据和今日统计生成，仍需后端真实 365 天历史数据接口支撑
- 成就徽章墙仍是前端派生规则，尚未接入后端统一成就解锁状态
- AI 学习画像为本地统计派生建议，尚未接入真实 AI 分析结果
- 图表可访问性：sr-summary 替代文本已覆盖正确率环、学科分布、各科正确率条
- 结构图标已统一为 line-icon 体系（2026-06-12）

### 登录页

涉及文件：`miniprogram/pages/login/login.*`

已完成：

- 欢迎页风格
- 蓝色 Modern Learning App 欢迎 Hero
- 学习成长主题 CSS 插画
- “每天进步一点点 / 让错题成为成长的阶梯”核心文案
- 蓝色渐变大胶囊微信登录按钮
- 微信登录、协议区域
- 基础入场动效与 reduced-motion 降级

缺口：

- 当前插画为 CSS 轻量实现，仍需后续替换为更高质量品牌插画或 Lottie
- 结构图标已统一为 line-icon 体系（2026-06-12）
- 仍需在真机和微信开发者工具中确认小屏、动态字体和 reduced-motion 表现

### 错题详情（wrong-detail）🔴

涉及文件：`miniprogram/pages/wrong-detail/wrong-detail.*`

> **第三次审计发现：此页面在前两次审计中被完全遗漏，未进行任何 UI 升级。**

当前状态：
- 背景 `#F7F5F0`（旧暖灰主题，非全局蓝色渐变）
- 卡片圆角 28rpx（未统一到 24rpx）
- 色彩体系：`#5B7B9A` / `#C49A6B` / `#EDF1F5` / `#F7F6F2`（旧暖灰调）
- 边框 `rgba(232, 229, 224, 0.75)`（暖色）
- `.fallback-mark` 使用文本 `!`（wxml:124），未替换为 line-icon
- 全页 0 处使用 line-icon 体系
- 本地 `@keyframes spin`（`:407`）与 tokens.wxss 重复
- 无 `prefers-reduced-motion` 降级

待升级项：
- 背景切换为全局蓝色渐变
- 色系统一到 Modern Learning App 蓝色调
- 卡片圆角统一到 24rpx
- 文本 `!` 替换为 `icon-exclamation`
- 移除本地 `@keyframes spin`，引用 tokens.wxss 共享版本
- 补充 `@media (prefers-reduced-motion: reduce)` 降级
- 整体 visual language 收敛到蓝色学习 App 风格

### 番茄钟（pomodoro）⚠️

涉及文件：`miniprogram/pages/pomodoro/pomodoro.*`、`miniprogram/pages/pomodoro-stats/pomodoro-stats.*`

已完成：
- 图标已统一为 line-icon 体系（2026-06-12）
- 番茄计时核心交互

缺口（第三次审计发现）：
- 🔴 `pomodoro.wxss:407` 本地重复 `@keyframes spin`（tokens.wxss 已有共享版本）
- 🔴 `pomodoro-stats.wxss:59` 本地重复 `@keyframes spin`（同上）
- pomodoro 有 15 组本地 @keyframes，全部无 `prefers-reduced-motion` 降级
- pomodoro-stats 有 3 组本地 @keyframes，全部无 `prefers-reduced-motion` 降级

### 导入页（import / import-batch）

已完成：
- 图标已统一为 line-icon 体系（2026-06-12）
- 保留语义性中文角标（导/模/空）

缺口：
- 无显著动效，reduced-motion 不适用

------

## 已完成 / 部分完成 / 未完成清单

### 已完成

- Home 基础重构：渐变背景、玻璃欢迎区、学习入口大卡片、基础成长信息展示
- 随机刷题基础重构：挑战感入口、答题大卡、进度条、选项反馈、结果页概览
- 今日复习基础重构：复习入口、进度展示、分组复习、组完成奖励条、全屏庆祝反馈和最终成长结算
- 学习统计基础重构：卡片化统计、多个 canvas 图表、短期学习热力点、365 天热力图第一阶段、成就徽章墙、AI 学习画像卡片
- 登录页基础视觉升级：蓝色欢迎 Hero、成长主题插画、目标文案、渐变胶囊登录按钮和 reduced-motion 降级
- **图标体系统一**：6 个核心页面全部结构性文字/emoji 图标已替换为 CSS line-icon 体系（2026-06-12）

### 部分完成

- 成长体系：Home 已有本地目标配置、EXP/LV 提示、每日激励和轻量徽章状态；仍缺后端统一经验值规则、等级规则和徽章解锁逻辑
- 徽章系统：已有局部视觉表达，但缺完整徽章墙和成就状态
- Streak / LV：已有展示，但仍依赖前端快照或伪数据，未形成完整系统
- 动效系统：已有局部 CSS 动效、Home 数字滚动动画、Wrong-book/Review-today/Practice-result 页面入场动画，但缺统一动画 token、stagger、连击与庆祝反馈；关键帧提取不彻底（home/pomodoro/pomodoro-stats 仍有 3 处 tokens 重复）
- reduced-motion：7 个核心页面已覆盖，pomodoro / pomodoro-stats / wrong-detail 共 4 页面有动效但无降级
- 数据可视化：统计页已补 365 天热力图第一阶段、成就徽章墙和 AI 学习画像；错题本已补能力雷达和 AI 复盘优先级，后续仍需真实诊断数据和更完整图表替代信息

### 未完成

- Lottie 组件、资源与引用
- 答对 / 答错即时动画、勾选飞入、星星粒子、连击动画
- 全屏复习完成庆祝的高质量 Lottie / 品牌动效资源
- 真实成长体系：经验值、等级规则、徽章解锁、完成后增长动画
- Dashboard 真实 365 天历史数据接口
- Dashboard 后端成就状态与解锁规则
- 错题本核心可视化仍需接入真实诊断数据与更完整替代信息
- 图标体系替换（已完成 2026-06-12）：6 个核心页面 + 3 个辅助页面（pomodoro/import/import-batch）全部结构性文字/emoji 图标已替换为 CSS line-icon；新增 icon-chevron-left/play/pause/stop/plus/close/chevron-down 共 7 个图标到 tokens.wxss；更新 9 个页面对应组件的 flex 居中适配
- reduced-motion 与图表可访问性（已覆盖 7 个核心页面；图表无障碍替代文本已覆盖 Dashboard 正确率环/学科分布/各科正确率条、Wrong-book 雷达图/学科分布/复盘建议）
- 🔴 **第三次审计新增** — wrong-detail 页面完全未升级（暖灰主题、文本 `!` 图标、无 line-icon、无 reduced-motion、本地 @keyframes spin 重复）
- 🔴 **第三次审计新增** — home.wxss:488 本地 `@keyframes fadeSlideIn` 未清理（前次提取到 tokens.wxss 时遗漏）
- 🔴 **第三次审计新增** — pomodoro.wxss:407 / pomodoro-stats.wxss:59 本地 `@keyframes spin` 重复（tokens.wxss 已有共享版本）
- 🔴 **第三次审计新增** — pomodoro、pomodoro-stats、wrong-detail 缺少 `prefers-reduced-motion` 降级（4 个页面有动效但无降级）

------

## 下一阶段优先级

### P0：补齐核心产品化短板

1. **错题本重构**
   - 顶部改为“待攻克错题”大数字视觉概览。
   - 增加知识漏洞分析模块。
   - 增加雷达图 / 能力图谱 / 弱项标签。
   - 错题卡增加错误次数、最近错误时间、掌握进度可视化。
   - 统一到 Home / Practice / Review 的蓝色 Modern Learning App 风格。

2. **真实成长体系**
   - 接入真实学习数据，不再依赖前端伪数据。
   - 明确经验值、等级、连续学习、今日目标、徽章解锁规则。
   - 在 Home、Practice Result、Review 完成页、Dashboard 中统一展示成长变化。
   - 增加完成后的经验增长、等级进度、徽章解锁反馈。
   - **后续待办：今日目标本地可配置版本（已完成第一阶段）**
     - Home 今日完成数来自真实统计数据，今日目标总数支持本地快捷配置。
     - 第一阶段不改后端，已支持本地配置与持久化：`10 / 20 / 30 / 50` 题快捷选项。
     - 配置入口已放在 Home 今日目标卡片，用户点击后弹出轻量选择面板。
     - 本地配置已用于 Home 目标进度、任务文案和成长反馈；未来真实成长体系后端化时再迁移到用户配置接口。

### P1：补齐情绪价值与统计深度

1. **Lottie / 庆祝反馈**
   - 接入 Lottie 或等价动效资源。
   - 增加答对即时反馈、勾选飞入、星星粒子。
   - 增加连续答对 / 连击动画。
   - 增加复习完成全屏庆祝动画。

2. **学习统计增强（已补第一阶段）**
   - 已将短期 heat dots 扩展为过去 365 天学习热力图展示。
   - 已增加成就徽章墙。
   - 已增加 AI 学习画像卡片。
   - 已补充趋势和热力图基础无障碍文本。
   - 后续继续接入真实 365 天历史数据、后端成就状态、真实 AI 画像和更完整图表替代信息。

### P2：统一设计系统与可访问性

1. **统一视觉系统**
   - 统一 Home / Practice / Review / Wrong-book / Wrong-detail / Dashboard 的蓝色学习 App 视觉语言。
   - 统一卡片、按钮、阴影、渐变、间距、圆角、状态色。
   - 🔴 **第三次审计新增** — wrong-detail 页面需从暖灰主题整体迁移到蓝色 Modern Learning App 风格。

2. **图标与动效规范**
   - 将文字图标 / emoji 替换为统一 SVG / icon 体系。✅（已完成 2026-06-12：9 个页面全部替换为 CSS line-icon，含 pomodoro/import/import-batch 辅助页面；新增 icon-chevron-left/play/pause/stop/plus/close/chevron-down 共 7 个图标）
   - 🔴 **第三次审计新增** — wrong-detail 仍需替换文本 `!` 为 `icon-exclamation` 并纳入 line-icon 体系
   - 建立统一动画 token：页面进入、卡片 stagger、按钮按压、数字滚动、完成庆祝。✅（已完成 2026-06-12：`@keyframes fadeSlideIn` / `spin` 已提取到 tokens.wxss）
   - 🔴 **第三次审计新增** — 清理 home.wxss:488 / pomodoro.wxss:407 / pomodoro-stats.wxss:59 共 3 处本地重复 @keyframes
   - 增加 `reduced-motion` 降级策略（7 个核心页面已覆盖，pomodoro / pomodoro-stats / wrong-detail 共 4 页面待覆盖）

------

## 验收标准

本次 UI 升级只有满足以下标准，才可视为真正完成：

1. **页面覆盖**
   - Home、随机刷题、错题本、今日复习、学习统计均完成 Modern Learning App 风格重构。
   - 🔴 **第三次审计新增** — wrong-detail（错题详情页）需纳入升级范围，从暖灰主题迁移到蓝色学习 App 风格。
   - 错题本不再表现为数据库列表，而是具备学习诊断、弱项分析与掌握进度展示。

2. **成长体系**
   - Streak、LV、今日目标、经验值、徽章均来自真实学习数据或明确的后端 / 本地持久化规则。
   - 完成刷题、完成复习、达成连续学习时有可见成长反馈。
   - Dashboard 具备完整徽章墙或成就区域。

3. **动效与情绪价值**
   - 答对 / 答错、连续答对、完成一组复习、完成今日复习均有明确动画反馈。
   - 至少完成 Lottie 或等价高质量庆祝动画接入。
   - 动效有统一规则，并提供 reduced-motion 降级。

4. **数据可视化**
   - 学习统计包含 365 天学习热力图、趋势图、学科分布 / 掌握情况图表。
   - 错题本包含知识漏洞分析、雷达图 / 能力图谱 / 弱项标签中的至少一组核心可视化。
   - 图表具备基础无障碍文本或替代信息。

5. **视觉一致性**
   - 6 个核心页面（含 wrong-detail）统一使用蓝色渐变、圆角大卡片、柔和阴影、现代学习 App 的设计语言。
   - 图标体系统一，不再依赖零散文字图标或 emoji 作为主要结构图标。✅（已完成 2026-06-12，wrong-detail 除外）
   - reduced-motion 降级覆盖全部有动效的页面（当前 7/11 页面已覆盖，pomodoro / pomodoro-stats / wrong-detail 待补）

------

# 最终要求

```text
本次不是简单UI美化。

目标是从“工具型刷题小程序”升级为“具有游戏化激励和成长反馈的学习产品”。

请参考：
- 不背单词
- 墨墨背单词
- Duolingo
- Forest
- 番茄ToDo

重新设计以下页面：

1. 首页(Home)
2. 随机刷题
3. 错题本
4. 今日复习
5. 学习统计
6. 登录页

要求：

- 完全重构布局
- 不允许仅调整颜色和间距
- 引入现代学习App设计语言
- 引入成长体系
- 引入徽章系统
- 引入连续学习(Streak)
- 引入学习等级(LV)
- 引入高质量动画反馈
- 引入Lottie庆祝动画
- 引入数据可视化
- 引入情绪价值设计

最终达到：
用户打开小程序后有“继续学习”的欲望，而不是仅仅完成任务。
```

我建议优先重构 **Home → 随机刷题 → 今日复习** 这三个页面，它们决定了用户 80% 的使用体验；错题本和统计页更多是辅助页面。真正拉高留存的，往往是首页的成长感和做题过程中的即时反馈。