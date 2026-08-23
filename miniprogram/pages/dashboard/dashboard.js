const api = require('../../utils/api')
const model = require('./dashboard.model')
const charts = require('./dashboard.charts')
const { getChinaDate, parseServerUtc } = require('../../utils/china-time')

function clampPct(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)))
}

function buildDeepAnalysisState(source) {
  const hero = source.hero || {}
  const trend = source.trend || {}
  const subjects = source.subjects || null
  const reviewRisk = source.reviewRisk || null
  const growth = source.growth || null
  const yearly = source.yearly || null
  const insights = source.insights || null
  const repeatWrong = insights && insights.repeatWrong
  const speed = insights && insights.speedAccuracy
  const consistency = insights && insights.weeklyConsistency
  const weakest = subjects && subjects.itemsByWeak && subjects.itemsByWeak[0]

  const highForget = reviewRisk ? (reviewRisk.highForgetCount || 0) : 0
  const stuck = reviewRisk ? (reviewRisk.stuckQuestions || 0) : 0
  const pseudo = reviewRisk ? (reviewRisk.pseudoMasteredCount || 0) : 0
  const riskTotal = highForget + stuck + pseudo
  const riskWidthPct = clampPct(riskTotal <= 0 ? 0 : Math.min(100, riskTotal * 8))
  const riskEntries = [
    { key: 'stuck', value: stuck, priority: 3 },
    { key: 'highForget', value: highForget, priority: 2 },
    { key: 'pseudo', value: pseudo, priority: 1 },
  ].sort((a, b) => b.value - a.value || b.priority - a.priority)
  const primaryRisk = riskEntries[0].value > 0 ? riskEntries[0].key : 'none'
  const allTopics = reviewRisk && reviewRisk.topTopics ? reviewRisk.topTopics : []
  const topTopics = allTopics.slice(0, 3)
  const remainingTopicCount = Math.max(0, allTopics.length - topTopics.length)

  const correctSec = speed ? Number(speed.avgTimeCorrectSec || 0) : 0
  const wrongSec = speed ? Number(speed.avgTimeWrongSec || 0) : 0
  const hasSpeedData = correctSec > 0 && wrongSec > 0
  const speedMax = Math.max(correctSec, wrongSec, 1)
  const ratio = correctSec > 0 ? wrongSec / correctSec : 0
  const speedRatioText = ratio > 0 ? `错题耗时 ${ratio.toFixed(1)}×` : '数据积累中'
  const speedDiff = Math.abs(wrongSec - correctSec)
  const speedDiffText = hasSpeedData
    ? `${wrongSec >= correctSec ? '错题平均多用' : '正确题平均多用'} ${speedDiff.toFixed(1)} 秒`
    : '数据积累中'
  const positionFor = (seconds) => Math.round((8 + (seconds / speedMax) * 84) * 10) / 10
  const correctPositionPct = hasSpeedData ? positionFor(correctSec) : 8
  const wrongPositionPct = hasSpeedData ? positionFor(wrongSec) : 92
  const linkLeftPct = Math.min(correctPositionPct, wrongPositionPct)
  const linkWidthPct = Math.max(0, Math.abs(wrongPositionPct - correctPositionPct))
  const speedConclusion = speed ? speed.conclusion : '完成更多练习后，将显示正确题与错题的耗时差异。'

  let riskLabel = '风险较低'
  let riskTone = 'green'
  if (stuck >= 8 || riskTotal >= 12) {
    riskLabel = '需要优先处理'
    riskTone = 'orange'
  } else if (riskTotal > 0) {
    riskLabel = '建议持续复盘'
    riskTone = 'blue'
  }

  const memoryCompare = {
    highForget,
    stuck,
    pseudo,
    riskTotal,
    riskWidthPct,
    riskLabel,
    riskTone,
    primaryRisk,
    topTopics,
    remainingTopicCount,
    correctSec: correctSec ? Math.round(correctSec * 10) / 10 : 0,
    wrongSec: wrongSec ? Math.round(wrongSec * 10) / 10 : 0,
    correctWidthPct: clampPct(correctSec / speedMax * 100),
    wrongWidthPct: clampPct(wrongSec / speedMax * 100),
    hasSpeedData,
    correctPositionPct,
    wrongPositionPct,
    linkLeftPct,
    linkWidthPct,
    speedDiffText,
    speedRatioText,
    speedConclusion,
  }

  let diagnosis
  if (repeatWrong && repeatWrong.repeatRatePct >= 40) {
    diagnosis = {
      tone: 'orange',
      levelLabel: '优先级高',
      title: '重复错题正在拖慢整体提升',
      desc: '先处理反复答错的题目，再进入新题练习，能够更快降低无效重复。',
      evidence: [
        { label: '错题复发率', value: `${repeatWrong.repeatRatePct}%`, tone: 'orange' },
        { label: '反复错题', value: `${repeatWrong.repeatWrongCount || 0}道`, tone: '' },
        { label: '待复习', value: `${hero.dueReviewCount || 0}道`, tone: 'blue' },
      ],
    }
  } else if (stuck >= 5) {
    diagnosis = {
      tone: 'orange',
      levelLabel: '需要巩固',
      title: '长期未掌握内容需要集中突破',
      desc: '当前主要问题不是练习数量，而是部分知识点长期停留在低掌握状态。',
      evidence: [
        { label: '长期未掌握', value: `${stuck}`, tone: 'orange' },
        { label: '高频遗忘', value: `${highForget}`, tone: '' },
        { label: '错题掌握率', value: `${source.masteryRatePct || 0}%`, tone: 'blue' },
      ],
    }
  } else if (weakest && weakest.accuracyPct < 50) {
    diagnosis = {
      tone: 'blue',
      levelLabel: '重点关注',
      title: `${weakest.label}是当前最明显的短板`,
      desc: `该科目正确率为 ${weakest.accuracyPct}%，建议围绕高频错题进行小范围专项练习。`,
      evidence: [
        { label: '当前正确率', value: `${weakest.accuracyPct}%`, tone: 'orange' },
        { label: '累计错题', value: `${weakest.wrongCount || 0}道`, tone: '' },
        { label: '练习题量', value: `${weakest.totalQuestions || 0}题`, tone: 'blue' },
      ],
    }
  } else if (consistency && consistency.activeDays <= 2) {
    diagnosis = {
      tone: 'blue',
      levelLabel: '节奏提醒',
      title: '学习节奏仍不够连续',
      desc: '正确率之外，更稳定的活跃天数会让复习计划和薄弱点判断更加可靠。',
      evidence: [
        { label: '活跃天数', value: `${consistency.activeDays}/${consistency.days}`, tone: 'orange' },
        { label: '本期做题', value: `${trend.totalQuestions || 0}题`, tone: '' },
        { label: '平均正确率', value: `${trend.avgAccuracyPct || 0}%`, tone: 'blue' },
      ],
    }
  } else {
    diagnosis = {
      tone: 'green',
      levelLabel: '状态稳定',
      title: '当前学习节奏基本稳定',
      desc: '继续保持练习频率，并优先处理到期复习与当前排名最低的知识点。',
      evidence: [
        { label: '平均正确率', value: `${trend.avgAccuracyPct || 0}%`, tone: 'green' },
        { label: '活跃天数', value: `${trend.activeDays || 0}天`, tone: '' },
        { label: '今年学习', value: `${yearly ? yearly.activeDays : 0}天`, tone: 'blue' },
      ],
    }
  }

  return { deepDiagnosis: diagnosis, memoryCompare }
}

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
    masteryRatePct: 0,
    masteryStatusText: '',

    // UI state
    trendDays: 7,
    pendingTrendDays: null,
    _activeTabDays: 7,
    trendLoading: false,
    trendMetric: 'accuracy',
    showYearlyHeatmap: false,
    showDeepAnalysis: false,
    analysisActiveTab: 'subjects',
    deepDiagnosis: null,
    memoryCompare: {
      highForget: 0,
      stuck: 0,
      pseudo: 0,
      riskWidthPct: 0,
      riskLabel: '数据积累中',
      riskTone: '',
      primaryRisk: 'none',
      topTopics: [],
      remainingTopicCount: 0,
      correctSec: 0,
      wrongSec: 0,
      correctWidthPct: 0,
      wrongWidthPct: 0,
      hasSpeedData: false,
      correctPositionPct: 8,
      wrongPositionPct: 92,
      linkLeftPct: 8,
      linkWidthPct: 84,
      speedDiffText: '数据积累中',
      speedRatioText: '数据积累中',
      speedConclusion: '完成更多练习后显示效率比较。',
    },
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
  _insightSeq: 0,
  _insightRetryTimer: null,
  _insightKickoffTimer: null,

  goBack() {
    wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/home/home' }) })
  },

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
    this._trendSeq++
    this._yearlySeq++
    this._insightSeq++
    this._loadPromise = null  // 页面隐藏后使当前加载失效，允许下一次 onShow 发起新请求
    clearTimeout(this._insightRetryTimer)
    this._insightRetryTimer = null
    clearTimeout(this._insightKickoffTimer)
    this._insightKickoffTimer = null
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
    // Requests invalidated above will intentionally skip their completion
    // handlers, so clear transient loading flags here to avoid a stuck spinner
    // when the page is shown again within the normal refresh debounce window.
    this.setData({
      backgroundRefreshing: false,
      trendLoading: false,
      pendingTrendDays: null,
      _activeTabDays: this.data.trendDays,
      yearlyLoading: false,
    })
  },

  onUnload() {
    this._alive = false
    this._visible = false
    this._dashboardSeq++
    this._trendSeq++
    this._yearlySeq++
    this._insightSeq++
    this._loadPromise = null
    clearTimeout(this._insightRetryTimer)
    this._insightRetryTimer = null
    clearTimeout(this._insightKickoffTimer)
    this._insightKickoffTimer = null
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

    const loadPromise = (async () => {
      try {
        const res = await api.get('/stats/dashboard-v2', {
          trend_days: this.data.trendDays,
          include_yearly_summary: true,
          include_growth: true,
          include_adaptive: true,
        })
        if (!this._alive || !this._visible || seq !== this._dashboardSeq) return null

        this._lastLoadAt = Date.now()
        this._processDashboard(res, mode)
        return res
      } catch (e) {
        console.error('[dashboard] load failed', e)
        if (!this._alive || !this._visible || seq !== this._dashboardSeq) return null

        if (!hasExistingData) {
          this.setData({ initialLoading: false, error: '学习数据加载失败' })
        } else {
          // Keep existing data, just show toast
          this.setData({ backgroundRefreshing: false })
          wx.showToast({ title: '刷新失败', icon: 'none' })
        }
        return null
      }
    })()

    this._loadPromise = loadPromise
    try {
      return await loadPromise
    } finally {
      // A request invalidated by onHide may finish after a new onShow request
      // has already started. Never let the old request clear the new promise.
      if (this._loadPromise === loadPromise) this._loadPromise = null
    }
  },

  async loadInsights(retryCount = 0, requestSeq = null) {
    if (!this._alive || !this._visible) return

    let seq = requestSeq
    if (retryCount === 0 || seq == null) {
      clearTimeout(this._insightRetryTimer)
      this._insightRetryTimer = null
      seq = ++this._insightSeq
      this._insightsLoading = true
    }

    try {
      const res = await api.get('/stats/dashboard-insights', {
        days: this.data.trendDays,
        include_subjects: true,
        include_topics: true,
      })
      if (!this._alive || !this._visible || seq !== this._insightSeq) return
      const insights = model.buildInsights(res)
      // Enrich subjects with input_output data
      const enrichedMap = {}
      if (res && res.input_output && res.input_output.items) {
        res.input_output.items.forEach(item => {
          const sid = item.subject_id != null ? item.subject_id : item.subject
          if (sid == null) return
          enrichedMap[sid] = {
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
          const sid = t.subject_id != null ? t.subject_id : t.subject
          if (sid == null) return
          if (!enrichedMap[sid]) {
            enrichedMap[sid] = { weak_topics: [], suggestion: '', repeat_wrong_count: 0, status_label: '' }
          }
          if (!enrichedMap[sid].weak_topics) enrichedMap[sid].weak_topics = []
          if (enrichedMap[sid].weak_topics.length < 3) {
            enrichedMap[sid].weak_topics.push({ name: t.name })
          }
        })
      }
      // Re-build subjects with enriched data and refresh the diagnosis view-model.
      let nextSubjects = this.data.subjects
      if (this.data.subjects && this.data.subjects.items) {
        nextSubjects = model.buildSubjects(
          { items: this.data.subjects.items, strongest: this.data.subjects.strongest, weakest: this.data.subjects.weakest, totalQuestions: this.data.subjects.totalQuestions },
          enrichedMap
        )
      }
      const deepState = buildDeepAnalysisState({
        hero: this.data.hero,
        trend: this.data.trend,
        subjects: nextSubjects,
        reviewRisk: this.data.reviewRisk,
        growth: this.data.growth,
        yearly: this.data.yearly,
        masteryRatePct: this.data.masteryRatePct,
        insights,
      })
      this._insightsLoading = false
      this._insightsError = null
      this.setData({ subjects: nextSubjects, insights, ...deepState })
    } catch (e) {
      console.error('[dashboard] insights load failed', e)
      if (!this._alive || !this._visible || seq !== this._insightSeq) return
      if (retryCount < 2) {
        clearTimeout(this._insightRetryTimer)
        this._insightRetryTimer = setTimeout(() => {
          this._insightRetryTimer = null
          if (!this._alive || !this._visible || seq !== this._insightSeq) return
          this.loadInsights(retryCount + 1, seq)
        }, 2000)
        return
      }
      this._insightsLoading = false
      this._insightsError = '诊断数据加载失败'
    }
  },

  _redrawAllCharts() {
    if (!this._alive || !this._visible) return
    const tr = this.data.trend
    if (tr && tr.points && tr.points.length) {
      charts.drawTrendChart('trend-chart', this, tr.points, { metric: this.data.trendMetric, previousPoints: tr.previousPoints })
    }
  },

  _processDashboard(res, mode = 'initial') {
    // Kick off insights load (non-blocking, after main content renders)
    if (this._alive && this._visible) {
      clearTimeout(this._insightKickoffTimer)
      this._insightKickoffTimer = setTimeout(() => {
        this._insightKickoffTimer = null
        if (this._alive && this._visible) this.loadInsights()
      }, 200)
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
    const deepState = buildDeepAnalysisState({
      hero,
      trend,
      subjects,
      reviewRisk,
      growth,
      yearly,
      masteryRatePct,
      insights: this.data.insights,
    })

    // Build chart hashes
    const heroHash = '' + (hero.totalAccuracy || 0)
    const trendHash = trend ? [trend.points, trend.previousPoints || []].map(list => list.map(p => p.date + p.questions + p.accuracy).join('|')).join('::') : ''
    const subjectHash = subjects ? subjects.items.map(s => (s.subject_id != null ? s.subject_id : s.subject) + s.accuracyPct).join('|') : ''
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
    this._insight = rec
    this._masteryRate = masteryRate
    this.setData({
      hero,
      subtitle,
      trend,
      subjects,
      reviewRisk,
      growth,
      adaptive,
      yearly,
      wrongQuestionCount: wrongQ,
      masteredWrongCount: masteredW,
      masteryRatePct,
      masteryStatusText,
      ...deepState,
      initialLoading: false,
      backgroundRefreshing: false,
      pageReady: true,
      error: null,
      _hasData: hasData,
    }, () => {
      if (!this._alive) return

      // The redesigned dashboard uses a single primary chart to keep the page calm and focused.
      if (trend && canRedrawTrend) {
        this._trendTimer = setTimeout(() => {
          if (!this._alive || !this._visible) return
          charts.drawTrendChart('trend-chart', this, trend.points, { metric: this.data.trendMetric, previousPoints: trend.previousPoints })
        }, 160)
      }
    })
  },

  // ── Trend ──
  onTrendMetric(e) {
    const metric = e.currentTarget.dataset.metric
    if (!metric || metric === this.data.trendMetric) return
    this.setData({ trendMetric: metric }, () => {
      const trend = this.data.trend
      if (!trend || !trend.points || !trend.points.length) return
      clearTimeout(this._trendTimer)
      this._trendTimer = setTimeout(() => {
        if (!this._alive || !this._visible) return
        charts.drawTrendChart('trend-chart', this, trend.points, {
          metric,
          previousPoints: trend.previousPoints,
        })
      }, 40)
    })
  },

  onTrendTab(e) {
    const days = parseInt(e.currentTarget.dataset.days, 10)
    if (!days || days === this.data._activeTabDays) return
    // Highlight immediately. Existing chart stays mounted while the latest request wins.
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
      if (!this._alive || !this._visible || seq !== this._trendSeq) return
      const trend = model.buildTrends(res.trends)
      const trendHash = trend ? [trend.points, trend.previousPoints || []].map(list => list.map(p => p.date + p.questions + p.accuracy).join('|')).join('::') : ''
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
            if (!this._alive || !this._visible) return
            charts.drawTrendChart('trend-chart', this, trend.points, { metric: this.data.trendMetric, previousPoints: trend.previousPoints })
          }, 80)
        }
      })
    } catch (e) {
      console.error('[dashboard] trend load failed', e)
      if (!this._alive || !this._visible || seq !== this._trendSeq) return
      // Keep old trend data visible, show inline error
      this.setData({ trendLoading: false, pendingTrendDays: null, _activeTabDays: this.data.trendDays, trendError: '趋势数据加载失败' })
    }
  },

  onRetryTrend() {
    this.setData({ trendError: null, trendLoading: true })
    this._loadTrendData(this.data.trendDays)
  },

  onToggleDeepAnalysis() {
    this.setData({ showDeepAnalysis: !this.data.showDeepAnalysis })
  },

  onAnalysisTab(e) {
    const tab = e.currentTarget.dataset.tab
    if (!tab || tab === this.data.analysisActiveTab) return
    this.setData({ analysisActiveTab: tab })
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
    if (!this._alive || !this._visible || this.data.yearlyLoading) return
    this.setData({ yearlyLoading: true, yearlyError: null })
    const seq = ++this._yearlySeq
    try {
      const res = await api.get('/stats/trends', { days: 365 })
      if (!this._alive || !this._visible || seq !== this._yearlySeq) return
      const weeks = this._buildHeatmapWeeks(res || [])
      this.setData({ showYearlyHeatmap: true, yearlyLoading: false, yearlyHeatmapWeeks: weeks })
    } catch (e) {
      console.error('[dashboard] yearly heatmap load failed', e)
      if (!this._alive || !this._visible || seq !== this._yearlySeq) return
      this.setData({ yearlyLoading: false, yearlyError: '热力图加载失败' })
      wx.showToast({ title: '热力图加载失败', icon: 'none' })
    }
  },

  _buildHeatmapWeeks(trends) {
    const byDate = {}
    ;(trends || []).forEach(t => { if (t && t.date) byDate[t.date] = t })
    const cells = []
    for (let i = 364; i >= 0; i--) {
      const date = getChinaDate(-i)
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
      const elapsed = Date.now() - parseServerUtc(this.data.llmAnalysisGeneratedAt)
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
    this.goTo('/subpackages/study/review-today/review-today', { refreshOnReturn: true })
  },

  goPractice() {
    this._forceRefreshOnNextShow = true
    this.goTo('/subpackages/study/practice/practice', { refreshOnReturn: true })
  },

  goWrongBook() {
    this.goTo('/subpackages/study/wrong-book/wrong-book')
  },

  goSubjectWrongBook(e) {
    const subjectId = e.currentTarget.dataset.subjectId
    if (subjectId == null || subjectId === '') return
    this.goTo('/subpackages/study/wrong-book/wrong-book?subject_id=' + encodeURIComponent(subjectId))
  },

  goTopicWrongBook(e) {
    const topic = e.currentTarget.dataset.topic
    let url = '/subpackages/study/wrong-book/wrong-book'
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
    const subjectId = e.currentTarget.dataset.subjectId
    let url = '/subpackages/study/wrong-book/wrong-book'
    const params = []
    if (topic) params.push('topic=' + encodeURIComponent(topic))
    if (subjectId != null && subjectId !== '') params.push('subject_id=' + encodeURIComponent(subjectId))
    if (params.length) url += '?' + params.join('&')
    this.goTo(url)
  },

  // ── Action Plan ──
  goActionPlan(e) {
    const type = e.currentTarget.dataset.type
    const topic = e.currentTarget.dataset.topic
    if (type === 'review') this.goReview()
    else if (type === 'wrong') {
      let url = '/subpackages/study/wrong-book/wrong-book'
      if (topic) url += '?topic=' + encodeURIComponent(topic)
      this.goTo(url)
    }
    else if (type === 'practice') this.goPractice()
    else this.goPractice()
  },
  onInsightCta() {
    const ctaType = this._insight && this._insight.cta_type
    if (ctaType === 'review') this.goReview()
    else if (ctaType === 'wrong' || ctaType === 'subject') this.goWrongBook()
    else this.goPractice()
  },

  onRetry() {
    this.loadDashboard({ mode: 'initial' })
  },
})
