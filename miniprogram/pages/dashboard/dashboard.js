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
    yearlyHeatmap: [],
    yearlyHeatmapWeeks: [],
    yearlyHeatmapMeta: null,
    badgeWall: [],
    learningProfile: null,
    adaptiveOverview: null,
  },

  onShow() {
    this.loadData()
  },

  async loadData() {
    this.setData({ loading: true })
    try {
      const [res, yearlyTrends, growthRes, adaptiveRes] = await Promise.all([
        api.get('/stats/dashboard'),
        api.get('/stats/trends?days=365').catch(() => []),
        api.get('/stats/growth').catch(() => null),
        api.get('/adaptive-learning/overview').catch(() => null),
      ])
      this._cachedDashboard = res
      this._cachedYearlyTrends = yearlyTrends
      this._cachedGrowth = growthRes
      this._cachedAdaptive = adaptiveRes
      const processed = this._process(res, yearlyTrends, growthRes)
      // Phase 1: render core sections only, defer canvas draws
      const { yearlyHeatmap, yearlyHeatmapWeeks, yearlyHeatmapMeta, badgeWall, ...coreData } = processed
      // Process adaptive overview for display
      const adaptiveData = this._processAdaptive(adaptiveRes)
      this.setData({ ...coreData, adaptiveOverview: adaptiveData }, () => {
        // Stagger canvas draws to spread JS thread cost on low-end devices
        setTimeout(() => this.drawScoreRing(), 80)
        setTimeout(() => this.drawSubjectDonut(), 180)
        setTimeout(() => this.drawTrendLine(), 280)
      })

      // Phase 2: defer heavy DOM sections after main layout settles
      setTimeout(() => {
        this.setData({ yearlyHeatmap, yearlyHeatmapWeeks, yearlyHeatmapMeta })
      }, 500)
      setTimeout(() => {
        this.setData({ badgeWall })
      }, 700)
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
        yearlyHeatmap: [],
        yearlyHeatmapWeeks: [],
        yearlyHeatmapMeta: null,
        badgeWall: [],
        learningProfile: null,
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
        _heatBarData: this._sampleHeatBar(trends),
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

  _process(res, yearlyTrends, growthRes) {
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
    const yearlyTrendsProc = this._processTrends(yearlyTrends || [])
    const yearlyHeatmap = this._buildYearlyHeatmap(yearlyTrendsProc, ov)
    const yearlyHeatmapWeeks = this._chunkHeatmapWeeks(yearlyHeatmap)
    const yearlyHeatmapMeta = this._calcYearlyHeatmapMeta(yearlyHeatmap)
    const badgeWall = growthRes && growthRes.badges
      ? growthRes.badges.map(b => ({
          key: b.key, title: b.title, desc: b.desc,
          unlocked: b.unlocked, progressText: b.progress_text,
        }))
      : this._buildBadgeWall(ov, trendMeta, fg)
    const learningProfile = this._buildLearningProfile(ov, subs, trendMeta, fg, bh)

    return {
      overview: ov,
      subjects: subs,
      trends: trs,
      _heatBarData: this._sampleHeatBar(trs),
      behavior: bh,
      forgetting: fg,
      subjectTotal,
      trendMeta,
      yearlyHeatmap,
      yearlyHeatmapWeeks,
      yearlyHeatmapMeta,
      badgeWall,
      learningProfile,
      pageEntered: true,
      loading: false,
    }
  },

  _processAdaptive(res) {
    if (!res) return null

    // 间隔状态中文映射
    const statusMap = {
      fast_forgetting: '遗忘较快',
      slightly_fast_forgetting: '略偏快遗忘',
      normal: '节奏正常',
      stable_memory: '记忆稳定',
    }

    // 建议文案
    const suggestionMap = {
      fast_forgetting: '系统已自动缩短复习间隔，帮助巩固记忆',
      slightly_fast_forgetting: '系统已略微缩短复习间隔',
      normal: '复习节奏合理，继续保持',
      stable_memory: '记忆保持良好，间隔适当拉长',
    }

    const status = res.interval_status || 'normal'
    const recallPct = Math.round((res.recent_due_recall_rate || 0) * 100)

    return {
      intervalFactor: res.interval_factor || 1.0,
      intervalStatus: statusMap[status] || '节奏正常',
      intervalSuggestion: suggestionMap[status] || '',
      targetRecallPct: Math.round((res.target_recall_rate || 0.8) * 100),
      recentRecallPct: recallPct,
      hardQuestionCount: res.hard_question_count || 0,
      fastForgettingKPCount: res.fast_forgetting_knowledge_count || 0,
      pathBlockedKPCount: res.path_blocked_knowledge_count || 0,
      weightsAdjusted: res.weights_adjusted || false,
      weightSummary: res.weight_summary || '',
      _hasData: (res.interval_factor !== undefined && res.interval_factor !== 1.0)
        || (res.hard_question_count > 0)
        || (res.fast_forgetting_knowledge_count > 0)
        || (res.path_blocked_knowledge_count > 0),
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
    const palette = ['#4F7FFF', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4']
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
        _accColor: acc >= 0.7 ? '#22C55E' : acc >= 0.4 ? '#F59E0B' : '#EF4444',
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
      summaryText: `近${this.data.trendDays}天累计做题${total}题，平均正确率${Math.round(avgAcc * 100)}%，活跃${active}天。`,
    }
  },

  _buildYearlyHeatmap(trends, overview) {
    const byDate = {}
    ;(trends || []).forEach(item => {
      if (item && item.date) byDate[item.date] = item
    })

    const today = new Date()
    const cells = []
    for (let i = 364; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(today.getDate() - i)
      const date = this._fmtDateKey(d)
      const source = byDate[date] || {}
      const questions = source.questions || 0
      const heatClass = questions === 0 ? '' : questions <= 5 ? 'lv1' : questions <= 15 ? 'lv2' : questions <= 30 ? 'lv3' : 'lv4'
      cells.push({
        date,
        questions,
        accuracy: source.accuracy || 0,
        _shortDate: date.slice(5),
        _heatClass: heatClass,
      })
    }

    const todayCell = cells[cells.length - 1]
    if (todayCell && overview) {
      todayCell.questions = overview.today_questions || todayCell.questions
      todayCell.accuracy = overview.today_questions ? (overview.today_correct || 0) / Math.max(1, overview.today_questions) : todayCell.accuracy
      todayCell._heatClass = todayCell.questions === 0 ? '' : todayCell.questions <= 5 ? 'lv1' : todayCell.questions <= 15 ? 'lv2' : todayCell.questions <= 30 ? 'lv3' : 'lv4'
    }

    return cells
  },

  _chunkHeatmapWeeks(cells) {
    const weeks = []
    for (let i = 0; i < cells.length; i += 7) {
      weeks.push({ key: 'w' + i, days: cells.slice(i, i + 7) })
    }
    return weeks
  },

  _calcYearlyHeatmapMeta(cells) {
    const activeDays = cells.filter(item => item.questions > 0).length
    const totalQuestions = cells.reduce((sum, item) => sum + item.questions, 0)
    const bestDay = cells.reduce((best, item) => item.questions > best.questions ? item : best, { questions: 0, date: '' })
    return {
      activeDays,
      totalQuestions,
      bestDayText: bestDay.questions ? `${bestDay._shortDate} · ${bestDay.questions}题` : '暂无记录',
      summaryText: `过去365天活跃${activeDays}天，累计完成${totalQuestions}题，最高单日${bestDay.questions || 0}题。`,
    }
  },

  _buildBadgeWall(overview, trendMeta, forgetting) {
    const total = overview.total_questions || 0
    const streak = overview.consecutive_days || 0
    const accuracy = overview._accuracyPct || 0
    const mastered = overview.mastered_count || 0
    const due = overview.due_review_count || 0
    return [
      { key: 'first', title: '首次学习', desc: '完成第一道题', unlocked: total > 0, progressText: total > 0 ? '已解锁' : '0/1' },
      { key: 'streak7', title: '连续7天', desc: '保持一周学习节奏', unlocked: streak >= 7, progressText: `${Math.min(streak, 7)}/7天` },
      { key: 'hundred', title: '完成100题', desc: '建立刷题手感', unlocked: total >= 100, progressText: `${Math.min(total, 100)}/100题` },
      { key: 'thousand', title: '完成1000题', desc: '进入高强度训练', unlocked: total >= 1000, progressText: `${Math.min(total, 1000)}/1000题` },
      { key: 'accuracy90', title: '正确率90%', desc: '稳定高质量输出', unlocked: accuracy >= 90 && total >= 30, progressText: `${accuracy}%` },
      { key: 'review-clear', title: '清空复习', desc: '今日复习全部完成', unlocked: due === 0 && total > 0, progressText: due === 0 && total > 0 ? '已完成' : `${due}题待复习` },
      { key: 'active-month', title: '活跃30天', desc: '形成长期学习习惯', unlocked: (trendMeta.activeDays || 0) >= 30, progressText: `${Math.min(trendMeta.activeDays || 0, 30)}/30天` },
      { key: 'master100', title: '掌握100题', desc: '错题转化为能力', unlocked: mastered >= 100, progressText: `${Math.min(mastered, 100)}/100题` },
    ]
  },

  _buildLearningProfile(overview, subjects, trendMeta, forgetting, behavior) {
    const strongest = subjects.reduce((best, item) => item._accPct > best._accPct ? item : best, { _label: '待积累', _accPct: 0 })
    const weakest = subjects.reduce((worst, item) => item._accPct < worst._accPct ? item : worst, subjects[0] || { _label: '待积累', _accPct: 0 })
    const total = overview.total_questions || 0
    const streak = overview.consecutive_days || 0
    const focus = forgetting._hasRisk
      ? '优先复盘高频遗忘和长期未掌握题'
      : (overview.due_review_count > 0 ? '先完成今日复习，再补充新题训练' : '保持当前节奏，适合提高题量')
    const rhythm = trendMeta.activeDays >= 5 ? '节奏稳定' : (trendMeta.activeDays > 0 ? '节奏起步' : '等待数据')

    return {
      title: total > 0 ? 'AI学习画像' : '学习画像待生成',
      summary: total > 0
        ? `${rhythm}，累计${total}题，连续学习${streak}天。`
        : '开始刷题后会自动生成优势、弱项和下一步建议。',
      strengths: [
        strongest._label !== '待积累' ? `${strongest._label}正确率${strongest._accPct}%` : '完成更多题目后识别优势',
        streak >= 7 ? `连续学习${streak}天，习惯稳定` : `当前连续${streak}天，建议先冲刺7天`,
      ],
      weaknesses: [
        weakest._label !== '待积累' ? `${weakest._label}正确率${weakest._accPct}%` : '暂无明显弱项',
        forgetting._hasRisk ? `遗忘风险${forgetting._totalRisk}项，需要集中复盘` : '遗忘风险较低，适合巩固提升',
      ],
      actions: [
        focus,
        behavior.avg_time_sec > 0 ? `平均用时${behavior._avgTimeText}，可做限时训练` : '积累用时数据后会给出速度建议',
      ],
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
      ctx.setStrokeStyle('#E2EAF7')
      ctx.setLineWidth(lineWidth)
      ctx.arc(center, center, radius, 0, Math.PI * 2)
      ctx.stroke()

      // Progress ring with gradient effect
      const startAngle = -Math.PI / 2
      const endAngle = startAngle + Math.PI * 2 * accuracy
      const gradient = ctx.createLinearGradient(0, 0, size, size)
      gradient.addColorStop(0, '#4F7FFF')
      gradient.addColorStop(0.5, '#6EC1FF')
      gradient.addColorStop(1, '#4F7FFF')

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
        ctx.setStrokeStyle('#4F7FFF')
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
      ctx.setStrokeStyle('#E2EAF7')
      ctx.setLineWidth(1)
      for (let i = 0; i <= 3; i++) {
        const y = pad.t + (ch * i) / 3
        ctx.beginPath()
        ctx.moveTo(pad.l, y)
        ctx.lineTo(w - pad.r, y)
        ctx.stroke()
      }

      // Y-axis labels
      ctx.setFillStyle('#8EA0BA')
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
      ctx.setFillStyle('rgba(79, 127, 255, 0.08)')
      ctx.fill()

      // Question line
      ctx.beginPath()
      qPoints.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.setStrokeStyle('#4F7FFF')
      ctx.setLineWidth(2.5)
      ctx.stroke()

      // Question dots
      qPoints.forEach(p => {
        ctx.beginPath()
        ctx.setFillStyle('#FFFFFF')
        ctx.arc(p.x, p.y, 4, 0, Math.PI * 2)
        ctx.fill()
        ctx.setStrokeStyle('#4F7FFF')
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
        ctx.setStrokeStyle('rgba(34, 197, 94, 0.72)')
        ctx.setLineWidth(2)
        ctx.stroke()

        // Accuracy dots
        accPoints.forEach(p => {
          if (p.acc > 0) {
            ctx.beginPath()
            ctx.setFillStyle('#FFFFFF')
            ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2)
            ctx.fill()
            ctx.setStrokeStyle('rgba(34, 197, 94, 0.82)')
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
          ctx.setFillStyle('#8EA0BA')
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
    if (days === 30 || days === 90) {
      this.loadTrendData(days)
    } else if (this._cachedDashboard && this._cachedYearlyTrends) {
      const processed = this._process(this._cachedDashboard, this._cachedYearlyTrends, this._cachedGrowth)
      const { yearlyHeatmap, yearlyHeatmapWeeks, yearlyHeatmapMeta, badgeWall, ...coreData } = processed
      this.setData({ ...coreData, trendDays: 7 }, () => {
        setTimeout(() => this.drawTrendLine(), 50)
      })
      setTimeout(() => {
        this.setData({ yearlyHeatmap, yearlyHeatmapWeeks, yearlyHeatmapMeta })
      }, 300)
      setTimeout(() => {
        this.setData({ badgeWall })
      }, 500)
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

  _fmtDateKey(date) {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  },

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

  // Limit heat-bar cells to reduce DOM nodes on 30/90-day views
  _sampleHeatBar(trends) {
    if (!trends || trends.length <= 14) return trends || []
    const step = Math.floor(trends.length / 14)
    const sampled = []
    for (let i = 0; i < trends.length; i += step) {
      if (sampled.length >= 14) break
      sampled.push(trends[i])
    }
    return sampled
  },
})
