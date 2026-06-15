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

      // Draw initial empty chart backgrounds then animate
      this._drawEmptyChart()
      this._drawEmptyBars()
      this._cacheDimensions(() => this._startAnimations())
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
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
    this._animActive = false
  },

  _cacheDimensions(callback) {
    let count = 0
    const check = () => { if (++count >= 2) callback() }

    const q1 = wx.createSelectorQuery().in(this)
    q1.select('#trend-bars-canvas').boundingClientRect(rect => {
      this._trendBarsRect = rect
      check()
    }).exec()

    const q2 = wx.createSelectorQuery().in(this)
    q2.select('#pie-canvas').boundingClientRect(rect => {
      this._pieRect = rect
      check()
    }).exec()
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

    const tick = () => {
      if (!this._animActive) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const eased = this._easeOutCubic(rawP)

      const curTodaySess = Math.round(tSessions * eased)
      const curWeekSess = Math.round(wSessions * eased)
      const curTodayDur = Math.round(this._rawTodayDur * eased)
      const curWeekDur = Math.round(this._rawWeekDur * eased)

      // Only setData when a displayed value actually changed — avoids ~30 redundant
      // view updates per second when rounding produces the same int two ticks in a row.
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

      // quick=true keeps 3D look but cuts depth-layer count from ~27 to 4 during animation
      this._renderPieChart(eased, true)
      this._renderTrendBars(eased)

      if (rawP < 1) {
        // 30fps tick — visually smooth, halves canvas work vs. 60fps
        this._animTimer = setTimeout(tick, 33)
      } else {
        this._animActive = false
        this._animTimer = null
        // Final draw at full quality (all depth layers, gloss, highlights)
        this._renderPieChart(1, false)
        this._renderTrendBars(1)
      }
    }
    tick()
  },

  /* ==================== Trend Bars ==================== */

  _drawEmptyBars() {
    this._renderTrendBars(0)
  },

  _renderTrendBars(progress) {
    const trends = this.data.trends
    if (!trends || !trends.length) return
    const rect = this._trendBarsRect
    if (!rect || !rect.width) return

    const ctx = wx.createCanvasContext('trend-bars-canvas', this)
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

    // Horizontal grid lines
    for (let i = 0; i <= 3; i++) {
      const y = padT + chartH * (1 - i / 3)
      ctx.beginPath()
      ctx.setStrokeStyle('rgba(255,255,255,0.04)')
      ctx.setLineWidth(0.5)
      ctx.moveTo(padL, y)
      ctx.lineTo(w - padR, y)
      ctx.stroke()
    }

    // Baseline
    ctx.beginPath()
    ctx.setStrokeStyle('rgba(255,255,255,0.06)')
    ctx.setLineWidth(1)
    ctx.moveTo(padL, padT + chartH)
    ctx.lineTo(w - padR, padT + chartH)
    ctx.stroke()

    // Gradient fill for positive bars
    const grad = ctx.createLinearGradient(0, padT, 0, padT + chartH)
    grad.addColorStop(0, 'rgba(59,130,246,0.5)')
    grad.addColorStop(0.6, '#3B82F6')
    grad.addColorStop(1, 'rgba(59,130,246,0.8)')

    trends.forEach((t, i) => {
      const x = padL + gap * i + (gap - barW) / 2
      const finalBarH = (t.duration_sec || 0) / maxDur * chartH
      const barH = Math.max(0, finalBarH * progress)
      const y = padT + chartH - barH

      if (t.duration_sec > 0 && barH > 0) {
        // Main bar with gradient
        ctx.beginPath()
        ctx.setFillStyle(grad)
        ctx.rect(x, y, barW, barH)
        ctx.fill()

        // Top highlight cap
        if (barH > 4) {
          ctx.beginPath()
          ctx.setFillStyle('rgba(255,255,255,0.2)')
          ctx.rect(x, y, barW, Math.min(4, barH / 3))
          ctx.fill()
        }
      } else if (t.duration_sec > 0) {
        // Very thin bar (when progress is near 0)
        ctx.beginPath()
        ctx.setFillStyle('rgba(255,255,255,0.05)')
        ctx.rect(x, padT + chartH - 1, barW, 1)
        ctx.fill()
      } else {
        // Empty bar placeholder
        ctx.beginPath()
        ctx.setFillStyle('rgba(255,255,255,0.03)')
        ctx.rect(x, padT + chartH - 2, barW, 2)
        ctx.fill()
      }

      // Date label
      ctx.setFillStyle('rgba(255,255,255,0.25)')
      ctx.setFontSize(9)
      ctx.setTextAlign('center')
      ctx.fillText(t._shortDate || '', x + barW / 2, padT + chartH + 18)
    })

    ctx.draw()
  },

  /* ==================== Pie Chart ==================== */

  _drawEmptyChart() {
    const rect = this._pieRect
    if (!rect || !rect.width) return
    this._renderPieChart(0, true)
  },

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
    ctx.setFillStyle(fillStyle)
    ctx.fill()
    if (strokeStyle) {
      ctx.setStrokeStyle(strokeStyle)
      ctx.setLineWidth(lineW || 1)
      ctx.stroke()
    }
    ctx.restore()
  },

  _renderPieChart(progress, quick) {
    const subjects = this.data.subjects
    const rect = this._pieRect
    if (!rect || !rect.width) return
    const ctx = wx.createCanvasContext('pie-canvas', this)
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
      const shadow = ctx.createLinearGradient(centerX, centerY + depth * 0.4, centerX, centerY + depth * 1.7)
      shadow.addColorStop(0, 'rgba(0,0,0,0.28)')
      shadow.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.save()
      ctx.translate(centerX, centerY + depth)
      ctx.scale(1, 0.35)
      ctx.beginPath()
      ctx.arc(0, 0, radius * 1.1, 0, Math.PI * 2)
      ctx.setFillStyle(shadow)
      ctx.fill()
      ctx.restore()
      this._drawEllipticSector(ctx, centerX, centerY, radius, tilt, 0, Math.PI * 2, 'rgba(255,255,255,0.05)', 'rgba(255,255,255,0.08)', 1)
      ctx.setFillStyle('rgba(255,255,255,0.28)')
      ctx.setFontSize(12)
      ctx.setTextAlign('center')
      ctx.fillText('今日暂无数据', centerX, centerY + 6)
      ctx.draw()
      return
    }

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

    const shadow = ctx.createLinearGradient(centerX, centerY + depth * 0.35, centerX, centerY + depth * 1.85)
    shadow.addColorStop(0, 'rgba(0,0,0,0.34)')
    shadow.addColorStop(0.55, 'rgba(0,0,0,0.22)')
    shadow.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.save()
    ctx.translate(centerX, centerY + depth * 1.02)
    ctx.scale(1, 0.32)
    ctx.beginPath()
    ctx.arc(0, 0, radius * 1.18, 0, Math.PI * 2)
    ctx.setFillStyle(shadow)
    ctx.fill()
    ctx.restore()

    const selectedSubject = this.data._selectedSubject
    // quick mode (during entrance animation): 4 depth layers ≈ 85% fewer canvas ops
    // full mode (final paint, taps): ~27 layers for crisp 3D edge
    const sideSteps = quick ? 4 : Math.max(8, Math.round(depth / 3))
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
        const shade = this._shadeColor(sec.color, -80 + Math.round(layer / sideSteps * 24))
        this._drawEllipticSector(ctx, cx, cy, radius, tilt, sec.startA, curEnd, shade, 'rgba(0,0,0,0.12)', 0.5)
      })
    }

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

    ctx.save()
    ctx.translate(centerX, centerY)
    ctx.scale(1, tilt)
    ctx.beginPath()
    ctx.arc(0, 0, radius, 0, Math.PI * 2)
    ctx.closePath()
    ctx.clip()
    const gloss = ctx.createLinearGradient(-radius, -radius, radius, radius)
    gloss.addColorStop(0, 'rgba(255,255,255,0.32)')
    gloss.addColorStop(0.28, 'rgba(255,255,255,0.08)')
    gloss.addColorStop(0.58, 'rgba(255,255,255,0)')
    gloss.addColorStop(1, 'rgba(0,0,0,0.28)')
    ctx.beginPath()
    ctx.arc(0, 0, radius, 0, Math.PI * 2)
    ctx.setFillStyle(gloss)
    ctx.fill()
    ctx.restore()

    ctx.save()
    ctx.translate(centerX - radius * 0.23, centerY - radius * 0.14)
    ctx.scale(1, 0.24)
    ctx.beginPath()
    ctx.arc(0, 0, radius * 0.48, 0, Math.PI * 2)
    ctx.setFillStyle('rgba(255,255,255,0.16)')
    ctx.fill()
    ctx.restore()

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

    ctx.draw()
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
          }, () => this._renderPieChart(1, false))
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
            this._renderPieChart(1, false)
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
    }, () => this._renderPieChart(1, false))
  },

  noop() {},

  _fmtMin(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分钟`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },
})
