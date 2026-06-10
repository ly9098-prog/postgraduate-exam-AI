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
      })
      setTimeout(() => this.drawTrendBars(), 100)
      setTimeout(() => this.drawPieChart(), 200)
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

  drawTrendBars() {
    if (!this.data.trends.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#trend-bars-canvas').boundingClientRect(rect => {
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
      const trends = this.data.trends
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

      trends.forEach((t, i) => {
        const x = padL + gap * i + (gap - barW) / 2
        const barH = Math.max(4, (t.duration_sec || 0) / maxDur * chartH)
        const y = padT + chartH - barH

        if (t.duration_sec > 0) {
          // Bar with rounded look
          const radius = Math.min(4, barW / 2)
          ctx.beginPath()
          ctx.setFillStyle('#3B82F6')
          ctx.rect(x, y, barW, barH)
          ctx.fill()

          // Top highlight
          ctx.beginPath()
          ctx.setFillStyle('rgba(255,255,255,0.15)')
          ctx.rect(x, y, barW, Math.min(4, barH / 3))
          ctx.fill()
        } else {
          // Empty bar (dim)
          ctx.beginPath()
          ctx.setFillStyle('rgba(255,255,255,0.05)')
          ctx.rect(x, y, barW, barH)
          ctx.fill()
        }

        // Date label
        ctx.setFillStyle('rgba(255,255,255,0.25)')
        ctx.setFontSize(9)
        ctx.setTextAlign('center')
        ctx.fillText(t._shortDate || '', x + barW / 2, padT + chartH + 18)
      })

      ctx.draw()
    }).exec()
  },

  /* ==================== Pie Chart ==================== */

  drawPieChart() {
    const subjects = this.data.subjects
    if (!subjects || !subjects.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#pie-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 24
      const ctx = wx.createCanvasContext('pie-canvas', this)
      ctx.clearRect(0, 0, size, size)

      const total = subjects.reduce((sum, s) => sum + (s._pct > 0 ? 1 : 0), 0)
      if (total === 0) {
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
      let startAngle = -Math.PI / 2

      subjects.forEach(s => {
        const pct = (s.duration_sec || 0) / totalDur
        const endAngle = startAngle + Math.PI * 2 * pct

        // Draw sector
        ctx.beginPath()
        ctx.moveTo(center, center)
        ctx.arc(center, center, radius, startAngle, endAngle)
        ctx.closePath()
        ctx.setFillStyle(s._color || '#3B82F6')
        ctx.fill()

        // Draw separator line
        ctx.beginPath()
        ctx.moveTo(center, center)
        ctx.arc(center, center, radius, endAngle, endAngle)
        ctx.setStrokeStyle('rgba(11,17,33,0.4)')
        ctx.setLineWidth(1)
        ctx.stroke()

        // Percentage label on sector (if large enough)
        if (pct > 0.06) {
          const midAngle = startAngle + (endAngle - startAngle) / 2
          const labelR = radius * 0.6
          const lx = center + labelR * Math.cos(midAngle)
          const ly = center + labelR * Math.sin(midAngle)
          ctx.setFillStyle('rgba(255,255,255,0.9)')
          ctx.setFontSize(11)
          ctx.setTextAlign('center')
          ctx.setTextBaseline('middle')
          ctx.fillText(Math.round(pct * 100) + '%', lx, ly)
        }

        startAngle = endAngle
      })

      // Center hole (donut effect)
      ctx.beginPath()
      ctx.setFillStyle('#111827')
      ctx.arc(center, center, radius * 0.35, 0, Math.PI * 2)
      ctx.fill()

      ctx.draw()
    }).exec()
  },

  onPieTap(e) {
    const query = wx.createSelectorQuery().in(this)
    query.select('#pie-chart-wrap').boundingClientRect(rect => {
      if (!rect) return
      const x = e.detail.x - rect.left
      const y = e.detail.y - rect.top
      const centerX = rect.width / 2
      const centerY = rect.height / 2
      const radius = Math.min(rect.width, rect.height) / 2 - 24

      const dx = x - centerX
      const dy = y - centerY
      const dist = Math.sqrt(dx * dx + dy * dy)

      // Outside pie or inside center hole
      if (dist > radius || dist < radius * 0.35) {
        this.setData({ selectedSubjectDetail: null })
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
          this.setData({ selectedSubjectDetail: s })
          return
        }
        cumulativeStart = cumulativeEnd
      }

      this.setData({ selectedSubjectDetail: null })
    }).exec()
  },

  onLegendTap(e) {
    const subject = e.currentTarget.dataset.subject
    const found = this.data.subjects.find(s => s.subject === subject)
    if (found) {
      this.setData({ selectedSubjectDetail: found })
    }
  },

  closeDetail() {
    this.setData({ selectedSubjectDetail: null })
  },

  noop() {},

  _fmtMin(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分钟`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },
})
