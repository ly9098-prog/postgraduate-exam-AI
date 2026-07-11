const api = require('../../utils/api')
const model = require('./dashboard.model')
const charts = require('./dashboard.charts')

Page({
  data: {
    // 三种独立加载状态
    initialLoading: true,
    refreshing: false,
    backgroundRefreshing: false,
    error: null,
    pageReady: false,

    hero: null,
    subtitle: '',
    insight: null,
    trend: null,
    trendError: null,
    subjects: null,
    reviewRisk: null,
    growth: null,
    adaptive: null,
    yearly: null,

    // Mastery rate
    wrongQuestionCount: 0,
    masteredWrongCount: 0,
    masteryRate: 0,
    masteryRatePct: 0,
    masteryStatusText: '',

    // UI state
    trendDays: 7,
    pendingTrendDays: null,
    _activeTabDays: 7,
    trendLoading: false,
    showYearlyHeatmap: false,
    yearlyLoading: false,
    yearlyError: null,
    yearlyHeatmapWeeks: [],

    // LLM analysis
    llmAnalysis: null,
    llmAnalysisLoading: false,
    llmAnalysisError: null,
    llmAnalysisGeneratedAt: null,

    _hasData: false,

    // Diagnosis insights
    insights: null,
  },

  _alive: false,
  _visible: false,
  _forceRefreshOnNextShow: false,
  _dashboardSeq: 0,
  _trendSeq: 0,
  _yearlySeq: 0,
  _ringTimer: null,
  _trendTimer: null,
  _gaugeTimer: null,
  _growthTimer: null,
  _adaptiveTimer: null,
  _lastLoadAt: 0,
  _loadPromise: null,
  _chartsCancelled: false,
  _heroHash: '',
  _trendHash: '',
  _subjectHash: '',
  _masteryHash: '',
  _growthHash: '',
  _adaptiveHash: '',
  _insightsLoading: false,
  _insightsError: null,

  onShow() {
    this._alive = true
    this._visible = true

    var forceRefresh = this._forceRefreshOnNextShow
    this._forceRefreshOnNextShow = false

    if (!this.data.pageReady) {
      this.loadDashboard({ mode: 'initial' })
      return
    }

    if (forceRefresh) {
      this.loadDashboard({ mode: 'background' })
      return
    }

    var now = Date.now()
    // 30s debounce: avoid rapid background refreshes
    if (now - this._lastLoadAt < 30000) {
      // Redraw charts if they were cancelled by hide
      if (this._chartsCancelled) {
        this._chartsCancelled = false
        this._redrawAllCharts()
      }
      return
    }

    this.loadDashboard({ mode: 'background' })
  },

  onHide() {
    this._visible = false
    this._chartsCancelled = true
    this._dashboardSeq++
    this._loadPromise = null  // 页面隐藏后使当前加载失效，允许下一次 onShow 发起新请求
    clearTimeout(this._ringTimer)
    this._ringTimer = null
    clearTimeout(this._trendTimer)
    this._trendTimer = null
    clearTimeout(this._gaugeTimer)
    this._gaugeTimer = null
    clearTimeout(this._growthTimer)
    this._growthTimer = null
    clearTimeout(this._adaptiveTimer)
    this._adaptiveTimer = null
  },

  onUnload() {
    this._alive = false
    this._visible = false
    this._dashboardSeq++
    this._loadPromise = null
    clearTimeout(this._ringTimer)
    this._ringTimer = null
    clearTimeout(this._trendTimer)
    this._trendTimer = null
    clearTimeout(this._gaugeTimer)
    this._gaugeTimer = null
    clearTimeout(this._growthTimer)
    this._growthTimer = null
    clearTimeout(this._adaptiveTimer)
    this._adaptiveTimer = null
  },

  onPullDownRefresh() {
    this.loadDashboard({ mode: 'refresh' }).finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async loadDashboard({ mode = 'initial' } = {}) {
    if (!this._alive || !this._visible) return null

    // Dedup concurrent loads
    if (this._loadPromise) return this._loadPromise

    const hasExistingData = this.data.pageReady && this.data.hero
    const seq = ++this._dashboardSeq

    if (mode === 'initial' && !hasExistingData) {
      this.setData({ initialLoading: true, error: null })
    } else if (mode === 'background') {
      this.setData({ backgroundRefreshing: true })
    }
    // silent: no visual change

    this._loadPromise = (async () => {
      try {
        const res = await api.get('/stats/dashboard-v2', {
          trend_days: this.data.trendDays,
          include_yearly_summary: true,
          include_growth: true,
          include_adaptive: true,
        })
        if (!this._alive || seq !== this._dashboardSeq) return null

        this._lastLoadAt = Date.now()
        this._processDashboard(res, mode)
        return res
      } catch (e) {
        console.error('[dashboard] load failed', e)
        if (!this._alive || seq !== this._dashboardSeq) return null

        if (!hasExistingData) {
          this.setData({ initialLoading: false, error: '学习数据加载失败' })
        } else {
          // Keep existing data, just show toast
          this.setData({ backgroundRefreshing: false })
          wx.showToast({ title: '刷新失败', icon: 'none' })
        }
        return null
      } finally {
        this._loadPromise = null
      }
    })()

    return this._loadPromise
  },

  async loadInsights(retryCount = 0) {
    if (!this._alive) return
    this._insightSeq = (this._insightSeq || 0) + 1
    const seq = this._insightSeq
    if (retryCount === 0) this._insightsLoading = true
    try {
      const res = await api.get('/stats/dashboard-insights', {
        days: this.data.trendDays,
        include_subjects: true,
        include_topics: true,
      })
      if (!this._alive || seq !== this._insightSeq) return
      const insights = model.buildInsights(res)
      // Enrich subjects with input_output data
      const enrichedMap = {}
      if (res && res.input_output && res.input_output.items) {
        res.input_output.items.forEach(item => {
          enrichedMap[item.subject] = {
            weak_topics: [],
            suggestion: item.suggestion,
            repeat_wrong_count: 0,
            status_label: item.efficiency_label,
          }
        })
      }
      // Merge weak topics from weak_topic_ranking into enriched map
      if (res && res.weak_topic_ranking && res.weak_topic_ranking.items) {
        res.weak_topic_ranking.items.forEach(t => {
          if (!enrichedMap[t.subject]) {
            enrichedMap[t.subject] = { weak_topics: [], suggestion: '', repeat_wrong_count: 0, status_label: '' }
          }
          if (!enrichedMap[t.subject].weak_topics) enrichedMap[t.subject].weak_topics = []
          if (enrichedMap[t.subject].weak_topics.length < 3) {
            enrichedMap[t.subject].weak_topics.push({ name: t.name })
          }
        })
      }
      // Re-build subjects with enriched data
      if (this.data.subjects && this.data.subjects.items) {
        const enrichedSubjects = model.buildSubjects(
          { items: this.data.subjects.items, strongest: this.data.subjects.strongest, weakest: this.data.subjects.weakest, totalQuestions: this.data.subjects.totalQuestions },
          enrichedMap
        )
        this.setData({ subjects: enrichedSubjects })
      }
      this._insightsLoading = false
      this._insightsError = null
      this.setData({ insights }, () => {
        // Draw diagnosis gauges after setData render
        if (!this._alive) return
        setTimeout(() => {
          if (insights && insights.todayQuality) {
            charts.drawScoreGauge('diag-quality', this, insights.todayQuality.score, 120)
          }
          if (insights && insights.weeklyConsistency) {
            charts.drawScoreGauge('diag-consistency', this, insights.weeklyConsistency.score, 120, String(Math.round(insights.weeklyConsistency.score)))
          }
          if (insights && insights.repeatWrong) {
            // Invert repeat rate for gauge: lower recurrence = better score
            const invScore = Math.max(0, 100 - (insights.repeatWrong.repeatRatePct || 0) * 2)
            charts.drawScoreGauge('diag-repeat', this, invScore, 120)
          }
        }, 100)
      })
    } catch (e) {
      console.error('[dashboard] insights load failed', e)
      if (!this._alive) return
      if (retryCount < 2) {
        // Retry twice with 2s delay
        await new Promise(r => setTimeout(r, 2000))
        return this.loadInsights(retryCount + 1)
      }
      this._insightsLoading = false
      this._insightsError = '诊断数据加载失败'
    }
  },

  _redrawAllCharts() {
    if (!this._alive || !this._visible) return
    const h = this.data.hero
    if (!h) return

    charts.drawScoreRing('score-ring', this, h.totalAccuracy)
    if (this.data._hasData) charts.drawMasteryGauge('mastery-gauge', this, this.data.masteryRate)

    const tr = this.data.trend
    if (tr && tr.points && tr.points.length) charts.drawTrendChart('trend-chart', this, tr.points)

    const subs = this.data.subjects
    if (subs && subs.items) charts.drawSubjectDonut('subject-donut', this, subs.items)

    const gr = this.data.growth
    if (gr) charts.drawGrowthRing('growth-ring', this, gr.levelProgressPct, (gr.levelProgressPct || 0) + '%')

    const ad = this.data.adaptive
    if (ad) charts.drawAdaptiveGauge('adaptive-gauge', this, ad.recallPct)

    // Diagnosis gauges
    const ins = this.data.insights
    if (ins) {
      if (ins.todayQuality) charts.drawScoreGauge('diag-quality', this, ins.todayQuality.score, 120)
      if (ins.weeklyConsistency) charts.drawScoreGauge('diag-consistency', this, ins.weeklyConsistency.score, 120, String(Math.round(ins.weeklyConsistency.score)))
      if (ins.repeatWrong) {
        const invScore = Math.max(0, 100 - (ins.repeatWrong.repeatRatePct || 0) * 2)
        charts.drawScoreGauge('diag-repeat', this, invScore, 120)
      }
    }
  },

  _processDashboard(res, mode = 'initial') {
    // Kick off insights load (non-blocking, after main content renders)
    if (this._alive) {
      setTimeout(() => this.loadInsights(), 200)
    }

    const hero = model.buildHero(res.overview)
    const rec = res.recommendation
    const trend = model.buildTrends(res.trends)
    const subjects = model.buildSubjects(res.subjects)
    const reviewRisk = model.buildReviewRisk(res.review_risk)
    const growth = model.buildGrowth(res.growth)
    const adaptive = model.buildAdaptive(res.adaptive)
    const yearly = model.buildYearly(res.yearly_summary)
    const subtitle = model.buildSubtitle(hero, rec, reviewRisk)

    const hasData = (hero.totalQuestions || 0) > 0
    const ov = res.overview || {}
    const wrongQ = ov.wrong_question_count || 0
    const masteredW = ov.mastered_wrong_count || 0
    const masteryRate = ov.mastery_rate || 0
    const masteryRatePct = Math.round(masteryRate * 100)
    const masteryStatusText = model.buildMasteryStatus(masteryRatePct)

    // Build chart hashes
    const heroHash = '' + (hero.totalAccuracy || 0)
    const trendHash = trend ? trend.points.map(p => p.date + p.questions + p.accuracy).join('|') : ''
    const subjectHash = subjects ? subjects.items.map(s => s.subject + s.accuracyPct).join('|') : ''
    const masteryHash = '' + masteryRatePct
    const growthHash = growth ? '' + (growth.levelProgressPct || 0) : ''
    const adaptiveHash = adaptive ? '' + (adaptive.recallPct || 0) : ''

    // Prevent canvas flicker: skip redraw if hash unchanged
    const canRedrawHero = heroHash !== this._heroHash
    const canRedrawTrend = trendHash !== this._trendHash
    const canRedrawSubject = subjectHash !== this._subjectHash
    const canRedrawMastery = masteryHash !== this._masteryHash
    const canRedrawGrowth = growthHash !== this._growthHash
    const canRedrawAdaptive = adaptiveHash !== this._adaptiveHash

    // Update instance hash keys
    this._heroHash = heroHash
    this._trendHash = trendHash
    this._subjectHash = subjectHash
    this._masteryHash = masteryHash
    this._growthHash = growthHash
    this._adaptiveHash = adaptiveHash

    // When background/refresh, keep old data until setData
    this.setData({
      hero,
      subtitle,
      insight: rec,
      trend,
      subjects,
      reviewRisk,
      growth,
      adaptive,
      yearly,
      wrongQuestionCount: wrongQ,
      masteredWrongCount: masteredW,
      masteryRate,
      masteryRatePct,
      masteryStatusText,
      initialLoading: false,
      backgroundRefreshing: false,
      pageReady: true,
      error: null,
      _hasData: hasData,
    }, () => {
      if (!this._alive) return

      // Draw charts only when data changed and page is visible
      this._ringTimer = setTimeout(() => {
        if (!this._alive || !this._visible) return
        if (canRedrawHero) {
          charts.drawScoreRing('score-ring', this, hero.totalAccuracy)
        }
        if (canRedrawMastery && hasData) {
          charts.drawMasteryGauge('mastery-gauge', this, masteryRate)
        }
      }, 80)

      if (trend && canRedrawTrend) {
        this._trendTimer = setTimeout(() => {
          if (!this._alive || !this._visible) return
          charts.drawTrendChart('trend-chart', this, trend.points)
        }, 200)
      }

      if (subjects && canRedrawSubject) {
        this._gaugeTimer = setTimeout(() => {
          if (!this._alive || !this._visible) return
          charts.drawSubjectDonut('subject-donut', this, subjects.items)
        }, 120)
      }

      // Growth ring chart
      if (growth && canRedrawGrowth) {
        this._growthTimer = setTimeout(() => {
          if (!this._alive || !this._visible) return
          charts.drawGrowthRing('growth-ring', this, growth.levelProgressPct, (growth.levelProgressPct || 0) + '%')
        }, 140)
      }

      // Adaptive mini gauge
      if (adaptive && canRedrawAdaptive) {
        this._adaptiveTimer = setTimeout(() => {
          if (!this._alive || !this._visible) return
          charts.drawAdaptiveGauge('adaptive-gauge', this, adaptive.recallPct)
        }, 160)
      }
    })
  },

  // ── Trend ──
  onTrendTab(e) {
    const days = parseInt(e.currentTarget.dataset.days, 10)
    if (days === this.data.trendDays || this.data.trendLoading) return
    // Use pendingTrendDays so tab highlight changes immediately
    // but trend data/meta/chart only update after API responds
    this.setData({ pendingTrendDays: days, _activeTabDays: days, trendLoading: true, trendError: null })
    this._loadTrendData(days)
  },

  async _loadTrendData(days) {
    const seq = ++this._trendSeq
    try {
      const res = await api.get('/stats/dashboard-v2', {
        trend_days: days,
        include_yearly_summary: false,
        include_growth: false,
        include_adaptive: false,
      })
      if (!this._alive || seq !== this._trendSeq) return
      const trend = model.buildTrends(res.trends)
      const trendHash = trend ? trend.points.map(p => p.date + p.questions + p.accuracy).join('|') : ''
      this._trendHash = trendHash
      this.setData({
        trend,
        trendLoading: false,
        trendError: null,
        trendDays: days,
        pendingTrendDays: null,
        _activeTabDays: days,
      }, () => {
        if (trend && this._alive) {
          // Clear any pending draw timer
          clearTimeout(this._trendTimer)
          this._trendTimer = setTimeout(() => {
            if (!this._alive) return
            charts.drawTrendChart('trend-chart', this, trend.points)
          }, 80)
        }
      })
    } catch (e) {
      console.error('[dashboard] trend load failed', e)
      if (!this._alive || seq !== this._trendSeq) return
      // Keep old trend data visible, show inline error
      this.setData({ trendLoading: false, pendingTrendDays: null, _activeTabDays: this.data.trendDays, trendError: '趋势数据加载失败' })
    }
  },

  onRetryTrend() {
    this.setData({ trendError: null, trendLoading: true })
    this._loadTrendData(this.data.trendDays)
  },

  // ── Yearly heatmap ──
  onToggleYearly() {
    if (this.data.showYearlyHeatmap) {
      this.setData({ showYearlyHeatmap: false })
      return
    }
    this._loadYearlyHeatmap()
  },

  async _loadYearlyHeatmap() {
    this.setData({ yearlyLoading: true, yearlyError: null })
    const seq = ++this._yearlySeq
    try {
      const res = await api.get('/stats/trends', { days: 365 })
      if (!this._alive || seq !== this._yearlySeq) return
      const weeks = this._buildHeatmapWeeks(res || [])
      this.setData({ showYearlyHeatmap: true, yearlyLoading: false, yearlyHeatmapWeeks: weeks })
    } catch (e) {
      console.error('[dashboard] yearly heatmap load failed', e)
      if (!this._alive || seq !== this._yearlySeq) return
      this.setData({ yearlyLoading: false, yearlyError: '热力图加载失败' })
      wx.showToast({ title: '热力图加载失败', icon: 'none' })
    }
  },

  _buildHeatmapWeeks(trends) {
    const byDate = {}
    ;(trends || []).forEach(t => { if (t && t.date) byDate[t.date] = t })
    const cells = []
    const today = new Date()
    for (let i = 364; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(today.getDate() - i)
      const date = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
      const src = byDate[date] || {}
      const q = src.questions || 0
      cells.push({ date, questions: q, shortDate: date.slice(5), heatClass: q === 0 ? '' : q <= 5 ? 'lv1' : q <= 15 ? 'lv2' : q <= 30 ? 'lv3' : 'lv4' })
    }
    const weeks = []
    for (let i = 0; i < cells.length; i += 7) {
      weeks.push({ key: 'w' + i, days: cells.slice(i, i + 7) })
    }
    return weeks
  },

  // ── LLM Analysis ──
  onGenerateLlmAnalysis() {
    if (this.data.llmAnalysisLoading) return

    // 60s cooldown
    if (this.data.llmAnalysisGeneratedAt) {
      const elapsed = Date.now() - new Date(this.data.llmAnalysisGeneratedAt).getTime()
      if (elapsed < 60000) {
        wx.showToast({ title: '刚刚已生成分析，可稍后再试', icon: 'none' })
        return
      }
    }

    this.setData({ llmAnalysisLoading: true, llmAnalysisError: null })
    this._doLlmAnalysis()
  },

  async _doLlmAnalysis() {
    try {
      const res = await api.post('/stats/dashboard-llm-analysis', {
        trend_days: this.data.trendDays,
      })
      if (!this._alive) return
      this.setData({
        llmAnalysis: res,
        llmAnalysisLoading: false,
        llmAnalysisError: null,
        llmAnalysisGeneratedAt: res.generated_at || new Date().toISOString(),
      })
    } catch (e) {
      console.error('[dashboard] LLM analysis failed', e)
      if (!this._alive) return
      if (e.code === 'LLM_NOT_CONFIGURED' || (typeof e.detail === 'string' && e.detail.includes('LLM_NOT_CONFIGURED'))) {
        this.setData({ llmAnalysisLoading: false, llmAnalysisError: 'AI 分析暂不可用（未配置服务）' })
      } else {
        this.setData({ llmAnalysisLoading: false, llmAnalysisError: 'AI 分析生成失败' })
      }
    }
  },

  onRetryLlmAnalysis() {
    this.setData({ llmAnalysis: null, llmAnalysisError: null })
    this.onGenerateLlmAnalysis()
  },

  onClearLlmAnalysis() {
    this.setData({ llmAnalysis: null, llmAnalysisError: null, llmAnalysisGeneratedAt: null })
  },

  onLlmFeedback() {
    var self = this
    var types = ['内容有误', '建议不准确', '其他问题']
    wx.showActionSheet({
      itemList: types,
      success: function (res) {
        var feedbackType = types[res.tapIndex] || '其他问题'
        api.post('/ai/feedback', {
          source: 'dashboard',
          feedback_type: feedbackType,
        }).then(function () {
          wx.showToast({ title: '反馈已提交，感谢您的帮助', icon: 'success' })
        }).catch(function () {
          wx.showToast({ title: '反馈提交失败，请稍后重试', icon: 'none' })
        })
      },
    })
  },

  // ── Navigation ──
  goTo(url, opts) {
    var self = this
    wx.navigateTo({
      url,
      fail: function() {
        if (opts && opts.refreshOnReturn) self._forceRefreshOnNextShow = false
        wx.showToast({ title: '跳转失败', icon: 'none' })
      },
    })
  },

  goReview() {
    this._forceRefreshOnNextShow = true
    this.goTo('/pages/review-today/review-today', { refreshOnReturn: true })
  },

  goPractice() {
    this._forceRefreshOnNextShow = true
    this.goTo('/pages/practice/practice', { refreshOnReturn: true })
  },

  goWrongBook() {
    this.goTo('/pages/wrong-book/wrong-book')
  },

  goSubjectWrongBook(e) {
    const subject = e.currentTarget.dataset.subject
    if (!subject) return
    this.goTo('/pages/wrong-book/wrong-book?subject=' + encodeURIComponent(subject))
  },

  goTopicWrongBook(e) {
    const topic = e.currentTarget.dataset.topic
    let url = '/pages/wrong-book/wrong-book'
    if (topic) url += '?topic=' + encodeURIComponent(topic)
    this.goTo(url)
  },

  // LLM action navigation
  goLlmAction(e) {
    const type = e.currentTarget.dataset.type
    if (type === 'review') this.goReview()
    else if (type === 'wrong' || type === 'subject') this.goWrongBook()
    else if (type === 'practice') this.goPractice()
    else this.goPractice()
  },

  // ── Topic Detail ──
  goTopicDetail(e) {
    const topic = e.currentTarget.dataset.topic
    const subject = e.currentTarget.dataset.subject
    let url = '/pages/wrong-book/wrong-book'
    const params = []
    if (topic) params.push('topic=' + encodeURIComponent(topic))
    if (subject) params.push('subject=' + encodeURIComponent(subject))
    if (params.length) url += '?' + params.join('&')
    this.goTo(url)
  },

  // ── Action Plan ──
  goActionPlan(e) {
    const type = e.currentTarget.dataset.type
    const topic = e.currentTarget.dataset.topic
    if (type === 'review') this.goReview()
    else if (type === 'wrong') {
      let url = '/pages/wrong-book/wrong-book'
      if (topic) url += '?topic=' + encodeURIComponent(topic)
      this.goTo(url)
    }
    else if (type === 'practice') this.goPractice()
    else this.goPractice()
  },
  onInsightCta() {
    const ctaType = this.data.insight && this.data.insight.cta_type
    if (ctaType === 'review') this.goReview()
    else if (ctaType === 'wrong' || ctaType === 'subject') this.goWrongBook()
    else this.goPractice()
  },

  onRetry() {
    this.loadDashboard({ mode: 'initial' })
  },
})
