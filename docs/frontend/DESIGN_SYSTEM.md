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
