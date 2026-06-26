const api = require('../../utils/api')

const SUBJECT_LABELS = {
  data_structure: '数据结构',
  computer_organization: '计算机组成原理',
  operating_system: '操作系统',
  computer_network: '计算机网络',
  english: '英语',
  math: '数学',
  politics: '政治',
}

const SUBJECT_COLORS = {
  data_structure: '#3B82F6',
  computer_organization: '#F59E0B',
  operating_system: '#10B981',
  computer_network: '#06B6D4',
  english: '#F97316',
  math: '#2DD4BF',
  politics: '#EA580C',
}

Page({
  data: {
    loading: true,
    pageEntered: false,
    todaySessions: 0,
    todayDurationText: '0分钟',
    weekSessions: 0,
    weekDurationText: '0分钟',
    trends: [],
    subjects: [],
    history: [],
    historyTotal: 0,

    // date picker
    selectedDate: '',
    _todayDate: '',

    // pie chart detail popup
    selectedSubjectDetail: null,
    _selectedSubject: null,
    pieTapped: false,

    // Animated display values
    _dispTodaySessions: 0,
    _dispTodayDurationText: '0分钟',
    _dispWeekSessions: 0,
    _dispWeekDurationText: '0分钟',
    _chartsReady: false,
  },

  onLoad() {
    this._alive = true
    this._isVisible = false
    this._requestId = 0
    this._viewReady = false
    this._hasData = false
    this._finalDrawn = false
    wx.setNavigationBarColor({
      frontColor: '#ffffff',
      backgroundColor: '#0B1121',
    })
    const now = new Date()
    const y = now.getFullYear()
    const m = String(now.getMonth() + 1).padStart(2, '0')
    const d = String(now.getDate()).padStart(2, '0')
    const today = `${y}-${m}-${d}`
    this.setData({ selectedDate: today, _todayDate: today, pageEntered: true })
  },

  onShow() {
    this._isVisible = true
    if (!this._viewReady) return
    this._requestId++
    this.loadData()
  },

  onReady() {
    this._viewReady = true
    this._isVisible = true
    this._requestId++
    this.loadData()
  },

  onHide() {
    this._isVisible = false
  },

  onUnload() {
    this._alive = false
    this._isVisible = false
    this._cancelPendingWork()
  },

  /* ==================== Color Helpers ==================== */

  _easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3)
  },

  /* ==================== Data Loading ==================== */

  async loadData() {
    // 性能优先：停止上一次可能残留的动画/定时器；首次加载才显示 loading，避免刷新时反复销毁页面 DOM。
    this._cancelPendingWork()
    const reqId = this._requestId
    const isInitialLoad = !this._hasData
    this.setData({ loading: isInitialLoad })
    try {
      const [stats, trends, subjects, hist] = await Promise.all([
        api.get('/pomodoro/stats'),
        api.get('/pomodoro/trends', { days: 7 }),
        api.get('/pomodoro/subjects'),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: this.data.selectedDate }),
      ])
      if (!this._alive || reqId !== this._requestId) return
      const subjArr = subjects || []
      const totalDur = Math.max(1, subjArr.reduce((sum, s) => sum + (s.duration_sec || 0), 0))
      this._rawTodayDur = stats.today_duration_sec || 0
      this._rawWeekDur = stats.week_duration_sec || 0
      this._pieSectors = null
      this._shadeCache = null

      const isInitialRender = !this._hasData
      this._hasData = true

      this.setData({
        todaySessions: stats.today_sessions || 0,
        todayDurationText: this._fmtMin(stats.today_duration_sec || 0),
        weekSessions: stats.week_sessions || 0,
        weekDurationText: this._fmtMin(stats.week_duration_sec || 0),
        trends: (trends || []).map(t => ({
          date: t.date,
          duration_sec: t.duration_sec,
          _shortDate: (t.date || '').slice(5),
        })),
        subjects: subjArr.map(s => {
          const dur = s.duration_sec || 0
          const pct = dur / totalDur
          return {
            subject: s.subject,
            duration_sec: dur,
            sessions: s.sessions || 0,
            _label: SUBJECT_LABELS[s.subject] || s.subject || '未分类',
            _color: SUBJECT_COLORS[s.subject] || '#3B82F6',
            _durationText: this._fmtMin(dur),
            _pctText: (pct * 100).toFixed(1) + '%',
          }
        }),
        history: (hist.items || []).map(this._formatSession),
        historyTotal: hist.total || 0,
        loading: false,
        pageEntered: true,
        // 首次进入保留轻量 0→1 动态加载；非首次刷新直接保持最终值，避免重复闪动。
        _dispTodaySessions: isInitialRender ? 0 : (stats.today_sessions || 0),
        _dispTodayDurationText: isInitialRender ? '0分钟' : this._fmtMin(stats.today_duration_sec || 0),
        _dispWeekSessions: isInitialRender ? 0 : (stats.week_sessions || 0),
        _dispWeekDurationText: isInitialRender ? '0分钟' : this._fmtMin(stats.week_duration_sec || 0),
        // 图表先挂载，再由轻量动画从 0 绘制到最终 3D 状态。
        _chartsReady: isInitialRender ? false : this.data._chartsReady,
      }, () => {
        this._drawChartsWithSmoothAnimation(reqId, isInitialRender)
      })
    } catch (e) {
      if (!this._alive || reqId !== this._requestId) return
      console.error('加载统计失败', e)
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _formatSession(s) {
    const start = new Date(s.start_time + '+00:00')
    const timeStr = `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`
    const durMin = Math.floor((s.actual_duration || 0) / 60)
    return {
      ...s,
      _time: timeStr,
      _date: `${start.getMonth() + 1}/${start.getDate()}`,
      _duration: durMin >= 60 ? `${Math.floor(durMin / 60)}时${durMin % 60}分` : `${durMin}分钟`,
      _subjectLabel: SUBJECT_LABELS[s.subject] || s.subject || '未分类',
      _color: SUBJECT_COLORS[s.subject] || '#3B82F6',
      _statusLabel: s.status === 'completed' ? '完成' : '中断',
      _statusClass: s.status === 'completed' ? 'status-done' : 'status-interrupt',
    }
  },

  onDateChange(e) {
    const date = e.detail.value
    this.setData({ selectedDate: date }, () => {
      this.loadHistory(date)
    })
  },

  goToToday() {
    const now = new Date()
    const y = now.getFullYear()
    const m = String(now.getMonth() + 1).padStart(2, '0')
    const d = String(now.getDate()).padStart(2, '0')
    const today = `${y}-${m}-${d}`
    if (today === this.data.selectedDate) return
    this.setData({ selectedDate: today }, () => {
      this.loadHistory(today)
    })
  },

  async loadHistory(date) {
    const reqId = this._requestId
    try {
      const hist = await api.get('/pomodoro/history', { page: 1, page_size: 20, date })
      if (!this._alive || !this._isVisible || reqId !== this._requestId) return
      const formatted = (hist.items || []).map(this._formatSession)
      this.setData({
        history: formatted,
        historyTotal: hist.total || 0,
      })
    } catch (e) {
      if (!this._alive || !this._isVisible) return
      console.error('加载历史记录失败', e)
    }
  },

  /* ==================== Animation Control ==================== */

  _cancelPendingWork() {
    this._animActive = false
    this._finalDrawn = false
    if (this._finalDrawTimers && this._finalDrawTimers.length) {
      this._finalDrawTimers.forEach(id => clearTimeout(id))
      this._finalDrawTimers = []
    }
    this._requestId++
    if (this._rafId) {
      if (this._rafIsTimer) {
        clearTimeout(this._rafId)
      } else if (this._pieCanvasNode && this._pieCanvasNode.cancelAnimationFrame) {
        this._pieCanvasNode.cancelAnimationFrame(this._rafId)
      }
    }
    this._rafId = null
    this._rafIsTimer = false
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
  },

  _initCanvases(callback) {
    let pending = 2
    const done = () => { if (--pending === 0) callback() }
    // Cap DPR at 2 — backbuffer cost grows quadratically and DPR=3 on iPhones
    // produces ~56% more pixel-fill work for negligible visual gain on a 250px pie.
    const dpr = Math.min(2, wx.getSystemInfoSync().pixelRatio || 2)

    const setup = (selector, nodeKey, ctxKey, rectKey) => {
      wx.createSelectorQuery().in(this)
        .select(selector)
        .fields({ node: true, size: true })
        .exec(res => {
          if (!res || !res[0] || !res[0].node) { done(); return }
          const node = res[0].node
          const ctx = node.getContext('2d')
          const w = res[0].width
          const h = res[0].height
          node.width = Math.round(w * dpr)
          node.height = Math.round(h * dpr)
          ctx.scale(dpr, dpr)
          this[nodeKey] = node
          this[ctxKey] = ctx
          this[rectKey] = { width: w, height: h }
          done()
        })
    }

    setup('#pie-canvas', '_pieCanvasNode', '_pieCtx', '_pieRect')
    setup('#trend-bars-canvas', '_trendCanvasNode', '_trendCtx', '_trendBarsRect')
  },

  _shadeColorCached(hex, amount) {
    const key = hex + '|' + amount
    if (!this._shadeCache) this._shadeCache = {}
    if (this._shadeCache[key]) return this._shadeCache[key]
    const v = this._shadeColor(hex, amount)
    this._shadeCache[key] = v
    return v
  },

  _drawChartsWithSmoothAnimation(reqId, isInitialRender) {
    const draw = () => {
      if (!this._alive || !this._isVisible || reqId !== this._requestId) return
      this._initCanvases(() => {
        if (!this._alive || !this._isVisible || reqId !== this._requestId) return

        if (isInitialRender) {
          // 先画 0 帧并显示画布，再启动轻量 0→1 动画。
          this._renderPieChart(0, true)
          this._renderTrendBars(0, true)
          this.setData({ _chartsReady: true }, () => {
            this._startAnimations(reqId)
          })
        } else {
          // 非首次刷新不重新跑入场动画，避免页面回退/切换时闪动。
          this._renderPieChart(1, false)
          this._renderTrendBars(1, false)
          if (!this.data._chartsReady) this.setData({ _chartsReady: true })
        }
      })
    }

    // loading 隐藏后先让页面完成一次布局，再初始化 canvas。
    // 这样保留动态加载感，同时避免 DOM 挂载、canvas 初始化、重 3D 绘制挤在同一帧。
    if (typeof wx.nextTick === 'function') {
      wx.nextTick(() => {
        setTimeout(draw, 32)
      })
    } else {
      setTimeout(draw, 32)
    }
  },

  _startAnimations(reqId) {
    if (!this._alive || !this._isVisible || reqId !== this._requestId) return
    this._animActive = true
    this._finalDrawn = false

    // 控制在较短时长内完成，减少用户等待；canvas 低频刷新。
    // 注意：动画结束时不在同一帧绘制完整重细节，而是先停在轻量 3D 终态，再分帧精修。
    const animDuration = 520
    const startTime = Date.now()

    // Number animation：只更新 10 次，避免频繁 setData 抢主线程。
    const tSessions = this.data.todaySessions
    const wSessions = this.data.weekSessions
    const totalSteps = 10
    let step = 0
    const numTick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      step++
      const p = Math.min(1, step / totalSteps)
      const e = this._easeOutCubic(p)
      const isLast = p >= 1
      this.setData({
        _dispTodaySessions: isLast ? tSessions : Math.round(tSessions * e),
        _dispTodayDurationText: this._fmtMin(isLast ? this._rawTodayDur : Math.round(this._rawTodayDur * e)),
        _dispWeekSessions: isLast ? wSessions : Math.round(wSessions * e),
        _dispWeekDurationText: this._fmtMin(isLast ? this._rawWeekDur : Math.round(this._rawWeekDur * e)),
      })
      if (step < totalSteps) {
        this._animTimer = setTimeout(numTick, Math.round(animDuration / totalSteps))
      }
    }
    numTick()

    // Canvas animation：约 20–25fps 的轻量绘制，避免每 16ms 都重建复杂渐变。
    // 3D 几何结构在动画过程中就同步存在，最终只做质感增强，不做末帧突变。
    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => {
          this._rafIsTimer = false
          return node.requestAnimationFrame(cb)
        }
      : cb => {
          this._rafIsTimer = true
          return setTimeout(cb, 16)
        }
    let lastPaint = 0
    const minFrameGap = 40

    const tick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const eased = this._easeOutCubic(rawP)
      const now = Date.now()
      const shouldPaint = rawP >= 1 || now - lastPaint >= minFrameGap

      if (shouldPaint) {
        lastPaint = now
        // 动画帧始终使用轻量 3D 画法；即使 rawP 已到 1，也先画轻量终态。
        // 这样不会在动画最后一帧突然创建大量渐变/阴影导致掉帧。
        this._renderPieChart(eased, true)
        this._renderTrendBars(eased, true)
      }

      if (rawP < 1) {
        this._rafId = raf(tick)
      } else if (!this._finalDrawn) {
        this._finalDrawn = true
        this._animActive = false
        this._rafId = null
        // 数字先到最终值；canvas 仍保持轻量 3D 终态。
        this.setData({
          _dispTodaySessions: tSessions,
          _dispTodayDurationText: this._fmtMin(this._rawTodayDur),
          _dispWeekSessions: wSessions,
          _dispWeekDurationText: this._fmtMin(this._rawWeekDur),
        })
        // 完整质感不要挤在最后一帧，而是拆成后续不同帧逐步补齐。
        this._scheduleProgressiveFinalDraw(reqId)
      }
    }
    this._rafId = raf(tick)
  },

  _scheduleProgressiveFinalDraw(reqId) {
    if (!this._alive || !this._isVisible || reqId !== this._requestId) return
    if (this._finalDrawTimers && this._finalDrawTimers.length) {
      this._finalDrawTimers.forEach(id => clearTimeout(id))
    }
    this._finalDrawTimers = []

    const queue = (delay, fn) => {
      const id = setTimeout(() => {
        this._finalDrawTimers = (this._finalDrawTimers || []).filter(tid => tid !== id)
        if (!this._alive || !this._isVisible || reqId !== this._requestId) return
        fn()
      }, delay)
      this._finalDrawTimers.push(id)
    }

    // 第 1 帧：先补柱状图质感。柱状图面积小，先完成不会明显影响饼图展开结束观感。
    queue(32, () => {
      this._renderTrendBars(1, false)
    })

    // 第 2 帧：再补饼图统一光照和阴影。与柱状图错帧，避免两个 canvas 同帧重绘。
    queue(80, () => {
      this._renderPieChart(1, false)
    })
  },

  /* ==================== Trend Bars ==================== */

  _renderTrendBars(progress, fastMode) {
    fastMode = !!fastMode
    const TREND_COLORS = ['#22C55E', '#06B6D4', '#3B82F6', '#818CF8', '#A78BFA', '#D946EF']
    const trends = this.data.trends
    if (!trends || !trends.length) return
    const ctx = this._trendCtx
    const rect = this._trendBarsRect
    if (!ctx || !rect || !rect.width) return

    const w = rect.width
    const h = rect.height
    const padL = 44
    const padR = 16
    const padT = 24
    const padB = 32
    const chartW = w - padL - padR
    const chartH = h - padT - padB
    const barW = Math.min(32, chartW / trends.length * 0.5)
    const gap = chartW / trends.length
    const maxDur = Math.max(1, ...trends.map(t => t.duration_sec || 0))
    const depth = Math.min(7, barW * 0.28)
    const topTilt = 0.45

    const isFinal = progress >= 1 && !fastMode
    const fadeIn = (start) => Math.max(0, Math.min(1, (progress - start) / (1 - start)))
    // 即便将来重新启用动画，也让 3D 效果随柱体同步出现，避免末帧突然补 3D。
    const finalFade = progress

    ctx.clearRect(0, 0, w, h)

    // Grid lines — subtle horizontal guides
    for (let i = 0; i <= 3; i++) {
      const y = padT + chartH * (1 - i / 3)
      ctx.beginPath()
      ctx.strokeStyle = 'rgba(255,255,255,0.03)'
      ctx.lineWidth = 0.5
      ctx.moveTo(padL, y)
      ctx.lineTo(w - padR, y)
      ctx.stroke()
    }

    // Baseline
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(255,255,255,0.08)'
    ctx.lineWidth = 1
    ctx.moveTo(padL, padT + chartH)
    ctx.lineTo(w - padR, padT + chartH)
    ctx.stroke()

    trends.forEach((t, i) => {
      const x = padL + gap * i + (gap - barW) / 2
      const finalBarH = (t.duration_sec || 0) / maxDur * chartH
      const barH = Math.max(0, finalBarH * progress)
      const baseY = padT + chartH
      const topY = baseY - barH
      const show3D = barH > Math.max(4, depth * topTilt * 2)

      if (t.duration_sec > 0 && barH > 0) {
        // Ground shadow — 最终精修时用纯色椭圆，不再为每根柱子创建 radialGradient。
        if (!fastMode && finalFade > 0) {
          ctx.save()
          ctx.globalAlpha = finalFade * 0.18
          ctx.translate(x + barW / 2, baseY + 2)
          ctx.scale(1, 0.24)
          ctx.fillStyle = 'rgba(0,0,0,0.34)'
          ctx.beginPath()
          ctx.arc(0, 0, barW * 0.7, 0, Math.PI * 2)
          ctx.fill()
          ctx.restore()
        }

        // Per-bar color
        const barColor = TREND_COLORS[i % TREND_COLORS.length]
        const rc = parseInt(barColor.slice(1, 3), 16)
        const gc = parseInt(barColor.slice(3, 5), 16)
        const bc = parseInt(barColor.slice(5, 7), 16)

        // Right side face — darker crystal depth
        if (show3D) {
          ctx.save()
          ctx.globalAlpha = finalFade
          ctx.fillStyle = `rgba(${Math.round(rc*0.5)},${Math.round(gc*0.5)},${Math.round(bc*0.5)},0.85)`
          ctx.beginPath()
          ctx.moveTo(x + barW, topY)
          ctx.lineTo(x + barW + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW + depth, baseY - depth * topTilt)
          ctx.lineTo(x + barW, baseY)
          ctx.closePath()
          ctx.fill()
          ctx.restore()
        }

        // Left edge glow — light escaping crystal facet
        if (!fastMode && barH > 6) {
          ctx.fillStyle = `rgba(${Math.min(255,rc+110)},${Math.min(255,gc+110)},${Math.min(255,bc+110)},0.3)`
          ctx.fillRect(x, topY + 2, 1.5, Math.max(0, barH - 4))
        }

        // Front face — 动画中用纯色，最终帧再使用渐变，减少中间帧开销。
        if (fastMode) {
          ctx.fillStyle = `rgba(${rc},${gc},${bc},0.86)`
          ctx.fillRect(x, topY, barW, barH)
        } else {
          const barGrad = ctx.createLinearGradient(0, topY, 0, baseY)
          barGrad.addColorStop(0, 'rgba(255,255,255,0.12)')
          barGrad.addColorStop(0.1, `rgba(${rc},${gc},${bc},0.6)`)
          barGrad.addColorStop(0.42, `rgba(${rc},${gc},${bc},0.92)`)
          barGrad.addColorStop(0.82, `rgba(${Math.round(rc*0.7)},${Math.round(gc*0.7)},${Math.round(bc*0.7)},0.72)`)
          barGrad.addColorStop(1, `rgba(${Math.round(rc*0.4)},${Math.round(gc*0.4)},${Math.round(bc*0.4)},0.5)`)
          ctx.fillStyle = barGrad
          ctx.fillRect(x, topY, barW, barH)
        }

        // Center light channel — light pipe through crystal
        if (!fastMode && barH > 8) {
          const lcW = Math.max(2, barW * 0.28)
          const lcX = x + (barW - lcW) / 2
          const lcGrad = ctx.createLinearGradient(0, topY, 0, topY + barH * 0.7)
          lcGrad.addColorStop(0, 'rgba(255,255,255,0.52)')
          lcGrad.addColorStop(0.35, 'rgba(255,255,255,0.12)')
          lcGrad.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.fillStyle = lcGrad
          ctx.fillRect(lcX, topY, lcW, barH)
        }

        // Front top-edge highlight — sharp crystal rim
        if (!fastMode && barH > 4) {
          ctx.fillStyle = 'rgba(255,255,255,0.35)'
          ctx.fillRect(x, topY, barW, Math.min(2.5, barH / 5))
          ctx.fillStyle = 'rgba(255,255,255,0.15)'
          ctx.fillRect(x, topY + Math.min(2.5, barH / 5), barW, Math.min(1.5, barH / 8))
        }

        // Front gloss sweep — refined light wash on upper portion
        if (!fastMode && show3D && barH > 20) {
          ctx.save()
          ctx.globalAlpha = finalFade * 0.18
          const fg = ctx.createLinearGradient(x, topY, x + barW, topY)
          fg.addColorStop(0, 'rgba(255,255,255,0)')
          fg.addColorStop(0.2, 'rgba(255,255,255,0.5)')
          fg.addColorStop(0.45, 'rgba(255,255,255,0.04)')
          fg.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.fillStyle = fg
          ctx.fillRect(x, topY, barW, barH * 0.55)
          ctx.restore()
        }

        // Top face — bright crystal facet；动画中保留基础顶面，最终帧补细节。
        if (show3D) {
          ctx.save()
          ctx.globalAlpha = finalFade
          ctx.fillStyle = `rgba(${Math.min(255,rc+100)},${Math.min(255,gc+100)},${Math.min(255,bc+100)},0.6)`
          ctx.beginPath()
          ctx.moveTo(x, topY)
          ctx.lineTo(x + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW, topY)
          ctx.closePath()
          ctx.fill()

          if (!fastMode) {
            // Crystal ridge — bright seam along front-top edge
            ctx.fillStyle = 'rgba(255,255,255,0.4)'
            ctx.fillRect(x + depth * 0.15, topY - depth * topTilt * 0.3, barW * 0.7, depth * topTilt * 0.3)

            // Top facet highlight spot
            ctx.fillStyle = 'rgba(255,255,255,0.18)'
            const spotW = barW * 0.3
            const spotX = x + barW * 0.5
            ctx.fillRect(spotX, topY - depth * topTilt * 0.65, spotW, depth * topTilt * 0.35)
          }
          ctx.restore()
        }
      } else if (t.duration_sec > 0) {
        ctx.fillStyle = 'rgba(255,255,255,0.05)'
        ctx.fillRect(x, baseY - 1, barW, 1)
      } else {
        ctx.fillStyle = 'rgba(255,255,255,0.03)'
        ctx.fillRect(x, baseY - 2, barW, 2)
      }

      // Date label
      ctx.fillStyle = 'rgba(255,255,255,0.25)'
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(t._shortDate || '', x + barW / 2, baseY + 18)
    })
  },

  /* ==================== Pie Chart ==================== */

  _shadeColor(hex, amount) {
    const safeHex = /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : '#3B82F6'
    const num = parseInt(safeHex.slice(1), 16)
    const clamp = value => Math.max(0, Math.min(255, value))
    const r = clamp((num >> 16) + amount)
    const g = clamp(((num >> 8) & 0xff) + amount)
    const b = clamp((num & 0xff) + amount)
    return `rgb(${r}, ${g}, ${b})`
  },

  _drawEllipticSector(ctx, cx, cy, radius, scaleY, startA, endA, fillStyle, strokeStyle, lineW) {
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(1, scaleY)
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.arc(0, 0, radius, startA, endA)
    ctx.closePath()
    if (fillStyle) {
      ctx.fillStyle = fillStyle
      ctx.fill()
    }
    if (strokeStyle) {
      ctx.strokeStyle = strokeStyle
      ctx.lineWidth = lineW || 1
      ctx.stroke()
    }
    ctx.restore()
  },

  _renderPieChart(progress, fastMode) {
    fastMode = !!fastMode
    const subjects = this.data.subjects
    const ctx = this._pieCtx
    const rect = this._pieRect
    if (!ctx || !rect || !rect.width) return
    const w = rect.width
    const h = rect.height
    const size = Math.min(w, h)
    const centerX = w / 2
    const centerY = h * 0.44
    const radius = size * 0.39
    const tilt = 0.72
    const depth = radius * 0.08
    const isFinal = progress >= 1 && !fastMode

    ctx.clearRect(0, 0, w, h)

    const hasData = subjects && subjects.length && subjects.some(s => (s.duration_sec || 0) > 0)
    if (!hasData) {
      this._drawEllipticSector(ctx, centerX, centerY, radius, tilt, 0, Math.PI * 2, 'rgba(255,255,255,0.05)', 'rgba(255,255,255,0.08)', 1)
      ctx.fillStyle = 'rgba(255,255,255,0.28)'
      ctx.font = '12px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('今日暂无数据', centerX, centerY + 6)
      return
    }

    // Build sector + shade caches once per data set
    if (!this._pieSectors) {
      const totalDur = subjects.reduce((sum, s) => sum + (s.duration_sec || 0), 0) || 1
      const sectors = []
      let angle = -Math.PI / 2
      subjects.filter(s => (s.duration_sec || 0) > 0).forEach(s => {
        const pct = (s.duration_sec || 0) / totalDur
        const endA = angle + Math.PI * 2 * pct
        sectors.push({
          subject: s,
          color: s._color || '#3B82F6',
          startA: angle,
          endA,
        })
        angle = endA
      })
      this._pieSectors = sectors
      const wallStepsFull = Math.max(6, Math.round(depth * 1.5))
      this._pieWallSteps = wallStepsFull
      sectors.forEach(sec => {
        sec._wallShades = []
        for (let layer = 1; layer <= wallStepsFull; layer++) {
          const ratio = layer / wallStepsFull
          // Progressive darkening: -55 at bottom, -15 at top
          const darken = Math.round(-55 + ratio * 40)
          sec._wallShades.push(this._shadeColorCached(sec.color, darken))
        }
      })
    }

    const sectors = this._pieSectors
    const wallStepsFull = this._pieWallSteps
    const wallSteps = fastMode ? Math.min(3, wallStepsFull) : (isFinal ? wallStepsFull : Math.min(3, wallStepsFull))

    const selectedSubject = this.data._selectedSubject

    // === 1. Drop shadow (final only) — soft, offset to bottom-right ===
    if (isFinal) {
      ctx.save()
      ctx.translate(centerX + 4, centerY + depth * 1.3)
      ctx.scale(1, tilt)
      const shadowGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius * 1.05)
      shadowGrad.addColorStop(0, 'rgba(0,0,0,0.25)')
      shadowGrad.addColorStop(0.5, 'rgba(0,0,0,0.10)')
      shadowGrad.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = shadowGrad
      ctx.beginPath()
      ctx.arc(0, 0, radius * 1.05, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // Sort: selected sector drawn last for correct overlap
    const sortedSectors = [...sectors]
    if (selectedSubject) {
      sortedSectors.sort((a, b) => {
        const aSel = a.subject.subject === selectedSubject ? 1 : 0
        const bSel = b.subject.subject === selectedSubject ? 1 : 0
        return aSel - bSel
      })
    }

    // === 2. Side walls — stacked elliptic layers with progressive darkening ===
    for (let layer = wallSteps; layer >= 1; layer--) {
      const layerOffset = depth * layer / wallSteps * progress
      const shadeIdx = Math.min(wallStepsFull - 1, Math.round((layer - 1) * wallStepsFull / wallSteps))
      sortedSectors.forEach(sec => {
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.002) return
        const mid = (sec.startA + curEnd) / 2
        const isSelected = selectedSubject && sec.subject.subject === selectedSubject
        const pull = isSelected ? 6 : 0
        const cx = centerX + Math.cos(mid) * pull
        const cy = centerY + Math.sin(mid) * pull * tilt + layerOffset
        this._drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, sec._wallShades[shadeIdx])
      })
    }

    // === 3. Top sectors — clean color fills, no per-sector strokes ===
    sortedSectors.forEach(sec => {
      const curEnd = sec.startA + (sec.endA - sec.startA) * progress
      if (curEnd - sec.startA < 0.002) return
      const mid = (sec.startA + curEnd) / 2
      const isSelected = selectedSubject && sec.subject.subject === selectedSubject
      const pull = isSelected ? 6 : 0
      const cx = centerX + Math.cos(mid) * pull
      const cy = centerY + Math.sin(mid) * pull * tilt
      const fillColor = isSelected ? this._shadeColorCached(sec.color, 12) : sec.color
      this._drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, fillColor)
    })

    // === 4. Sector separators — thin, low-opacity dark lines ===
    if (isFinal && sectors.length > 1) {
      ctx.save()
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.strokeStyle = 'rgba(0,0,0,0.12)'
      ctx.lineWidth = 1
      sectors.forEach(sec => {
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(Math.cos(sec.startA) * radius, Math.sin(sec.startA) * radius)
        ctx.stroke()
      })
      // Close the ring — draw separator at last sector's end angle
      const last = sectors[sectors.length - 1]
      ctx.beginPath()
      ctx.moveTo(0, 0)
      ctx.lineTo(Math.cos(last.endA) * radius, Math.sin(last.endA) * radius)
      ctx.stroke()
      ctx.restore()
    }

    // === 5. Unified lighting — single radial gradient from top-left ===
    if (isFinal) {
      ctx.save()
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.clip()
      const lightGrad = ctx.createRadialGradient(
        -radius * 0.2, -radius * 0.2, 0,
        -radius * 0.2, -radius * 0.2, radius
      )
      lightGrad.addColorStop(0, 'rgba(255,255,255,0.14)')
      lightGrad.addColorStop(0.35, 'rgba(255,255,255,0.04)')
      lightGrad.addColorStop(0.7, 'rgba(0,0,0,0.04)')
      lightGrad.addColorStop(1, 'rgba(0,0,0,0.10)')
      ctx.fillStyle = lightGrad
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // === 6. Selected state: dim non-selected + highlight selected ===
    if (selectedSubject && isFinal) {
      // Dim non-selected sectors
      sectors.forEach(sec => {
        if (sec.subject.subject === selectedSubject) return
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.002) return
        ctx.save()
        ctx.globalAlpha = 0.12
        ctx.fillStyle = 'rgba(0,0,0,0.7)'
        this._drawEllipticSector(ctx, centerX, centerY, radius, tilt, sec.startA, curEnd)
        ctx.restore()
      })
      // Highlight selected — thin bright border
      sectors.forEach(sec => {
        if (sec.subject.subject !== selectedSubject) return
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.002) return
        const mid = (sec.startA + curEnd) / 2
        const cx = centerX + Math.cos(mid) * 6
        const cy = centerY + Math.sin(mid) * 6 * tilt
        this._drawEllipticSector(ctx, cx, cy, radius * 1.03, tilt, sec.startA, curEnd, null, 'rgba(255,255,255,0.2)', 1.5)
      })
    }
  },

  /* ==================== Touch Interactions ==================== */

  onPieTap(e) {
    const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0])
    const tapX = touch ? touch.clientX : e.detail && e.detail.x
    const tapY = touch ? touch.clientY : e.detail && e.detail.y
    if (typeof tapX !== 'number' || typeof tapY !== 'number') return

    const query = wx.createSelectorQuery().in(this)
    query.select('#pie-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width) return
      const x = tapX - rect.left
      const y = tapY - rect.top
      const centerX = rect.width / 2
      const centerY = rect.height * 0.44
      const radius = Math.min(rect.width, rect.height) * 0.39
      const tilt = 0.72

      const dx = x - centerX
      const dy = (y - centerY) / tilt
      const dist = Math.sqrt(dx * dx + dy * dy)

      // Outside the 3D pie footprint — dismiss
      if (dist > radius) {
        if (this.data.selectedSubjectDetail) {
          this.setData({
            selectedSubjectDetail: null,
            _selectedSubject: null,
          }, () => { if (this._alive) this._renderPieChart(1) })
        }
        return
      }

      let angle = Math.atan2(dy, dx)
      if (angle < -Math.PI / 2) angle += Math.PI * 2

      const subjects = this.data.subjects
      const totalDur = subjects.reduce((sum, s) => sum + (s.duration_sec || 0), 0) || 1
      let cumulativeStart = -Math.PI / 2
      for (const s of subjects) {
        const pct = (s.duration_sec || 0) / totalDur
        const cumulativeEnd = cumulativeStart + Math.PI * 2 * pct
        if (pct > 0 && angle >= cumulativeStart && angle < cumulativeEnd) {
          this.setData({
            selectedSubjectDetail: s,
            _selectedSubject: s.subject,
            pieTapped: true,
          }, () => {
            if (!this._alive) return
            this._renderPieChart(1)
            setTimeout(() => { if (this._alive) this.setData({ pieTapped: false }) }, 350)
          })
          return
        }
        cumulativeStart = cumulativeEnd
      }
    }).exec()
  },

  closeDetail() {
    this.setData({
      selectedSubjectDetail: null,
      _selectedSubject: null,
    }, () => { if (this._alive) this._renderPieChart(1) })
  },

  noop() {},

  _fmtMin(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分钟`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },
})
