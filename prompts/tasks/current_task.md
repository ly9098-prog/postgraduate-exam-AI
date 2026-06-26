# 小程序渲染修复任务

你是一名资深微信小程序前端工程师。请直接检查并修改当前项目中的题干渲染代码，解决 practice 页面及其他共用题干渲染页面的重复题干、文字与代码混排异常、行内公式原样显示、压缩代码不换行、长代码被截断等问题。

不要只给出分析或修改建议，请直接完成代码修改、测试更新和回归验证。

一、项目中已经确认的问题

主要相关文件：

- utils/stem-render.js
- utils/code-reconstructor.js
- pages/practice/practice.js
- pages/practice/practice.wxml
- pages/practice/practice.wxss
- pages/review-today/review-today.wxml
- pages/review-today/review-today.wxss
- pages/wrong-detail/wrong-detail.wxml
- pages/wrong-detail/wrong-detail.wxss
- tests/test-code-mode.js
- tests/test-render-invariant.js
- tests/render_regression/*.json
- tests/render_regression/run.js

当前问题如下。

1. 题干重复

例如接口题干可能为：

在线性表 $a_0,a_1,\ldots,a_{100}$ 中，删除元素 a50 需要移动多少个元素。
在线性表 a₀,a₁,…,a₁₀₀ 中，删除元素 a50 需要移动多少个元素。

两段原始字符串可能因为 LaTeX、HTML、空格、标点或实体不同而无法被现有去重函数识别，但最终渲染后肉眼看起来完全相同。

当前 `_cleanStemText()` 中：

```js
_deduplicateRepeatedText(_deduplicateLines(stemText))
```

存在两个问题：

- 去重发生在 HTML、LaTeX、空格和标点规范化之前。
- `_deduplicateLines()` 使用 `trim()` 比较相邻行，会错误删除代码中的合法重复行。

例如下面两行不能被删除任何一行：

```c
  }
}
```

1. 整道题被误判为 CODE

当前 `buildRenderModel()` 对整个题干调用 `containsCode(cleanedStem)`。

对于以下混合题干：

```text
下列算法中加下划线语句的执行次数为（ ）。

int m = 0, i, j;
for (i = 1; i <= n; i++)
    for (j = 1; j <= 2 * i; j++)
        m++;
```

只要后面的代码达到 CODE 阈值，整道题都会进入 CODE 模式，造成：

- 普通题目说明进入灰色代码框。
- 字体全部变成等宽字体。
- 行内公式不再转换。
- 题目说明和程序代码无法使用不同的渲染方式。

1. 行内公式原样显示

例如：

```text
两个进程 $P_{0}$、$P_{1}$ 互斥的 Peterson 算法如下
```

当前整题进入 CODE 模式后使用：

```js
rawText = cleanedStem
```

所以页面直接显示 `$P_{0}$`、`$P_{1}$`，而不是 `P₀`、`P₁` 或正确的公式效果。

1. 压缩代码全部显示在一行

项目中已经有 `reconstructCode()`，但当前渲染流程完全不调用它，测试甚至强制要求压缩代码保持一行。

例如：

```c
void f(){int sum=0;for(int i=0;i<n;i++)sum++;}
```

会一直显示为单行。

需要改成：仅对明确属于代码块、且明显是 OCR 或导入压缩结果的代码进行保守换行恢复；已经有合理换行和缩进的代码必须保持原样。

1. 长代码横向截断

当前 WXML 使用：

```xml
<view class="code-wrapper">
  <text class="code-text">{{rawText}}</text>
</view>
```

WXSS 使用：

```css
.code-wrapper {
  overflow-x: auto;
}

.code-text {
  white-space: pre;
}
```

普通 `view` 的横向滚动在微信小程序中不可靠，长代码容易超出容器或被截断。应使用原生 `scroll-view scroll-x`。

二、总体修改目标

请重构题干渲染流程，支持：

1. 纯文字题干。
2. 纯 LaTeX 题干。
3. 纯代码题干。
4. 文字、行内公式、复杂 LaTeX 和代码混合的题干。
5. OCR 或导入导致的重复题干。
6. OCR 或导入导致的单行压缩代码。
7. 长代码在手机屏幕中完整横向滚动查看。
8. 保留现有选项剥离、数学符号转换、SEGMENTS 模式和 Render Guard 功能。

三、必须实现的架构修改

1. 新增 MIXED 渲染模式

在 `utils/stem-render.js` 的 `RENDER_MODE` 中新增：

```js
MIXED: 'MIXED'
```

RenderModel 增加：

```js
blocks: []
```

MIXED 模式的数据结构建议如下：

```js
{
  mode: 'MIXED',
  blocks: [
    {
      type: 'RICH_TEXT',
      richTextNodes: [...]
    },
    {
      type: 'LATEX',
      html: '...'
    },
    {
      type: 'CODE',
      rawText: '...'
    }
  ]
}
```

可以根据项目实际情况调整字段，但必须满足：

- 题目说明和代码分别渲染。
- 简单行内公式在普通文字块中转换。
- 复杂 LaTeX 使用现有 mp-html 渲染。
- 代码块走零 HTML 的 `<text>` 路径。
- 纯代码题仍然可以保留 CODE 模式。
- 纯文本、纯 LaTeX、SEGMENTS 的现有行为不能被破坏。
- 整个题目仍然只有一个顶层 render mode，MIXED 内部允许多个 block。

1. 增加混合题干分块逻辑

请实现独立、可测试的分块函数，例如：

```js
splitStemBlocks(text)
```

不要简单地根据整段文本是否包含 `for`、`int` 或分号就判定整道题为代码。

分块规则必须保守并至少支持：

- Markdown 围栏代码：

~~~text
题目说明

```c
int x = 0;
- 普通多行代码，没有围栏。
- 题目说明后接代码块。
- OCR 把题目说明和代码压在同一行的情况。
- 连续代码行应合并为一个代码块。
- 空行应作为文字块和代码块的自然边界。
- 自然语言中偶尔出现 `P_0`、`for`、`int` 等单词时不能轻易误判为代码。
- 代码中的注释、字符串、括号、花括号、分号、缩进应尽量保留。

对于同一行文字后出现明显代码起点的情况，例如：

```text
下列程序的时间复杂度是（ ）。 int m=0; for(i=0;i<n;i++) m++;
~~~

应尽量分为：

- 普通文字块：`下列程序的时间复杂度是（ ）。`
- 代码块：`int m=0; for(i=0;i<n;i++) m++;`

不要把整行全部放进 CODE。

1. 修复题干去重

请重新设计 `_cleanStemText()` 中的去重流程。

要求：

- 统一 `\r\n`、`\r` 为 `\n`。
- 只删除题干整体重复或相邻完整段落重复。
- 禁止继续对全部相邻行执行 `trim()` 后去重。
- 代码块不能参与普通文本逐行去重。
- 不能删除代码中的重复 `}`、`else`、空行或其他合法结构。
- 去重比较前，需要生成仅用于比较的 canonical 文本，但最终输出应尽量保留原始格式。

canonical 比较至少规范化：

- HTML 标签。
- `<br>`。
- ` `、`&`、`<`、`>` 等基础实体。
- 简单行内 LaTeX，例如 `$P_{0}$`、`$a_1$`。
- Unicode 下标和对应简单 LaTeX。
- 连续空白。
- 全角与半角的常见逗号、句号。
- 段落首尾空白。

只允许删除 canonical 内容一致的完整重复段落或完整重复题干，不能因某一行相同就删除该行。

例如以下内容最终只能显示一次：

```text
在线性表 $a_0,a_1,\ldots,a_{100}$ 中，删除元素 a50 需要移动多少个元素。

在线性表 a₀,a₁,…,a₁₀₀ 中，删除元素 a50 需要移动多少个元素。
```

以下代码必须完整保留：

```c
if (x) {
  if (y) {
    run();
  }
}
```

1. 保守恢复压缩代码

允许复用和改进 `utils/code-reconstructor.js`，但必须采用保守策略。

增加类似：

```js
shouldReconstructCode(text)
```

仅在以下情况同时满足时恢复结构：

- 当前 block 已经明确被识别为代码。
- 换行数量很少，例如 0 或 1。
- 存在多个语句、分号、控制流或花括号。
- 明显属于压缩代码，而不是普通文字。

要求：

- 已经正确换行和缩进的多行代码原样保留。
- 不要默认修改运算符语义。
- 默认不要自动把 `< =` 改成 `<=`、`+ +` 改成 `++`，除非有非常确定的规则和对应测试。
- 恢复换行时不能拆开 `for(init; condition; step)` 内部的分号。
- 不能拆开字符串中的分号、花括号或关键字。
- 尽量保留原有代码内容，只恢复必要的换行。
- 检查微信小程序 JavaScript 运行环境兼容性，不要让实际运行路径依赖不兼容的正则 lookbehind。若现有 `code-reconstructor.js` 使用 lookbehind，请改写成兼容实现。

示例：

输入：

```c
void f(){int sum=0;for(int i=0;i<n;i++)sum++;}
```

输出应类似：

```c
void f(){
int sum=0;
for(int i=0;i<n;i++)
sum++;
}
```

是否增加缩进可以保守处理，重点是不能全部挤在一行，也不能改变代码语义。

1. 修改 WXML

以下所有页面都使用了统一的 `buildRenderModel()`，必须同步支持 MIXED：

- pages/practice/practice.wxml
- pages/review-today/review-today.wxml
- pages/wrong-detail/wrong-detail.wxml

MIXED 分支参考结构：

```xml
<block wx:elif="{{renderModel.mode === 'MIXED'}}">
  <block wx:for="{{renderModel.blocks}}" wx:key="index">
    <rich-text
      wx:if="{{item.type === 'RICH_TEXT'}}"
      class="q-content mixed-text-block"
      nodes="{{item.richTextNodes}}"
    />

    <mp-html
      wx:elif="{{item.type === 'LATEX'}}"
      class="q-content mixed-latex-block"
      content="{{item.html}}"
      lazy-load
    />

    <scroll-view
      wx:elif="{{item.type === 'CODE'}}"
      scroll-x
      class="code-wrapper mixed-code-block"
    >
      <text decode="false" class="code-text">{{item.rawText}}</text>
    </scroll-view>
  </block>
</block>
```

请根据每个页面实际变量名修改，不能直接机械复制错误变量。

纯 CODE 分支也要从普通 `view` 改为：

```xml
<scroll-view scroll-x class="code-wrapper">
  <text decode="false" class="code-text">{{...}}</text>
</scroll-view>
```

1. 修改 WXSS

在 practice、review-today、wrong-detail 中同步修复代码样式。

要求：

- `scroll-view` 宽度不能超出父容器。
- 必须能够横向滚动。
- 保留缩进和换行。
- 长代码不能被裁剪。
- 普通题目文字不能使用等宽字体或灰色代码背景。
- 混合模式中不同 block 之间间距自然。
- 避免每一个普通文字 block 都产生过大的 `margin-bottom`。

参考：

```css
.code-wrapper {
  display: block;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  background: #F5F6FA;
  border-radius: 12rpx;
  padding: 24rpx 20rpx;
  margin: 16rpx 0 28rpx;
  overflow: hidden;
}

.code-text {
  display: inline-block;
  min-width: 100%;
  box-sizing: border-box;
  white-space: pre;
  font-family: 'Courier New', Courier, monospace;
  font-size: 28rpx;
  line-height: 1.7;
  color: #1A1A2E;
}
```

如果微信小程序对某些 CSS 属性支持有限，请使用兼容写法。

1. 更新 Render Guard 和 trace

需要同步修改：

- `utils/stem-render.js` 中的模式断言。
- `pages/practice/practice.js` 中 `_checkRenderInvariant()`。
- 其他存在类似单路径断言的代码。
- 测试中的 `checkSingleRoot()`。

要求：

- MIXED 算一个顶层 render path。
- MIXED 的 `blocks` 必须非空。
- 每个 block 只能激活自己的一个渲染字段。
- CODE block 不得包含 HTML 实体编码。
- MIXED 中的 CODE block 也要执行 CODE 完整性检查。
- renderTrace 最好增加 block 类型信息，例如：

```js
blockTypes: ['RICH_TEXT', 'CODE']
```

四、必须新增或修改的测试

不要为了让旧测试通过而保留错误行为。旧测试如果明确要求错误行为，应修改预期。

至少新增以下回归测试。

1. 重复题干：完全相同

输入：

```text
测试题干
测试题干
```

结果只保留一次。

1. 重复题干：LaTeX 与 Unicode 等价

输入：

```text
两个进程 $P_{0}$、$P_{1}$ 互斥。
两个进程 P₀、P₁ 互斥。
```

结果只保留一次。

1. 重复题干：HTML 与普通文本等价

输入：

```text
<p>在线性表&nbsp;a₀ 中删除元素。</p>
在线性表 a₀ 中删除元素。
```

结果只保留一次。

1. 代码合法重复行不能删除

输入：

```c
if (x) {
  if (y) {
    run();
  }
}
```

结果中的两个 `}` 都必须保留。

1. 文字加代码应进入 MIXED

输入：

```text
下列程序段的时间复杂度是（ ）。

int sum = 0;
for(int i = 1; i < n; i *= 2)
    sum++;
```

期望：

```js
mode === RENDER_MODE.MIXED
blocks[0].type === 'RICH_TEXT'
blocks[1].type === 'CODE'
```

题目说明不能进入 CODE block。

1. Peterson 题干

输入：

```text
两个进程 $P_{0}$、$P_{1}$ 互斥的 Peterson 算法如下：

while (true) {
  flag[i] = true;
}
```

要求：

- mode 为 MIXED。
- 普通文字 block 中不能残留 `$P_{0}$`、`$P_{1}$`。
- 应显示为 `P₀`、`P₁`，或进入正确公式渲染。
- `while` 及其代码只存在于 CODE block。

1. 纯代码仍为 CODE

输入：

```c
void f() {
  int x = 1;
  while (x < 10) {
    x++;
  }
}
```

要求：

- mode 仍为 CODE。
- 原始换行、Tab 和缩进保持不变。
- 不进入 MIXED。

1. 压缩纯代码恢复换行

输入：

```c
void f(){int sum=0;for(int i=0;i<n;i++)sum++;}
```

要求：

- mode 为 CODE。
- 输出包含换行。
- `for` 头部三个部分不能被错误拆分。
- 代码语义字符不能丢失。

修改现有测试：

当前 `tests/test-code-mode.js` 中以下测试的预期是错误的：

```text
No reconstructCode — compressed code stays compressed
```

需要改为验证：

- 已格式化多行代码保持不变。
- 明显压缩的单行代码才恢复换行。

当前部分测试要求“文字加代码整题进入 CODE”，也需要改为 MIXED。

1. 单顶层路径

更新 `checkSingleRoot()`：

- RICH_TEXT、LATEX、SEGMENTS、CODE、MIXED 中只能有一个顶层模式。
- MIXED 通过 `blocks.length > 0` 判断。
- MIXED 内部不同 block 不违反顶层 single root invariant。

五、测试执行要求

修改完成后，请实际运行：

```bash
node tests/test-code-mode.js
node tests/test-render-invariant.js
node tests/test-latex-symbols.js
node tests/render_regression/run.js
```

如果项目内还有其他 Node 测试，也一并运行。

不能只说“理论上通过”，必须给出真实测试输出摘要。

六、验收标准

最终必须满足：

1. 重复题干只显示一次。
2. 不会因去重删除代码中的合法重复行或花括号。
3. 普通题目说明不再进入灰色代码框。
4. 文字和程序代码可以在同一道题中分别渲染。
5. `$P_{0}$`、`$P_{1}$` 不再原样显示在普通题目说明中。
6. 已格式化代码的换行和缩进不被修改。
7. 明显压缩的单行代码能够保守恢复换行。
8. 长代码可以在微信小程序中横向滚动，不能被截断。
9. practice、review-today、wrong-detail 三个页面行为一致。
10. 现有普通文字、数学公式、选项、SEGMENTS 功能不回归。
11. 所有测试通过。

七、输出格式

完成后请按以下格式汇报：

1. 根因确认。
2. 修改过的文件列表。
3. 核心实现说明。
4. 关键代码差异。
5. 新增或修改的测试用例。
6. 实际测试命令及结果。
7. 仍然存在的边界情况或风险。

请先阅读相关文件和现有测试，再直接开始修改，不要停留在方案讨论阶段。

