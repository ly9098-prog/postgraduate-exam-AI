const api = require('../../utils/api')
const model = require('./dashboard.model')
const charts = require('./dashboard.charts')
const { getChinaDate, parseServerUtc } = require('../../utils/china-time')
const errorDiagnosis = require('./utils/error-diagnosis')
const { studyStrategy } = require('../../utils/storage')

const DASHBOARD_AI_HTTP_TIMEOUT_MS = 55000
const DASHBOARD_AI_SUCCESS_COOLDOWN_MS = 60000
const DASHBOARD_AI_FALLBACK_COOLDOWN_MS = 15000

function clampPct(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)))
}

function nullablePct(value) {
  if (value == null || !Number.isFinite(Number(value))) return null
  return clampPct(value)
}

function ratioPct(value) {
  if (value == null || !Number.isFinite(Number(value))) return 0
  const number = Number(value)
  return clampPct(Math.abs(number) <= 1 ? number * 100 : number)
}

function normalizeSubjectAnalysis(raw) {
  if (Array.isArray(raw)) return { items: raw }
  if (!raw || typeof raw !== 'object') return raw
  if (Array.isArray(raw.items)) return raw
  if (Array.isArray(raw.subject_stats)) return { ...raw, items: raw.subject_stats }
  return raw
}

function choiceBudgetItemsFromSubjects(subjects) {
  return subjects && Array.isArray(subjects.items) ? subjects.items : []
}

function buildChoiceBudgetWithFallback(subjects, fallbackStats) {
  const primaryItems = choiceBudgetItemsFromSubjects(subjects)
  const fallbackItems = Array.isArray(fallbackStats) ? fallbackStats : []
  // dashboard-v2 is authoritative for a subject once it has actual attempts and a
  // usable accuracy. Legacy subject_stats only fills a missing/zero placeholder, so
  // first-seen deduplication no longer lets stale fallback data mask primary rows.
  const fallbackByCode = new Map()
  fallbackItems.forEach((item) => {
    const code = studyStrategy.subjectCodeFromItem(item)
    if (code && !fallbackByCode.has(code)) fallbackByCode.set(code, item)
  })
  const primaryCodes = new Set(primaryItems.map(item => studyStrategy.subjectCodeFromItem(item)).filter(Boolean))
  const filledItems = primaryItems.slice()
  fallbackByCode.forEach((item, code) => {
    if (!primaryCodes.has(code)) filledItems.push(item)
  })
  return studyStrategy.buildChoiceLossBudget(filledItems)
}

function buildKnowledgeDiagnosisSnapshot(raw) {
  if (!raw || typeof raw !== 'object') return null
  const recommendations = Array.isArray(raw.recommendations) ? raw.recommendations : []
  const primaryRaw = raw.primary_recommendation || recommendations[0] || null
  const report = raw.report || {}
  const primary = primaryRaw ? {
    knowledgePointId: Number(primaryRaw.knowledge_point_id) || 0,
    knowledgePointName: String(primaryRaw.knowledge_point_name || ''),
    title: String(primaryRaw.title || primaryRaw.knowledge_point_name || '章节专项'),
    reason: String(primaryRaw.reason || ''),
    actionLabel: String(primaryRaw.action_label || '开始章节专项'),
    masteryText: nullablePct(primaryRaw.mastery_score) == null ? '待建立' : `${nullablePct(primaryRaw.mastery_score)}%`,
    coverageText: `${ratioPct(primaryRaw.coverage_ratio)}%`,
    weakCount: Math.max(0, Number(primaryRaw.weak_knowledge_points) || 0),
    trainableCount: Math.max(0, Number(primaryRaw.trainable_knowledge_points) || 0),
    routeParams: primaryRaw.route_params && typeof primaryRaw.route_params === 'object' ? primaryRaw.route_params : {},
  } : null
  const accuracy = report.accuracy == null ? null : ratioPct(report.accuracy)
  return {
    subjectId: Number(raw.subject_id) || 0,
    subjectName: String(raw.subject_name || ''),
    periodDays: Number(raw.period_days || report.period_days) || 30,
    primary,
    report: {
      sessionCount: Math.max(0, Number(report.session_count) || 0),
      questionCount: Math.max(0, Number(report.question_count) || 0),
      accuracyText: accuracy == null ? '--' : `${accuracy}%`,
      practicedChapterCount: Math.max(0, Number(report.practiced_chapter_count) || 0),
      servedKnowledgePointCount: Math.max(0, Number(report.served_knowledge_point_count) || 0),
      coverageText: `${ratioPct(report.current_coverage_ratio)}%`,
      weakCount: Math.max(0, Number(report.current_weak_knowledge_points) || 0),
    },
  }
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
    choiceLossBudget: studyStrategy.buildChoiceLossBudget([]),
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
    heroCardMode: 'summary',
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

    // 408-ERROR: recent error-cause diagnosis
    errorDiagnosisStats: null,
    errorDiagnosisLoading: false,
    errorDiagnosisSummary: '错因数据积累中',
    errorDiagnosisTopTypes: [],
    errorDiagnosisPrimary: null,
    errorDiagnosisPrimaryChange: null,
    errorDiagnosisChanges: [],
    errorDiagnosisTopKnowledge: null,

    // Knowledge hierarchy diagnosis (uses the existing learning-report page).
    knowledgeDiagnosisLoading: false,
    knowledgeDiagnosisError: '',
    knowledgeDiagnosis: null,
    knowledgeDiagnosisSubjectId: 0,
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
  _errorDiagnosisSeq: 0,
  _knowledgeDiagnosisSeq: 0,
  _knowledgeDiagnosisLoadedAt: 0,
  _chapterPracticeNavigationPending: false,
  _insightRetryTimer: null,
  _insightKickoffTimer: null,

  onLoad(options) {
    this._focusSubjectId = Math.max(0, Number(options && options.focus_subject_id) || 0)
    this._focusDiagnosisOnLoad = String((options && options.section) || '') === 'knowledge_diagnosis'
    this._diagnosisAutoScrolled = false
    this._chapterPracticeNavigationPending = false
  },

  goBack() {
    wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/home/home' }) })
  },

  onShow() {
    this._alive = true
    this._visible = true
    this._chapterPracticeNavigationPending = false

    var forceRefresh = this._forceRefreshOnNextShow
    this._forceRefreshOnNextShow = false

    if (!this.data.pageReady) {
      this.loadDashboard({ mode: 'initial' })
      return
    }

    if (forceRefresh) {
      this.loadDashboard({ mode: 'silent' })
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
    this._errorDiagnosisSeq++
    this._knowledgeDiagnosisSeq++
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
      knowledgeDiagnosisLoading: false,
    })
  },

  onUnload() {
    this._alive = false
    this._visible = false
    this._dashboardSeq++
    this._trendSeq++
    this._yearlySeq++
    this._insightSeq++
    this._errorDiagnosisSeq++
    this._knowledgeDiagnosisSeq++
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
          include_subjects: true,
        })
        if (!this._alive || !this._visible || seq !== this._dashboardSeq) return null

        // dashboard-v2 is the primary source. Only an actual contract gap warrants
        // the legacy endpoint; users who have practiced 1-3 subjects must not trigger
        // a compatibility request on every dashboard load.
        let choiceSubjectStats = []
        const subjectsResponse = res && res.subjects
        const totalQuestions = Math.max(
          0,
          Number(res && res.overview && res.overview.total_questions) || 0
        )
        const hasSubjectContract = Boolean(
          subjectsResponse && (
            (Array.isArray(subjectsResponse) && subjectsResponse.length) ||
            (!Array.isArray(subjectsResponse) && Array.isArray(subjectsResponse.items) && subjectsResponse.items.length)
          )
        )
        if (totalQuestions > 0 && !hasSubjectContract) {
          try {
            const legacyDashboard = await api.get('/stats/dashboard')
            if (!this._alive || !this._visible || seq !== this._dashboardSeq) return null
            choiceSubjectStats = legacyDashboard && Array.isArray(legacyDashboard.subject_stats)
              ? legacyDashboard.subject_stats
              : []
          } catch (fallbackError) {
            console.warn('[dashboard] choice loss budget fallback unavailable', fallbackError)
          }
        }

        this._lastLoadAt = Date.now()
        this._processDashboard(res, mode, choiceSubjectStats)
        this.loadErrorDiagnosisStats()
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

  async loadErrorDiagnosisStats() {
    if (!this._alive || !this._visible) return
    const seq = ++this._errorDiagnosisSeq
    this.setData({ errorDiagnosisLoading: true })
    try {
      const raw = await api.get('/wrong-questions/diagnosis/stats', {
        window_days: this.data.trendDays || 7,
      })
      if (!this._alive || !this._visible || seq !== this._errorDiagnosisSeq) return
      const byType = (raw.by_type || []).map(item => ({
        ...item,
        label: item.label || errorDiagnosis.labelOf(item.type),
        percentPct: Math.round(Number(item.percent || 0) * 100),
      }))
      const classified = byType.filter(item => item.type !== 'unknown' && Number(item.count || 0) > 0)
      const topTypes = classified.slice(0, 5)
      const top = topTypes[0]
      let summary = '近期暂无错题，继续保持'
      if (Number(raw.total_errors || 0) > 0 && top) {
        summary = `最近主要是“${top.label}”，占已记录错误的 ${top.percentPct}%`
      } else if (Number(raw.total_errors || 0) > 0) {
        summary = `近 ${raw.window_days || this.data.trendDays} 天有 ${raw.total_errors} 次错误待确认错因`
      }
      const changes = (raw.changes || [])
        .filter(item => item.type !== 'unknown' && Number(item.delta || 0) !== 0)
        .slice(0, 3)
        .map(item => ({
          ...item,
          label: item.label || errorDiagnosis.labelOf(item.type),
          deltaText: Number(item.delta || 0) > 0 ? `较上期 +${item.delta}` : `较上期 ${item.delta}`,
        }))
      const kp = (raw.by_knowledge_point || [])[0]
      const primaryChange = top ? changes.find(item => item.type === top.type) || changes[0] || null : changes[0] || null
      this.setData({
        errorDiagnosisStats: raw,
        errorDiagnosisLoading: false,
        errorDiagnosisSummary: summary,
        errorDiagnosisTopTypes: topTypes,
        errorDiagnosisPrimary: top || null,
        errorDiagnosisPrimaryChange: primaryChange,
        errorDiagnosisChanges: changes,
        errorDiagnosisTopKnowledge: kp ? {
          name: kp.name,
          count: kp.count,
          topLabel: kp.top_label || errorDiagnosis.labelOf(kp.top_type),
        } : null,
      })
    } catch (e) {
      if (!this._alive || !this._visible || seq !== this._errorDiagnosisSeq) return
      this.setData({ errorDiagnosisLoading: false })
    }
  },

  async loadKnowledgeDiagnosis(subjectId, options = {}) {
    const id = Math.max(0, Number(subjectId) || 0)
    if (!id || !this._alive || !this._visible) return null
    const force = Boolean(options && options.force)
    if (!force && this.data.knowledgeDiagnosisSubjectId === id && this.data.knowledgeDiagnosis && Date.now() - this._knowledgeDiagnosisLoadedAt < 30000) {
      return this.data.knowledgeDiagnosis
    }

    const seq = ++this._knowledgeDiagnosisSeq
    const keepCurrent = this.data.knowledgeDiagnosisSubjectId === id && this.data.knowledgeDiagnosis
    if (!keepCurrent) this.setData({ knowledgeDiagnosisLoading: true, knowledgeDiagnosisError: '', knowledgeDiagnosisSubjectId: id })
    try {
      const raw = await api.get('/study-hub/knowledge-diagnosis', { subject_id: id, days: 30 })
      if (!this._alive || !this._visible || seq !== this._knowledgeDiagnosisSeq) return null
      const snapshot = buildKnowledgeDiagnosisSnapshot(raw)
      this._knowledgeDiagnosisLoadedAt = Date.now()
      this.setData({
        knowledgeDiagnosisLoading: false,
        knowledgeDiagnosisError: '',
        knowledgeDiagnosis: snapshot,
        knowledgeDiagnosisSubjectId: id,
      }, () => {
        if (this._focusDiagnosisOnLoad && !this._diagnosisAutoScrolled && typeof wx.pageScrollTo === 'function') {
          this._diagnosisAutoScrolled = true
          const scroll = () => wx.pageScrollTo({ selector: '#knowledge-diagnosis-section', duration: 180 })
          if (typeof wx.nextTick === 'function') wx.nextTick(scroll)
          else setTimeout(scroll, 0)
        }
      })
      return snapshot
    } catch (e) {
      if (!this._alive || !this._visible || seq !== this._knowledgeDiagnosisSeq) return null
      console.warn('[dashboard] knowledge diagnosis load failed', e)
      if (!keepCurrent) this.setData({ knowledgeDiagnosisLoading: false, knowledgeDiagnosisError: '章节诊断暂不可用' })
      return null
    }
  },

  retryKnowledgeDiagnosis() {
    const id = this.data.knowledgeDiagnosisSubjectId || this._focusSubjectId || (this.data.subjects && this.data.subjects.focusItem && this.data.subjects.focusItem.subjectId)
    return this.loadKnowledgeDiagnosis(id, { force: true })
  },

  startKnowledgeDiagnosisPractice() {
    if (this._chapterPracticeNavigationPending) return
    const diagnosis = this.data.knowledgeDiagnosis
    const item = diagnosis && diagnosis.primary
    if (!item || !diagnosis.subjectId || !item.knowledgePointId) return
    const routeParams = item.routeParams || {}
    const count = Math.max(1, Math.min(50, Number(routeParams.count) || 10))
    const includeDescendants = Number(routeParams.include_descendants) === 1 || routeParams.include_descendants === true
    const returnTo = encodeURIComponent(`/pages/dashboard/dashboard?focus_subject_id=${diagnosis.subjectId}&section=knowledge_diagnosis`)
    const subjectName = encodeURIComponent(diagnosis.subjectName || '章节专项')
    const url = `/subpackages/study/practice/practice?subject_id=${diagnosis.subjectId}&subject_name=${subjectName}&mode=random&count=${count}&knowledge_point_id=${item.knowledgePointId}&include_descendants=${includeDescendants ? 1 : 0}&include_children=1&allow_repeat=1&autostart=1&source=knowledge_diagnosis&return_to=${returnTo}`
    this._chapterPracticeNavigationPending = true
    this._forceRefreshOnNextShow = true
    wx.navigateTo({
      url,
      fail: () => {
        this._chapterPracticeNavigationPending = false
        this._forceRefreshOnNextShow = false
        wx.showToast({ title: '专项练习打开失败，请重试', icon: 'none' })
      },
    })
  },

  openKnowledgeDiagnosisMap() {
    const diagnosis = this.data.knowledgeDiagnosis
    const subjectId = Number(diagnosis && diagnosis.subjectId) || Number(this.data.knowledgeDiagnosisSubjectId) || 0
    if (!subjectId) return
    this.goTo(`/subpackages/knowledge/knowledge-subject/index?subject_id=${subjectId}`)
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
      // Prefer fresh subject rows returned by dashboard-insights when present;
      // otherwise enrich the already-rendered dashboard subject rows.
      let nextSubjects = this.data.subjects
      const insightSubjectAnalysis = normalizeSubjectAnalysis(res && res.subjects)
      if (insightSubjectAnalysis && Array.isArray(insightSubjectAnalysis.items) && insightSubjectAnalysis.items.length) {
        nextSubjects = model.buildSubjects(insightSubjectAnalysis, enrichedMap)
      } else if (this.data.subjects && this.data.subjects.items) {
        nextSubjects = model.buildSubjects(
          { items: this.data.subjects.items, strongest: this.data.subjects.strongest, weakest: this.data.subjects.weakest, totalQuestions: this.data.subjects.totalQuestions },
          enrichedMap
        )
      }
      const currentChoiceBudget = this.data.choiceLossBudget || studyStrategy.buildChoiceLossBudget([])
      const insightChoiceBudget = buildChoiceBudgetWithFallback(nextSubjects, [])
      const nextChoiceLossBudget = insightChoiceBudget.coveredSubjects >= currentChoiceBudget.coveredSubjects
        ? insightChoiceBudget
        : currentChoiceBudget
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
      this.setData({ subjects: nextSubjects, choiceLossBudget: nextChoiceLossBudget, insights, ...deepState })
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

  _processDashboard(res, mode = 'initial', choiceSubjectStats = []) {
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
    let subjects = model.buildSubjects(normalizeSubjectAnalysis(res.subjects))
    // If dashboard-v2 did not expose subject analysis, keep the dashboard
    // useful by building the same subject view-model from legacy subject_stats.
    if ((!subjects || !subjects.items || !subjects.items.length) && choiceSubjectStats.length) {
      subjects = model.buildSubjects({ items: choiceSubjectStats })
    }
    const choiceLossBudget = buildChoiceBudgetWithFallback(subjects, choiceSubjectStats)
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
      choiceLossBudget,
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
      choiceLossBudget,
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

      const diagnosisSubjectId = this._focusSubjectId || (subjects && subjects.focusItem && subjects.focusItem.subjectId) || 0
      if (diagnosisSubjectId) {
        this.loadKnowledgeDiagnosis(diagnosisSubjectId, { force: mode !== 'initial' })
      }

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

    // 正常 AI 结果限制一分钟重复生成；本地降级结果允许更快重试模型。
    if (this.data.llmAnalysisGeneratedAt) {
      const generatedAt = parseServerUtc(this.data.llmAnalysisGeneratedAt)
      const elapsed = Number.isFinite(generatedAt) ? Date.now() - generatedAt : Infinity
      const isFallback = this.data.llmAnalysis && this.data.llmAnalysis.generated === false
      const cooldown = isFallback ? DASHBOARD_AI_FALLBACK_COOLDOWN_MS : DASHBOARD_AI_SUCCESS_COOLDOWN_MS
      if (elapsed >= 0 && elapsed < cooldown) {
        wx.showToast({
          title: isFallback ? '刚刚已生成数据诊断，请稍后重试 AI' : '刚刚已生成分析，可稍后再试',
          icon: 'none',
        })
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
      }, { timeout: DASHBOARD_AI_HTTP_TIMEOUT_MS })
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
      const message = e && typeof e.message === 'string' && e.message.trim()
        ? e.message.trim()
        : 'AI 分析生成失败，请稍后重试'
      if (this.data.llmAnalysis) {
        // A retry must not discard an already usable data diagnosis / previous
        // analysis merely because the provider is temporarily unavailable.
        this.setData({ llmAnalysisLoading: false, llmAnalysisError: null })
        wx.showToast({ title: 'AI 重试失败，已保留当前诊断', icon: 'none' })
      } else {
        this.setData({ llmAnalysisLoading: false, llmAnalysisError: message })
      }
    }
  },

  onRetryLlmAnalysis() {
    if (this.data.llmAnalysisLoading) return

    const isFallback = this.data.llmAnalysis && this.data.llmAnalysis.generated === false
    if (isFallback && this.data.llmAnalysisGeneratedAt) {
      const generatedAt = parseServerUtc(this.data.llmAnalysisGeneratedAt)
      const elapsed = Number.isFinite(generatedAt) ? Date.now() - generatedAt : Infinity
      if (elapsed >= 0 && elapsed < DASHBOARD_AI_FALLBACK_COOLDOWN_MS) {
        wx.showToast({ title: '刚刚已尝试 AI，请稍后再试', icon: 'none' })
        return
      }
    }

    this.setData({ llmAnalysisError: null, llmAnalysisLoading: true })
    this._doLlmAnalysis()
  },

  onClearLlmAnalysis() {
    this.setData({ llmAnalysis: null, llmAnalysisError: null, llmAnalysisGeneratedAt: null })
  },

  _showAppOptions(opts) {
    const dialog = this.selectComponent('#appDialog')
    if (!dialog || typeof dialog.showOptions !== 'function') return Promise.resolve(-1)
    return dialog.showOptions(opts || {})
  },

  async onLlmFeedback() {
    const types = ['内容有误', '建议不准确', '其他问题']
    const index = await this._showAppOptions({ title: '反馈这次分析', items: types })
    if (index < 0) return
    const feedbackType = types[index] || '其他问题'
    try {
      await api.post('/ai/feedback', { source: 'dashboard', feedback_type: feedbackType })
      wx.showToast({ title: '反馈已提交，感谢您的帮助', icon: 'success' })
    } catch (_) {
      wx.showToast({ title: '反馈提交失败，请稍后重试', icon: 'none' })
    }
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

  toggleHeroCard() {
    // Both reports remain mounted in the same CSS grid cell. A single state flip
    // is enough; avoiding timer-driven unmount/remount keeps page height stable.
    const nextMode = this.data.heroCardMode === 'budget' ? 'summary' : 'budget'
    this.setData({ heroCardMode: nextMode })
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
