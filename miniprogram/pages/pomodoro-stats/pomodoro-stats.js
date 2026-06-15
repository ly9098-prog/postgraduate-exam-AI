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
    const animDuration = 1200
    const startTime = Date.now()
    const tSessions = this.data.todaySessions
    const wSessions = this.data.weekSessions

    const tick = () => {
      if (!this._animActive) return
      const elapsed = Date.now() - startTime
      const rawP = Math.min(1, elapsed / animDuration)
      const eased = this._easeOutCubic(rawP)

      // Update number animations
      const curTodaySess = Math.round(tSessions * eased)
      const curWeekSess = Math.round(wSessions * eased)
      const curTodayDur = Math.round(this._rawTodayDur * eased)
      const curWeekDur = Math.round(this._rawWeekDur * eased)

      this.setData({
        _dispTodaySessions: curTodaySess,
        _dispTodayDurationText: this._fmtMin(curTodayDur),
        _dispWeekSessions: curWeekSess,
        _dispWeekDurationText: this._fmtMin(curWeekDur),
      })

      // Draw chart animations
      this._renderPieChart(eased)
      this._renderTrendBars(eased)

      if (rawP < 1) {
        this._animTimer = setTimeout(tick, 16)
      } else {
        this._animActive = false
        this._animTimer = null
        // Final draw at full progress to ensure crisp rendering
        this._renderPieChart(1)
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
    const size = Math.min(rect.width, rect.height)
    const center = size / 2
    const radius = center - 24
    const ctx = wx.createCanvasContext('pie-canvas', this)
    ctx.clearRect(0, 0, size, size)
    ctx.beginPath()
    ctx.setFillStyle('rgba(255,255,255,0.02)')
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.draw()
  },

  _renderPieChart(progress) {
    const subjects = this.data.subjects
    const rect = this._pieRect
    if (!rect || !rect.width) return
    const size = Math.min(rect.width, rect.height)
    const center = size / 2
    const radius = center - 24
    const holeR = radius * 0.35
    const ctx = wx.createCanvasContext('pie-canvas', this)
    ctx.clearRect(0, 0, size, size)

    const hasData = subjects && subjects.length && subjects.some(s => (s.duration_sec || 0) > 0)

    if (!hasData) {
      ctx.beginPath()
      ctx.setFillStyle('rgba(255,255,255,0.04)')
      ctx.arc(center, center, radius, 0, Math.PI * 2)
      ctx.fill()
      ctx.setFillStyle('rgba(255,255,255,0.2)')
      ctx.setFontSize(11)
      ctx.setTextAlign('center')
      ctx.fillText('今日暂无数据', center, center + 4)
      ctx.draw()
      return
    }

    const totalDur = subjects.reduce((sum, s) => sum + (s.duration_sec || 0), 0) || 1
    const total = subjects.filter(s => (s.duration_sec || 0) > 0)

    // Helper: draw a sector from startAngle to endAngle
    const drawSector = (cx, cy, r, startA, endA, fillStyle, strokeStyle, lineW) => {
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.arc(cx, cy, r, startA, endA)
      ctx.closePath()
      ctx.setFillStyle(fillStyle)
      ctx.fill()
      if (strokeStyle) {
        ctx.beginPath()
        ctx.moveTo(cx, cy)
        ctx.arc(cx, cy, r, endA, endA)
        ctx.setStrokeStyle(strokeStyle)
        ctx.setLineWidth(lineW || 1)
        ctx.stroke()
      }
    }

    // Compute all sector angles first (at full progress)
    const sectors = []
    let angle = -Math.PI / 2
    total.forEach(s => {
      const pct = (s.duration_sec || 0) / totalDur
      const endA = angle + Math.PI * 2 * pct
      sectors.push({
        subject: s,
        color: s._color || '#3B82F6',
        startA: angle,
        endA: endA,
        pct: pct,
      })
      angle = endA
    })

    // === Layer 1: Drop shadow (offset dark circle) ===
    ctx.beginPath()
    ctx.arc(center + 4, center + 5, radius + 2, 0, Math.PI * 2)
    ctx.setFillStyle('rgba(0,0,0,0.18)')
    ctx.fill()

    // === Layer 2: Dark thickness ring (offset sectors = 3D depth) ===
    // Only when progress is enough to show
    if (progress > 0.02) {
      const thickOffX = 3
      const thickOffY = 5
      sectors.forEach(sec => {
        const curEnd = sec.startA + (sec.endA - sec.startA) * Math.min(1, progress * 1.5)
        if (curEnd - sec.startA < 0.005) return
        // Draw offset sector in darker color to simulate side face
        ctx.beginPath()
        ctx.moveTo(center + thickOffX, center + thickOffY)
        ctx.arc(center + thickOffX, center + thickOffY, radius, sec.startA, curEnd)
        ctx.closePath()
        ctx.setFillStyle('rgba(0,0,0,0.25)')
        ctx.fill()
      })
    }

    // === Layer 3: Sectors (top face, flat colors) ===
    if (progress > 0) {
      const hlSubject = this.data._selectedSubject

      sectors.forEach(sec => {
        const curEnd = sec.startA + (sec.endA - sec.startA) * progress
        if (curEnd - sec.startA < 0.001) return

        const isHL = hlSubject && sec.subject.subject === hlSubject
        let cx = center, cy = center
        let strokeStyle = 'rgba(11,17,33,0.5)'
        let lineW = 1.2

        if (isHL) {
          const mid = (sec.startA + curEnd) / 2
          const pull = 12
          cx += Math.cos(mid) * pull
          cy += Math.sin(mid) * pull
          strokeStyle = 'rgba(255,255,255,0.6)'
          lineW = 2.5
        }

        drawSector(cx, cy, radius, sec.startA, curEnd, sec.color, strokeStyle, lineW)
      })

      // === Layer 4: Strong directional lighting overlay ===
      if (progress >= 0.05) {
        const grad = ctx.createLinearGradient(
          0, 0,
          size, size
        )
        grad.addColorStop(0, 'rgba(255,255,255,0.22)')
        grad.addColorStop(0.3, 'rgba(255,255,255,0.05)')
        grad.addColorStop(0.5, 'rgba(0,0,0,0)')
        grad.addColorStop(0.7, 'rgba(0,0,0,0.15)')
        grad.addColorStop(1, 'rgba(0,0,0,0.35)')

        ctx.beginPath()
        ctx.arc(center, center, radius, 0, Math.PI * 2)
        ctx.setFillStyle(grad)
        ctx.fill()
      }

      // === Layer 5: Outer edge bevel ===
      // Top arc highlight
      ctx.beginPath()
      ctx.arc(center, center, radius - 0.5, -Math.PI * 0.9, -Math.PI * 0.1)
      ctx.setStrokeStyle('rgba(255,255,255,0.2)')
      ctx.setLineWidth(2)
      ctx.stroke()

      // Bottom arc shadow
      ctx.beginPath()
      ctx.arc(center, center, radius - 0.5, Math.PI * 0.1, Math.PI * 0.9)
      ctx.setStrokeStyle('rgba(0,0,0,0.2)')
      ctx.setLineWidth(2)
      ctx.stroke()

      // === Layer 5b: Highlighted sector glow ===
      if (progress >= 0.05) {
        const hlSubject = this.data._selectedSubject
        if (hlSubject) {
          sectors.forEach(sec => {
            if (sec.subject.subject !== hlSubject) return
            const curEnd = sec.startA + (sec.endA - sec.startA) * progress
            if (curEnd - sec.startA < 0.001) return

            const mid = (sec.startA + curEnd) / 2
            const pull = 12
            const cx = center + Math.cos(mid) * pull
            const cy = center + Math.sin(mid) * pull

            // Outer glow ring
            ctx.beginPath()
            ctx.arc(cx, cy, radius + 5, sec.startA, curEnd)
            ctx.setStrokeStyle('rgba(255,255,255,0.15)')
            ctx.setLineWidth(8)
            ctx.stroke()

            // Inner bright rim
            ctx.beginPath()
            ctx.arc(cx, cy, radius + 1, sec.startA, curEnd)
            ctx.setStrokeStyle('rgba(255,255,255,0.35)')
            ctx.setLineWidth(2)
            ctx.stroke()
          })
        }
      }
    }

    // === Layer 6: Center hole ===
    ctx.beginPath()
    ctx.setFillStyle('#111827')
    ctx.arc(center, center, holeR, 0, Math.PI * 2)
    ctx.fill()

    // === Layer 7: Inner shadow bevel (center hole edge) ===
    ctx.beginPath()
    ctx.arc(center, center, holeR + 1, 0, Math.PI * 2)
    ctx.setStrokeStyle('rgba(0,0,0,0.4)')
    ctx.setLineWidth(2)
    ctx.stroke()

    // === Layer 8: Subtle outer glow ===
    ctx.beginPath()
    ctx.arc(center, center, radius + 2, 0, Math.PI * 2)
    ctx.setStrokeStyle('rgba(255,255,255,0.04)')
    ctx.setLineWidth(1)
    ctx.stroke()

    ctx.draw()
  },

  /* ==================== Touch Interactions ==================== */

  onPieTap(e) {
    const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0])
    const tapX = touch ? touch.clientX : e.detail && e.detail.x
    const tapY = touch ? touch.clientY : e.detail && e.detail.y

    const query = wx.createSelectorQuery().in(this)
    query.select('#pie-chart-wrap').boundingClientRect(rect => {
      if (!rect || typeof tapX !== 'number' || typeof tapY !== 'number') return
      const x = tapX - rect.left
      const y = tapY - rect.top
      const centerX = rect.width / 2
      const centerY = rect.height / 2
      const radius = Math.min(rect.width, rect.height) / 2 - 24

      const dx = x - centerX
      const dy = y - centerY
      const dist = Math.sqrt(dx * dx + dy * dy)

      // Outside the pie — dismiss
      if (dist > radius) {
        if (this.data.selectedSubjectDetail) {
          this.setData({
            selectedSubjectDetail: null,
            _selectedSubject: null,
          }, () => this._renderPieChart(1))
        }
        return
      }

      // Center hole — dismiss if popup is open
      if (dist < radius * 0.35) {
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
