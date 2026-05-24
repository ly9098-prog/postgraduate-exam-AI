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
