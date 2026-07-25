请直接检查并修改当前微信小程序项目，美化：

- pages/review-today/review-today

中的“每组 N 道”底部选择弹层。

不要只给设计建议，需要实际修改 WXML、WXSS、JS，补充交互回归测试并运行测试。

---

# 一、当前问题

点击首页卡片右上角的：

```text
每组 10 道
```

当前通过微信原生 `wx.showActionSheet` 显示选项：

- 每组 5 道
- 每组 10 道
- 每组 20 道
- 每组 30 道
- 取消

当前真机效果存在以下问题：

1. 原生白色 ActionSheet 与页面深绿色、荧光绿色视觉风格不一致。
2. 选项只是普通文本列表，没有当前选中状态。
3. “取消”与选项视觉层级不明显。
4. 弹层缺少标题、说明和明确的操作反馈。
5. 弹层占用面积较大，但信息密度和设计感较低。
6. 无法通过 WXSS 深度定制原生 `wx.showActionSheet`。

因此，本任务应将原生 `wx.showActionSheet` 替换为页面内部的自定义底部弹层。

不要尝试通过修改全局样式去美化系统 ActionSheet，因为微信原生弹层无法可靠应用页面 WXSS。

------

# 二、目标效果

底部弹层需要与 `review-today` 页面现有设计统一：

- 深绿色或暖白色卡片体系；
- 荧光绿作为选中强调色；
- 大圆角；
- 轻量阴影；
- 克制的网格或渐变装饰；
- 清晰的层级和留白。

弹层建议结构：

```text
┌─────────────────────────────┐
│ ━━━━━                       │  顶部拖拽指示条
│ 每组题数                     │
│ 选择每轮复习包含的题目数量   │
│                             │
│ [ 5 道 ] [ 10 道 ]          │
│ [20 道 ] [ 30 道 ]          │
│                             │
│ 当前选择：每组 10 道         │
│                             │
│ [取消]       [确认使用]      │
└─────────────────────────────┘
```

也可以使用纵向列表，但优先使用两列网格卡片，更符合当前页面视觉风格。

------

# 三、交互逻辑

## 1. 替换原生 ActionSheet

定位当前类似实现：

```js
wx.showActionSheet({
  itemList: [...]
})
```

替换为页面内部状态控制，例如：

```js
data: {
  showBatchSizeSheet: false,
  pendingBatchSize: 10
}
```

建议增加方法：

```js
openBatchSizeSheet()
closeBatchSizeSheet()
selectPendingBatchSize(event)
confirmBatchSize()
handleBatchSheetMaskTap()
stopBatchSheetPropagation()
```

命名请遵循项目现有风格。

------

## 2. 打开弹层

点击“每组 N 道”胶囊时：

1. 仅在 `overview` 阶段允许打开。
2. `isStarting` 或其他加载状态下不能打开。
3. 打开时将：

```js
pendingBatchSize
```

初始化为当前：

```js
reviewBatchSize
```

1. 显示遮罩和底部弹层。
2. 背景页面不能滚动或误触。

------

## 3. 临时选择与确认分离

点击 5、10、20、30 时，只修改：

```js
pendingBatchSize
```

不要立即修改真正的：

```js
reviewBatchSize
```

只有点击“确认使用”后，才执行：

```js
reviewBatchSize = pendingBatchSize
```

并设置已有的“用户主动选择过”状态，例如：

```js
this._userSelectedReviewBatchSize = true
```

然后关闭弹层。

这样用户点击“取消”时，可以保持原来的题数不变。

------

## 4. 关闭方式

以下操作关闭弹层：

- 点击“取消”；
- 点击遮罩；
- 点击确认后；
- 页面卸载时。

关闭时：

- 不修改正式选择，除非用户点击确认；
- 清理临时状态；
- 防止遮罩点击穿透。

点击弹层内容区域本身不能触发遮罩关闭。

------

## 5. 当前选中状态

必须同时区分：

- 当前已经生效的 `reviewBatchSize`；
- 弹层内临时选择的 `pendingBatchSize`。

选项状态建议：

### 未选择

- 浅色背景；
- 深绿色文字；
- 细边框。

### 临时选中

- 荧光绿色背景；
- 深绿色文字；
- 更明显边框；
- 右上角显示勾选图标；
- 轻微放大或阴影反馈。

### 当前已生效但尚未临时选择

如果与 `pendingBatchSize` 相同，则按选中状态显示即可，不需要重复标识。

------

# 四、WXML 实现要求

在 `review-today.wxml` 中增加自定义弹层结构。

建议：

```xml
<view
  wx:if="{{showBatchSizeSheet}}"
  class="batch-sheet-mask"
  catchtap="handleBatchSheetMaskTap"
>
  <view
    class="batch-sheet"
    catchtap="stopBatchSheetPropagation"
  >
    ...
  </view>
</view>
```

注意：

1. 使用 `catchtap` 防止事件穿透。
2. 遮罩与弹层必须位于页面较高层级。
3. 弹层需要兼容底部安全区。
4. 不能遮挡微信底部 Home Indicator。
5. 不要使用只能在 Web 浏览器工作的 DOM API。
6. 不要引入第三方 UI 库。

选项可以通过数组渲染：

```js
batchSizeOptions: [5, 10, 20, 30]
```

WXML 中使用：

```xml
wx:for="{{batchSizeOptions}}"
wx:key="*this"
```

不要重复写四份几乎相同的选项节点。

每个选项建议包含：

```text
5
道 / 题
适合快速复习
```

可选辅助文案：

- 5 道：快速复习
- 10 道：推荐
- 20 道：集中巩固
- 30 道：深度复习

辅助文案保持简短，不要让选项卡过高。

------

# 五、WXSS 设计要求

主要修改：

- pages/review-today/review-today.wxss

## 1. 遮罩

使用半透明深色遮罩，例如：

```css
.batch-sheet-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(4, 20, 13, 0.58);
}
```

可增加轻微背景模糊，但必须有无模糊时的稳定回退：

```css
backdrop-filter: blur(6px);
```

不要依赖模糊才能看清弹层。

------

## 2. 底部弹层

建议：

- 底部贴合；
- 左右留少量间距，或全宽；
- 顶部圆角 32rpx～48rpx；
- 暖白色或深绿色背景；
- 带安全区 padding；
- 最大宽度适配平板；
- 真机窄屏下不能溢出。

示例方向：

```css
.batch-sheet {
  position: absolute;
  left: 24rpx;
  right: 24rpx;
  bottom: calc(24rpx + env(safe-area-inset-bottom));
  border-radius: 40rpx;
  padding: 20rpx 28rpx 28rpx;
  background: #f7f8f1;
  box-shadow: 0 24rpx 64rpx rgba(4, 22, 14, 0.24);
}
```

不要使用当前原生 ActionSheet 那种整块纯白、无层次的列表样式。

------

## 3. 顶部拖拽指示条

增加仅用于视觉提示的短横条：

```css
.batch-sheet-handle
```

要求：

- 居中；
- 颜色低对比；
- 圆角；
- 不需要真的实现拖拽关闭。

不要为了一个视觉横条引入复杂触摸手势。

------

## 4. 标题区域

标题：

```text
每组题数
```

说明：

```text
选择每轮复习包含的题目数量
```

标题使用页面现有深绿色粗体风格。

可以增加一个小标签：

```text
REVIEW BATCH
```

但不要让英文抢占主视觉。

------

## 5. 选项网格

使用两列布局：

```css
.batch-size-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16rpx;
}
```

如果当前微信基础库或项目规范不建议使用 CSS Grid，则使用：

```css
display: flex;
flex-wrap: wrap;
```

确保兼容项目当前最低基础库版本。

每个选项：

- 高度约 120rpx～144rpx；
- 大圆角；
- 明确边框；
- 数字较大；
- “道”字号较小；
- 按压状态轻微缩放；
- 不要只依赖颜色表达选中状态。

建议加入：

- 勾选图标；
- “推荐”角标用于 10 道；
- 边框加粗；
- 背景变化。

不要使用 emoji 作为主要勾选图标，可使用纯文本 `✓` 或项目已有图标组件。

------

## 6. 底部操作区

底部两个按钮：

### 取消

- 次级浅色按钮；
- 深绿色文字；
- 清晰边框。

### 确认使用

- 荧光绿色强调背景；
- 深绿色文字；
- 明显但不过度发光；
- 真机必须有稳定 `background-color` 回退。

示例：

```css
.batch-sheet-confirm {
  background-color: #b8f21c;
  background-image: linear-gradient(135deg, #a9ef12, #c9f83c);
  color: #0b2b1c;
}
```

不要只写渐变而没有纯色回退。

按钮使用 `<button>` 时，需要局部重置：

```css
.batch-sheet-action::after {
  border: 0;
}
```

不要在 `app.wxss` 中修改所有 button。

------

## 7. 动画

增加简洁动画：

### 遮罩

- 透明度从 0 到 1；
- 约 180ms～240ms。

### 弹层

- 从底部轻微上移；
- 同时透明度变化；
- 约 220ms～300ms。

不要使用弹跳过强或持续时间过长的动画。

微信小程序中 `wx:if` 关闭时无法直接播放离场动画，不要求为了离场动画增加复杂状态机。优先保证打开动画稳定。

------

# 六、视觉细节

请参考当前 `review-today` 页面现有设计，而不是做成通用系统弹窗。

弹层应复用或呼应：

- 页面深绿色：标题、主要文字、确认区；
- 荧光绿色：选中、确认按钮、重点数字；
- 暖白色：弹层主体背景；
- 浅绿色：普通选项背景；
- 大圆角卡片；
- MEMORY CURVE 卡片中的克制科技感。

可以在弹层背景右上角增加非常浅的网格装饰，但必须：

- 不影响文字可读性；
- 不使用图片资源；
- 不增加复杂 DOM；
- 不让低端机出现明显性能问题。

------

# 七、无障碍与可用性

每个可点击区域增加合理的：

```xml
aria-role="button"
aria-label="每组 10 道"
```

要求：

1. 点击区域至少约 88rpx 高。
2. 选中状态不能只靠颜色，必须有勾选或文字标识。
3. 字号不能过小。
4. 深色文字与荧光背景保持足够对比。
5. 操作按钮不能贴近底部安全区。
6. 横屏或矮屏设备上弹层内容不能超出屏幕。
7. 必要时弹层主体允许纵向滚动，但正常手机不应需要滚动。
8. 打开弹层时，底层“开始今日复习”按钮不能被点击。

------

# 八、状态与业务逻辑约束

不要破坏此前已有的每组题数功能：

```js
[5, 10, 20, 30]
```

顺序必须保持：

```text
5、10、20、30
```

并继续满足：

1. 用户确认后更新 `reviewBatchSize`。
2. 第一次开始复习请求使用最新选择。
3. 下一组请求使用最新选择。
4. 用户主动选择后，不被接口概览刷新覆盖。
5. 取消弹层不修改当前选择。
6. 非 overview 阶段不能修改。
7. `isStarting` 时不能重复操作。
8. 非法值仍通过已有 `normalizeReviewBatchSize` 回退。
9. 不修改后端接口。
10. 不改变题目分组逻辑。

如果此前已经实现：

```js
showBatchSizeSelector()
```

请将它改为打开自定义弹层，或替换为语义更清晰的方法。

清理已经不再使用的 `wx.showActionSheet` 代码，避免保留两套选择逻辑。

------

# 九、回归测试

新增或扩展：

```text
scripts/test-review-today-interactions.js
```

至少覆盖：

## 结构检查

1. WXML 中存在自定义弹层遮罩。
2. WXML 中存在自定义底部弹层。
3. 不再调用 `wx.showActionSheet`。
4. 选项通过 `[5, 10, 20, 30]` 渲染。
5. 存在取消按钮。
6. 存在确认按钮。
7. 存在当前选中态 class。
8. 确认按钮具有独立强调 class。

## 状态检查

1. 打开弹层时：

```js
showBatchSizeSheet === true
```

1. 打开时 `pendingBatchSize` 等于当前 `reviewBatchSize`。
2. 点击选项只修改 `pendingBatchSize`。
3. 点击取消不修改 `reviewBatchSize`。
4. 点击确认后正式更新 `reviewBatchSize`。
5. 确认后设置用户主动选择标记。
6. 点击遮罩关闭弹层。
7. 点击弹层内容不会触发遮罩关闭。
8. 非 overview 阶段不能打开。
9. `isStarting === true` 时不能打开。
10. 非法临时值不能被确认。

## 业务回归

1. 选择 5 后开始请求传 5。
2. 选择 20 后下一组请求传 20。
3. 用户选择 30 后刷新概览仍保持 30。
4. 未主动选择时接口合法值仍可初始化页面。
5. 取消后请求仍使用原值。

## 样式检查

1. 遮罩使用 fixed 定位和明确 z-index。
2. 弹层包含底部安全区适配。
3. 弹层有顶部圆角。
4. 当前选项存在明确背景或边框变化。
5. 确认按钮存在稳定 `background-color`。
6. 原生 button 的局部 `::after` 边框已处理。
7. 不允许通过全局 button 样式完成本次美化。
8. 不能只靠 CSS 变量且没有回退色。
9. 底层页面不会因为遮罩而发生点击穿透。

------

# 十、运行测试

完成后运行：

```bash
node scripts/test-review-today-interactions.js
```

然后运行全部已有测试：

```bash
for f in scripts/test-*.js; do
  echo "== $f =="
  node "$f" || exit 1
done
```

如果项目存在 lint、类型检查或微信小程序构建检查，也一并运行。

同时检查编译输出中是否存在：

- WXML 事件方法不存在；
- WXSS 不支持的选择器；
- `env(safe-area-inset-bottom)` 使用错误；
- `wx:for` key 警告；
- class 动态拼接错误；
- 页面层级遮挡问题。

------

# 十一、约束

- 不引入新的 npm 依赖。
- 不使用第三方弹窗组件。
- 不修改后端接口。
- 不改变题目分组规则。
- 不重做整个 review-today 页面。
- 不使用图片模拟弹层。
- 不继续使用无法定制的原生 `wx.showActionSheet`。
- 不在 app.wxss 中添加全局弹层或 button 覆盖。
- 不破坏原有“开始今日复习”功能。
- 不破坏用户批量选择的持久优先级。
- 动画保持轻量，兼容微信真机。
- 修改应局部、清晰，并添加必要注释。

完成后请输出：

1. 当前弹层体验问题和根因。
2. 修改过的文件列表。
3. 自定义弹层的结构说明。
4. 临时选择与正式选择的状态流转。
5. 视觉设计说明。
6. 真机安全区和点击穿透处理。
7. 新增或修改的测试用例。
8. 实际执行的测试命令和结果。
9. 尚未能自动验证的真机视觉风险。

```

```