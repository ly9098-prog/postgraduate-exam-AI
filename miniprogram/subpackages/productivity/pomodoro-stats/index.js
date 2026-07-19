const api = require('../../../utils/api')

function parseServerTime(value) {
  if (!value) return NaN
  if (typeof value === 'number') return value
  const s = String(value).trim()
  if (!s) return NaN
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(hasTimezone ? s : s + '+00:00').getTime()
}

function getSubjectColor(subject) {
  const COLORS = ['#3B82F6', '#F59E0B', '#10B981', '#06B6D4', '#F97316', '#2DD4BF', '#EA580C', '#8B5CF6', '#6366F1', '#EC4899']
  let hash = 0
  const str = subject || ''
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  return COLORS[Math.abs(hash) % COLORS.length]
}

/**
 * Format duration seconds into a human-readable hours/minutes string.
 *
 * Rules:
 *  - Floor to complete minutes (no rounding up).
 *  - < 1 hour: "X分钟" (e.g. "41分钟")
 *  - >= 1 hour: "X时Y分" (e.g. "4时19分", "1时0分")
 *  - Never show seconds.
 */
function formatDuration(sec) {
  var s = Math.max(0, sec || 0)
  var totalMin = Math.floor(s / 60)
  var hours = Math.floor(totalMin / 60)
  var mins = totalMin % 60
  if (hours > 0) return hours + '时' + mins + '分'
  return mins + '分钟'
}

var pageConfig = {
  data: {
    loading: true,
    errorText: '',
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
    this.setData({ selectedDate: today, _todayDate: today })
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
    const reqId = this._requestId
    this.setData({ loading: true, errorText: '' })
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

      const willAnimate = !this._hasData
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
          const name = s.subject_name || '未分类'
          const code = s.subject_code || ''
          return {
            subject: code,
            subject_id: s.subject_id,
            subject_code: code,
            duration_sec: dur,
            sessions: s.sessions || 0,
            _label: name,
            _color: getSubjectColor(code),
            _durationText: this._fmtMin(dur),
            _pctText: (pct * 100).toFixed(1) + '%',
          }
        }),
        history: (hist.items || []).map(this._formatSession),
        historyTotal: hist.total || 0,
        loading: false,
        errorText: '',
        pageEntered: true,
        _dispTodaySessions: 0,
        _dispTodayDurationText: '0分钟',
        _dispWeekSessions: 0,
        _dispWeekDurationText: '0分钟',
      }, () => {
        if (!this._alive || !this._isVisible || reqId !== this._requestId) return
        this._initCanvases(() => {
          if (!this._alive || !this._isVisible) return
          if (willAnimate) {
            this._renderPieChart(0)
            this._renderTrendBars(0)
            const node = this._pieCanvasNode
            const raf = node && node.requestAnimationFrame
              ? cb => node.requestAnimationFrame(cb)
              : cb => setTimeout(cb, 16)
            const animReqId = this._requestId
            raf(() => raf(() => this._startAnimations(animReqId)))
          } else {
            this._renderPieChart(1)
            this._renderTrendBars(1)
          }
        })
      })
    } catch (e) {
      if (!this._alive || reqId !== this._requestId) return
      console.error('加载统计失败', e)
      this.setData({ loading: false, errorText: '加载失败，请检查网络后重试' })
    }
  },

  _formatSession(s) {
    const startTime = parseServerTime(s.start_time)
    const start = new Date(Number.isFinite(startTime) ? startTime : Date.now())
    const timeStr = `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`
    const durSec = s.actual_duration ?? s.actual_duration_sec ?? s.duration_sec ?? 0
    const subjectName = s.subject_name || '未分类'
    const subjectKey = s.subject_code || ''
    const isFree = s.preset === 'free'
    const durationText = formatDuration(durSec)
    return {
      ...s,
      _time: timeStr,
      _date: `${start.getMonth() + 1}/${start.getDate()}`,
      _duration: durationText,
      _subjectLabel: isFree ? '自由计时 · ' + subjectName : subjectName,
      _color: getSubjectColor(subjectKey),
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
    this._historySeq = (this._historySeq || 0) + 1
    const seq = this._historySeq
    try {
      const hist = await api.get('/pomodoro/history', { page: 1, page_size: 20, date })
      if (!this._alive || !this._isVisible || seq !== this._historySeq) return
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
    this._requestId++
    if (this._rafId && this._pieCanvasNode && this._pieCanvasNode.cancelAnimationFrame) {
      this._pieCanvasNode.cancelAnimationFrame(this._rafId)
    }
    this._rafId = null
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
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
    const rawDpr = windowInfo.pixelRatio || 2
    const dpr = Math.min(2, rawDpr)

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

  _startAnimations(reqId) {
    if (!this._alive || !this._isVisible || reqId !== this._requestId) return
    this._animActive = true
    this._finalDrawn = false
    const animDuration = 700
    const startTime = Date.now()

    // Number animation — independent timer (~12 updates), no setData in Canvas RAF
    const tSessions = this.data.todaySessions
    const wSessions = this.data.weekSessions
    const totalSteps = 12
    let step = 0
    const numTick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      step++
      const p = Math.min(1, step / totalSteps)
      const e = this._easeOutCubic(p)
      this.setData({
        _dispTodaySessions: Math.round(tSessions * e),
        _dispTodayDurationText: this._fmtMin(Math.round(this._rawTodayDur * e)),
        _dispWeekSessions: Math.round(wSessions * e),
        _dispWeekDurationText: this._fmtMin(Math.round(this._rawWeekDur * e)),
      })
      if (step < totalSteps) {
        this._animTimer = setTimeout(numTick, Math.round(animDuration / totalSteps))
      }
    }
    numTick()

    // Canvas animation — RAF only, no setData
    const node = this._pieCanvasNode
    const raf = node && node.requestAnimationFrame
      ? cb => node.requestAnimationFrame(cb)
      : cb => setTimeout(cb, 16)

    const tick = () => {
      if (!this._animActive || !this._alive || !this._isVisible || reqId !== this._requestId) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const eased = this._easeOutCubic(rawP)

      this._renderPieChart(eased)
      if (Math.round(elapsed / 16) % 2 === 0 || rawP >= 1) {
        this._renderTrendBars(eased)
      }

      if (rawP < 1) {
        this._rafId = raf(tick)
      } else if (!this._finalDrawn) {
        this._finalDrawn = true
        this._animActive = false
        this._rafId = null
        // Final frame already drawn in the render calls above (rawP>=1 triggers both)
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
    const tilt = 0.72
    const depth = radius * 0.08
    const isFinal = progress >= 1

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
    const wallSteps = isFinal ? wallStepsFull : Math.min(3, wallStepsFull)

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
}

if (typeof Page === 'function') Page(pageConfig)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { formatDuration }
}
