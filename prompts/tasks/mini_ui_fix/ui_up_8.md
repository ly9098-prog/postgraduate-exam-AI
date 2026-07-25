请直接检查并修改当前微信小程序项目，修复 `pages/pomodoro` 中结束自由计时确认弹窗的“确认结束”按钮在真机上只显示文字、没有按钮背景色的问题。

不要只给修改建议，需要实际编辑代码、补充回归检查并运行测试。

## 问题表现

在自由计时结束确认弹窗中：

- “继续计时”按钮背景正常显示；
- “确认结束”按钮在真机上仅显示白色文字；
- 按钮原本应有明显的强调色背景；
- 微信开发者工具中的表现可能与真机不同。

弹窗文案包括：

```text
结束自由计时？
当前计时时长较短，确认后仍会结束本次
继续计时
确认结束
```

请先通过这些文案定位真实实现位置，不要仅凭文件名猜测。

## 重点检查文件

主要检查：

- pages/pomodoro/pomodoro.wxml
- pages/pomodoro/pomodoro.wxss
- pages/pomodoro/pomodoro.js
- pages/pomodoro/pomodoro.json
- app.wxss

如果弹窗由公共组件实现，还需要继续检查对应组件的：

- `.wxml`
- `.wxss`
- `.js`
- `.json`

请搜索：

```text
结束自由计时
确认结束
继续计时
```

确认按钮实际使用的是：

- 原生 `<button>`
- `<view>`
- 公共弹窗组件
- 第三方组件

然后根据真实结构修复。

------

# 一、分析并修复按钮背景丢失原因

重点排查以下真机兼容问题。

## 1. class 是否真正命中

检查 WXML 中“确认结束”按钮的实际 class 与 WXSS 选择器是否完全一致。

例如排查：

```xml
class="modal-btn {{condition ? 'confirm-btn' : ''}}"
```

是否因为条件、字符串拼接、状态更新或命名不一致，导致真机上没有应用强调按钮 class。

不能通过给弹窗内所有按钮统一增加背景来掩盖问题，必须确认“确认结束”按钮拥有独立、稳定的 class。

建议使用明确 class，例如：

```xml
<button class="timer-dialog-btn timer-dialog-btn--confirm">
  确认结束
</button>
```

实际命名请遵循项目现有风格。

## 2. 原生 button 的 plain 属性

如果按钮使用了：

```xml
<button plain>
```

或动态 `plain` 属性，请检查它是否导致真机强制使用透明背景。

“确认结束”按钮不应依赖 `plain` 按钮样式实现强调背景。

如果业务必须保留 `plain`，需要使用足够明确的局部选择器覆盖，例如：

```css
.timer-dialog-btn--confirm[plain] {
  background-color: ...;
}
```

但优先移除不必要的 `plain` 属性。

## 3. 微信原生 button 默认样式和伪元素

原生 `<button>` 在真机上存在默认样式和 `::after` 边框。

对弹窗按钮做局部重置，至少确认：

```css
.timer-dialog-btn {
  margin: 0;
  padding: 0;
  border: 0;
  line-height: normal;
  box-sizing: border-box;
}

.timer-dialog-btn::after {
  border: 0;
}
```

不要在 `app.wxss` 中粗暴修改所有 button，避免影响项目其他页面。

## 4. CSS 变量或背景表达式失效

检查按钮背景是否仅依赖类似写法：

```css
background: var(--primary-button-bg);
```

如果 CSS 变量未定义、作用域不正确，或真机没有读取到变量，整个 `background` 声明可能失效。

需要提供稳定回退值，例如：

```css
background-color: #16c784;
background-color: var(--pomodoro-confirm-bg, #16c784);
```

如果使用渐变，需要同时提供纯色回退：

```css
background-color: #16c784;
background-image: linear-gradient(...);
```

不要只依赖：

- 未定义的 CSS 自定义变量；
- 不稳定的嵌套变量；
- 不兼容的颜色函数；
- 仅在开发者工具中正常的实验性 CSS。

检查是否使用了以下可能存在真机兼容问题的写法：

```css
color-mix(...)
rgb(... / ...)
oklch(...)
lab(...)
```

若存在，请替换为微信小程序真机稳定支持的 `#RRGGBB` 或 `rgba()`。

## 5. background 被后续规则覆盖

检查完整 WXSS 优先级，尤其是：

```css
button {}
.modal button {}
.dialog-btn {}
button[plain] {}
button[disabled] {}
.confirm-btn {}
```

确认强调按钮背景没有被后面的规则覆盖为：

```css
background: transparent;
background-color: transparent;
background: none;
opacity: 0;
```

优先通过更清晰的局部选择器和规则顺序修复，不要无条件堆叠多个 `!important`。

只有确认是微信原生属性样式优先级问题时，才允许对背景色使用一次局部 `!important`，并添加注释说明原因。

## 6. disabled、loading 和状态 class

检查确认按钮是否在弹窗显示时被错误设置为：

```xml
disabled
loading
```

或者拥有类似：

```text
disabled
inactive
transparent
ghost
plain
```

的状态 class。

确认按钮在可点击状态下必须：

- 有强调背景；
- 有清晰文字颜色；
- 不透明；
- 能正常触发确认事件。

请求提交期间可以禁用，但禁用状态也不能让按钮背景完全消失。应保留按钮轮廓并降低透明度，例如：

```css
.timer-dialog-btn--confirm[disabled] {
  opacity: 0.6;
}
```

## 7. 层级与遮挡

检查按钮背景是否由绝对定位伪元素实现。

如果背景放在：

```css
::before
::after
```

中，可能因为：

- `z-index`；
- `overflow: hidden`；
- stacking context；
- 伪元素尺寸；
- 真机合成层；

导致背景不可见。

优先直接将背景色设置在按钮元素本身，不要依赖伪元素绘制主要背景。

同时检查是否存在覆盖在按钮上方的透明元素。不能只提升文字 `z-index`，要保证整个按钮可见且可点击。

------

# 二、目标视觉效果

“确认结束”按钮需要保持当前弹窗设计语言，并满足：

1. 有清晰可见的强调色背景。
2. 与“继续计时”次级按钮能够明显区分。
3. 按钮高度、圆角、宽度与现有布局保持一致。
4. 文字在背景上有足够对比度。
5. iOS 和 Android 真机均不依赖系统主题色。
6. 深色模式下不能变成透明背景。
7. 按压时有轻微反馈，但按压后背景不能消失。
8. 禁用状态保留背景轮廓。
9. 不修改弹窗文案和业务逻辑。
10. 不重做页面整体设计。

可以采用项目现有绿色强调色，例如：

```css
.timer-dialog-btn--confirm {
  background-color: #19c98b;
  color: #071a13;
}
```

具体色值优先复用项目中已有、且真机已验证正常显示的主题色。

如果设计要求白色文字，需要保证绿色背景足够深。

------

# 三、事件和交互回归

确认修复样式时不能破坏已有行为：

- 点击“继续计时”关闭弹窗并继续计时；
- 点击“确认结束”正常结束当前自由计时；
- 快速重复点击时不能重复提交；
- 弹窗遮罩仍能阻止点击后方页面；
- 按钮区域不能被透明元素遮挡；
- 计时器暂停、恢复和结束逻辑不能改变；
- 番茄钟模式和自由计时模式的其他按钮不能被全局样式影响。

请检查按钮绑定事件，例如：

```xml
bindtap
catchtap
```

确保修改标签或结构后事件仍然绑定到正确方法。

如果当前使用 `<view>`，没有必要仅为修复背景而改成 `<button>`；如果当前使用 `<button>`，也不要无理由改成 `<view>`。

------

# 四、增加回归检查

请新增或扩展 Node 静态回归测试，例如：

```text
scripts/test-pomodoro-end-dialog-style.js
```

至少验证：

1. 能定位“确认结束”按钮。
2. 确认按钮拥有独立的强调按钮 class。
3. 对应 WXSS 中存在明确的 `background-color` 或稳定的背景回退。
4. 不能只使用无回退值的 `var(...)` 作为背景。
5. 确认按钮样式中不能是：
   - `background: transparent`
   - `background: none`
   - `background-color: transparent`
6. 原生 button 的局部 `::after` 边框已处理。
7. 不允许通过全局 `button { ... }` 影响整个小程序来修复。
8. “继续计时”和“确认结束”仍绑定原有事件。
9. 确认按钮不能永久带有 `disabled` 属性。
10. 弹窗文字和两个操作按钮仍存在。
11. 项目中不存在仅通过伪元素绘制确认按钮主要背景的实现。
12. WXML 和 WXSS 中的确认按钮 class 名能够对应。

如果项目已有适合的页面测试框架，优先使用现有框架，不引入新依赖。

------

# 五、测试与检查

完成后运行新增测试：

```bash
node scripts/test-pomodoro-end-dialog-style.js
```

再运行全部已有测试：

```bash
for f in scripts/test-*.js; do
  echo "== $f =="
  node "$f" || exit 1
done
```

如果项目存在以下命令，也请运行：

- lint
- type check
- 微信小程序构建检查

同时检查编译输出中是否存在：

- WXSS 非法选择器；
- 不支持的 CSS 属性；
- 未定义样式变量；
- WXML class 拼接错误；
- 事件处理方法不存在。

------

# 六、约束

- 不修改后端接口。
- 不修改计时数据结构。
- 不引入新的 npm 依赖。
- 不重做弹窗布局。
- 不通过截图背景或图片模拟按钮。
- 不通过隐藏问题文字来伪修复。
- 不在 `app.wxss` 中粗暴覆盖所有原生 button。
- 不破坏其他页面按钮样式。
- 不使用仅在浏览器支持、微信真机不稳定的 CSS。
- 优先使用明确的 `background-color` 和局部选择器。
- 修改应尽量局部、清晰，并为真机兼容处理添加简短注释。

完成后请输出：

1. 根因分析。
2. 修改过的文件列表。
3. 真机与开发者工具表现不同的具体原因。
4. 最终按钮背景样式及其兼容回退。
5. 是否涉及 `plain`、`disabled`、CSS 变量或原生 button 伪元素。
6. 新增的回归测试。
7. 实际运行的测试命令和结果。
8. 尚未能自动验证的真机风险。

