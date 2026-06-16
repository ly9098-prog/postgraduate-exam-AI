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
  },

  onLoad() {
    wx.setNavigationBarColor({
      frontColor: '#ffffff',
      backgroundColor: '#0B1121',
    })
    const now = new Date()
    const y = now.getFullYear()
    const m = String(now.getMonth() + 1).padStart(2, '0')
    const d = String(now.getDate()).padStart(2, '0')
    const today = `${y}-${m}-${d}`
    this.setData({ selectedDate: today, _todayDate: today })
  },

  onShow() {
    this.loadData()
    setTimeout(() => {
      this.setData({ pageEntered: true })
    }, 50)
  },

  onUnload() {
    this._stopAnimation()
  },

  /* ==================== Color Helpers ==================== */

  _easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3)
  },

  /* ==================== Data Loading ==================== */

  async loadData() {
    this.setData({ loading: true })
    try {
      const [stats, trends, subjects, hist] = await Promise.all([
        api.get('/pomodoro/stats'),
        api.get('/pomodoro/trends', { days: 7 }),
        api.get('/pomodoro/subjects'),
        api.get('/pomodoro/history', { page: 1, page_size: 20, date: this.data.selectedDate }),
      ])
      const subjArr = subjects || []
      const totalDur = Math.max(1, subjArr.reduce((sum, s) => sum + (s.duration_sec || 0), 0))
      this._rawTodayDur = stats.today_duration_sec || 0
      this._rawWeekDur = stats.week_duration_sec || 0
      this._pieSectors = null
      this._shadeCache = null

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
        _dispTodaySessions: 0,
        _dispTodayDurationText: '0分钟',
        _dispWeekSessions: 0,
        _dispWeekDurationText: '0分钟',
      }, () => {
        // setData has committed; view layer is mounting. Init canvases inside the
        // callback so #pie-canvas / #trend-bars-canvas are guaranteed in the tree.
        this._initCanvases(() => {
          // Pre-warm: build _pieSectors cache and paint frame 0 of both charts so
          // the first animation frame doesn't pay the cache-construction tax.
          this._renderPieChart(0)
          this._renderTrendBars(0)
          // Defer 2 vsync ticks so initial page paint (history list, cards, legend)
          // completes before the heavy 60fps render loop starts. Avoids contention
          // on the first few frames that produced the visible entry stutter.
          const node = this._pieCanvasNode
          const raf = node && node.requestAnimationFrame
            ? cb => node.requestAnimationFrame(cb)
            : cb => setTimeout(cb, 16)
          raf(() => raf(() => this._startAnimations()))
        })
      })
    } catch (e) {
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
    try {
      const hist = await api.get('/pomodoro/history', { page: 1, page_size: 20, date })
      const formatted = (hist.items || []).map(this._formatSession)
      this.setData({
        history: formatted,
        historyTotal: hist.total || 0,
      })
    } catch (e) {
      console.error('加载历史记录失败', e)
    }
  },

  /* ==================== Animation Control ==================== */

  _stopAnimation() {
    if (this._rafId && this._pieCanvasNode && this._pieCanvasNode.cancelAnimationFrame) {
      this._pieCanvasNode.cancelAnimationFrame(this._rafId)
    }
    this._rafId = null
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
    this._animActive = false
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

  _startAnimations() {
    this._animActive = true
    const animDuration = 700
    const startTime = Date.now()
    const tSessions = this.data.todaySessions
    const wSessions = this.data.weekSessions
    let prevTodaySess = -1
    let prevWeekSess = -1
    let prevTodayDur = -1
    let prevWeekDur = -1

    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)

    let frameCount = 0

    const tick = () => {
      if (!this._animActive) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const eased = this._easeOutCubic(rawP)
      frameCount++

      // Throttle setData to ~3-frame intervals (~48ms) to reduce cross-bridge cost
      if (frameCount % 3 === 1 || rawP >= 1) {
        const curTodaySess = Math.round(tSessions * eased)
        const curWeekSess = Math.round(wSessions * eased)
        const curTodayDur = Math.round(this._rawTodayDur * eased)
        const curWeekDur = Math.round(this._rawWeekDur * eased)

        if (curTodaySess !== prevTodaySess ||
            curWeekSess !== prevWeekSess ||
            curTodayDur !== prevTodayDur ||
            curWeekDur !== prevWeekDur) {
          prevTodaySess = curTodaySess
          prevWeekSess = curWeekSess
          prevTodayDur = curTodayDur
          prevWeekDur = curWeekDur
          this.setData({
            _dispTodaySessions: curTodaySess,
            _dispTodayDurationText: this._fmtMin(curTodayDur),
            _dispWeekSessions: curWeekSess,
            _dispWeekDurationText: this._fmtMin(curWeekDur),
          })
        }
      }

      // Throttle canvas renders to alternating frames (~30fps) — final frame always renders
      if (frameCount % 2 === 1 || rawP >= 1) {
        this._renderPieChart(eased)
        this._renderTrendBars(eased)
      }

      if (rawP < 1) {
        this._rafId = raf(tick)
      } else {
        this._animActive = false
        this._rafId = null
        this._renderPieChart(1)
        this._renderTrendBars(1)
      }
    }
    this._rafId = raf(tick)
  },

  /* ==================== Trend Bars ==================== */

  _renderTrendBars(progress) {
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

    const isFinal = progress >= 1
    const fadeIn = (start) => Math.max(0, Math.min(1, (progress - start) / (1 - start)))
    const finalFade = fadeIn(0.82)

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
      const show3D = finalFade > 0.01 && barH > depth * topTilt * 2

      if (t.duration_sec > 0 && barH > 0) {
        // Ground shadow — soft ellipse at base, fades in with finalFade
        if (finalFade > 0) {
          ctx.save()
          ctx.globalAlpha = finalFade * 0.45
          ctx.translate(x + barW / 2, baseY + 2)
          ctx.scale(1, 0.28)
          const shGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, barW * 0.75)
          shGrad.addColorStop(0, 'rgba(0,0,0,0.32)')
          shGrad.addColorStop(0.5, 'rgba(0,0,0,0.14)')
          shGrad.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = shGrad
          ctx.beginPath()
          ctx.arc(0, 0, barW * 0.75, 0, Math.PI * 2)
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
        ctx.fillStyle = `rgba(${Math.min(255,rc+110)},${Math.min(255,gc+110)},${Math.min(255,bc+110)},0.3)`
        ctx.fillRect(x, topY + 2, 1.5, barH - 4)

        // Front face — translucent crystal gradient
        const barGrad = ctx.createLinearGradient(0, topY, 0, baseY)
        barGrad.addColorStop(0, 'rgba(255,255,255,0.12)')
        barGrad.addColorStop(0.1, `rgba(${rc},${gc},${bc},0.6)`)
        barGrad.addColorStop(0.42, `rgba(${rc},${gc},${bc},0.92)`)
        barGrad.addColorStop(0.82, `rgba(${Math.round(rc*0.7)},${Math.round(gc*0.7)},${Math.round(bc*0.7)},0.72)`)
        barGrad.addColorStop(1, `rgba(${Math.round(rc*0.4)},${Math.round(gc*0.4)},${Math.round(bc*0.4)},0.5)`)
        ctx.fillStyle = barGrad
        ctx.fillRect(x, topY, barW, barH)

        // Center light channel — light pipe through crystal
        if (barH > 8) {
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
        if (barH > 4) {
          ctx.fillStyle = 'rgba(255,255,255,0.35)'
          ctx.fillRect(x, topY, barW, Math.min(2.5, barH / 5))
          ctx.fillStyle = 'rgba(255,255,255,0.15)'
          ctx.fillRect(x, topY + Math.min(2.5, barH / 5), barW, Math.min(1.5, barH / 8))
        }

        // Front gloss sweep — refined light wash on upper portion
        if (show3D && barH > 20) {
          ctx.save()
          ctx.globalAlpha = fadeIn(0.84) * 0.28
          const fg = ctx.createLinearGradient(x, topY, x + barW, topY)
          fg.addColorStop(0, 'rgba(255,255,255,0)')
          fg.addColorStop(0.2, 'rgba(255,255,255,0.5)')
          fg.addColorStop(0.45, 'rgba(255,255,255,0.04)')
          fg.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.fillStyle = fg
          ctx.fillRect(x, topY, barW, barH * 0.55)
          ctx.restore()
        }

        // Top face — bright crystal facet
        if (show3D) {
          ctx.save()
          ctx.globalAlpha = fadeIn(0.83)
          ctx.fillStyle = `rgba(${Math.min(255,rc+100)},${Math.min(255,gc+100)},${Math.min(255,bc+100)},0.6)`
          ctx.beginPath()
          ctx.moveTo(x, topY)
          ctx.lineTo(x + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW + depth, topY - depth * topTilt)
          ctx.lineTo(x + barW, topY)
          ctx.closePath()
          ctx.fill()

          // Crystal ridge — bright seam along front-top edge
          ctx.fillStyle = 'rgba(255,255,255,0.4)'
          ctx.fillRect(x + depth * 0.15, topY - depth * topTilt * 0.3, barW * 0.7, depth * topTilt * 0.3)

          // Top facet highlight spot
          ctx.fillStyle = 'rgba(255,255,255,0.18)'
          const spotW = barW * 0.3
          const spotX = x + barW * 0.5
          ctx.fillRect(spotX, topY - depth * topTilt * 0.65, spotW, depth * topTilt * 0.35)
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
    ctx.fillStyle = fillStyle
    ctx.fill()
    if (strokeStyle) {
      ctx.strokeStyle = strokeStyle
      ctx.lineWidth = lineW || 1
      ctx.stroke()
    }
    ctx.restore()
  },

  _renderPieChart(progress) {
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
    const tilt = 0.58
    const depth = size * 0.16
    // Phase final-quality effects (full depth, shadow, gloss, specular) across
    // the tail of animation. Staggered start times (0.82→0.92) spread the
    // clip + gradient draw-call cost frame-to-frame instead of spiking at once.
    const isFinal = progress >= 1
    const fadeIn = (start) => Math.max(0, Math.min(1, (progress - start) / (1 - start)))

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
      const sideStepsFull = Math.max(8, Math.round(depth / 3))
      this._pieSideSteps = sideStepsFull
      // Pre-compute per-layer shade amounts (sector color + layer index) for ALL
      // layers up to full quality. During animation we use a subset; final frame
      // uses every entry.
      sectors.forEach(sec => {
        sec._shades = []
        for (let layer = 1; layer <= sideStepsFull; layer++) {
          sec._shades[layer] = this._shadeColorCached(sec.color, -30 + Math.round(layer / sideStepsFull * 20))
        }
      })
    }

    const sectors = this._pieSectors
    const sideStepsFull = this._pieSideSteps
    const motionSteps = Math.min(12, sideStepsFull)
    const sideSteps = isFinal
      ? sideStepsFull
      : Math.round(motionSteps + (sideStepsFull - motionSteps) * fadeIn(0.82))
    // When using a reduced layer count, sample shades evenly from the full cache so
    // gradient feels the same — just coarser steps.
    const shadeStride = sideStepsFull / sideSteps

    // Drop shadow — fade in during the quality-transition tail so its gradient
    // build + ellipse fill cost is amortized across frames.
    if (fadeIn(0.82) > 0) {
      ctx.save()
      ctx.globalAlpha = fadeIn(0.82)
      ctx.translate(centerX, centerY + depth * 1.02)
      ctx.scale(1, tilt)
      const shadow = ctx.createLinearGradient(0, -radius * 0.4, 0, radius * 1.2)
      shadow.addColorStop(0, 'rgba(0,0,0,0.34)')
      shadow.addColorStop(0.55, 'rgba(0,0,0,0.22)')
      shadow.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = shadow
      ctx.beginPath()
      ctx.arc(0, 0, radius * 1.18, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    const selectedSubject = this.data._selectedSubject

    // Side depth layers
    for (let layer = sideSteps; layer >= 1; layer--) {
      const layerOffset = depth * layer / sideSteps * progress
      // Map reduced-count layer index back into full-cache index for the shade
      const shadeIdx = Math.max(1, Math.min(sideStepsFull, Math.round(layer * shadeStride)))
      sectors.forEach(sec => {
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.002) return
        const isSelected = selectedSubject && sec.subject.subject === selectedSubject
        const mid = (sec.startA + curEnd) / 2
        const pull = isSelected ? 14 : 0
        const cx = centerX + Math.cos(mid) * pull
        const cy = centerY + Math.sin(mid) * pull * tilt + layerOffset
        this._drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, sec._shades[shadeIdx], 'rgba(0,0,0,0.12)', 0.5)
      })
    }

    // Top sectors
    sectors.forEach(sec => {
      const curEnd = sec.startA + (sec.endA - sec.startA) * progress
      if (curEnd - sec.startA < 0.002) return
      const isSelected = selectedSubject && sec.subject.subject === selectedSubject
      const mid = (sec.startA + curEnd) / 2
      const pull = isSelected ? 14 : 0
      const cx = centerX + Math.cos(mid) * pull
      const cy = centerY + Math.sin(mid) * pull * tilt
      this._drawEllipticSector(
        ctx,
        cx,
        cy,
        radius * (isSelected ? 1.03 : 1),
        tilt,
        sec.startA,
        curEnd,
        sec.color,
        isSelected ? 'rgba(200,230,255,0.95)' : 'rgba(200,230,255,0.65)',
        isSelected ? 3 : 2.5
      )
    })

    // Center light burst — ice glows from center, radiates through all sectors
    if (fadeIn(0.84) > 0) {
      ctx.save()
      ctx.globalAlpha = fadeIn(0.84) * 0.5
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.clip()
      const centerLight = ctx.createRadialGradient(0, 0, 0, 0, 0, radius * 0.7)
      centerLight.addColorStop(0, 'rgba(220,235,255,0.6)')
      centerLight.addColorStop(0.25, 'rgba(220,235,255,0.18)')
      centerLight.addColorStop(0.55, 'rgba(220,235,255,0.05)')
      centerLight.addColorStop(1, 'rgba(220,235,255,0)')
      ctx.fillStyle = centerLight
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // Outer rim glow — ice edge catches light
    if (fadeIn(0.86) > 0) {
      ctx.save()
      ctx.globalAlpha = fadeIn(0.86) * 0.45
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius * 1.02, -1.2, 0.2)
      ctx.strokeStyle = 'rgba(200,230,255,0.6)'
      ctx.lineWidth = 6
      ctx.stroke()
      ctx.restore()
    }

    // Frost overlay — icy sheen across top facets
    if (fadeIn(0.88) > 0) {
      ctx.save()
      ctx.globalAlpha = fadeIn(0.88) * 0.25
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.clip()
      const frost = ctx.createLinearGradient(-radius, -radius * 0.5, radius, radius * 0.5)
      frost.addColorStop(0, 'rgba(200,230,255,0.5)')
      frost.addColorStop(0.25, 'rgba(240,248,255,0.1)')
      frost.addColorStop(0.65, 'rgba(200,230,255,0.05)')
      frost.addColorStop(1, 'rgba(180,215,250,0.15)')
      ctx.fillStyle = frost
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // Gloss sheen — most expensive clip+gradient pass, starts late
    if (fadeIn(0.90) > 0) {
      ctx.save()
      ctx.globalAlpha = fadeIn(0.90)
      ctx.translate(centerX, centerY)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.clip()
      const gloss = ctx.createLinearGradient(-radius, -radius, radius, radius)
      gloss.addColorStop(0, 'rgba(220,240,255,0.55)')
      gloss.addColorStop(0.2, 'rgba(220,240,255,0.2)')
      gloss.addColorStop(0.45, 'rgba(255,255,255,0)')
      gloss.addColorStop(0.75, 'rgba(200,225,255,0.08)')
      gloss.addColorStop(1, 'rgba(140,175,215,0.4)')
      ctx.fillStyle = gloss
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // Specular highlight — last to fade, no clip, cheap radial gradient
    if (fadeIn(0.92) > 0) {
      ctx.save()
      ctx.globalAlpha = fadeIn(0.92)
      ctx.translate(centerX - radius * 0.17, centerY - radius * 0.09)
      ctx.scale(1, tilt)
      ctx.beginPath()
      ctx.arc(0, 0, radius * 0.28, 0, Math.PI * 2)
      const specGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius * 0.28)
      specGrad.addColorStop(0, 'rgba(230,245,255,0.85)')
      specGrad.addColorStop(0.25, 'rgba(220,240,255,0.2)')
      specGrad.addColorStop(1, 'rgba(200,230,255,0)')
      ctx.fillStyle = specGrad
      ctx.fill()
      ctx.restore()
    }

    // Selected sector ring
    if (selectedSubject) {
      sectors.forEach(sec => {
        if (sec.subject.subject !== selectedSubject) return
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        const mid = (sec.startA + curEnd) / 2
        const cx = centerX + Math.cos(mid) * 14
        const cy = centerY + Math.sin(mid) * 14 * tilt
        this._drawEllipticSector(ctx, cx, cy, radius * 1.08, tilt, sec.startA, curEnd, 'rgba(200,230,255,0.08)', 'rgba(200,230,255,0.3)', 7)
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
      const tilt = 0.58

      const dx = x - centerX
      const dy = (y - centerY) / tilt
      const dist = Math.sqrt(dx * dx + dy * dy)

      // Outside the 3D pie footprint — dismiss
      if (dist > radius) {
        if (this.data.selectedSubjectDetail) {
          this.setData({
            selectedSubjectDetail: null,
            _selectedSubject: null,
          }, () => this._renderPieChart(1))
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
            this._renderPieChart(1)
            setTimeout(() => this.setData({ pieTapped: false }), 350)
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
    }, () => this._renderPieChart(1))
  },

  noop() {},

  _fmtMin(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分钟`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },
})
