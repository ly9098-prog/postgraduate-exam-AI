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
  english: '#8B5CF6',
  math: '#EC4899',
  politics: '#F97316',
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
        api.get('/pomodoro/history', { page: 1, page_size: 20 }),
      ])
      const subjArr = subjects || []
      const maxDur = Math.max(1, ...subjArr.map(s => s.duration_sec || 0))
      const totalDur = Math.max(1, subjArr.reduce((sum, s) => sum + (s.duration_sec || 0), 0))
      let cumulativeAngle = -Math.PI / 2
      this.setData({
        todaySessions: stats.today_sessions || 0,
        todayDurationText: this._fmtMin(stats.today_duration_sec || 0),
        weekSessions: stats.week_sessions || 0,
        weekDurationText: this._fmtMin(stats.week_duration_sec || 0),
        trends: (trends || []).map(t => ({
          ...t,
          _shortDate: (t.date || '').slice(5),
          _barPct: this._calcBarPct(trends, t.duration_sec),
          _durationText: this._fmtMin(t.duration_sec || 0),
        })),
        subjects: subjArr.map(s => {
          const dur = s.duration_sec || 0
          const pct = dur / totalDur
          const sectorStart = cumulativeAngle
          const sectorEnd = cumulativeAngle + Math.PI * 2 * pct
          cumulativeAngle = sectorEnd
          return {
            ...s,
            _label: SUBJECT_LABELS[s.subject] || s.subject || '未分类',
            _color: SUBJECT_COLORS[s.subject] || '#3B82F6',
            _durationText: this._fmtMin(dur),
            _barPct: maxDur > 0 ? dur / maxDur * 100 : 0,
            _pct: pct,
            _pctText: (pct * 100).toFixed(1) + '%',
            _sectorStart: sectorStart,
            _sectorEnd: sectorEnd,
            sessions: s.sessions || 0,
          }
        }),
        history: (hist.items || []).map(this._formatSession),
        historyTotal: hist.total || 0,
        loading: false,

        // Reset display values
        _dispTodaySessions: 0,
        _dispTodayDurationText: '0分钟',
        _dispWeekSessions: 0,
        _dispWeekDurationText: '0分钟',
      })

      // Store raw seconds for animation
      this._rawTodayDur = stats.today_duration_sec || 0
      this._rawWeekDur = stats.week_duration_sec || 0
      // Invalidate caches that depend on subject set
      this._pieSectors = null
      this._shadeCache = null

      // Initialize canvases (sync 2D contexts) then animate
      this._initCanvases(() => this._startAnimations())
    } catch (e) {
      console.error('加载统计失败', e)
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _calcBarPct(trends, value) {
    const max = Math.max(1, ...(trends || []).map(t => t.duration_sec || 0))
    return Math.max(4, Math.min(100, (value || 0) / max * 100)).toFixed(0)
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
      _statusLabel: s.status === 'completed' ? '完成' : '中断',
      _statusClass: s.status === 'completed' ? 'status-done' : 'status-interrupt',
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

    const setup = (selector, nodeKey, ctxKey, rectKey) => {
      wx.createSelectorQuery().in(this)
        .select(selector)
        .fields({ node: true, size: true })
        .exec(res => {
          if (!res || !res[0] || !res[0].node) { done(); return }
          const node = res[0].node
          const ctx = node.getContext('2d')
          const dpr = wx.getSystemInfoSync().pixelRatio || 2
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
    const animDuration = 900
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

    const tick = () => {
      if (!this._animActive) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const eased = this._easeOutCubic(rawP)

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

      this._renderPieChart(eased)
      this._renderTrendBars(eased)

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

    ctx.clearRect(0, 0, w, h)

    for (let i = 0; i <= 3; i++) {
      const y = padT + chartH * (1 - i / 3)
      ctx.beginPath()
      ctx.strokeStyle = 'rgba(255,255,255,0.04)'
      ctx.lineWidth = 0.5
      ctx.moveTo(padL, y)
      ctx.lineTo(w - padR, y)
      ctx.stroke()
    }

    ctx.beginPath()
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.lineWidth = 1
    ctx.moveTo(padL, padT + chartH)
    ctx.lineTo(w - padR, padT + chartH)
    ctx.stroke()

    if (!this._trendGrad) {
      const g = ctx.createLinearGradient(0, padT, 0, padT + chartH)
      g.addColorStop(0, 'rgba(59,130,246,0.5)')
      g.addColorStop(0.6, '#3B82F6')
      g.addColorStop(1, 'rgba(59,130,246,0.8)')
      this._trendGrad = g
    }

    trends.forEach((t, i) => {
      const x = padL + gap * i + (gap - barW) / 2
      const finalBarH = (t.duration_sec || 0) / maxDur * chartH
      const barH = Math.max(0, finalBarH * progress)
      const y = padT + chartH - barH

      if (t.duration_sec > 0 && barH > 0) {
        ctx.fillStyle = this._trendGrad
        ctx.fillRect(x, y, barW, barH)
        if (barH > 4) {
          ctx.fillStyle = 'rgba(255,255,255,0.2)'
          ctx.fillRect(x, y, barW, Math.min(4, barH / 3))
        }
      } else if (t.duration_sec > 0) {
        ctx.fillStyle = 'rgba(255,255,255,0.05)'
        ctx.fillRect(x, padT + chartH - 1, barW, 1)
      } else {
        ctx.fillStyle = 'rgba(255,255,255,0.03)'
        ctx.fillRect(x, padT + chartH - 2, barW, 2)
      }

      ctx.fillStyle = 'rgba(255,255,255,0.25)'
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(t._shortDate || '', x + barW / 2, padT + chartH + 18)
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
      // Pre-compute per-layer shade amounts (sector color + layer index)
      sectors.forEach(sec => {
        sec._shades = []
        for (let layer = 1; layer <= sideStepsFull; layer++) {
          sec._shades[layer] = this._shadeColorCached(sec.color, -80 + Math.round(layer / sideStepsFull * 24))
        }
      })
    }

    const sectors = this._pieSectors
    const sideSteps = this._pieSideSteps

    // Drop shadow
    ctx.save()
    ctx.translate(centerX, centerY + depth * 1.02)
    ctx.scale(1, 0.32)
    const shadow = ctx.createLinearGradient(0, -radius * 0.4, 0, radius * 1.2)
    shadow.addColorStop(0, 'rgba(0,0,0,0.34)')
    shadow.addColorStop(0.55, 'rgba(0,0,0,0.22)')
    shadow.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = shadow
    ctx.beginPath()
    ctx.arc(0, 0, radius * 1.18, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()

    const selectedSubject = this.data._selectedSubject

    // Side depth layers
    for (let layer = sideSteps; layer >= 1; layer--) {
      const layerOffset = depth * layer / sideSteps * progress
      sectors.forEach(sec => {
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.002) return
        const isSelected = selectedSubject && sec.subject.subject === selectedSubject
        const mid = (sec.startA + curEnd) / 2
        const pull = isSelected ? 14 : 0
        const cx = centerX + Math.cos(mid) * pull
        const cy = centerY + Math.sin(mid) * pull * tilt + layerOffset
        this._drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, sec._shades[layer], 'rgba(0,0,0,0.12)', 0.5)
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
        isSelected ? 'rgba(255,255,255,0.72)' : 'rgba(11,17,33,0.48)',
        isSelected ? 2.4 : 1
      )
    })

    // Gloss overlay
    ctx.save()
    ctx.translate(centerX, centerY)
    ctx.scale(1, tilt)
    ctx.beginPath()
    ctx.arc(0, 0, radius, 0, Math.PI * 2)
    ctx.clip()
    const gloss = ctx.createLinearGradient(-radius, -radius, radius, radius)
    gloss.addColorStop(0, 'rgba(255,255,255,0.32)')
    gloss.addColorStop(0.28, 'rgba(255,255,255,0.08)')
    gloss.addColorStop(0.58, 'rgba(255,255,255,0)')
    gloss.addColorStop(1, 'rgba(0,0,0,0.28)')
    ctx.fillStyle = gloss
    ctx.beginPath()
    ctx.arc(0, 0, radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()

    // Specular highlight
    ctx.save()
    ctx.translate(centerX - radius * 0.23, centerY - radius * 0.14)
    ctx.scale(1, 0.24)
    ctx.beginPath()
    ctx.arc(0, 0, radius * 0.48, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(255,255,255,0.16)'
    ctx.fill()
    ctx.restore()

    // Selected sector ring
    if (selectedSubject) {
      sectors.forEach(sec => {
        if (sec.subject.subject !== selectedSubject) return
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        const mid = (sec.startA + curEnd) / 2
        const cx = centerX + Math.cos(mid) * 14
        const cy = centerY + Math.sin(mid) * 14 * tilt
        this._drawEllipticSector(ctx, cx, cy, radius * 1.08, tilt, sec.startA, curEnd, 'rgba(255,255,255,0.08)', 'rgba(255,255,255,0.28)', 7)
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
