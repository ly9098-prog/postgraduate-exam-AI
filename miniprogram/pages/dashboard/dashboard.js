const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    pageEntered: false,
    overview: null,
    subjects: [],
    trends: [],
    behavior: null,
    forgetting: null,
    subjectTotal: 0,
    trendMeta: null,
    trendDays: 7,
    darkMode: false,
  },

  onShow() {
    this.loadData()
  },

  async loadData() {
    this.setData({ loading: true })
    try {
      const res = await api.get('/stats/dashboard')
      this._cachedDashboard = res
      const processed = this._process(res)
      this.setData(processed, () => {
        this.drawAllCharts()
      })
    } catch (e) {
      console.error('加载学习统计失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({
        loading: false,
        overview: null,
        subjects: [],
        trends: [],
        behavior: null,
        forgetting: null,
        subjectTotal: 0,
        trendMeta: null,
        pageEntered: false,
      })
    }
  },

  async loadTrendData(days) {
    try {
      const res = await api.get('/stats/trends?days=' + days)
      const rawTrends = res || []
      const trends = rawTrends.map(t => this._enrichTrendPoint(t))
      const trendMeta = this._calcTrendMeta(trends)
      this.setData({
        trends,
        trendMeta,
        trendDays: days,
      }, () => {
        this.drawTrendLine()
      })
    } catch (e) {
      console.error('加载趋势数据失败', e)
      wx.showToast({ title: '加载趋势失败', icon: 'none' })
    }
  },

  // ─────────────────────────────────────────────
  // DATA PROCESSING
  // ─────────────────────────────────────────────

  _process(res) {
    const overview = res.overview || {}
    const subjects = (res.subject_stats || []).filter(s => s.total_questions > 0)
    const trends = res.recent_trend || []
    const behavior = res.behavior || {}
    const forgetting = res.forgetting || {}

    const ov = this._processOverview(overview)
    const subs = this._processSubjects(subjects)
    const subjectTotal = subs.reduce((sum, s) => sum + (s.total_questions || 0), 0)
    const trs = this._processTrends(trends)
    const trendMeta = this._calcTrendMeta(trs)
    const bh = this._processBehavior(behavior)
    const fg = this._processForgetting(forgetting)

    return {
      overview: ov,
      subjects: subs,
      trends: trs,
      behavior: bh,
      forgetting: fg,
      subjectTotal,
      trendMeta,
      pageEntered: true,
      loading: false,
    }
  },

  _processOverview(ov) {
    const wrongTotal = (ov.total_wrong || 0) + (ov.total_correct || 0)
    const masteryPct = wrongTotal > 0
      ? Math.round(((ov.mastered_count || 0) / wrongTotal) * 100)
      : 0

    return {
      ...ov,
      _accuracyPct: Math.round((ov.accuracy || 0) * 100),
      _accuracyText: ((ov.accuracy || 0) * 100).toFixed(1) + '%',
      _todayDurationText: this._fmtDuration(ov.today_duration_sec || 0),
      _masteryPct: Math.min(100, Math.max(0, masteryPct)),
      _wrongTotal: wrongTotal,
    }
  },

  _processSubjects(subjects) {
    const palette = ['#5B7B9A', '#C49A6B', '#6B9B6B', '#C47A7A', '#7D8CC4', '#8CA7A1']
    const total = subjects.reduce((sum, s) => sum + (s.total_questions || 0), 0)

    let startAngle = 0
    return subjects.map((s, i) => {
      const share = total ? (s.total_questions || 0) / total : 0
      const endAngle = startAngle + share * 360
      const acc = s.accuracy || 0
      const accClass = acc >= 0.7 ? 'green' : acc >= 0.4 ? 'orange' : 'red'

      const result = {
        ...s,
        _label: this._subjectLabel(s.subject),
        _color: palette[i % palette.length],
        _startAngle: startAngle,
        _endAngle: endAngle,
        _sharePct: Math.round(share * 100),
        _accPct: Math.round(acc * 100),
        _accClass: accClass,
        _accColor: acc >= 0.7 ? '#6B9B6B' : acc >= 0.4 ? '#C49A6B' : '#C47A7A',
        _durationText: this._fmtDuration(s.total_duration_sec || 0),
      }
      startAngle = endAngle
      return result
    })
  },

  _enrichTrendPoint(t) {
    const acc = t.accuracy || 0
    const q = t.questions || 0
    const heatClass = q === 0 ? '' : q <= 5 ? 'lv1' : q <= 15 ? 'lv2' : q <= 30 ? 'lv3' : 'lv4'
    return {
      ...t,
      _shortDate: (t.date || '').slice(5),
      _accPct: Math.round(acc * 100),
      _accClass: acc >= 0.7 ? 'green' : acc >= 0.4 ? 'orange' : 'red',
      _heatClass: heatClass,
    }
  },

  _processTrends(trends) {
    return trends.map(t => this._enrichTrendPoint(t))
  },

  _calcTrendMeta(trends) {
    const total = trends.reduce((s, t) => s + (t.questions || 0), 0)
    const active = trends.filter(t => (t.questions || 0) > 0).length
    const avgAcc = trends.length
      ? trends.reduce((s, t) => s + (t.accuracy || 0), 0) / trends.length
      : 0
    return {
      totalQuestions: total,
      activeDays: active,
      avgAccuracyText: Math.round(avgAcc * 100) + '%',
    }
  },

  _processBehavior(bh) {
    return {
      ...bh,
      _avgTimeText: this._fmtDuration(bh.avg_time_sec || 0),
    }
  },

  _processForgetting(fg) {
    const high = fg.high_forget_count || 0
    const stuck = fg.stuck_questions || 0
    const pseudo = (fg.pseudo_mastered || []).length
    const total = high + stuck + pseudo
    return {
      ...fg,
      _pseudoMasteredCount: pseudo,
      _totalRisk: total,
      _hasRisk: total > 0,
    }
  },

  // ─────────────────────────────────────────────
  // CHART DRAWING
  // ─────────────────────────────────────────────

  drawAllCharts() {
    setTimeout(() => {
      this.drawScoreRing()
      this.drawSubjectDonut()
      this.drawTrendLine()
    }, 100)
  },

  drawScoreRing() {
    const query = wx.createSelectorQuery().in(this)
    query.select('#score-ring').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 12
      const lineWidth = 10
      const accuracy = Math.max(0, Math.min(1, (this.data.overview && this.data.overview.accuracy) || 0))
      const ctx = wx.createCanvasContext('score-ring', this)
      ctx.clearRect(0, 0, size, size)

      // Track ring
      ctx.beginPath()
      ctx.setStrokeStyle('#EDF1F5')
      ctx.setLineWidth(lineWidth)
      ctx.arc(center, center, radius, 0, Math.PI * 2)
      ctx.stroke()

      // Progress ring with gradient effect
      const startAngle = -Math.PI / 2
      const endAngle = startAngle + Math.PI * 2 * accuracy
      const gradient = ctx.createLinearGradient(0, 0, size, size)
      gradient.addColorStop(0, '#5B7B9A')
      gradient.addColorStop(0.5, '#7B9BBA')
      gradient.addColorStop(1, '#5B7B9A')

      ctx.beginPath()
      ctx.setStrokeStyle(gradient)
      ctx.setLineWidth(lineWidth)
      ctx.setLineCap('round')
      ctx.arc(center, center, radius, startAngle, endAngle)
      ctx.stroke()

      // End dot for visual polish
      if (accuracy > 0.02) {
        const dotX = center + radius * Math.cos(endAngle)
        const dotY = center + radius * Math.sin(endAngle)
        ctx.beginPath()
        ctx.setFillStyle('#FFFFFF')
        ctx.arc(dotX, dotY, 5, 0, Math.PI * 2)
        ctx.fill()
        ctx.setStrokeStyle('#5B7B9A')
        ctx.setLineWidth(2)
        ctx.stroke()
      }

      ctx.draw()
    }).exec()
  },

  drawSubjectDonut() {
    if (!this.data.subjects.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#subject-donut').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const size = Math.min(rect.width, rect.height)
      const center = size / 2
      const radius = center - 8
      const innerRadius = radius * 0.6
      const ctx = wx.createCanvasContext('subject-donut', this)
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

      // Inner white circle
      ctx.beginPath()
      ctx.setFillStyle('#FFFFFF')
      ctx.arc(center, center, innerRadius, 0, Math.PI * 2)
      ctx.fill()

      ctx.draw()
    }).exec()
  },

  drawTrendLine() {
    const trends = this.data.trends
    if (!trends || !trends.length) return

    const query = wx.createSelectorQuery().in(this)
    query.select('#trend-line').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const ctx = wx.createCanvasContext('trend-line', this)
      const w = rect.width
      const h = rect.height
      const pad = { l: 36, r: 20, t: 24, b: 32 }
      const cw = w - pad.l - pad.r
      const ch = h - pad.t - pad.b
      const count = trends.length
      const maxQ = Math.max(1, ...trends.map(t => t.questions || 0))
      const step = count > 1 ? cw / (count - 1) : cw

      ctx.clearRect(0, 0, w, h)

      // Grid lines
      ctx.setStrokeStyle('#EDF1F5')
      ctx.setLineWidth(1)
      for (let i = 0; i <= 3; i++) {
        const y = pad.t + (ch * i) / 3
        ctx.beginPath()
        ctx.moveTo(pad.l, y)
        ctx.lineTo(w - pad.r, y)
        ctx.stroke()
      }

      // Y-axis labels
      ctx.setFillStyle('#9AABBA')
      ctx.setFontSize(10)
      ctx.fillText(maxQ + '题', 2, pad.t + 10)
      ctx.fillText('0', 8, pad.t + ch + 4)

      // Build points
      const qPoints = trends.map((t, i) => ({
        x: pad.l + step * i,
        y: pad.t + ch - ((t.questions || 0) / maxQ) * ch,
        q: t.questions || 0,
      }))
      const accPoints = trends.map((t, i) => ({
        x: pad.l + step * i,
        y: pad.t + ch - (t.accuracy || 0) * ch,
        acc: t.accuracy || 0,
      }))

      // Area fill under question line
      ctx.beginPath()
      ctx.moveTo(qPoints[0].x, pad.t + ch)
      qPoints.forEach(p => ctx.lineTo(p.x, p.y))
      ctx.lineTo(qPoints[qPoints.length - 1].x, pad.t + ch)
      ctx.closePath()
      ctx.setFillStyle('rgba(91, 123, 154, 0.08)')
      ctx.fill()

      // Question line
      ctx.beginPath()
      qPoints.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.setStrokeStyle('#5B7B9A')
      ctx.setLineWidth(2.5)
      ctx.stroke()

      // Question dots
      qPoints.forEach(p => {
        ctx.beginPath()
        ctx.setFillStyle('#FFFFFF')
        ctx.arc(p.x, p.y, 4, 0, Math.PI * 2)
        ctx.fill()
        ctx.setStrokeStyle('#5B7B9A')
        ctx.setLineWidth(2)
        ctx.stroke()
      })

      // Accuracy line (solid, lighter weight)
      const hasAccuracy = trends.some(t => (t.questions || 0) > 0)
      if (hasAccuracy) {
        ctx.beginPath()
        accPoints.forEach((p, i) => {
          if (i === 0) ctx.moveTo(p.x, p.y)
          else ctx.lineTo(p.x, p.y)
        })
        ctx.setStrokeStyle('rgba(107, 155, 107, 0.7)')
        ctx.setLineWidth(2)
        ctx.stroke()

        // Accuracy dots
        accPoints.forEach(p => {
          if (p.acc > 0) {
            ctx.beginPath()
            ctx.setFillStyle('#FFFFFF')
            ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2)
            ctx.fill()
            ctx.setStrokeStyle('rgba(107, 155, 107, 0.8)')
            ctx.setLineWidth(1.5)
            ctx.stroke()
          }
        })
      }

      // X-axis labels (alternating to avoid crowding)
      trends.forEach((t, i) => {
        const showLabel = count <= 7 || i % Math.ceil(count / 7) === 0 || i === count - 1
        if (showLabel) {
          const x = pad.l + step * i
          ctx.setFillStyle('#9AABBA')
          ctx.setFontSize(9)
          ctx.setTextAlign('center')
          ctx.fillText(t._shortDate, x, pad.t + ch + 18)
        }
      })

      ctx.draw()
    }).exec()
  },

  // ─────────────────────────────────────────────
  // INTERACTIONS
  // ─────────────────────────────────────────────

  onTrendTab(e) {
    const days = parseInt(e.currentTarget.dataset.days, 10)
    if (days === this.data.trendDays) return
    if (days === 30) {
      this.loadTrendData(30)
    } else if (this._cachedDashboard) {
      // Use cached dashboard data for instant 7-day switch
      const processed = this._process(this._cachedDashboard)
      this.setData({ ...processed, trendDays: 7 }, () => this.drawTrendLine())
    } else {
      this.loadData()
    }
  },

  onSubjectTap(e) {
    const subject = e.currentTarget.dataset.subject
    if (!subject) return
    const subjData = this.data.subjects.find(s => s.subject === subject)
    if (!subjData) return

    wx.showToast({
      title: subjData._accPct + '% · ' + subjData.total_questions + '题',
      icon: 'none',
      duration: 2000,
    })
  },

  // ─────────────────────────────────────────────
  // HELPERS
  // ─────────────────────────────────────────────

  _fmtDuration(sec) {
    const s = Math.max(0, sec || 0)
    if (s < 60) return s + '秒'
    const m = Math.floor(s / 60)
    if (m < 60) return m + '分' + (s % 60 > 0 ? s % 60 + '秒' : '')
    const h = Math.floor(m / 60)
    return h + '时' + (m % 60 > 0 ? m % 60 + '分' : '')
  },

  _subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || ''
  },
})
