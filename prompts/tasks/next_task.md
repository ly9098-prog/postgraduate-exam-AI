你是一名资深微信小程序前端架构、Canvas 渲染和状态机调试工程师。请基于当前最新源码，执行第五阶段修复。

本阶段优先级：

P0：修复 Pomodoro 页面功能回归和环形计时器错位。
P1：清理真实代码警告。
P1：处理最新 audits(1).json 中仍然失败的审计项。
P2：保留但暂不继续大规模清理 unused-css。

不要只提出建议，请直接修改代码。

==================================================
一、修改边界
==================================================

1. 保留此前已经完成的：
   - 高频 setData 优化；
   - 运行态迁移；
   - hover-class；
   - 点击热区；
   - Wrong Detail AI 防串；
   - 已完成的 WXSS 清理。

2. 禁止：
   - git reset --hard；
   - git checkout .；
   - 批量删除 WXSS；
   - 修改后端 API 路径和参数语义；
   - 改变计时统计口径；
   - 通过隐藏弹窗或删除结束按钮规避问题；
   - 用 setData({}) 作为无意义刷新；
   - 伪造微信开发者工具审计结果。

3. 本轮重点文件：
   - pages/pomodoro/pomodoro.js
   - pages/pomodoro/pomodoro.wxml
   - pages/pomodoro/pomodoro.wxss
   - pages/pomodoro-stats/pomodoro-stats.js
   - components/quiz-runner/quiz-runner.wxss
   - components/loading-lottie/loading-lottie.js
   - components/AnimatedView/AnimatedView.js
   - components/mp-html/latex/katex.wxss
   - pages/dashboard/dashboard.wxml
   - pages/dashboard/dashboard.charts.js
   - pages/home/home.js
   - pages/dashboard/dashboard.js
   - pages/review-today/review-today.js
   - pages/review-today/review-today.wxss

==================================================
二、P0：修复 Pomodoro 环形位置错位
==================================================

现象：

1. Canvas 绘制的圆环位于上方。
2. 科目、状态、计时时间和背景光晕位于下方。
3. 标准计时和自由计时均可能出现。
4. 圆环和 ring-center 没有共享同一视觉中心。

重点检查当前结构：

- .page-inner 使用 transform 进入动画；
- .timer-wrap 使用 transform: scale(...) 的 timer-in 动画；
- type="2d" Canvas 位于这些带 transform 的祖先元素中；
- Canvas 是原生/同层渲染节点，祖先 transform、动画和重新布局可能造成坐标不同步。

必须按以下原则修复：

1. Canvas 的全部祖先节点不得长期保留 transform。
2. 不允许在包含 Canvas 的：
   - .page-inner
   - .main-content
   - .timer-wrap
   - .ring-wrapper
   上执行 translate、scale 或 animation-fill-mode: both 后留下 transform。

3. 将运行中页面的动画调整为：
   - 仅 opacity 动画；
   - 或只动画 timer-header、controls-row；
   - ring-wrapper 和 Canvas 所在层保持 transform: none。

4. 推荐将结构调整为：

   timer-wrap
   ├── timer-header（允许淡入）
   ├── ring-stage（禁止 transform）
   │   ├── ring-glow
   │   ├── canvas
   │   └── ring-center
   └── controls-row（允许淡入）

5. ring-stage/ring-wrapper 必须是唯一定位容器：

   .ring-wrapper {
     position: relative;
     width: 520rpx;
     height: 520rpx;
     flex: none;
     margin: 0 auto;
     transform: none;
   }

   .ring-canvas {
     position: absolute;
     left: 0;
     top: 0;
     width: 520rpx;
     height: 520rpx;
     z-index: 1;
   }

   .ring-center {
     position: absolute;
     inset: 0;
     z-index: 2;
     pointer-events: none;
   }

   .ring-glow {
     z-index: 0;
   }

6. 不允许 Canvas 和时间文字分别放入两个尺寸不同的圆形容器。

7. Canvas 初始化必须在布局稳定后进行：
   - wx.nextTick；
   - 再通过 SelectorQuery 获取 ring-wrapper 和 Canvas 的真实尺寸；
   - 确认宽高大于 0；
   - 再设置 canvas.width、canvas.height 和绘图上下文。

8. 不要依赖固定 setTimeout(50) 猜测布局已经完成。实现一个明确方法：

   _scheduleCanvasInit() {
     wx.nextTick(() => {
       // 查询 ring-wrapper 与 progress-ring 尺寸
       // 尺寸有效后初始化
       // 无效时最多有限次数重试
     })
   }

9. 初始化完成后：
   - this._canvasSize 使用 Canvas 实际 CSS 尺寸；
   - DPR 使用 wx.getWindowInfo().pixelRatio；
   - 重设 transform 前先 ctx.setTransform(1, 0, 0, 1, 0, 0)，避免重复缩放；
   - 再执行 ctx.scale 或 ctx.setTransform。

10. 字体大小切换、计时模式切换、页面恢复后重新校验 Canvas 尺寸。

11. 不得创建第二个 Canvas 作为临时补丁。

验收：

- 标准计时圆环、光晕、时间文字共用完全相同的中心。
- 自由计时圆环、光晕、时间文字共用完全相同的中心。
- 暂停、恢复后不偏移。
- 从统计页返回后不偏移。
- 切换大字体后不偏移。
- 页面进入动画期间不闪到错误位置。
- 不出现两个重叠圆环。

==================================================
三、P0：修复标准计时“确认结束无效”
==================================================

已发现的关键问题：

_pauseCountdownForEndConfirm() 创建了 mode 为 countdown-interrupt 的 snapshot，
但没有同步设置：

this._timerState.endConfirmMode = 'countdown-interrupt'

因此 confirmEndTimer() 读取到空字符串，既不会调用
_confirmEndFreeTimer()，也不会调用 _confirmInterruptCountdown()。

必须修复：

1. 在打开标准计时确认弹窗前明确设置：

   this._timerState.endConfirmMode = 'countdown-interrupt'

2. 自由计时明确设置：

   this._timerState.endConfirmMode = 'free-complete'

3. 不允许通过当前页面颜色或 isFreeTimer 猜测弹窗模式。

4. confirmEndTimer() 增加防御：

   async confirmEndTimer() {
     if (this.data.actionLoading) return

     const mode = this._timerState.endConfirmMode
     const snapshot = this._confirmTimerSnapshot

     if (mode === 'countdown-interrupt') {
       return this._confirmInterruptCountdown()
     }

     if (mode === 'free-complete') {
       return this._confirmEndFreeTimer()
     }

     console.warn('[pomodoro] invalid end confirm mode', {
       mode,
       sessionId: this._timerState.sessionId,
       snapshotMode: snapshot && snapshot.mode
     })

     // 不允许静默无响应
     wx.showToast({
       title: '结束状态异常，请重新操作',
       icon: 'none'
     })
   }

5. 标准计时确认结束成功后必须：

   - 请求 interrupt 接口；
   - 解除 actionLoading；
   - 清理本地计时器；
   - 清理：
     pomodoro_confirm_pause
     pomodoro_pause
     pomodoro_pause_adjustment
     pomodoro_running_state
   - 清空 _confirmTimerSnapshot；
   - 清空 endConfirmMode；
   - reset 到 idle；
   - 刷新今日统计。

6. 请求失败时：

   - 不得静默；
   - 保留确认弹窗，允许再次点击；
   - actionLoading 恢复 false；
   - 不得错误地自动继续计时；
   - 显示明确错误信息。

7. 确认按钮 actionLoading 时必须禁用重复点击。

8. 删除所有为了触发刷新而调用的：

   this.setData({})

直接修改实例变量即可。

==================================================
四、P0：修复打开结束弹窗时的错误自动暂停
==================================================

需要区分两个概念：

1. “冻结前端显示，等待用户确认”；
2. “用户主动点击暂停”。

打开结束确认弹窗不应被永久记录成用户主动暂停状态。

处理原则：

1. 用户打开确认弹窗时，可以暂时停止本地 tick。
2. 但必须保存：
   - wasPaused；
   - openedAt；
   - remainingMs；
   - remainingSec；
   - totalPausedMs；
   - sessionId；
   - mode。

3. 用户原本正在运行：
   - 点击“继续专注”后必须自动恢复运行；
   - 不得留在暂停态；
   - 恢复时间必须扣除弹窗停留时长；
   - 不得使倒计时凭空减少。

4. 用户原本已经暂停：
   - 取消结束后仍保持暂停；
   - 不得自动恢复。

5. 用户点击确认结束：
   - 不需要先执行普通暂停流程再结束；
   - 避免 pause 和 interrupt 两个接口竞争；
   - 如果后端业务必须先暂停，则必须保证状态机串行且 mode 正确。

6. 推荐将“弹窗冻结”从 isPaused 中分离：

   this._confirmFrozen = true

isPaused 只表示真实用户暂停状态。

如果暂时无法分离，必须保证取消和确认两个出口都能完全恢复一致状态。

==================================================
五、P0：修复 Pomodoro Stats 返回后自动弹出结束确认
==================================================

现象：

从 Pomodoro 页面进入 pomodoro-stats，再返回时，自动出现“是否结束计时”。

根因方向：

onShow() 当前优先读取：

pomodoro_confirm_pause

并在验证活动会话之前恢复弹窗。陈旧快照或模式不匹配时也会触发。

必须修改：

1. goStats() 设置明确导航标记：

   this._navigatingToStats = true

2. 正常跳转统计页不得：
   - 打开结束弹窗；
   - 写入新的 pomodoro_confirm_pause；
   - 请求 pause 接口；
   - 修改 endConfirmMode；
   - 把正在运行的计时改成暂停。

3. onHide() 只停止本地渲染 tick并保存运行状态，不要把“页面隐藏”当成“暂停”。

4. onShow() 恢复顺序调整为：

   A. 获取当前活动 session；
   B. 校验本地 confirmation snapshot；
   C. 仅在快照有效且确实是用户未处理的弹窗时恢复；
   D. 否则删除陈旧快照；
   E. 恢复正常计时。

5. 快照有效条件至少包括：

   - snapshot.sessionId === active.id；
   - snapshot.mode 与 active.preset 一致：
     - free-complete 只能对应 preset === 'free'
     - countdown-interrupt 只能对应 preset !== 'free'
   - snapshot.openedAt 合法；
   - 快照未超时；
   - 快照明确标记 confirmVisible === true；
   - 不是从 pomodoro-stats 正常返回产生的状态。

6. 任一条件不满足：

   wx.removeStorageSync('pomodoro_confirm_pause')
   this._confirmTimerSnapshot = null
   this._timerState.endConfirmMode = ''

7. 从统计页返回时：

   - 不显示结束确认；
   - 根据服务器 start_time、total_paused_sec 和本地时间恢复；
   - 原本运行则继续运行；
   - 原本暂停则保持暂停。

8. 导航标记使用后立即清除：

   this._navigatingToStats = false

9. 不得简单地在 onShow 中无条件删除所有快照，因为用户真正打开弹窗后切后台仍需要恢复。

==================================================
六、P0：修复标准计时错误使用自由计时弹窗风格
==================================================

当前恢复 countdown snapshot 时，没有完整设置：

- endConfirmTheme
- endConfirmTitle
- endConfirmText
- endConfirmOkText
- endConfirmCancelText

可能继承上一次自由计时的绿色主题。

必须建立唯一的弹窗 ViewModel 构造方法：

_buildEndConfirmViewModel(mode, snapshot) {
  if (mode === 'free-complete') {
    return {
      endConfirmTheme: 'free',
      endConfirmTitle: '结束自由计时？',
      endConfirmText: ...,
      endConfirmOkText: '确认结束',
      endConfirmCancelText: '继续计时'
    }
  }

  if (mode === 'countdown-interrupt') {
    const isBreak = snapshot.phase === 'break'
    return {
      endConfirmTheme: isBreak ? 'break' : 'focus',
      endConfirmTitle: isBreak ? '结束休息？' : '结束本次专注？',
      endConfirmText: ...,
      endConfirmOkText: '结束',
      endConfirmCancelText: isBreak ? '继续休息' : '继续专注'
    }
  }

  throw new Error('Unknown confirm mode')
}

要求：

1. 首次打开弹窗使用该方法。
2. onShow 恢复弹窗也使用同一个方法。
3. 不得在两个分支分别手写部分字段。
4. 每次打开必须一次性覆盖全部弹窗字段。
5. resetToIdle 时恢复默认值。
6. 开始新 session 时主动清理上一个模式和主题。
7. 标准计时绝不能显示绿色自由计时主题。
8. 自由计时绝不能显示蓝色标准计时文案。

==================================================
七、P1：处理控制台真实代码警告
==================================================

最新日志存在以下真实代码警告。

------------------------------------------
7.1 wx.getSystemInfoSync 已废弃
------------------------------------------

涉及：

- pages/pomodoro/pomodoro.js
- pages/pomodoro-stats/pomodoro-stats.js
- components/loading-lottie/loading-lottie.js
- components/AnimatedView/AnimatedView.js

替换规则：

1. pixelRatio：

   const windowInfo = wx.getWindowInfo
     ? wx.getWindowInfo()
     : {}

   const dpr = windowInfo.pixelRatio || 1

2. SDKVersion：

   const appBaseInfo = wx.getAppBaseInfo
     ? wx.getAppBaseInfo()
     : {}

3. platform：

   const deviceInfo = wx.getDeviceInfo
     ? wx.getDeviceInfo()
     : {}

4. 不要在现代基础库路径中继续调用 getSystemInfoSync。
5. 如保留兼容 fallback，只有在新 API 不存在时才调用，并集中在一个兼容工具方法中。
6. Pomodoro 和 Pomodoro Stats 不应再产生该警告。

------------------------------------------
7.2 跨分包同步 require 警告
------------------------------------------

日志大量出现：

Requires "../../subpackages/animation/lottie-loader.js"
without a callback may fail in production

涉及：

- components/loading-lottie/loading-lottie.js
- components/AnimatedView/AnimatedView.js

必须修复架构，而不是隐藏 console：

1. 主包组件不得在分包尚未加载时同步 require 分包文件。
2. 统一提供 Promise 型加载器：

   loadAnimationLoader()

3. 先调用 wx.loadSubpackage 或现有 app.loadRewardAnimationPackage()。
4. 分包加载成功后，再使用微信支持的异步/callback require 形式。
5. 多个组件同时请求时，只允许一个真实加载任务，其他复用同一 Promise。
6. 缓存加载成功的 module。
7. 加载失败时使用静态 fallback，不重复无限重试。
8. detached 后异步回调不得继续操作组件。
9. 不得把整个大型 lottie vendor 直接复制进主包，除非明确核算主包体积并说明原因。

验收：

- 控制台不再出现 without a callback may fail in production。
- 真机首次进入仍能加载动画。
- 分包失败时显示 fallback。
- 不重复加载分包。

------------------------------------------
7.3 mp-html 组件 WXSS 非法选择器
------------------------------------------

日志定位：

components/mp-html/latex/katex.wxss 约第 839 行：

.katex img

组件 WXSS 不允许标签选择器。

同时检查：

.katex .katex-svg path

处理方法：

1. KaTeX 生成的图片已有 class="katex-svg"。
2. 将 .katex img 的属性合并到：

   .katex .katex-svg

3. 删除 .katex img。
4. SVG 已经被转换成 data URI image，外部 WXSS 无法直接设置内部 path，因此删除无效的：

   .katex .katex-svg path

5. 全文件扫描标签、ID、属性选择器。
6. 不得破坏公式、分数、根号、矩阵、上下标和行内公式。

验收：

- practice、practice-result、wrong-detail、review-today 不再提示非法组件选择器。
- 数学公式仍正常显示。

------------------------------------------
7.4 Dashboard 旧 Canvas 接口
------------------------------------------

Dashboard 多个图表仍使用：

canvas-id="..."
但没有 type="2d"。

请逐个评估迁移：

- score-ring
- diag-quality
- diag-consistency
- trend-chart
- subject-donut
- mastery-gauge
- growth-ring
- adaptive-gauge

要求：

1. 改为 type="2d" Canvas。
2. 使用 SelectorQuery fields({node:true,size:true})。
3. 使用 canvas.getContext('2d')。
4. DPR 使用 wx.getWindowInfo().pixelRatio。
5. 不要一次迁移后不测试全部图表。
6. 若本轮风险过高，可先迁移一个公共绘图适配层，但最终不得混用两套互相覆盖的绘图逻辑。

------------------------------------------
7.5 需要分类而非修改的环境警告
------------------------------------------

以下通常不是业务代码问题：

- SharedArrayBuffer 浏览器弃用提示；
- WAWorker reportRealtimeAction:fail not support；
- 开发者工具关闭合法域名检查的提示。

处理方式：

1. 不要修改业务代码试图屏蔽它们。
2. 在最终报告中标记为“开发者工具/运行环境提示”。
3. 发布前重新开启：
   - 合法域名检查；
   - TLS 检查；
   - HTTPS 证书检查。

------------------------------------------
7.6 401 登录过期日志
------------------------------------------

日志中出现：

- /users/me 401
- /auth/refresh 401

处理原则：

1. 没有 access token 时，不要请求 /users/me。
2. refresh token 不存在时，不要请求 refresh。
3. 同一时间只允许一个 refresh 请求。
4. refresh 失败后：
   - 清除无效 token；
   - 回到登录态；
   - 不重复递归刷新；
   - 不把预期登录过期打印为长堆栈错误。
5. 不得吞掉真正的服务器 500 或网络异常。

==================================================
八、P1：处理最新 audits(1).json 剩余失败项
==================================================

当前审计：

- 总分：91
- 性能：100
- 体验：69
- 最佳实践：91

------------------------------------------
8.1 overflow-scroll
------------------------------------------

命中：

components/quiz-runner/quiz-runner.wxss
.runner-nav-center

该区域已有：

overflow-x: auto

补充：

.runner-nav-center {
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
}

如果 overscroll-behavior 在目标基础库不稳定，可以不使用，但
-webkit-overflow-scrolling: touch 必须添加。

验证页面：

- practice
- wrong-detail
- review-today

------------------------------------------
8.2 set-data-no-binding
------------------------------------------

审计剩余字段：

Home：
- isAdmin

Dashboard：
- insight
- masteryRate

Review Today：
- todayNewDueCount
- remainingBatchCount
- _groupProgressStyle
- celebrationProgressText

Pomodoro Stats：
- weekSessions
- weekDurationText
- trends
- historyTotal

逐项处理原则：

1. 先检查 WXML、Canvas 绘图和 JS 使用。
2. 仅供 JS、Canvas 或业务计算使用的字段移出 data。
3. 迁移到实例状态，例如：
   - this._isAdmin
   - this._dashboardState
   - this._reviewSession
   - this._statsRawData
4. 真正展示的数据保留最终 ViewModel。
5. Canvas 绘图不得继续从未绑定 data 中读取，应从实例数据或方法参数读取。
6. 禁止直接修改 this.data。
7. 不得为了通过审计删除实际功能。

特别注意：

- dashboard.masteryRate 被 Canvas 绘图使用，应迁移到实例变量或直接传给绘图函数，WXML 继续使用 masteryRatePct。
- dashboard.insight 若只用于 onInsightTap，移到实例变量。
- pomodoro-stats.trends 用于 Canvas 绘图，移到 this._statsRawData.trends。
- weekSessions、weekDurationText 如果 WXML 使用的是其他展示字段，则删除重复 data 字段。
- _groupProgressStyle 不应以下划线字段放入 data；如果 WXML需要，改成明确的 groupProgressStyle。
- celebrationProgressText 如果完全未展示，移出 data 或删除。

------------------------------------------
8.3 color-contrast
------------------------------------------

仍命中 review-today 最终结果页：

- .fr-card.fr-summary.weak
- .fr-status-tag.weak
- .fr-cell
- .fr-card.fr-progress-card
- .fr-weak-count
- .fr-advice-tag.review
- .fr-action-primary
- .fr-action-secondary

要求：

1. 普通文字对比度目标至少 4.5:1。
2. 大号粗体至少 3:1。
3. 不得只加 font-weight 逃避颜色问题。
4. 主按钮蓝色背景上的文字使用纯白或高对比白。
5. 次按钮浅蓝背景使用深蓝文字。
6. 弱项红色使用更深的红色：
   - 文本建议 #9F1D1D 或更深；
   - 背景可保留浅红。
7. 重点标签橙色文字改为深棕橙：
   - 例如 #8A4B08。
8. fr-cell 普通辅助文字不得使用过浅灰。
9. 修改后实际计算对比度，不要只凭肉眼。

------------------------------------------
8.4 基础库版本
------------------------------------------

项目使用 aria-label、rich-text、slider、cover-view。

最终报告提示人工设置：

微信公众平台最低基础库版本不低于 2.5.0。

不要为了兼容极旧版本删除无障碍属性或核心组件。

------------------------------------------
8.5 unused-css
------------------------------------------

本轮不继续批量清理。

原因：

当前首先修复功能回归和警告。

仅允许删除因本轮修改明确废弃的少量样式，不得依据审计覆盖率大规模删除。

==================================================
九、Pomodoro 状态机约束
==================================================

请明确建立状态转换表：

IDLE
→ RUNNING
→ PAUSED
→ END_CONFIRM
→ RUNNING / PAUSED / IDLE

自由计时和倒计时都必须满足：

1. 结束弹窗模式明确。
2. 打开弹窗前记录原状态。
3. 取消后恢复原状态。
4. 确认后进入 IDLE。
5. 返回统计页不是状态转换。
6. 页面 hide 不是用户暂停。
7. 页面 show 不是自动弹窗。
8. 旧 storage 不得覆盖新 session。
9. 不同 sessionId 的状态不能混用。
10. free 与 standard 的 snapshot 不能混用。

建议增加开发态断言方法：

_assertTimerState(source)

检查：

- sessionId；
- phase；
- isFreeTimer；
- isPaused；
- endConfirmMode；
- snapshot.mode；
- snapshot.sessionId。

只在 debugMode 下输出，不污染正式控制台。

==================================================
十、回归测试
==================================================

必须逐项测试并真实记录。

A. 环形位置

1. 标准计时首次启动。
2. 自由计时首次启动。
3. 暂停。
4. 恢复。
5. 切换字体大小。
6. 切后台再返回。
7. 进入统计页再返回。
8. 标准模式与自由模式互相切换。
9. 开发者工具和至少一台真机。

B. 标准计时结束

1. 运行中点击结束。
2. 点击取消，应继续运行。
3. 暂停中点击结束。
4. 点击取消，应保持暂停。
5. 点击确认，应立即结束。
6. 连续点击确认，只发起一次请求。
7. 结束接口失败，弹窗保留并可重试。
8. 成功后回到 idle，统计刷新。

C. 自由计时结束

1. 运行中结束。
2. 取消后继续。
3. 暂停中结束。
4. 取消后保持暂停。
5. 确认结束。
6. 文案和主题保持绿色自由计时风格。

D. Stats 返回

1. 运行中的标准计时进入统计再返回。
2. 暂停中的标准计时进入统计再返回。
3. 运行中的自由计时进入统计再返回。
4. 暂停中的自由计时进入统计再返回。
5. 四种情况均不得自动弹出结束确认。
6. 时间状态必须正确恢复。

E. 控制台

确认不再出现：

- getSystemInfoSync deprecated；
- cross-subpackage require without callback；
- component WXSS tag selector；
- Pomodoro 相关 JavaScript 异常。

环境提示单独记录，不作为代码失败。

F. 审计

重新访问全部相关页面后运行审计，记录：

- 总分；
- 性能；
- 体验；
- 最佳实践；
- overflow-scroll；
- set-data-no-binding；
- color-contrast；
- js-exception。

==================================================
十一、最终输出格式
==================================================

## 1. 根因确认

逐项说明：

- 环形错位根因；
- 标准结束无效根因；
- 自动暂停根因；
- Stats 返回弹窗根因；
- 标准弹窗继承自由主题根因。

## 2. Pomodoro 修改文件

列出文件、方法和修改内容。

## 3. 状态机修改

提供修改前后状态转换说明。

## 4. Canvas 修复

说明：

- 哪些 transform 被移除；
- Canvas 初始化时机；
- DPR 获取方式；
- 环形和文字如何保证同心。

## 5. 弹窗修复

说明：

- endConfirmMode 设置位置；
- ViewModel 构建；
- 快照校验；
- storage 清理；
- 取消和确认行为。

## 6. Stats 返回修复

说明四种计时状态的恢复结果。

## 7. 警告处理

用表格列出：

| 警告 | 文件 | 根因 | 修改 | 是否消失 |
| ---- | ---- | ---- | ---- | -------- |

## 8. 审计残项

用表格列出：

| 审计 ID | 原命中 | 修改 | 最新结果 |
| ------- | ------ | ---- | -------- |

## 9. 回归测试

每项标注：

- 通过；
- 失败；
- 未执行。

静态检查不得写成功能测试通过。

## 10. 最新审计

填写真实分数。

如未运行 GUI，明确写：

“未执行微信开发者工具 GUI 审计，本结论仅为代码级检查结果。”

## 11. 剩余问题

列出仍需人工处理的配置和环境提示。
