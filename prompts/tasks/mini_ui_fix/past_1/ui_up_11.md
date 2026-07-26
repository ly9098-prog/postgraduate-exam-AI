请直接检查并修改当前微信小程序项目，修复：

- pages/review-today/review-today

自定义“每组题数”底部弹层中，底部“确认使用”按钮向右溢出弹层、超出白色卡片边界，并在真机屏幕右侧被裁切的问题。

不要只给修改建议，需要实际修改 WXML、WXSS，必要时调整少量 JS，并补充回归测试、运行测试。

---

# 一、问题表现

根据当前真机截图：

1. 底部白色弹层本身左右留有正常边距。
2. 左侧“取消”按钮位于弹层内部。
3. 右侧绿色“确认使用”按钮明显向右超出白色弹层。
4. 按钮一直延伸到设备屏幕右边缘，并被屏幕裁切。
5. 两个按钮宽度、间距和弹层内容宽度不匹配。
6. 问题重点是布局计算错误，不是按钮背景色问题。

目标效果：

```text
┌──────────────────────────┐
│                          │
│ [      取消      ] [   确认使用   ] │
│                          │
└──────────────────────────┘
```

两个按钮必须完整位于弹层内容区域内：

- 左右边缘与上方选项卡片对齐；
- 中间保留合理间距；
- 不超过弹层右边界；
- 不接触设备屏幕边缘；
- 不被裁切；
- 在不同尺寸真机上稳定显示。

------

# 二、先定位实际结构

重点检查：

- pages/review-today/review-today.wxml
- pages/review-today/review-today.wxss
- pages/review-today/review-today.js

搜索以下 class 或文案：

```text
取消
确认使用
batch-sheet
batch-sheet-actions
batch-sheet-action
batch-sheet-cancel
batch-sheet-confirm
```

确认底部操作区实际使用的是：

- `<button>`
- `<view>`
- flex 布局
- grid 布局
- 固定宽度
- 百分比宽度
- `calc(...)`
- 绝对定位

不要仅根据建议中的 class 名修改，必须以项目当前真实代码为准。

------

# 三、重点排查根因

## 1. 两个按钮宽度之和超过父容器

重点检查是否存在类似写法：

```css
.action-button {
  width: 50%;
}
```

同时父容器又设置了：

```css
gap: 16rpx;
```

两个 `50%` 按钮再加 gap 后，总宽度会大于父容器：

```text
50% + 50% + gap > 100%
```

这很可能是当前溢出的直接原因。

也要检查：

```css
width: 320rpx;
width: 360rpx;
width: 50vw;
width: calc(50% - ...);
min-width: ...
```

以及确认按钮是否单独设置了过大的固定宽度。

修复后不要让两个按钮依赖彼此独立计算的固定宽度。

------

## 2. 推荐使用稳定 flex 分配

底部操作区优先使用：

```css
.batch-sheet-actions {
  display: flex;
  align-items: center;
  gap: 16rpx;
  width: 100%;
  box-sizing: border-box;
}

.batch-sheet-action {
  flex: 1 1 0;
  min-width: 0;
  width: auto;
  box-sizing: border-box;
}
```

关键要求：

- 两个按钮都使用 `flex: 1 1 0`；
- 子元素增加 `min-width: 0`；
- 不再设置 `width: 50%`；
- 不再设置会超过父容器的固定宽度；
- gap 由父容器统一控制；
- 按钮的 padding 和 border 必须计入自身宽度。

如果产品设计希望确认按钮稍宽，可以使用：

```css
.batch-sheet-cancel {
  flex: 0.9 1 0;
}

.batch-sheet-confirm {
  flex: 1.1 1 0;
}
```

但两者必须仍然完全位于父容器内部。

不要通过负 margin、translateX 或绝对定位实现宽度差异。

------

## 3. 检查原生 button 默认宽度

如果使用微信小程序原生 `<button>`，需要局部重置其默认行为：

```css
.batch-sheet-action {
  margin: 0;
  padding: 0 24rpx;
  width: auto;
  min-width: 0;
  box-sizing: border-box;
  line-height: normal;
}

.batch-sheet-action::after {
  border: 0;
}
```

检查当前是否存在：

```css
button {
  width: 100%;
}
```

或页面内其他通用规则导致确认按钮强制占满整行。

不要在 `app.wxss` 中修改全局 button。

本次修复只能作用于当前底部弹层的按钮 class。

------

## 4. 检查弹层自身的盒模型

确认白色弹层的宽度、左右定位和 padding 不会叠加溢出。

如果当前写法类似：

```css
.batch-sheet {
  left: 24rpx;
  right: 24rpx;
  width: 100%;
  padding: 28rpx;
}
```

则 `left + right + width:100%` 会导致整体宽度超过屏幕。

使用 `left/right` 定位时，不应再设置 `width: 100%`：

```css
.batch-sheet {
  position: absolute;
  left: 24rpx;
  right: 24rpx;
  bottom: ...;
  box-sizing: border-box;
}
```

或者使用：

```css
.batch-sheet {
  width: calc(100% - 48rpx);
  margin: 0 auto;
  box-sizing: border-box;
}
```

两种方案选一种，不要混用。

同时检查弹层内容容器是否出现：

```css
width: 100%;
padding-left: ...;
padding-right: ...;
```

但没有：

```css
box-sizing: border-box;
```

弹层以及关键内容容器统一使用：

```css
box-sizing: border-box;
```

------

## 5. 检查确认按钮的特殊定位

确认按钮不得使用以下方式撑出卡片：

```css
position: absolute;
right: -24rpx;
transform: translateX(...);
margin-right: -...;
width: calc(100% + ...);
```

如果存在，请移除。

确认按钮背景必须直接绘制在按钮自身，不要通过超宽伪元素实现：

```css
::before
::after
```

不要使用 `overflow: hidden` 简单裁掉超出部分来伪修复。

正确结果必须是按钮本身尺寸就处于弹层内部，而不是超出后被隐藏。

------

# 四、目标布局要求

## 1. 操作区

底部操作区必须满足：

1. 总宽度等于弹层内容宽度。
2. 左右边缘与上方选项卡片对齐。
3. 两个按钮在同一行。
4. 两个按钮之间保留约 `12rpx～20rpx` 间距。
5. 两个按钮都不能换行。
6. 两个按钮文字不能被压缩或截断。
7. 窄屏下不能横向滚动。
8. 不使用 `100vw` 或 `50vw` 计算按钮宽度。

推荐结构：

```xml
<view class="batch-sheet-actions">
  <button
    class="batch-sheet-action batch-sheet-cancel"
    bindtap="closeBatchSizeSheet"
  >
    取消
  </button>

  <button
    class="batch-sheet-action batch-sheet-confirm"
    bindtap="confirmBatchSize"
  >
    确认使用
  </button>
</view>
```

保留项目已有方法名和业务逻辑，不要为了样式修复随意重命名事件。

------

## 2. 建议样式

根据项目真实 class 进行调整，可参考：

```css
.batch-sheet-actions {
  display: flex;
  align-items: stretch;
  width: 100%;
  gap: 16rpx;
  margin-top: 18rpx;
  box-sizing: border-box;
}

.batch-sheet-action {
  flex: 1 1 0;
  min-width: 0;
  width: auto;
  height: 82rpx;
  margin: 0;
  padding: 0 20rpx;
  border: 0;
  border-radius: 20rpx;
  box-sizing: border-box;
  font-size: 28rpx;
  font-weight: 600;
  line-height: 82rpx;
  text-align: center;
}

.batch-sheet-action::after {
  border: 0;
}

.batch-sheet-cancel {
  background-color: #eef1e9;
  color: #365044;
  border: 2rpx solid rgba(34, 67, 49, 0.1);
}

.batch-sheet-confirm {
  background-color: #aaf20f;
  background-image: linear-gradient(135deg, #aaf20f, #baf91b);
  color: #12351f;
}
```

具体色值优先复用当前页面已有配色。

确认按钮必须保留稳定的纯色回退：

```css
background-color: ...
```

不能只依赖渐变。

------

# 五、窄屏和真机适配

至少考虑以下设备宽度：

```text
320px
360px
375px
390px
414px
```

要求：

1. 320px 窄屏下两个按钮仍完整显示。
2. 弹层右边缘与左边缘保持对称。
3. 确认按钮不能延伸到屏幕边缘。
4. 按钮文字“确认使用”不能换行。
5. 页面缩放或系统字体稍大时不能横向溢出。
6. iPhone 底部 Home Indicator 安全区不能挤压操作按钮。
7. Android 真机不能因为原生 button 默认样式改变宽度。
8. 弹层最大宽度需要适配平板或大屏，但手机上优先使用左右固定边距。

可以为弹层增加：

```css
max-width: 720rpx;
```

但不要使用会让普通手机计算异常的固定像素宽度。

------

# 六、不要破坏现有功能

本次修复只处理布局和必要的局部结构，不得破坏：

- 5、10、20、30 道选择；
- 当前选中状态；
- “推荐”标记；
- 勾选图标；
- 临时选择 `pendingBatchSize`；
- 点击取消不保存；
- 点击确认后更新 `reviewBatchSize`；
- 遮罩点击关闭；
- 点击弹层内部不穿透；
- 用户主动选择后不被接口刷新覆盖；
- 开始今日复习请求使用最新题数；
- 下一组请求使用最新题数。

不要重新实现整套弹层业务逻辑。

如果只需修改 WXSS 即可修复，不要无意义修改 JS。

------

# 七、视觉微调

在解决溢出的基础上，同时检查：

1. “取消”和“确认使用”按钮高度一致。
2. 两个按钮圆角一致。
3. 两个按钮文字垂直居中。
4. 确认按钮不能比弹层圆角区域更宽。
5. 操作区与“当前选择：每组 10 道”之间留白合理。
6. 按钮左右边缘与选项网格边缘对齐。
7. 确认按钮按压态不能再次扩宽或位移。

按压反馈可以改变透明度或轻微缩放：

```css
.batch-sheet-action--pressed {
  opacity: 0.88;
}
```

如果使用缩放，必须以按钮自身中心缩放，且不能导致布局溢出。

不要使用改变 width、margin 或 padding 的按压状态。

------

# 八、回归测试

请扩展现有：

```text
scripts/test-review-today-interactions.js
```

如果现有文件不适合，可以新增：

```text
scripts/test-review-today-batch-sheet-layout.js
```

至少覆盖以下静态检查：

1. WXML 中仍存在“取消”按钮。
2. WXML 中仍存在“确认使用”按钮。
3. 两个按钮位于同一个操作区父容器内。
4. 操作区使用 flex 或等价的稳定双列布局。
5. 两个按钮使用 `flex` 分配宽度。
6. 按钮存在 `min-width: 0`。
7. 按钮存在 `box-sizing: border-box`。
8. 操作区存在 `width: 100%` 和 `box-sizing: border-box`。
9. 不允许两个按钮同时使用 `width: 50%` 再配合非零 gap。
10. 确认按钮不能使用：
    - `width: 100vw`
    - `width: 50vw`
    - 过大的固定宽度
    - 负 `margin-right`
    - `right` 负值
    - 横向 `translate`
11. 弹层使用 `left/right` 时不能同时使用 `width: 100%`。
12. 不允许通过 `overflow: hidden` 作为唯一修复方案。
13. 原生 button 的局部 `::after` 边框仍被处理。
14. 确认按钮具有稳定的 `background-color`。
15. 事件绑定仍指向原来的取消和确认方法。
16. 题数选择的业务测试继续通过。

如果测试采用正则静态检查，请避免过度依赖空格和格式，确保代码格式调整后测试仍稳定。

------

# 九、运行测试

完成后运行：

```bash
node scripts/test-review-today-interactions.js
```

如果新增了单独测试，也运行：

```bash
node scripts/test-review-today-batch-sheet-layout.js
```

然后运行全部已有测试：

```bash
for f in scripts/test-*.js; do
  echo "== $f =="
  node "$f" || exit 1
done
```

如果项目存在 lint、类型检查或微信小程序构建检查，也一并运行。

检查编译输出中是否存在：

- WXSS 不支持的属性；
- WXML 标签未闭合；
- class 名不匹配；
- 事件方法不存在；
- 原生 button 默认 margin；
- 弹层横向溢出；
- 页面出现横向滚动条。

------

# 十、验收标准

必须人工或通过开发者工具至少确认：

1. “确认使用”按钮完整显示在白色弹层内。
2. 按钮右边缘与弹层右侧内边距之间有清晰留白。
3. 按钮不再延伸到设备屏幕右侧。
4. “取消”和“确认使用”按钮在同一行。
5. 两个按钮之间间距正常。
6. 两个按钮宽度视觉均衡。
7. 320px 窄屏下不溢出。
8. 375px 和 390px 屏幕下不溢出。
9. iOS 和 Android 真机均不依赖偶然的裁切效果。
10. 弹层其他选项、文字和交互保持正常。

最终效果不允许通过把超出部分隐藏来达成，必须真正修正按钮和父容器的宽度计算。

------

# 十一、约束

- 不修改后端接口。
- 不修改每组题数业务规则。
- 不引入新的 npm 依赖。
- 不重做整个弹层设计。
- 不删除“推荐”和选中状态。
- 不使用负 margin 修补位置。
- 不使用绝对定位摆放两个操作按钮。
- 不使用 `100vw` 作为弹层内部元素宽度。
- 不通过 `overflow: hidden` 掩盖错误。
- 不在 `app.wxss` 中全局覆盖 button。
- 不破坏安全区适配。
- 修改应尽量局部、清晰，并添加必要注释。

完成后请输出：

1. 根因分析。
2. 修改过的文件列表。
3. 原来是哪条宽度或定位规则导致溢出。
4. 修复后的按钮宽度分配方式。
5. 弹层和按钮的盒模型处理。
6. 窄屏及真机兼容处理。
7. 新增或修改的测试。
8. 实际运行的测试命令和结果。
9. 尚未能自动验证的真机风险。

```

```