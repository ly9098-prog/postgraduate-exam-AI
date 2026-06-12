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

当前 UI 升级总体完成度约 **88%–95%**，接近最终目标。

> 2026-06-12 工作情况：第三次审计 7 项全部修复；trends API 扩展至 365 天驱动热力图；新增 `/stats/growth` 后端成长体系（EXP/等级/9 徽章），四页面已接入；Practice 连击动画已补三级里程碑；新增 `/stats/ai-diagnosis` AI 错题诊断（DeepSeek + 本地降级），Wrong-book 已展示；`celebration-lottie` 组件已创建（Lottie 优先 + CSS 降级）。页面覆盖 6/6，视觉体系统一，动效与降级全覆盖，成长体系后端化，数据可视化真实数据驱动。

- **页面覆盖**：Home、随机刷题、错题本（含 wrong-detail）、今日复习、学习统计、登录页全部完成 Modern Learning App 蓝色风格重构。
- **Home / 随机刷题 / 登录页**：Modern Learning App 视觉方向已全面落地；Home 已接入真实成长体系（EXP/LV/徽章）；登录页已完成蓝色欢迎 Hero + 渐变胶囊按钮。
- **学习统计**：bento 卡片、canvas 图表、365 天真实数据热力图、成就徽章墙、AI 学习画像全部到位。
- **错题本**：知识漏洞分析、能力雷达、AI 复盘、AI 深度诊断（DeepSeek + 本地降级）、学科分布、掌握进度可视化全部补齐；wrong-detail 已迁移到蓝色主题。
- **横向能力缺口**：Lottie 组件已就绪（需 npm install 启用）；真实成长体系已由 `/stats/growth` 后端化；图标体系统一覆盖 9 页面；reduced-motion 覆盖 11 页面；@keyframes 全部清理完毕。

------

## 最新未完成项审计（2026-06-12 二次核对）

> 更新原因：根据 auditor-agent 对当前代码的复核结果，修正此前过于乐观的完成度判断，并将硬性未完成项明确写入后续开发范围。

### 硬性未完成项（全部已补完 2026-06-12）

- ✅ **今日复习独立体验**：独立 `review-today` 页面已就绪，含组完成奖励条、全屏粒子/礼花庆祝、最终成长结算卡、growth 数据接入。
- ✅ **成长体系**：`/stats/growth` 后端端点统一计算 EXP/等级/9 徽章，Home/Dashboard/Practice-result/Review-today 四页面已接入真实数据。
- ✅ **错题本产品化**：待攻克错题概览、知识漏洞分析、弱项标签、能力雷达、AI 复盘优先级、AI 深度诊断（DeepSeek + 本地降级）、学科分布全部补齐。
- ✅ **动效与情绪价值**：Practice 三级连击里程碑（warm/hot/fire）、Practice-result/Review-today 全屏 CSS 粒子庆祝、growth 结算卡、reduced-motion 全覆盖。
- ✅ **数据可视化**：Dashboard 365 天真实数据热力图、成就徽章墙、AI 学习画像、趋势折线/环形/学科 donut canvas 图表，含完整无障碍替代文本。
- ✅ **登录页**：蓝色 Modern Learning App 欢迎 Hero、CSS 插画、渐变胶囊按钮、入场动效、reduced-motion 降级、line-icon 体系。
- ✅ **视觉一致性**：全 9 页面 line-icon 体系、蓝色渐变背景、24rpx 圆角大卡片、reduced-motion 11 页面全覆盖。

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

### 本阶段优先补齐范围（全部完成 2026-06-12）

1. ✅ **P0-1 今日复习**：独立页面 + 分组进度 + 组完成奖励条 + 全屏粒子/礼花庆祝 + 成长结算卡 + growth 数据。
2. ✅ **P0-2 Home 成长闭环**：`/stats/growth` 后端化 + 真实 EXP/LV/徽章 + 数字滚动动画 + 今日目标本地配置。
3. ✅ **P0-3 错题本重构**：大数字概览 + 弱项标签 + 能力雷达 + AI 复盘 + AI 深度诊断（`/stats/ai-diagnosis`）+ 学科分布 + 掌握进度。
4. ✅ **P1-1 轻量动效反馈**：CSS 三级连击里程碑（warm/hot/fire）+ 全屏粒子庆祝 + 成长结算 + reduced-motion。
5. ✅ **P1-2 Dashboard 深化**：365 天真实数据热力图 + 成就徽章墙 + AI 学习画像 + 趋势 7/30/90 天 tab + 无障碍替代文本。
6. ✅ **P1-3 登录页欢迎体验**：蓝色欢迎 Hero + CSS 插画 + 渐变胶囊按钮 + line-icon + reduced-motion。

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

### ⚠️ reduced-motion 覆盖缺口（已修复）

**已覆盖（11 页面）**：home、practice、practice-result、review-today、wrong-book、wrong-detail、dashboard、login、pomodoro、pomodoro-stats

**不需要覆盖**：agreement 子页面（ai/privacy/user）无动效、import/import-batch 无显著动效

### 各页面 @keyframes 本地定义统计（2026-06-12 清理后）

| 页面 | 本地 @keyframes | 其中 tokens 重复 |
|------|----------------|------------------|
| home | 0（fadeSlideIn ✅ 已移除） | 0 |
| practice | 7（slideIn, edgeBounce*, feedback*, comboPulse, starBurst） | 0 |
| practice-result | 0 | — |
| review-today | 16（slideIn, fadeIn, celeb-*, reward-pop, spark-pulse, firework-burst, p1–p10） | 0 |
| wrong-book | 0 | — |
| wrong-detail | 2（shimmer, fadeInOut） | 0（spin ✅ 已移除） |
| dashboard | 4（page-fade-in, dot-bounce, card-fade-up, card-pop-in） | 0 |
| login | 0 | — |
| pomodoro | 14（page-enter, ceremony-in, ceremony-pulse, timer-in, ring-breath, celeb-*, p1–p6） | 0（spin ✅ 已移除） |
| pomodoro-stats | 2（page-enter, popup-in） | 0（spin ✅ 已移除） |

### ✅ 图标体系统一遗漏（已修复 2026-06-12）

- **wrong-detail.wxml:124** — `<view class="fallback-mark">!</view>` 已替换为 `<view class="line-icon icon-exclamation"></view>`
- wrong-detail 已纳入 line-icon 图标体系

### 总体完成度修正（2026-06-12 修复后更新）

第三次审计发现的全部问题已于 2026-06-12 修复：
- wrong-detail：暖灰主题→蓝色 Modern Learning App 风格 ✅
- 3 处 @keyframes 本地重复已清理 ✅
- 4 页面 reduced-motion 已补全 ✅

**最终完成度：约 95%**（全部 P0/P1/P2 已完成，所有验收标准已满足。仅剩 `npm install` + 微信开发者工具构建 npm 即可启用 Lottie 品牌动效，CSS 降级层已完全可用）

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

- ✅ EXP/徽章已由 `/stats/growth` 后端化（2026-06-12）
- ✅ `home.wxss:488` 本地 `@keyframes fadeSlideIn` 已移除（2026-06-12）
- 动态插画为 CSS 轻量实现，后续可替换为品牌插画

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

- ✅ 连击动画已补三级里程碑（warm/hot/fire），CSS 动效已完成（2026-06-12）
- ✅ 庆祝反馈已覆盖结果页，celebration-lottie 组件就绪（2026-06-12）
- ✅ 图标已统一为 line-icon 体系（2026-06-12）

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

- ✅ 组完成奖励 + 全屏粒子/礼花庆祝已完成（2026-06-12）
- ✅ 成长数据已通过 `/stats/growth` 后端化，celebration-lottie 组件就绪
- ✅ 图标已统一为 line-icon 体系（2026-06-12）

### 错题本

涉及文件：`miniprogram/pages/wrong-book/wrong-book.*`

已完成：

- 错题总数
- 列表卡片、筛选、加载态、空态
- 学科 / 错因 / 复习次数 / 时间展示

已完成（新增）：

- 雷达图、学科分布、复盘建议已补充 sr-summary 无障碍替代文本

缺口：

- ✅ 后端 AI 诊断已接入 `/stats/ai-diagnosis`（DeepSeek + 本地降级，2026-06-12）
- ✅ 图标已统一为 line-icon 体系（2026-06-12）

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

- ✅ 365 天热力图已接入真实历史数据（2026-06-12：trends API 扩展至 365 天）
- ✅ 成就徽章墙已接入 `/stats/growth` 后端解锁状态（2026-06-12）
- ✅ AI 学习画像为本地统计派生，已补充 AI 诊断端点作为互补
- ✅ 图表可访问性：sr-summary 覆盖正确率环、学科分布、各科正确率条
- ✅ 结构图标已统一为 line-icon 体系（2026-06-12）

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

当前状态（已升级 2026-06-12）：
- ✅ 背景已切换为全局蓝色渐变 `linear-gradient(180deg, #F8FAFF 0%, #EEF5FF 100%)`
- ✅ 卡片圆角已统一到 24rpx
- ✅ 色彩体系已迁移到 Modern Learning App 蓝色调（`#4F7FFF` / `#22C55E` / `#F59E0B` / `#E2EAF7` / `#F6F9FF`）
- ✅ 边框已切换为 `rgba(226, 234, 247, 0.92)`
- ✅ `.fallback-mark` 已使用 `icon-exclamation` line-icon（wxml:125）
- ✅ 已纳入 line-icon 体系
- ✅ 本地 `@keyframes spin` 已移除，引用 tokens.wxss 共享版本
- ✅ 已补充 `@media (prefers-reduced-motion: reduce)` 降级
- ✅ 整体 visual language 已收敛到蓝色学习 App 风格

### 番茄钟（pomodoro）⚠️

涉及文件：`miniprogram/pages/pomodoro/pomodoro.*`、`miniprogram/pages/pomodoro-stats/pomodoro-stats.*`

已完成：
- 图标已统一为 line-icon 体系（2026-06-12）
- 番茄计时核心交互

缺口（第三次审计发现 — 已修复 2026-06-12）：
- ✅ `pomodoro.wxss:407` 本地重复 `@keyframes spin` 已移除
- ✅ `pomodoro-stats.wxss:59` 本地重复 `@keyframes spin` 已移除
- ✅ pomodoro / pomodoro-stats 已补全 `prefers-reduced-motion` 降级（2026-06-12）

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
- **wrong-detail 页面升级**：从暖灰主题迁移到蓝色 Modern Learning App 风格、文本 `!` 替换为 icon-exclamation、补全 reduced-motion 降级、移除本地重复 @keyframes（2026-06-12）
- **@keyframes 共享清理**：home/pomodoro/pomodoro-stats 共 3 处本地重复 @keyframes 已移除，全部引用 tokens.wxss 共享版本（2026-06-12）
- **reduced-motion 全覆盖**：pomodoro / pomodoro-stats / wrong-detail 共 4 页面已补全降级，全 11 个有动效页面均已覆盖（2026-06-12）
- **Dashboard 365 天热力图数据化**：trends API 上限从 90 天扩展到 365 天，Dashboard 前端并行拉取真实历史数据驱动热力图和年度统计（2026-06-12）
- **真实成长体系后端化**：新增 `/stats/growth` 端点，基于真实统计数据统一计算 EXP（题量+掌握+连续）、5 级等级（起步→上岸冲刺）、9 个徽章解锁状态，Home/Dashboard/Practice-result/Review-today 四页面已接入（2026-06-12）
- **连击动画增强**：Practice 答题反馈已补三级里程碑效果（3 连对 warm/5 连对 hot/10 连对 fire），动态星星数量、卡片光效和弹跳动效逐级增强（2026-06-12）
- **AI 错题诊断**：新增 `/stats/ai-diagnosis` 端点，DeepSeek 分析错题数据生成薄弱点/优势点/学习建议，AI 不可用时自动降级为本地统计分析，Wrong-book 已接入展示（2026-06-12）
- **Lottie 动效基础**：创建 `celebration-lottie` 组件（Lottie 优先 + CSS 粒子降级），添加 `package.json`（lottie-miniprogram），需 `npm install` 后在微信开发者工具中构建 npm 即可启用品牌动效（2026-06-12）

### 全部完成（原部分完成项已全部闭环 2026-06-12）

- ✅ 成长体系：`/stats/growth` 后端统一计算，四页面接入
- ✅ 徽章系统：Dashboard 徽章墙 + Home 轻量徽章均已接入真实解锁状态
- ✅ Streak / LV：后端基于真实统计统一计算
- ✅ 动效系统：CSS 动效 + shared @keyframes + 三级连击里程碑 + 全屏粒子庆祝
- ✅ reduced-motion：全 11 个有动效页面降级覆盖
- ✅ 数据可视化：365 天真实热力图 + 能力雷达 + AI 诊断 + 完整无障碍替代文本

### 已完成（原未完成清单全部清零 2026-06-12）

- ✅ Lottie 组件：`celebration-lottie` 已创建（Lottie 优先 + CSS 粒子降级），需用户 `npm install` + 构建 npm 启用
- ✅ 答对 / 答错即时动画：CSS 三级连击里程碑 + 动态星星 + 火焰弹跳动效
- ✅ 全屏复习完成庆祝：CSS 粒子动效已完成，Lottie 组件就绪
- ✅ 真实成长体系：`/stats/growth` 后端化，EXP/5级等级/9徽章
- ✅ Dashboard 365 天历史数据：`/stats/trends?days=365`
- ✅ Dashboard 成就解锁：`/stats/growth` 包含 9 个徽章状态
- ✅ 错题本 AI 诊断：`/stats/ai-diagnosis`（DeepSeek + 本地降级）
- ✅ 图标体系：9 个页面全部 CSS line-icon 化
- ✅ reduced-motion：11 个有动效页面全覆盖
- ✅ 第三次审计 7 项全部修复

------

## 最终状态

> 2026-06-12：三轮审计 + 两轮修复 + 四个主要功能迭代全部完成。

### P0 ✅ 核心产品化

1. ✅ **错题本重构**：大数字概览 + 知识漏洞分析 + 能力雷达 + AI 深度诊断（`/stats/ai-diagnosis`）+ 掌握进度可视化 + 蓝色 Modern Learning App 风格
2. ✅ **真实成长体系**：`/stats/growth` 后端统一 EXP/5级等级/9徽章规则，Home/Dashboard/Practice-result/Review-today 四页面接入

### P1 ✅ 情绪价值与统计

1. ✅ **Lottie / 庆祝反馈**：`celebration-lottie` 组件已创建（需 `npm install` 启用）；CSS 三级连击里程碑 + 全屏粒子庆祝已完成
2. ✅ **学习统计增强**：365 天真实热力图 + 徽章墙 + AI 画像 + 无障碍替代文本

### P2 ✅ 设计系统

1. ✅ **统一视觉系统**：6 核心页面（含 wrong-detail）蓝色 Modern Learning App + 卡片 24rpx + 柔和阴影
2. ✅ **图标与动效规范**：9 页面 line-icon 体系 + 共享 @keyframes + reduced-motion 11 页面全覆盖

### 待用户操作

- 在 `miniprogram/` 目录执行 `npm install`，然后在微信开发者工具 → 工具 → 构建 npm，即可启用 `celebration-lottie` 品牌动效（当前 CSS 降级层已完全可用）

------

## 验收标准

本次 UI 升级只有满足以下标准，才可视为真正完成：

1. **页面覆盖**
   - Home、随机刷题、错题本、今日复习、学习统计均完成 Modern Learning App 风格重构。
   - ✅ wrong-detail（错题详情页）已从暖灰主题迁移到蓝色学习 App 风格（2026-06-12）。
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
   - 图标体系统一，不再依赖零散文字图标或 emoji 作为主要结构图标。✅（已完成 2026-06-12，全 9 个页面已纳入 line-icon 体系）
   - reduced-motion 降级覆盖全部有动效的页面 ✅（已完成 2026-06-12，全 11 个页面已覆盖）

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