const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    overview: null,
    subjects: [],
    trends: [],
    behavior: null,
    forgetting: null,
    subjectTotal: 0,
    trendMeta: null,
  },

  onShow() {
    this.loadData()
  },

  async loadData() {
    this.setData({ loading: true })
    try {
      const res = await api.get('/stats/dashboard')
      this.setData(this._process(res), () => {
        this.drawCharts()
      })
    } catch (e) {
      console.error('加载学习统计失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false, overview: null, subjects: [], trends: [], behavior: null, forgetting: null, subjectTotal: 0, trendMeta: null })
    }
  },

  _process(res) {
    const overview = res.overview || {}
    const subjects = (res.subject_stats || []).filter(s => s.total_questions > 0)
    const trends = res.recent_trend || []
    const behavior = res.behavior || {}
    const forgetting = res.forgetting || {}
    const subjectTotal = subjects.reduce((sum, s) => sum + (s.total_questions || 0), 0)
    const subjectPalette = ['#5B7B9A', '#C49A6B', '#6B9B6B', '#C47A7A', '#7D8CC4', '#8CA7A1']

    // 预计算总览字段
    const ov = {
      ...overview,
      _accuracyPct: Math.max(0, Math.min(100, (overview.accuracy || 0) * 100)).toFixed(0),
      _accuracyText: (overview.accuracy * 100 || 0).toFixed(1) + '%',
      _totalDuration: this._fmt(overview.total_duration_sec || 0),
      _todayDuration: this._fmt(overview.today_duration_sec || 0),
    }

    // 预计算学科字段与饼图区间
    let start = 0
    const subs = subjects.map((s, index) => {
      const share = subjectTotal ? (s.total_questions || 0) / subjectTotal : 0
      const end = start + share * 360
      const data = {
        ...s,
        _label: this.subjectLabel(s.subject),
        _color: subjectPalette[index % subjectPalette.length],
        _sharePct: (share * 100).toFixed(0),
        _barPct: Math.max(6, Math.min(100, share * 100)).toFixed(0),
        _startAngle: start,
        _endAngle: end,
        _accPct: (s.accuracy * 100 || 0).toFixed(0),
        _accClass: s.accuracy >= 0.7 ? 'green' : s.accuracy >= 0.4 ? 'orange' : 'red',
        _durationText: this._fmt(s.total_duration_sec || 0),
      }
      start = end
      return data
    })

    const totalTrendQuestions = trends.reduce((sum, t) => sum + (t.questions || 0), 0)
    const activeTrendDays = trends.filter(t => (t.questions || 0) > 0).length
    const avgTrendAccuracy = trends.length
      ? trends.reduce((sum, t) => sum + (t.accuracy || 0), 0) / trends.length
      : 0
    const trendMeta = {
      totalQuestions: totalTrendQuestions,
      activeDays: activeTrendDays,
      avgAccuracyText: (avgTrendAccuracy * 100 || 0).toFixed(0) + '%',
    }
    const trs = trends.map(t => ({
      ...t,
      _shortDate: (t.date || '').slice(5),
      _accPct: (t.accuracy * 100 || 0).toFixed(0),
      _accClass: t.accuracy >= 0.7 ? 'green' : t.accuracy >= 0.4 ? 'orange' : 'red',
    }))

    const viewRate = behavior.view_answer_rate || 0
    const abandonRate = behavior.abandon_rate || 0
    const bh = {
      ...behavior,
      _avgTimeText: this._fmt(behavior.avg_time_sec || 0),
      _viewRate: (viewRate * 100 || 0).toFixed(0) + '%',
      _viewRatePct: Math.max(0, Math.min(100, viewRate * 100)).toFixed(0),
      _viewHint: viewRate >= 0.4 ? '建议回看基础知识点' : viewRate >= 0.2 ? '保持先思考再看解析' : '独立作答状态较好',
      _abandonRate: (abandonRate * 100 || 0).toFixed(0) + '%',
      _abandonRatePct: Math.max(0, Math.min(100, abandonRate * 100)).toFixed(0),
      _abandonHint: abandonRate >= 0.25 ? '优先降低放弃题比例' : abandonRate >= 0.1 ? '难题可加入复盘清单' : '放弃率保持较低',
    }

    const highForgetCount = forgetting.high_forget_count || 0
    const stuckQuestions = forgetting.stuck_questions || 0
    const pseudoMasteredCount = (forgetting.pseudo_mastered || []).length
    const totalRisk = highForgetCount + stuckQuestions + pseudoMasteredCount
    const fg = {
      ...forgetting,
      _pseudoMasteredCount: pseudoMasteredCount,
      _totalRisk: totalRisk,
      _priorityText: highForgetCount > 0 ? '先处理高频遗忘' : pseudoMasteredCount > 0 ? '先校准假掌握' : stuckQuestions > 0 ? '处理长期未掌握' : '暂无明显复习风险',
    }

    return {
      overview: ov,
      subjects: subs,
      trends: trs,
      behavior: bh,
      forgetting: fg,
      subjectTotal,
      trendMeta,
      loading: false,
    }
  },

  drawCharts() {
    setTimeout(() => {
      this.drawScoreRing()
      this.drawSubjectDonut()
      this.drawTrendLine()
    }, 80)
  },

  drawScoreRing() {
    const query = wx.createSelectorQuery().in(this)
    query.select('#score-ring-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 10
      const lineWidth = 9
      const accuracy = Math.max(0, Math.min(1, (this.data.overview && this.data.overview.accuracy) || 0))
      const ctx = wx.createCanvasContext('score-ring-canvas', this)
      ctx.clearRect(0, 0, size, size)

      ctx.beginPath()
      ctx.setStrokeStyle('#EDF1F5')
      ctx.setLineWidth(lineWidth)
      ctx.arc(center, center, radius, 0, Math.PI * 2)
      ctx.stroke()

      ctx.beginPath()
      ctx.setStrokeStyle('#5B7B9A')
      ctx.setLineWidth(lineWidth)
      ctx.setLineCap('round')
      ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * accuracy)
      ctx.stroke()
      ctx.draw()
    }).exec()
  },

  drawSubjectDonut() {
    if (!this.data.subjects.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#subject-donut-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 8
      const innerRadius = radius * 0.62
      const ctx = wx.createCanvasContext('subject-donut-canvas', this)
      ctx.clearRect(0, 0, size, size)

      this.data.subjects.forEach(item => {
        const start = (item._startAngle - 90) * Math.PI / 180
        const end = (item._endAngle - 90) * Math.PI / 180
        ctx.beginPath()
        ctx.moveTo(center, center)
        ctx.setFillStyle(item._color)
        ctx.arc(center, center, radius, start, end)
        ctx.closePath()
        ctx.fill()
      })

      ctx.beginPath()
      ctx.setFillStyle('#FFFFFF')
      ctx.arc(center, center, innerRadius, 0, Math.PI * 2)
      ctx.fill()
      ctx.draw()
    }).exec()
  },

  drawTrendLine() {
    if (!this.data.trends.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#trend-line-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const ctx = wx.createCanvasContext('trend-line-canvas', this)
      const w = rect.width
      const h = rect.height
      const padL = 34
      const padR = 24
      const padT = 24
      const padB = 34
      const chartW = w - padL - padR
      const chartH = h - padT - padB
      const trends = this.data.trends
      const maxQ = Math.max(1, ...trends.map(t => t.questions || 0))
      const step = trends.length > 1 ? chartW / (trends.length - 1) : chartW

      ctx.clearRect(0, 0, w, h)
      ctx.setStrokeStyle('#EDF1F5')
      ctx.setLineWidth(1)
      for (let i = 0; i < 4; i += 1) {
        const y = padT + chartH * i / 3
        ctx.beginPath()
        ctx.moveTo(padL, y)
        ctx.lineTo(w - padR, y)
        ctx.stroke()
      }

      ctx.setFillStyle('#9AABBA')
      ctx.setFontSize(10)
      ctx.fillText(`${maxQ}题`, 4, padT + 4)
      ctx.fillText('0题', 6, padT + chartH + 4)

      const qPoints = trends.map((t, index) => ({
        x: padL + step * index,
        y: padT + chartH - ((t.questions || 0) / maxQ) * chartH,
      }))
      const accPoints = trends.map((t, index) => ({
        x: padL + step * index,
        y: padT + chartH - (t.accuracy || 0) * chartH,
      }))

      ctx.beginPath()
      qPoints.forEach((p, index) => {
        if (index === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.lineTo(qPoints[qPoints.length - 1].x, padT + chartH)
      ctx.lineTo(qPoints[0].x, padT + chartH)
      ctx.closePath()
      ctx.setFillStyle('rgba(91, 123, 154, 0.10)')
      ctx.fill()

      ctx.beginPath()
      qPoints.forEach((p, index) => {
        if (index === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.setStrokeStyle('#5B7B9A')
      ctx.setLineWidth(2.5)
      ctx.stroke()

      ctx.beginPath()
      accPoints.forEach((p, index) => {
        if (index === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.setStrokeStyle('#6B9B6B')
      ctx.setLineWidth(2.5)
      ctx.stroke()

      accPoints.forEach(p => {
        ctx.beginPath()
        ctx.setFillStyle('#FFFFFF')
        ctx.arc(p.x, p.y, 4, 0, Math.PI * 2)
        ctx.fill()
        ctx.setStrokeStyle('#6B9B6B')
        ctx.setLineWidth(1)
        ctx.stroke()
      })

      ctx.draw()
    }).exec()
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    if (s < 60) return `${s}秒`
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分${s % 60}秒`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || ''
  },
})
