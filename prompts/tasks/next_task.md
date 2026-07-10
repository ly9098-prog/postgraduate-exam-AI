下面这份可以直接复制给修复 Agent 使用。重点把这次的“第三次修复番茄钟跳秒问题”写成强约束：**点击结束必须真正进入暂停态，不能只是清掉 timer；取消后必须从快照剩余时间恢复，不能再用 `sessionStartTime` 反推剩余时间。**

~~~md
你是一个微信小程序工程师。请基于当前 `miniprogram` 源码修复以下问题。不要只做样式表面调整，要定位真实状态流和渲染根因。

重点文件：

- `pages/pomodoro/pomodoro.js`
- `pages/pomodoro/pomodoro.wxml`
- `pages/pomodoro/pomodoro.wxss`
- `pages/practice-result/practice-result.js`
- `pages/practice-result/practice-result.wxml`
- `pages/practice-result/practice-result.wxss`
- `utils/stem-render.js`
- `utils/math-format.js`

---

# 一、pomodoro 第三次修复：结束确认期间计时器继续走 / 取消后跳秒

## 当前问题

`pages/pomodoro` 在第 a 秒点击结束计时后，结束确认弹窗停留 b 秒未操作，再点击取消，计时器不是从 a 或 a+1 秒继续，而是直接跳到 a+b 秒。

这是第三次修复同一问题。之前修复仍失败的根因是：

- 只调用 `_clearTimer()` 停止前端 tick，不等于真正进入暂停态。
- `_startTimer(totalSec)` 仍通过：

```js
Date.now() - sessionStartTime - totalPausedMs
~~~

反推剩余时间。

- 弹窗停留时间 b 秒期间，`sessionStartTime` 仍在过去，取消时重新 `_startTimer()` 会继续把这 b 秒算进已用时间。
- 仅在 `cancelEndConfirm()` 中给 `totalPausedMs` 加 `pauseDelta` 仍不可靠，因为 `setData` 异步、`_startTimer()` 立即读取旧值、以及服务端恢复数据都可能覆盖本地快照。

## 修复目标

点击“结束计时”时，非自由计时模式必须自动触发暂停。确认弹窗期间，倒计时必须冻结。

用户行为示例：

- 当前显示 `20:00`
- 点击结束计时
- 弹窗停留 5 秒
- 点击取消
- 应继续从 `20:00` 或下一秒 `19:59` 开始
- 不能直接跳到 `19:55`

## 强制修复要求

### 1. 不允许继续依赖 `sessionStartTime` 反推确认弹窗后的剩余时间

请新增本地倒计时结束时间模型：

```js
_countdownEndAt: 0,
_countdownTotalSec: 0,
_countdownRemainingSnapshot: null,
_confirmTimerSnapshot: null,
```

`_startTimer(totalSec, options)` 必须支持从指定剩余秒数恢复：

```js
_startTimer(totalSec, options = {}) {
  this._clearTimer()

  const remainSec = Number.isFinite(options.remainingSec)
    ? Math.max(0, options.remainingSec)
    : Math.max(0, this.data.remainingSec || totalSec)

  this._countdownTotalSec = totalSec
  this._countdownEndAt = Date.now() + remainSec * 1000

  this._initCanvas(true)

  const tick = () => {
    if (this.data.isPaused || this.data.showEndConfirm) return

    const remainingMs = Math.max(0, this._countdownEndAt - Date.now())
    const remainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
    const progress = totalSec > 0 ? remainingMs / (totalSec * 1000) : 0
    const fmt = this._formatCountdownDisplay(remainingSec)

    this.setData({
      remainingSec,
      displayMin: fmt.min,
      displaySec: fmt.sec,
      progress,
    })

    this.drawRing(totalSec, this.data.phase === PHASE.BREAK)

    if (remainingMs <= 0) {
      this._clearTimer()
      this._onWorkComplete()
      return
    }

    this._timer = setTimeout(tick, 200)
  }

  tick()
}
```

注意：

- `remainingSec` 的来源必须以本地快照为准。
- 取消确认后恢复时，必须调用：

```js
this._startTimer(snapshot.totalSec, {
  remainingSec: snapshot.remainingSec,
})
```

不能调用：

```js
this._startTimer(this._getCurrentTotalSec())
```

否则会重新用旧时间基准导致跳秒。

------

### 2. 点击结束计时必须自动进入暂停态

新增方法：

```js
_pauseCountdownForEndConfirm()
```

逻辑：

```js
_pauseCountdownForEndConfirm() {
  if (!this.data.sessionId || this.data.actionLoading) return

  const totalSec = this._getCurrentTotalSec()
  const remainingSec = Math.max(0, this.data.remainingSec || 0)
  const remainingMs = this._countdownEndAt
    ? Math.max(0, this._countdownEndAt - Date.now())
    : remainingSec * 1000

  const safeRemainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)

  this._clearTimer()

  this._confirmTimerSnapshot = {
    mode: 'countdown-interrupt',
    openedAt: Date.now(),
    wasPaused: !!this.data.isPaused,
    phase: this.data.phase,
    totalSec,
    remainingSec: safeRemainingSec,
    remainingMs,
    progress: this.data.progress,
    totalPausedMs: this.data.totalPausedMs || 0,
  }

  this.setData({
    isPaused: true,
    pauseStartTime: Date.now(),
    remainingSec: safeRemainingSec,
  })
}
```

`_showCountdownInterruptConfirm()` 必须先调用 `_pauseCountdownForEndConfirm()`，再显示弹窗：

```js
_showCountdownInterruptConfirm() {
  if (this.data.actionLoading) return

  this._pauseCountdownForEndConfirm()

  const snapshot = this._confirmTimerSnapshot
  const totalSec = snapshot.totalSec
  const elapsedSec = Math.max(0, totalSec - snapshot.remainingSec)
  const fmt = formatElapsedSec(elapsedSec)

  this.setData({
    showEndConfirm: true,
    ringCanvasVisible: false,
    endConfirmMode: 'countdown-interrupt',
    endConfirmTheme: this.data.phase === PHASE.BREAK ? 'break' : 'focus',
    endConfirmTitle: '结束本次专注？',
    endConfirmText: elapsedSec > 0
      ? `本次已专注 ${fmt.friendly}。确认后将结束当前番茄钟。`
      : '确认后将结束当前番茄钟。',
    endConfirmOkText: '结束',
    endConfirmCancelText: '继续专注',
  })
}
```

------

### 3. 取消确认必须从快照恢复，而不是重新计算

`cancelEndConfirm()` 中非自由计时分支改成：

```js
cancelEndConfirm() {
  if (this.data.actionLoading) return

  const mode = this.data.endConfirmMode
  const snapshot = this._confirmTimerSnapshot

  if (mode === 'countdown-interrupt' && snapshot) {
    const pauseDelta = Math.max(0, Date.now() - snapshot.openedAt)
    const nextTotalPausedMs = Math.max(0, snapshot.totalPausedMs + pauseDelta)

    this.setData({
      showEndConfirm: false,
      ringCanvasVisible: true,
      endConfirmMode: '',
      endConfirmTheme: '',
      endConfirmTitle: '',
      endConfirmText: '',
      totalPausedMs: nextTotalPausedMs,
      remainingSec: snapshot.remainingSec,
      progress: snapshot.progress,
      isPaused: snapshot.wasPaused,
      pauseStartTime: snapshot.wasPaused ? snapshot.openedAt : null,
    }, () => {
      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(snapshot.totalSec, snapshot.phase === PHASE.BREAK)

        if (!snapshot.wasPaused && snapshot.phase === PHASE.RUNNING) {
          this._startTimer(snapshot.totalSec, {
            remainingSec: snapshot.remainingSec,
          })
        }
      })
    })

    this._confirmTimerSnapshot = null
    return
  }

  // 自由计时保留原逻辑，但也要恢复 ringCanvasVisible
}
```

验收重点：

- 点击结束弹窗后，数据层 `isPaused` 应变为 `true`。
- 弹窗期间 `remainingSec` 不变化。
- 取消后必须从 `snapshot.remainingSec` 继续。
- 不能再出现 a 秒点击、b 秒后取消、直接跳到 a+b 的情况。

------

# 二、pomodoro 结束提示配色修复

## 当前问题

标准计时页面的结束提示直接复用了自由计时的绿色/深色结束提示样式，和计时器表盘光环风格不一致。

## 修复目标

结束提示颜色应根据当前模式切换：

- 标准专注：使用蓝色 / 青色光环风格。
- 休息：使用橙色 / 暖色光环风格。
- 自由计时：保留绿色风格。

## 修复要求

新增字段：

```js
endConfirmTheme: '', // 'focus' | 'break' | 'free'
```

自由计时：

```js
endConfirmTheme: 'free'
```

标准专注：

```js
endConfirmTheme: 'focus'
```

休息模式：

```js
endConfirmTheme: 'break'
```

WXML：

```xml
<cover-view
  wx:if="{{showEndConfirm}}"
  class="confirm-cover-overlay confirm-theme-{{endConfirmTheme}}"
  catchtap="cancelEndConfirm"
>
  <cover-view class="confirm-cover-card" catchtap="noop">
    ...
  </cover-view>
</cover-view>
```

WXSS 增加主题色：

```css
.confirm-theme-focus .confirm-cover-card {
  background: rgba(15, 23, 42, 0.98);
  border: 1rpx solid rgba(96, 165, 250, 0.24);
  box-shadow:
    0 0 50rpx rgba(59, 130, 246, 0.22),
    0 0 120rpx rgba(6, 182, 212, 0.12);
}

.confirm-theme-focus .confirm-cover-title {
  color: #93C5FD;
}

.confirm-theme-focus .confirm-cover-ok {
  background: linear-gradient(135deg, #3B82F6, #06B6D4);
  color: #FFFFFF;
}

.confirm-theme-break .confirm-cover-card {
  background: rgba(30, 23, 15, 0.98);
  border: 1rpx solid rgba(251, 146, 60, 0.25);
  box-shadow:
    0 0 50rpx rgba(249, 115, 22, 0.22),
    0 0 120rpx rgba(244, 63, 94, 0.12);
}

.confirm-theme-break .confirm-cover-title {
  color: #FDBA74;
}

.confirm-theme-break .confirm-cover-ok {
  background: linear-gradient(135deg, #F97316, #F43F5E);
  color: #FFFFFF;
}

.confirm-theme-free .confirm-cover-card {
  background: rgba(15, 30, 30, 0.98);
  border: 1rpx solid rgba(16, 185, 129, 0.24);
  box-shadow:
    0 0 50rpx rgba(16, 185, 129, 0.22),
    0 0 120rpx rgba(5, 150, 105, 0.12);
}

.confirm-theme-free .confirm-cover-title {
  color: #6EE7B7;
}

.confirm-theme-free .confirm-cover-ok {
  background: linear-gradient(135deg, #10B981, #059669);
  color: #FFFFFF;
}
```

验收：

- 标准计时结束提示是蓝色/青色风格。
- 自由计时仍是绿色风格。
- 休息结束/跳过确认如有弹窗，应是暖色风格。
- 不再所有模式都使用自由计时绿色样式。

------

# 三、pomodoro 标准计时页面光环消失修复

## 当前问题

标准计时页面表盘光环消失。当前代码已经有 `ringCanvasVisible`，但部分路径没有恢复它，导致 canvas 或光环显示异常。

## 修复目标

标准计时页面的表盘光环、canvas 圆环必须稳定存在：

- 进入标准计时后显示。
- 点击结束后弹窗期间可暂时隐藏 canvas，但取消后必须恢复。
- 接口失败后必须恢复。
- 暂停 / 继续后必须恢复。
- 从后台恢复页面也必须恢复。

## 修复要求

### 1. 所有进入计时态路径都要设置 `ringCanvasVisible: true`

检查并修改：

- `_beginCountdown(session)`
- `_restoreSession(active)`
- `_syncActiveSessionLight(active)`
- `_restoreBreak()`
- `_beginFreeTimer(session)`
- `_resumeSession()`
- `_resumeFreeTimer()`
- `cancelEndConfirm()`
- `_confirmInterruptCountdown()` 失败路径

例如：

```js
this.setData({
  phase: PHASE.RUNNING,
  ringCanvasVisible: true,
  ...
})
```

### 2. 取消确认后必须恢复 canvas 并重绘

```js
this.setData({
  showEndConfirm: false,
  ringCanvasVisible: true,
}, () => {
  wx.nextTick(() => {
    this._initCanvas(true)
    this.drawRing(this._getCurrentTotalSec(), this.data.phase === PHASE.BREAK)
  })
})
```

### 3. `_initCanvas(force)` 要支持强制重新获取 canvas

如果当前 `_initCanvas()` 内部因为已有 `this._canvas` 就 return，请修改：

```js
_initCanvas(force = false) {
  if (this._canvas && this._ctx && !force) return

  if (!this.data.ringCanvasVisible) return

  wx.createSelectorQuery()
    .in(this)
    .select('#progress-ring')
    .fields({ node: true, size: true })
    .exec(...)
}
```

### 4. `.ring-glow` 不应依赖 canvas 是否存在

确认 WXML 中：

```xml
<view class="ring-glow"></view>
<canvas wx:if="{{ringCanvasVisible}}" ...></canvas>
<view wx:else class="ring-canvas-placeholder"></view>
```

`.ring-glow` 必须始终渲染，不要跟随 `ringCanvasVisible` 被隐藏。

验收：

- 标准计时进入后能看到光环。
- 点击结束后取消，光环恢复。
- 暂停、继续后光环存在。
- 后台切回后光环存在。
- debug 10s 测试模式光环存在。

------

# 四、practice-result 答题详情字体颜色修复

## 当前问题

`pages/practice-result` 答题详情中，正确题 / 错题的题干和答案字体使用了与背景相近的绿色、红色，导致阅读性差。用户要求答题详情字体保持黑色即可。

## 修复目标

答题详情正文统一使用深黑色，不要让题干、答案文字跟背景同色系。

允许保留彩色元素：

- 正确 / 错误状态 pill
- 左侧细条
- 答案框浅色背景
- 边框颜色

但正文文本必须黑色或深灰。

## 修复要求

删除或覆盖以下样式：

```css
.detail-row.correct .detail-stem { color: #166534; }
.detail-row.wrong .detail-stem { color: #991B1B; }
.detail-answer-value.user { color: #EF4444; }
.detail-answer-value.right { color: #16A34A; }
.detail-rich-text { color: inherit; }
```

替换为：

```css
.detail-stem,
.detail-answer-value,
.detail-rich-text,
.detail-stem-rich {
  color: #18233A !important;
}

.detail-answer-label {
  color: #4B5563;
}

.detail-answer-label.correct {
  color: #4B5563;
}
```

如果 `mp-html` 内部节点仍继承红/绿，请给 `container-style` 增加：

```js
detailHtmlContainerStyle:
  'max-width:100%;overflow-x:hidden;word-break:break-word;overflow-wrap:anywhere;white-space:normal;line-height:1.65;color:#18233A;'
```

`detailHtmlTagStyle` 中也加：

```js
p: 'color:#18233A;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;line-height:1.65;margin:0;',
div: 'color:#18233A;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;line-height:1.65;',
span: 'color:#18233A;max-width:100%;white-space:normal;word-break:break-word;overflow-wrap:anywhere;',
```

验收：

- 答题详情题干为黑色/深灰。
- 我的答案为黑色/深灰。
- 正确答案为黑色/深灰。
- 状态标签、边框可以保留红绿区分。
- 不再出现浅绿背景配绿色字、浅红背景配红色字导致阅读困难的问题。

------

# 五、practice-result 题干 Latex 和 text 重复渲染修复

## 当前问题

截图中答题详情题干出现重复渲染：同一道题的题干被显示了两遍，看起来像 LaTeX 渲染路径和 text 渲染路径同时输出，或原始题干本身重复后未清理。

## 修复目标

答题详情中，每道题题干只能出现一次。

不允许出现：

- `mp-html` 渲染一遍，`text` 再显示一遍。
- LaTeX 原文一遍，转义后的 text 又一遍。
- 题干原文重复两段。

## 修复要求

### 1. 结果页题干只允许一种渲染路径

重构 `buildDetailRichText()`，返回明确的 `renderType`：

```js
function buildDetailRichText(value) {
  const raw0 = String(value || '').trim()
  const raw = dedupeRepeatedResultStem(raw0)

  if (!raw) {
    return {
      raw: '',
      renderType: 'empty',
      text: '',
      html: '',
    }
  }

  const plain = toPlainInlineMathText(raw)

  if (plain) {
    return {
      raw,
      renderType: 'text',
      text: plain,
      html: '',
    }
  }

  if (needsRichRender(raw)) {
    return {
      raw,
      renderType: 'html',
      text: '',
      html: normalizeResultHtml(textToHtml(raw)),
    }
  }

  return {
    raw,
    renderType: 'text',
    text: formatInlineMathText(raw),
    html: '',
  }
}
```

不要再使用模糊字段 `needsRich` 控制两个分支。

### 2. WXML 改成互斥分支

题干区域：

```xml
<view class="detail-stem-wrap" wx:if="{{item._stemRich && item._stemRich.raw}}">
  <mp-html
    wx:if="{{item._stemRich.renderType === 'html'}}"
    content="{{item._stemRich.html}}"
    class="detail-rich-text detail-stem-rich"
    container-style="{{detailHtmlContainerStyle}}"
    tag-style="{{detailHtmlTagStyle}}"
    scroll-table="{{false}}"
    lazy-load
  />
  <text
    wx:elif="{{item._stemRich.renderType === 'text'}}"
    class="detail-stem"
  >{{item._stemRich.text}}</text>
</view>
```

答案区域也同样使用 `renderType === 'html'` / `renderType === 'text'`，不要再用 `wx:else` 兜底到 text，避免异常情况下 html 和 text 同时出现。

### 3. 增加题干去重函数

在 `practice-result.js` 中新增：

```js
function canonicalForResultStem(text) {
  return String(text || '')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\s+/g, ' ')
    .replace(/[，。、；：！？,.!?;:]/g, ' ')
    .trim()
}

function dedupeRepeatedResultStem(text) {
  const raw = String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
  if (!raw) return ''

  // 处理完全重复的两段：A\nA
  const lines = raw.split('\n').map(s => s.trim()).filter(Boolean)
  if (lines.length >= 2) {
    const half = Math.floor(lines.length / 2)
    const left = lines.slice(0, half).join('\n')
    const right = lines.slice(half).join('\n')
    if (half > 0 && canonicalForResultStem(left) === canonicalForResultStem(right)) {
      return left
    }
  }

  // 处理同一行/相邻段重复
  const result = []
  for (let i = 0; i < lines.length; i++) {
    const cur = lines[i]
    const prev = result[result.length - 1]
    if (prev && canonicalForResultStem(prev) === canonicalForResultStem(cur)) {
      continue
    }
    result.push(cur)
  }

  // 处理整段前后重复：A + A
  const joined = result.join('\n').trim()
  const canon = canonicalForResultStem(joined)
  const len = joined.length

  for (let cut = Math.floor(len / 2) - 5; cut <= Math.floor(len / 2) + 5; cut++) {
    if (cut <= 0 || cut >= len) continue
    const left = joined.slice(0, cut).trim()
    const right = joined.slice(cut).trim()
    if (left && right && canonicalForResultStem(left) === canonicalForResultStem(right)) {
      return left
    }
  }

  return joined
}
```

然后在构建 stem 时：

```js
const stemRaw = dedupeRepeatedResultStem(cleanStemText(...))
const stemRich = buildDetailRichText(stemRaw)
```

### 4. 不要把 `_stemRich.text` 和 `_stemRich.html` 同时填充

当 `renderType === 'html'` 时：

```js
text: ''
html: ...
```

当 `renderType === 'text'` 时：

```js
text: ...
html: ''
```

这样即使 WXML 误写，也不容易重复。

### 5. 检查 mp-html 的 LaTeX 插件行为

如果 `mp-html` 对 KaTeX 同时显示源码和公式，需要检查 `textToHtml(raw)` 输出：

- 不要把同一个公式既转成纯文本又保留 `$...$`。
- 不要在 html 中拼接 `plain + raw`。
- `normalizeResultHtml()` 不应追加纯文本副本。

验收：

- 截图中的题干不再出现两遍。
- 含 LaTeX 的题干只显示一次。
- 普通纯文本题干只显示一次。
- 答案区域不出现公式原文 + 转换文本重复。
- 长题干仍然不会横向溢出。

------

# 六、回归验证清单

## pomodoro

- 第 a 秒点击结束计时，停留 b 秒后取消，不会跳到 a+b。
- 点击结束时，非自由计时自动进入暂停态。
- 取消后从点击结束时的剩余秒数继续。
- 原本暂停状态下点击结束，取消后仍保持暂停。
- 标准计时结束提示使用蓝色/青色风格。
- 自由计时结束提示仍使用绿色风格。
- 标准计时页面光环恢复显示。
- 暂停、继续、结束取消、后台切回后，光环都正常。
- debug 10s 模式下也稳定。

## practice-result

- 答题详情字体保持黑色/深灰，阅读清晰。
- 题干不再出现 LaTeX 和 text 重复渲染。
- 普通题干不重复。
- 含公式题干不重复。
- 我的答案、正确答案不重复。
- 长题干不横向溢出。
- 页面不能左右滑动。

## 编译检查

完成后请在微信开发者工具中重新编译，并检查：

- WXML 无语法错误。
- WXSS 无选择器错误。
- `mp-html` 正常渲染。
- `cover-view` 点击事件正常。
- `ringCanvasVisible` 恢复路径完整。
- JS 无 runtime error。

```

```
