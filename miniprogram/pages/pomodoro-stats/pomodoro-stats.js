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
  data_structure: '#5B7B9A',
  computer_organization: '#C49A6B',
  operating_system: '#6B9B6B',
  computer_network: '#7B8DB3',
  english: '#B38B6B',
  math: '#8B9B7B',
  politics: '#A08B8B',
}

Page({
  data: {
    loading: true,
    todaySessions: 0,
    todayDurationText: '0分钟',
    weekSessions: 0,
    weekDurationText: '0分钟',
    trends: [],
    subjects: [],
    history: [],
    historyTotal: 0,
  },

  onShow() {
    this.loadData()
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
        subjects: (subjects || []).map(s => ({
          ...s,
          _label: SUBJECT_LABELS[s.subject] || s.subject || '未分类',
          _color: SUBJECT_COLORS[s.subject] || '#5B7B9A',
          _durationText: this._fmtMin(s.duration_sec || 0),
        })),
        history: (hist.items || []).map(this._formatSession),
        historyTotal: hist.total || 0,
        loading: false,
      })
      setTimeout(() => this.drawTrendBars(), 100)
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
    const start = new Date(s.start_time)
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
      const barW = Math.min(36, chartW / trends.length * 0.55)
      const gap = chartW / trends.length
      const maxDur = Math.max(1, ...trends.map(t => t.duration_sec || 0))

      ctx.clearRect(0, 0, w, h)

      // 水平网格线
      for (let i = 0; i <= 3; i++) {
        const y = padT + chartH * (1 - i / 3)
        ctx.beginPath()
        ctx.setStrokeStyle('#EDF1F5')
        ctx.setLineWidth(0.5)
        ctx.moveTo(padL, y)
        ctx.lineTo(w - padR, y)
        ctx.stroke()
      }

      // 基线
      ctx.beginPath()
      ctx.setStrokeStyle('#E8E5E0')
      ctx.setLineWidth(1)
      ctx.moveTo(padL, padT + chartH)
      ctx.lineTo(w - padR, padT + chartH)
      ctx.stroke()

      trends.forEach((t, i) => {
        const x = padL + gap * i + (gap - barW) / 2
        const barH = Math.max(4, (t.duration_sec || 0) / maxDur * chartH)
        const y = padT + chartH - barH

        if (t.duration_sec > 0) {
          // 柱形主体
          ctx.beginPath()
          ctx.setFillStyle('#5B7B9A')
          ctx.rect(x, y, barW, barH)
          ctx.fill()

          // 柱形顶部高亮
          ctx.beginPath()
          ctx.setFillStyle('rgba(255,255,255,0.25)')
          ctx.rect(x, y, barW, Math.min(6, barH / 3))
          ctx.fill()

          // 柱形底部加深
          ctx.beginPath()
          ctx.setFillStyle('rgba(0,0,0,0.06)')
          ctx.rect(x, y + barH - Math.min(4, barH / 4), barW, Math.min(4, barH / 4))
          ctx.fill()
        } else {
          ctx.beginPath()
          ctx.setFillStyle('#E8E5E0')
          ctx.rect(x, y, barW, barH)
          ctx.fill()
        }

        // 日期标签
        ctx.setFillStyle('#9AABBA')
        ctx.setFontSize(9)
        ctx.setTextAlign('center')
        ctx.fillText(t._shortDate || '', x + barW / 2, padT + chartH + 18)
      })

      ctx.draw()
    }).exec()
  },

  _fmtMin(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分钟`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },
})
