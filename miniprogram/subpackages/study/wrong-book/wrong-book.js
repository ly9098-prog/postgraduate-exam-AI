const api = require('../../../utils/api')
const config = require('../../../config')
const { safeDecodeURIComponent } = require('../../../utils/route-params')
const { toPlainInlineMathText } = require('../utils/stem-render')
const storage = require('../../../utils/storage')
const aiCache = require('../utils/ai-diagnosis-cache')
const { getSubjectName, getSubjectShortName } = require('../../../utils/subject-meta')
const exportApi = require('../utils/export-capability')
const { parseServerUtc, getChinaDayRangeUtcMs, chinaCalendarDayDiff, formatChinaMonthDayCn } = require('../../../utils/china-time')

const AI_AUTO_SETTING_PREFIX = 'ai_wrong_book_auto_v1_'
const BATCH_CAPSULE_IDLE_MS = 5000
const AI_DIAGNOSIS_HTTP_TIMEOUT_MS = 55000

const ERROR_TYPES = [
  { value: '', label: '全部类型' },
  { value: 'concept_mistake', label: '概念错误' },
  { value: 'calculation', label: '计算错误' },
  { value: 'careless', label: '粗心' },
  { value: 'method', label: '方法错误' },
  { value: 'other', label: '其他' },
]

Page({
  data: {
    list: [],
    listTotal: 0,
    stats: { total: 0 },
    primaryStatCount: 0,
    masteredCount: 0,

    // 今日复习 Hero
    reviewOverviewAvailable: false,
    todayDueCount: 0,
    todayCompletedCount: 0,
    todayRemainingCount: 0,
    todayOverdueCount: 0,
    estimatedMinutes: 0,
    todayProgressPercent: 0,
    heroRemainingCount: 0,
    heroRingStyle: 'background: conic-gradient(from -90deg, rgba(255,255,255,0.14) 0deg 360deg);',

    // 新任务流与批量管理
    activeView: 'task',
    taskGroups: [],
    ungroupedCount: 0,
    highFrequencyCount: 0,
    batchMode: false,
    batchCapsuleVisible: true,
    selectedIds: [],
    selectedIdMap: {},
    selectedCount: 0,
    allVisibleSelected: false,
    batchSubmitting: false,
    batchMoreVisible: false,
    batchMasterUndoVisible: false,
    _batchMasterUndoCount: 0,
    selectionPulse: false,
    aiInsightText: '自动分析已关闭，点击生成获取 AI 洞察',
    autoAiInsightEnabled: false,
    aiAutoSwitchPulse: false,
    aiInsightExpanded: false,
    aiInsightHasDetails: false,
    aiInsightWeakPoints: [],
    aiInsightSuggestions: [],
    analysis: {
      sourceLabel: '待积累',
      weaknessTags: [],
      radarItems: [],
      subjectItems: [],
      summaryCards: [],
      actionPlan: [],
    },
    aiDiagnosis: null,
    aiDiagnosisLoading: false,
    aiDiagnosisRefreshing: false,
    aiDiagnosisCacheTimeLabel: '',
    aiDiagnosisCacheStale: false,
    aiDiagnosisError: false,
    page: 1,
    hasMore: false,
    loading: false,
    enableMathImage: false,

    // Export capability defaults to unavailable until the server explicitly
    // confirms that PDF export is enabled for the current account.
    exportAvailable: false,
    exportCapabilityChecked: false,
    exportUnavailableText: '当前导出功能不可用',

    // filters
    selectedSubjectId: null,
    selectedErrorType: '',
    selectedTopic: '',
    showFilter: false,
    filterCount: 0,

    subjects: [{ value: '', label: '全部' }],
    subjectsLoading: false,
    subjectsError: false,
    subjectsLoaded: false,
    errorTypes: ERROR_TYPES,
  },

  _updateFilterCount() {
    const count = (this.data.selectedSubjectId ? 1 : 0) + (this.data.selectedErrorType ? 1 : 0) + (this.data.selectedTopic ? 1 : 0)
    this.setData({ filterCount: count })
  },

  _beginFilterReload(patch) {
    // Invalidate both requests immediately. loadTaskFlow() is started only after
    // the new first page arrives, so without this guard an older task-flow
    // response can briefly overwrite the UI under the newly selected filter.
    this._listRequestSeq++
    this._taskFlowRequestSeq++
    this.setData(Object.assign({
      list: [],
      listTotal: 0,
      page: 1,
      hasMore: false,
      loading: true,
      taskGroups: [],
      ungroupedCount: 0,
      // Selections belong to the old filtered result set. Keeping them while
      // the list is empty lets users batch-operate invisible records.
      selectedIds: [],
      selectedIdMap: {},
      selectedCount: 0,
      allVisibleSelected: false,
      batchMoreVisible: false,
    }, patch || {}))
    this._updateFilterCount()
    this.loadList(true)
  },

  _ready: false,
  _alive: false,
  _aiDiagnosisPromise: null,
  _aiDiagnosisRequestId: 0,
  _aiDiagnosisCachedAt: 0,
  _aiStatsLoaded: false,
  _listRequestSeq: 0,
  _suppressQuestionTapUntil: 0,
  _selectionPulseTimer: null,
  _batchCapsuleIdleTimer: null,
  _batchMasterUndoIds: [],
  _batchMasterUndoTimer: null,
  _batchMasterUndoInFlight: false,
  _aiAutoSwitchTimer: null,
  _exportCapabilityRequestId: 0,
  _statsRequestSeq: 0,
  _reviewOverviewRequestSeq: 0,
  _subjectsRequestSeq: 0,
  _taskFlowRequestSeq: 0,
  _destroyed: false,

  onLoad(options) {
    this._destroyed = false
    this._statsRequestSeq = 0
    this._reviewOverviewRequestSeq = 0
    this._subjectsRequestSeq = 0
    this._taskFlowRequestSeq = 0
    this._batchMasterUndoInFlight = false
    this.setData({ enableMathImage: config.enableMathImage || false })
    // 从 dashboard 跳转携带 subject_id 或 topic 参数
    const subjectId = options && options.subject_id != null ? Number(options.subject_id) : null
    const topic = safeDecodeURIComponent(options && options.topic, '')
    if (subjectId && Number.isFinite(subjectId)) {
      this.setData({ selectedSubjectId: subjectId })
    }
    if (topic) {
      this.setData({ selectedTopic: topic })
    }
    this._updateFilterCount()
    this._checkExportCapability()

    // 自动分析偏好按当前用户保存在本机，默认关闭。
    this._restoreAiAutoSetting()
    // 尽早恢复缓存，使页面首次渲染时直接显示已有诊断。
    // 关闭自动分析不会清除既有结果，只是不再主动请求。
    this._restoreAiDiagnosisFromCache()
  },

  onReady() {
    this._ready = true
    this.loadSubjects()
    this._loadPage()
  },

  onShow() {
    this._alive = true
    if (this.data.batchMode) this._showBatchCapsuleAndRefreshTimer()
    if (!this._ready) return
    // 页面重新可见时先统一刷新数据，再根据本机开关决定是否自动生成 AI 洞察。
    Promise.all([
      this.loadStats(),
      this.loadList(true),
      this.loadReviewOverview(),
    ]).then(() => this._checkAiDiagnosis())
  },

  onHide() {
    this._alive = false
    this._clearBatchCapsuleIdleTimer()
  },

  onUnload() {
    this._alive = false
    this._destroyed = true
    this._exportCapabilityRequestId++
    this._statsRequestSeq++
    this._reviewOverviewRequestSeq++
    this._subjectsRequestSeq++
    this._taskFlowRequestSeq++
    this._listRequestSeq++
    this._aiDiagnosisRequestId++
    this._clearBatchCapsuleIdleTimer()
    if (this._selectionPulseTimer) {
      clearTimeout(this._selectionPulseTimer)
      this._selectionPulseTimer = null
    }
    if (this._aiAutoSwitchTimer) {
      clearTimeout(this._aiAutoSwitchTimer)
      this._aiAutoSwitchTimer = null
    }
    this._batchMasterUndoInFlight = false
    this._clearBatchMasterUndo(true)
  },

  async _checkExportCapability() {
    const requestId = ++this._exportCapabilityRequestId
    this.setData({
      exportAvailable: false,
      exportCapabilityChecked: false,
      exportUnavailableText: '当前导出功能不可用',
    })

    if (config.WRONG_BOOK_EXPORT_ENABLED !== true) {
      this.setData({
        exportCapabilityChecked: true,
        exportUnavailableText: '当前导出功能不可用',
      })
      return
    }

    try {
      const capability = await exportApi.getCapabilities()
      if (requestId !== this._exportCapabilityRequestId) return
      const available = !!(
        capability &&
        capability.export_enabled === true &&
        capability.pdf_enabled === true
      )
      this.setData({
        exportAvailable: available,
        exportCapabilityChecked: true,
        exportUnavailableText: available
          ? ''
          : exportApi.getExportCapabilityErrorMessage(null, capability),
      })
    } catch (error) {
      if (requestId !== this._exportCapabilityRequestId) return
      this.setData({
        exportAvailable: false,
        exportCapabilityChecked: true,
        exportUnavailableText: exportApi.getExportCapabilityErrorMessage(error),
      })
    }
  },

  // ════════════════════════════════════════════
  // Page loading
  // ════════════════════════════════════════════

  async _loadPage() {
    this.setData({ list: [], page: 1 })
    await Promise.all([
      this.loadStats(),
      this.loadList(true),
      this.loadReviewOverview(),
    ])
    if (this._destroyed) return
    // 首次加载完成后检查 AI 诊断
    await this._checkAiDiagnosis()
  },

  _getAiAutoSettingKey() {
    const userId = this._getUserId()
    return userId ? AI_AUTO_SETTING_PREFIX + String(userId) : ''
  },

  _getAiInsightIdleText(enabled) {
    return enabled
      ? '自动分析已开启，进入错题本时会生成最新洞察'
      : '自动分析已关闭，点击生成获取 AI 洞察'
  },

  _restoreAiAutoSetting() {
    const key = this._getAiAutoSettingKey()
    const enabled = key ? storage.get(key) === true : false
    this.setData({
      autoAiInsightEnabled: enabled,
      aiInsightText: this.data.aiDiagnosis
        ? this.data.aiInsightText
        : this._getAiInsightIdleText(enabled),
    })
  },

  toggleAiAutoAnalysis() {
    const enabled = !this.data.autoAiInsightEnabled
    const key = this._getAiAutoSettingKey()
    if (key) storage.set(key, enabled)

    if (this._aiAutoSwitchTimer) clearTimeout(this._aiAutoSwitchTimer)
    this.setData({
      autoAiInsightEnabled: enabled,
      aiAutoSwitchPulse: true,
      aiInsightText: this.data.aiDiagnosis
        ? this.data.aiInsightText
        : this._getAiInsightIdleText(enabled),
    })
    this._aiAutoSwitchTimer = setTimeout(() => {
      if (this._alive) this.setData({ aiAutoSwitchPulse: false })
      this._aiAutoSwitchTimer = null
    }, 420)

    if (!enabled) {
      // 关闭时停止接受尚未完成的自动请求结果；既有缓存仍保留展示。
      if (this.data.aiDiagnosisLoading || this.data.aiDiagnosisRefreshing) {
        this._aiDiagnosisRequestId++
        this.setData({ aiDiagnosisLoading: false, aiDiagnosisRefreshing: false, aiDiagnosisError: false })
      }
      wx.showToast({ title: '已切换为手动分析', icon: 'none' })
      return
    }

    wx.showToast({ title: '已开启自动分析', icon: 'none' })
    if (this._aiStatsLoaded && Number((this.data.stats || {}).total) > 0) {
      const startAutoAnalysis = () => {
        if (this._alive && this.data.autoAiInsightEnabled) {
          this.ensureAiDiagnosis({ background: true, refreshOnChange: true })
        }
      }
      if (this._aiDiagnosisPromise) this._aiDiagnosisPromise.finally(startAutoAnalysis)
      else startAutoAnalysis()
    }
  },

  _restoreAiDiagnosisFromCache() {
    var user = this._getUser()
    var userId = user && (user.id || user.user_id || user.openid || '')
    var cache = aiCache.restore(userId)
    if (cache.status !== 'miss' && this._hasAiDiagnosisContent(cache.data)) {
      this._aiDiagnosisCachedAt = cache.cachedAt
      const normalized = this._normalizeAiDiagnosis(cache.data)
      const detailState = this._buildAiInsightDetails(normalized)
      this.setData({
        aiDiagnosis: normalized,
        aiDiagnosisCacheTimeLabel: aiCache.formatCacheTime(cache.cachedAt),
        aiDiagnosisCacheStale: cache.status === 'stale',
        aiDiagnosisError: false,
        aiDiagnosisLoading: false,
        aiDiagnosisRefreshing: false,
        aiInsightText: this._oneLineInsight(cache.data.summary) || this.data.aiInsightText,
        ...detailState,
      })
    }
  },

  async loadStats() {
    const requestSeq = ++this._statsRequestSeq
    try {
      const stats = await api.get('/wrong-questions/stats', { product_scope: '408' })
      if (this._destroyed || requestSeq !== this._statsRequestSeq) return
      this._aiStatsLoaded = true
      const masteredCount = typeof stats.unmastered === 'number'
        ? Math.max(0, (stats.total || 0) - stats.unmastered)
        : this.data.list.filter(item => item._isMastered).length
      const primaryStatCount = typeof stats.unmastered === 'number' ? stats.unmastered : (stats.total || 0)
      const patch = {
        stats,
        primaryStatCount,
        masteredCount,
        highFrequencyCount: this._positiveNumber(
          stats.high_frequency_count,
          this.data.highFrequencyCount || 0
        ),
      }

      // 旧后端没有今日复习概览时，Hero 至少仍能展示“待复习错题”数量，
      // 但不会伪造完成率。
      if (!this.data.reviewOverviewAvailable) {
        patch.heroRemainingCount = primaryStatCount
        patch.todayProgressPercent = 0
        patch.heroRingStyle = this._buildHeroRingStyle(0)
      }

      this.setData(patch)

      // Rebuild analysis with fresh stats when no filter is active
      const hasFilter = this.data.selectedSubjectId || this.data.selectedErrorType || this.data.selectedTopic
      if (!hasFilter && this.data.list.length > 0) {
        const analysis = this._buildAnalysis(stats, this.data.list)
        this.setData({
          analysis,
          aiInsightText: this.data.aiDiagnosis
            ? this._oneLineInsight(this.data.aiDiagnosis.summary)
            : this._getAiInsightIdleText(this.data.autoAiInsightEnabled),
        })
      }
    } catch (e) {
      if (this._destroyed || requestSeq !== this._statsRequestSeq) return
      console.error('加载错题统计失败', e)
    }
  },

  async loadReviewOverview() {
    const requestSeq = ++this._reviewOverviewRequestSeq
    try {
      const overview = await api.get('/review/today/overview')
      if (this._destroyed || requestSeq !== this._reviewOverviewRequestSeq) return
      const due = this._positiveNumber(overview.today_due_count, 0)
      const completed = this._positiveNumber(overview.today_completed_count, 0)
      const remaining = this._positiveNumber(overview.today_remaining_count, Math.max(0, due - completed))
      const progress = due > 0 ? Math.round((completed / due) * 100) : 100

      this.setData({
        reviewOverviewAvailable: true,
        todayDueCount: due,
        todayCompletedCount: completed,
        todayRemainingCount: remaining,
        todayOverdueCount: this._positiveNumber(overview.today_overdue_count, 0),
        estimatedMinutes: this._positiveNumber(overview.estimated_minutes, Math.ceil(remaining * 0.5)),
        todayProgressPercent: Math.max(0, Math.min(100, progress)),
        heroRemainingCount: remaining,
        heroRingStyle: this._buildHeroRingStyle(progress),
      })
    } catch (e) {
      if (this._destroyed || requestSeq !== this._reviewOverviewRequestSeq) return
      // 兼容尚未提供 overview 接口的旧后端；页面其它能力继续可用。
      console.warn('今日复习概览暂不可用，已使用错题统计兜底', e)
      const fallback = this.data.primaryStatCount || 0
      this.setData({
        reviewOverviewAvailable: false,
        heroRemainingCount: fallback,
        todayProgressPercent: 0,
        heroRingStyle: this._buildHeroRingStyle(0),
      })
    }
  },

  _buildHeroRingStyle(percent) {
    const safe = Math.max(0, Math.min(100, Number(percent) || 0))
    const endDeg = Math.round(safe * 3.6)
    const splitDeg = Math.round(endDeg * 0.48)
    return `background: conic-gradient(from -90deg, #A9F16C 0deg ${splitDeg}deg, #32D276 ${splitDeg}deg ${endDeg}deg, rgba(255,255,255,0.14) ${endDeg}deg 360deg);`
  },

  async loadList(reset = false) {
    const page = reset ? 1 : this.data.page
    const seq = ++this._listRequestSeq
    this.setData({ loading: true })

    try {
      const params = { page, page_size: 20, product_scope: '408' }
      if (this.data.selectedSubjectId) params.subject_id = this.data.selectedSubjectId
      if (this.data.selectedErrorType) params.error_type = this.data.selectedErrorType
      if (this.data.selectedTopic) params.topic = this.data.selectedTopic

      const data = await api.get('/wrong-questions', params)

      // Stale response guard
      if (seq !== this._listRequestSeq || !this._alive) return

      const items = (data.items || []).map(item => this._decorateItem(item))
      const nextList = reset ? items : [...this.data.list, ...items]

      // When filter is active, build analysis from current list only (not global stats)
      const hasFilter = this.data.selectedSubjectId || this.data.selectedErrorType || this.data.selectedTopic
      const statsForAnalysis = hasFilter ? {} : (this.data.stats || {})
      if (seq !== this._listRequestSeq || !this._alive) return
      const analysis = this._buildAnalysis(statsForAnalysis, nextList)
      const taskVm = this._buildTaskGroups(nextList)
      const statsHighFrequency = Number((this.data.stats || {}).high_frequency_count)
      const highFrequencyCount = Number.isFinite(statsHighFrequency)
        ? Math.max(0, Math.round(statsHighFrequency))
        : nextList.filter(item => !item._isMastered && item._wrongCount >= 3).length

      this.setData({
        list: nextList,
        listTotal: Math.max(0, Number(data.total) || 0),
        analysis,
        taskGroups: taskVm.groups,
        ungroupedCount: taskVm.ungroupedCount,
        highFrequencyCount,
        aiInsightText: this.data.aiDiagnosis
          ? this._oneLineInsight(this.data.aiDiagnosis.summary)
          : this._getAiInsightIdleText(this.data.autoAiInsightEnabled),
        hasMore: page < data.total_pages,
        page: reset ? 2 : page + 1,
        loading: false,
      })
      this._syncSelectionState()
      if (reset) this.loadTaskFlow()
    } catch (e) {
      console.error('加载错题列表失败', e)
      if (seq === this._listRequestSeq && this._alive) {
        this.setData({ loading: false })
      }
    }
  },

  async loadTaskFlow() {
    const requestSeq = ++this._taskFlowRequestSeq
    const params = { preview_size: 3, product_scope: '408' }
    if (this.data.selectedSubjectId) params.subject_id = this.data.selectedSubjectId
    if (this.data.selectedErrorType) params.error_type = this.data.selectedErrorType
    if (this.data.selectedTopic) params.topic = this.data.selectedTopic

    try {
      const data = await api.get('/wrong-questions/task-flow', params)
      if (this._destroyed || !this._alive || requestSeq !== this._taskFlowRequestSeq) return

      const meta = {
        today_due: { desc: '基于复习计划，今天最值得先做的题', icon: '今', tone: 'lime' },
        high_frequency: { desc: '重复出错次数较多，建议集中攻克', icon: '频', tone: 'orange' },
        recent_added: { desc: '近 14 天新加入错题本的题目', icon: '新', tone: 'blue' },
        to_consolidate: { desc: '尚未到复习日，但仍未完全掌握', icon: '固', tone: 'neutral' },
        mastered: { desc: '已达到掌握标准，不再进入正常复习；再次答错会重新加入', icon: '✓', tone: 'green' },
      }
      const groups = (data.groups || []).map(group => {
        const cfg = meta[group.key] || { desc: '', icon: '·', tone: 'neutral' }
        return {
          key: group.key,
          title: group.title || '',
          total: Math.max(0, Number(group.total) || 0),
          items: (group.items || []).map(item => this._decorateItem(item)),
          desc: cfg.desc,
          icon: cfg.icon,
          tone: cfg.tone,
        }
      }).filter(group => group.total > 0 || group.items.length > 0)

      const summary = data.summary || {}
      const totalCount = Math.max(0, Number(summary.total_count) || 0)
      const previewCount = groups.reduce((sum, group) => sum + group.items.length, 0)
      const hasFilter = !!(this.data.selectedSubjectId || this.data.selectedErrorType || this.data.selectedTopic)
      const globalHighFrequency = Number((this.data.stats || {}).high_frequency_count)
      const highFrequencyCount = Number.isFinite(globalHighFrequency)
        ? Math.max(0, Math.round(globalHighFrequency))
        : (!hasFilter
            ? Math.max(0, Number(summary.high_frequency_count) || 0)
            : this._positiveNumber(this.data.highFrequencyCount, 0))
      this.setData({
        taskGroups: groups,
        ungroupedCount: Math.max(0, totalCount - previewCount),
        // The overview card is intentionally global (stats/masteredCount are
        // also global); filters only affect the list/task-flow below it.
        highFrequencyCount,
      })
      this._syncSelectionState()
    } catch (e) {
      if (this._destroyed || requestSeq !== this._taskFlowRequestSeq) return
      // The paginated list remains a functional fallback.  Do not blank the
      // task view merely because the aggregate task-flow endpoint is transiently
      // unavailable.
      console.warn('加载错题任务流失败，保留当前列表分组兜底', e)
    }
  },

  async loadSubjects() {
    if (this.data.subjectsLoading) return
    const requestSeq = ++this._subjectsRequestSeq
    this.setData({ subjectsLoading: true, subjectsError: false })
    try {
      const raw = await api.get('/practice/subjects')
      if (this._destroyed || requestSeq !== this._subjectsRequestSeq) return
      const subjects = this._flattenSubjectOptions(raw)
      this.setData({
        subjects: [{ value: '', label: '全部' }, ...subjects],
        subjectsLoading: false,
        subjectsError: false,
        subjectsLoaded: true,
      })
    } catch (e) {
      if (this._destroyed || requestSeq !== this._subjectsRequestSeq) return
      console.error('加载学科筛选失败', e)
      this.setData({
        subjects: [{ value: '', label: '全部' }],
        subjectsLoading: false,
        subjectsError: true,
        subjectsLoaded: false,
      })
    }
  },

  _flattenSubjectOptions(raw) {
    const source = Array.isArray(raw)
      ? raw
      : (raw && Array.isArray(raw.items) ? raw.items : [])
    const result = []
    const seen = new Set()

    const visit = (node) => {
      if (!node || node.is_active === false) return
      const value = node.subject_id != null
        ? node.subject_id
        : (node.id != null ? node.id : null)
      const label = node.subject_name != null
        ? node.subject_name
        : (node.display_name != null ? node.display_name : (node.name != null ? node.name : null))
      if (value != null && label) {
        const key = String(value)
        if (!seen.has(key)) {
          seen.add(key)
          result.push({ value: Number(value), label: String(label) })
        }
      }
      if (Array.isArray(node.children)) node.children.forEach(visit)
    }

    source.forEach(visit)
    return result
  },

  goBack() {
    wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/home/home' }) })
  },

  toggleFilter() {
    if (!this.data.subjectsLoaded && !this.data.subjectsLoading) this.loadSubjects()
    this.setData({ showFilter: !this.data.showFilter })
  },

  selectSubject(e) {
    const val = e.currentTarget.dataset.value
    const subjectId = (val === '' || val === null || val === undefined) ? null : Number(val)
    this._beginFilterReload({ selectedSubjectId: subjectId })
  },

  selectErrorType(e) {
    const val = e.currentTarget.dataset.value
    this._beginFilterReload({ selectedErrorType: val })
  },

  clearTopic() {
    this._beginFilterReload({ selectedTopic: '' })
  },

  loadMore() {
    if (this.data.loading || !this.data.hasMore) return
    this.loadList()
  },

  resetFilters() {
    this._beginFilterReload({
      selectedSubjectId: null,
      selectedErrorType: '',
      selectedTopic: '',
      filterCount: 0,
    })
  },

  switchView(e) {
    const view = e.currentTarget.dataset.view === 'all' ? 'all' : 'task'
    this.setData({ activeView: view })
    this._syncSelectionState()
  },

  openAllQuestions() {
    this.setData({ activeView: 'all' })
    this._syncSelectionState()
  },

  startTodayReview() {
    if (this.data.heroRemainingCount <= 0) {
      wx.showToast({ title: '今日复习已经完成', icon: 'none' })
      return
    }
    wx.navigateTo({ url: '/subpackages/study/review-today/review-today?autostart=1' })
  },

  toggleBatchMode() {
    const next = !this.data.batchMode
    if (!next) this._clearBatchCapsuleIdleTimer()
    this.setData({
      batchMode: next,
      batchCapsuleVisible: true,
      batchMoreVisible: false,
      showFilter: next ? false : this.data.showFilter,
      selectedIds: [],
      selectedIdMap: {},
      selectedCount: 0,
      allVisibleSelected: false,
      selectionPulse: false,
    }, () => {
      if (next) this._showBatchCapsuleAndRefreshTimer()
    })
  },

  onPageInteraction() {
    this._showBatchCapsuleAndRefreshTimer()
  },

  onPageScroll() {
    this._showBatchCapsuleAndRefreshTimer()
  },

  _clearBatchCapsuleIdleTimer() {
    if (!this._batchCapsuleIdleTimer) return
    clearTimeout(this._batchCapsuleIdleTimer)
    this._batchCapsuleIdleTimer = null
  },

  _scheduleBatchCapsuleAutoHide() {
    this._clearBatchCapsuleIdleTimer()
    if (!this._alive || !this.data.batchMode) return
    this._batchCapsuleIdleTimer = setTimeout(() => {
      this._batchCapsuleIdleTimer = null
      if (!this._alive || !this.data.batchMode || !this.data.batchCapsuleVisible) return
      this.setData({ batchCapsuleVisible: false })
    }, BATCH_CAPSULE_IDLE_MS)
  },

  _showBatchCapsuleAndRefreshTimer() {
    if (!this.data.batchMode) return
    if (this.data.batchCapsuleVisible) {
      this._scheduleBatchCapsuleAutoHide()
      return
    }
    this.setData({ batchCapsuleVisible: true }, () => {
      this._scheduleBatchCapsuleAutoHide()
    })
  },

  onQuestionTap(e) {
    if (Date.now() < this._suppressQuestionTapUntil) return
    const id = e.currentTarget.dataset.id
    if (this.data.batchMode) {
      this._toggleQuestionSelection(id)
      return
    }
    this._navigateToDetail(id)
  },

  onSelectControlTap(e) {
    if (Date.now() < this._suppressQuestionTapUntil) return
    const id = e.currentTarget.dataset.id
    if (!this.data.batchMode) {
      this.setData({ batchMode: true, batchCapsuleVisible: true, showFilter: false }, () => {
        this._showBatchCapsuleAndRefreshTimer()
      })
    }
    this._toggleQuestionSelection(id)
  },

  onQuestionLongPress(e) {
    const id = e.currentTarget.dataset.id
    // 微信长按结束后可能继续派发 tap，短暂屏蔽，避免刚选中又被取消。
    this._suppressQuestionTapUntil = Date.now() + 700
    if (!this.data.batchMode) {
      this.setData({ batchMode: true, batchCapsuleVisible: true, showFilter: false }, () => {
        this._showBatchCapsuleAndRefreshTimer()
      })
    }
    try {
      wx.vibrateShort({ type: 'light' })
    } catch (_e) {}
    this._toggleQuestionSelection(id)
  },

  _navigateToDetail(id) {
    const ids = this.data.activeView === 'task'
      ? this._getVisibleIds()
      : (this.data.list || []).map(item => item.id)
    if (!ids.some(itemId => String(itemId) === String(id))) ids.unshift(id)
    const idx = ids.findIndex(itemId => String(itemId) === String(id))
    try {
      wx.setStorageSync('wrong_detail_nav', { ids, ts: Date.now() })
    } catch (e) {
      console.warn('保存错题详情导航上下文失败', e)
    }
    wx.navigateTo({ url: `/subpackages/study/wrong-detail/wrong-detail?id=${encodeURIComponent(id)}&idx=${Math.max(0, idx)}&source=wrong-book` })
  },

  _toggleQuestionSelection(id) {
    const key = String(id)
    const map = { ...(this.data.selectedIdMap || {}) }
    const wasSelected = !!map[key]
    if (wasSelected) delete map[key]
    else map[key] = true
    const ids = Object.keys(map)
    this.setData({
      selectedIdMap: map,
      selectedIds: ids,
      selectedCount: ids.length,
    })
    this._syncSelectionState()
    if (!wasSelected) this._pulseSelectionBadge()
  },

  _pulseSelectionBadge() {
    if (this._selectionPulseTimer) clearTimeout(this._selectionPulseTimer)
    this.setData({ selectionPulse: false })
    setTimeout(() => {
      if (!this._alive) return
      this.setData({ selectionPulse: true })
      this._selectionPulseTimer = setTimeout(() => {
        if (this._alive) this.setData({ selectionPulse: false })
      }, 260)
    }, 16)
  },

  _getVisibleIds() {
    if (this.data.activeView === 'all') {
      return (this.data.list || []).map(item => String(item.id))
    }
    const ids = []
    ;(this.data.taskGroups || []).forEach(group => {
      ;(group.items || []).forEach(item => ids.push(String(item.id)))
    })
    return Array.from(new Set(ids))
  },

  toggleSelectAll() {
    const visibleIds = this._getVisibleIds()
    if (!visibleIds.length) return
    const current = this.data.selectedIdMap || {}
    const allSelected = visibleIds.every(id => !!current[id])
    const next = { ...current }
    visibleIds.forEach(id => {
      if (allSelected) delete next[id]
      else next[id] = true
    })
    const ids = Object.keys(next)
    this.setData({
      selectedIdMap: next,
      selectedIds: ids,
      selectedCount: ids.length,
      allVisibleSelected: !allSelected,
    })
    if (!allSelected) this._pulseSelectionBadge()
  },

  _syncSelectionState() {
    // Task-flow previews are aggregated by the backend and may contain records
    // outside the first paginated list page. Keep them selectable as well.
    const validIds = new Set((this.data.list || []).map(item => String(item.id)))
    ;(this.data.taskGroups || []).forEach(group => {
      ;(group.items || []).forEach(item => validIds.add(String(item.id)))
    })
    const nextMap = {}
    Object.keys(this.data.selectedIdMap || {}).forEach(id => {
      if (validIds.has(String(id))) nextMap[String(id)] = true
    })
    const selectedIds = Object.keys(nextMap)
    const visibleIds = this._getVisibleIds()
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => !!nextMap[id])
    this.setData({
      selectedIdMap: nextMap,
      selectedIds,
      selectedCount: selectedIds.length,
      allVisibleSelected,
    })
  },

  openBatchMore() {
    if (!this.data.selectedCount) {
      wx.showToast({ title: '请先选择错题', icon: 'none' })
      return
    }
    wx.showActionSheet({
      alertText: `将作用于已选择的 ${this.data.selectedCount} 道错题`,
      itemList: ['移出错题本', '永久删除'],
      success: ({ tapIndex }) => {
        const action = tapIndex === 0 ? 'remove_from_book' : 'delete'
        this.onBatchAction({ currentTarget: { dataset: { action } } })
      },
    })
  },

  closeBatchMore() {},

  noop() {},

  async onBatchAction(e) {
    if (this.data.batchSubmitting || this._batchMasterUndoInFlight) return
    const action = e.currentTarget.dataset.action
    if (this.data.batchMoreVisible) this.setData({ batchMoreVisible: false })
    const ids = (this.data.selectedIds || []).map(id => {
      const n = Number(id)
      return Number.isFinite(n) && String(n) === String(id) ? n : id
    })
    if (!ids.length) {
      wx.showToast({ title: '请先选择错题', icon: 'none' })
      return
    }

    const labels = {
      add_to_review: '加入今日复习',
      mark_mastered: '标记为已掌握',
      remove_from_book: '移出错题本',
      delete: '永久删除',
    }
    const dangerous = action === 'delete' || action === 'remove_from_book'
    if (dangerous) {
      const confirmed = await this._confirmBatchAction(
        labels[action],
        action === 'delete'
          ? `将永久删除已选择的 ${ids.length} 道错题记录，是否继续？`
          : `将把已选择的 ${ids.length} 道题移出错题本，是否继续？`
      )
      if (!confirmed) return
    }

    this.setData({ batchSubmitting: true })
    wx.showLoading({ title: '正在处理', mask: true })
    try {
      const result = await api.post('/wrong-questions/batch', { action, ids })
      wx.hideLoading()
      if (this._destroyed) return

      if (action === 'mark_mastered') {
        // Undo must target only rows that THIS request actually changed. A mixed
        // selection can contain questions that were already mastered. Sending
        // all selected ids to unmark_mastered would incorrectly unmaster those
        // pre-existing rows when the user taps Undo.
        const hasSkippedIds = Array.isArray(result && result.skipped_ids)
        const skippedSet = new Set(hasSkippedIds ? result.skipped_ids.map(id => String(id)) : [])
        const reportedUpdatedCount = result && result.updated_count != null ? Number(result.updated_count) : ids.length
        const undoIds = hasSkippedIds
          ? ids.filter(id => !skippedSet.has(String(id)))
          : (reportedUpdatedCount === ids.length ? ids.slice() : [])
        const updatedCount = Math.max(0, Number.isFinite(reportedUpdatedCount) ? reportedUpdatedCount : undoIds.length)

        this._clearBatchMasterUndo()
        this._batchMasterUndoIds = undoIds.slice()
        const canUndo = undoIds.length > 0
        this.setData({
          batchSubmitting: false,
          batchMasterUndoVisible: canUndo,
          _batchMasterUndoCount: canUndo ? undoIds.length : 0,
          selectionPulse: false,
          selectedIds: [],
          selectedIdMap: {},
          selectedCount: 0,
          allVisibleSelected: false,
        })
        if (canUndo) {
          this._batchMasterUndoTimer = setTimeout(() => {
            this._clearBatchMasterUndo()
          }, 5000)
        } else {
          wx.showToast({
            title: updatedCount > 0 ? `已标记掌握 ${updatedCount} 项` : '所选题目状态未变化',
            icon: 'none',
          })
        }
        await this._reloadAfterBatch()
        return
      }

      wx.showToast({
        title: `${labels[action]}成功 ${result.updated_count != null ? result.updated_count : ids.length} 项`,
        icon: 'success',
      })
      this._clearBatchCapsuleIdleTimer()
      this.setData({
        batchSubmitting: false,
        batchMode: false,
        batchCapsuleVisible: true,
        batchMoreVisible: false,
        selectionPulse: false,
        selectedIds: [],
        selectedIdMap: {},
        selectedCount: 0,
        allVisibleSelected: false,
      })
      await this._reloadAfterBatch()
    } catch (err) {
      wx.hideLoading()
      if (this._destroyed) return
      this.setData({ batchSubmitting: false })
      const isMissingEndpoint = err && (err.statusCode === 404 || err.statusCode === 405)
      if (isMissingEndpoint) {
        const modal = this.selectComponent('#actionConfirm')
        if (modal) {
          await modal.show({
            scenario: 'info',
            eyebrow: 'NOTICE',
            title: '批量接口尚未接入',
            message: '当前页面交互已经完成，但后端暂不支持该批量操作。',
            confirmText: '知道了',
            hideCancel: true,
          })
        } else {
          wx.showToast({ title: '批量接口尚未接入', icon: 'none' })
        }
      } else {
        wx.showToast({ title: (err && err.message) || '批量操作失败', icon: 'none' })
      }
    }
  },

  _reloadAfterBatch() {
    if (this._destroyed) return Promise.resolve([])
    return Promise.all([this.loadStats(), this.loadList(true), this.loadReviewOverview()])
  },

  onExportSelected() {
    if (!this.data.exportAvailable) {
      wx.showToast({
        title: this.data.exportUnavailableText || '当前导出功能不可用',
        icon: 'none',
      })
      return
    }

    const ids = (this.data.selectedIds || []).map(id => {
      const n = Number(id)
      return Number.isFinite(n) ? n : null
    }).filter(Boolean)

    if (!ids.length) {
      wx.showToast({ title: '请先选择错题', icon: 'none' })
      return
    }

    if (ids.length > 100) {
      wx.showToast({ title: '单次最多选择 100 道，请调整筛选条件后重试。', icon: 'none' })
      return
    }

    // Pass selected IDs via global data (not URL params — too many for URL).
    const app = getApp()
    const gd = app.getGlobalData()
    gd.exportSelectedIds = ids

    wx.navigateTo({ url: '/subpackages/export/export-config/export-config' })
  },

  onViewExportRecords() {
    wx.navigateTo({ url: '/subpackages/export/export-records/export-records' })
  },

  undoBatchMaster() {
    const ids = (this._batchMasterUndoIds || []).slice()
    if (!ids.length || this._batchMasterUndoInFlight) return
    this._batchMasterUndoInFlight = true
    // Stop the expiry timer while the request is in flight, but keep the ids and
    // toast visible. Clearing first makes a transient network failure impossible
    // to retry because the client no longer knows which records to unmaster.
    if (this._batchMasterUndoTimer) {
      clearTimeout(this._batchMasterUndoTimer)
      this._batchMasterUndoTimer = null
    }
    wx.showLoading({ title: '正在撤销', mask: true })
    api.post('/wrong-questions/batch', { action: 'unmark_mastered', ids }).then(result => {
      wx.hideLoading()
      this._batchMasterUndoInFlight = false
      if (this._destroyed) return
      this._clearBatchMasterUndo()
      wx.showToast({
        title: `已撤销掌握 ${result.updated_count != null ? result.updated_count : ids.length} 项`,
        icon: 'success',
      })
      this._reloadAfterBatch()
    }).catch(err => {
      wx.hideLoading()
      this._batchMasterUndoInFlight = false
      if (this._destroyed) return
      wx.showToast({ title: (err && err.message) || '撤销失败，可再次尝试', icon: 'none' })
      // Give the user another full undo window after a transient failure.
      this._batchMasterUndoTimer = setTimeout(() => {
        this._clearBatchMasterUndo()
      }, 5000)
    })
  },

  _clearBatchMasterUndo(skipSetData) {
    if (this._batchMasterUndoTimer) {
      clearTimeout(this._batchMasterUndoTimer)
      this._batchMasterUndoTimer = null
    }
    this._batchMasterUndoIds = []
    if (!skipSetData && !this._destroyed) {
      this.setData({ batchMasterUndoVisible: false, _batchMasterUndoCount: 0 })
    }
  },

  _confirmBatchAction(title, content) {
    const modal = this.selectComponent('#actionConfirm')
    if (!modal) return Promise.resolve(false)
    return modal.show({
      scenario: 'danger',
      eyebrow: 'IRREVERSIBLE',
      title,
      message: content,
      confirmText: '继续操作',
      cancelText: '取消',
    })
  },

  goDetail(e) {
    this._navigateToDetail(e.currentTarget.dataset.id)
  },

  // ════════════════════════════════════════════
  // AI 诊断缓存管理
  // ════════════════════════════════════════════

  _getUser() {
    try { return storage.get(storage.KEYS.USER) } catch (_) { return null }
  },

  _getUserId() {
    var user = this._getUser()
    return user && (user.id || user.user_id || user.openid || '')
  },

  /**
   * 标准化 AI 诊断数据
   */
  _normalizeAiDiagnosis(raw) {
    if (!raw) return null
    var copy = JSON.parse(JSON.stringify(raw))
    for (var listKey of ['weak_points', 'strong_points', 'learning_suggestions']) {
      if (!Array.isArray(copy[listKey])) copy[listKey] = []
    }
    for (var key of ['weak_points', 'strong_points']) {
      copy[key] = copy[key].map(function(item) {
        if (!item || typeof item !== 'object') return null
        var acc = item.accuracy
        if (typeof acc !== 'number') acc = 0
        if (acc > 1) acc = Math.min(acc, 100)
        var pct = acc <= 1 ? Math.round(acc * 100) : Math.round(acc)
        pct = Math.max(0, Math.min(100, pct))
        return {
          knowledge_point: String(item.knowledge_point || ''),
          accuracy: acc,
          _accuracyPercent: pct,
          suggestion: String(item.suggestion || ''),
        }
      }).filter(function(item) { return item && item.knowledge_point })
    }
    copy.learning_suggestions = copy.learning_suggestions.filter(function(s) { return s && String(s).trim() })
    return copy
  },

  /**
   * 构建数据指纹
   */
  _buildAiDiagnosisSourceSignature() {
    var stats = this.data.stats || {}
    var list = this.data.list || []
    var firstItem = list[0] || {}
    return aiCache.buildSignature(stats, list)
  },

  /**
   * 检查 AI 诊断状态，决定是否需要请求
   * 安全：不因为 stats 未加载就清除已有诊断
   */
  async _checkAiDiagnosis() {
    if (this._destroyed) return null
    var stats = this.data.stats || {}
    var total = stats.total
    // stats 尚未加载成功时，不基于初始值 { total: 0 } 做任何判断
    if (!this._aiStatsLoaded) {
      return this.data.aiDiagnosis || null
    }
    // 明确知道 total = 0
    if (total === 0) {
      if (this.data.aiDiagnosis) {
        var uid = this._getUserId()
        aiCache.clear(uid)
        this.setData({
          aiDiagnosis: null,
          aiDiagnosisLoading: false,
          aiDiagnosisRefreshing: false,
          aiDiagnosisCacheTimeLabel: '',
          aiDiagnosisCacheStale: false,
          aiDiagnosisError: false,
          aiInsightExpanded: false,
          aiInsightHasDetails: false,
          aiInsightWeakPoints: [],
          aiInsightSuggestions: [],
        })
      } else {
        // 无诊断 + total=0 → 清除 _loadPage 预置的 loading 状态，避免骨架屏卡死
        this.setData({ aiDiagnosisLoading: false })
      }
      return null
    }

    if (!this.data.autoAiInsightEnabled) {
      return this.data.aiDiagnosis || null
    }

    return this.ensureAiDiagnosis({ background: true, refreshOnChange: true })
  },

  _hasAiDiagnosisContent(value) {
    if (!value || typeof value !== 'object') return false
    const normalized = this._normalizeAiDiagnosis(value)
    return !!(
      (normalized.summary && String(normalized.summary).trim()) ||
      (normalized.weak_points && normalized.weak_points.length) ||
      (normalized.strong_points && normalized.strong_points.length) ||
      (normalized.learning_suggestions && normalized.learning_suggestions.length)
    )
  },

  _isAiDiagnosisPending(value) {
    if (!value || typeof value !== 'object') return false
    const status = String(value.status || value.state || value.generation_status || '').toLowerCase()
    const message = String(value.message || value.detail || value.summary || '').toLowerCase()
    const pendingText = /正在生成|生成中|处理中|排队中|generating|processing|queued/.test(message)
    return ['pending', 'processing', 'generating', 'queued', 'running'].includes(status) || value.generating === true || pendingText
  },

  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
  },

  async _pollAiDiagnosis(initial, requestId) {
    let current = initial
    for (let attempt = 0; attempt < 4 && this._isAiDiagnosisPending(current); attempt++) {
      await this._delay(1200 + attempt * 350)
      if (requestId !== this._aiDiagnosisRequestId || !this._alive) return null
      current = await api.get('/stats/ai-diagnosis', {}, { timeout: AI_DIAGNOSIS_HTTP_TIMEOUT_MS })
    }
    return current
  },

  /**
   * 统一 AI 诊断入口
   * @param {object} options
   *   force:     true = 忽略缓存和指纹，强制请求（手动刷新）
   *   background: true = 后台刷新，失败时静默
   *   refreshOnChange: true = 数据指纹变化时立即刷新，不受本地最短间隔限制
   */
  async ensureAiDiagnosis(options) {
    options = options || {}

    // 无错题 → 不请求（仅在 stats 已明确加载时）
    if (this._aiStatsLoaded) {
      var total = (this.data.stats || {}).total
      if (total === 0) return null
    }

    // 已有请求正在进行 → 复用
    if (this._aiDiagnosisPromise) return this._aiDiagnosisPromise

    // 强制刷新（手动）→ 直接请求
    if (options.force) {
      return this._requestAiDiagnosis({ force: true })
    }

    // 检查缓存状态
    var hasData = !!this.data.aiDiagnosis

    if (hasData && !options.background) {
      // 已有诊断，非后台 → 直接使用，不请求
      return this.data.aiDiagnosis
    }

    // 后台刷新场景：检查 TTL 和指纹
    var needRefresh = false
    var sourceChanged = false
    if (!hasData) {
      needRefresh = true
    } else {
      var cachedAt = this._aiDiagnosisCachedAt
      // fallback 结果使用更短 TTL；即使页面一直停留也会按实时钟判断过期。
      var isStale = this.data.aiDiagnosisCacheStale || aiCache.isExpired(cachedAt, this.data.aiDiagnosis)
      // 过期 → 刷新
      if (isStale) {
        needRefresh = true
      } else {
        // 检查指纹变化
        var currentSig = this._buildAiDiagnosisSourceSignature()
        // 从缓存读取上一次指纹
        var uid = this._getUserId()
        var cache = aiCache.restore(uid)
        if (cache.signature && cache.signature !== currentSig && (options.refreshOnChange || aiCache.canRefresh(cachedAt))) {
          needRefresh = true
          sourceChanged = true
        }
      }
    }

    if (!needRefresh) {
      return this.data.aiDiagnosis
    }

    return this._requestAiDiagnosis({ background: true, refresh: sourceChanged })
  },

  /**
   * 实际请求 AI 诊断
   */
  async _requestAiDiagnosis(opts) {
    var self = this
    opts = opts || {}
    var hasData = !!this.data.aiDiagnosis
    var requestId = ++this._aiDiagnosisRequestId

    // 设置 loading 状态
    if (!hasData) {
      this.setData({ aiDiagnosisLoading: true, aiDiagnosisError: false })
    } else {
      this.setData({ aiDiagnosisRefreshing: true, aiDiagnosisError: false })
    }

    this._aiDiagnosisPromise = (async function() {
      try {
        var params = (opts.force || opts.refresh) ? { refresh: 'true' } : {}
        var diagnosis = await api.get('/stats/ai-diagnosis', params, { timeout: AI_DIAGNOSIS_HTTP_TIMEOUT_MS })
        if (self._isAiDiagnosisPending(diagnosis)) {
          diagnosis = await self._pollAiDiagnosis(diagnosis, requestId)
        }
        if (self._isAiDiagnosisPending(diagnosis)) {
          throw new Error(String((diagnosis && (diagnosis.detail || diagnosis.message)) || 'AI 解析仍在生成，请稍后重试'))
        }
        // 过期响应保护
        if (requestId !== self._aiDiagnosisRequestId || !self._alive) return self.data.aiDiagnosis

        var normalized = self._normalizeAiDiagnosis(diagnosis)

        var hasContent = self._hasAiDiagnosisContent(normalized)

        if (hasContent) {
          var sig = self._buildAiDiagnosisSourceSignature()
          var uid = self._getUserId()
          var now = Date.now()
          self._aiDiagnosisCachedAt = now
          // 写入缓存
          aiCache.save(uid, normalized, sig)
          var detailState = self._buildAiInsightDetails(normalized)
          self.setData({
            aiDiagnosis: normalized,
            aiDiagnosisLoading: false,
            aiDiagnosisRefreshing: false,
            aiDiagnosisCacheTimeLabel: aiCache.formatCacheTime(now),
            aiDiagnosisCacheStale: false,
            aiDiagnosisError: false,
            aiInsightText: self._oneLineInsight(normalized.summary) || self.data.aiInsightText,
            ...detailState,
          })
          return normalized
        }

        // 接口返回空 — 有旧结果则保留
        if (hasData) {
          self.setData({
            aiDiagnosisLoading: false,
            aiDiagnosisRefreshing: false,
          })
          return self.data.aiDiagnosis
        }

        self.setData({
          aiDiagnosis: null,
          aiDiagnosisLoading: false,
          aiDiagnosisRefreshing: false,
          aiDiagnosisError: true,
        })
        return null
      } catch (e) {
        console.error('加载 AI 诊断失败', e)
        if (requestId !== self._aiDiagnosisRequestId || !self._alive) return self.data.aiDiagnosis

        // 有旧结果 → 保留
        if (hasData) {
          self.setData({
            aiDiagnosisLoading: false,
            aiDiagnosisRefreshing: false,
          })
          // 手动刷新才弹 Toast
          if (opts.force) {
            wx.showToast({ title: (e && typeof e.message === 'string' && e.message) || '更新失败，请稍后重试', icon: 'none' })
          }
          return self.data.aiDiagnosis
        }

        // 无旧结果 → 显示错误态
        self.setData({
          aiDiagnosis: null,
          aiDiagnosisLoading: false,
          aiDiagnosisRefreshing: false,
          aiDiagnosisError: true,
        })
        return null
      } finally {
        self._aiDiagnosisPromise = null
      }
    })()

    return this._aiDiagnosisPromise
  },

  _buildAiInsightDetails(diagnosis) {
    const data = diagnosis || {}
    const weakPoints = (Array.isArray(data.weak_points) ? data.weak_points : [])
      .slice(0, 3)
      .map(item => ({
        name: String((item && item.knowledge_point) || '待识别薄弱点'),
        accuracyPercent: Number(
          item && typeof item._accuracyPercent === 'number'
            ? item._accuracyPercent
            : Math.round(Math.max(0, Math.min(1, Number((item && item.accuracy) || 0))) * 100)
        ),
        suggestion: String((item && item.suggestion) || ''),
      }))
    const suggestions = (Array.isArray(data.learning_suggestions) ? data.learning_suggestions : [])
      .map(item => String(item || '').trim())
      .filter(Boolean)
      .slice(0, 3)

    return {
      aiInsightWeakPoints: weakPoints,
      aiInsightSuggestions: suggestions,
      aiInsightHasDetails: weakPoints.length > 0 || suggestions.length > 0,
    }
  },

  async toggleAiInsight() {
    if (this.data.aiInsightExpanded) {
      this.setData({ aiInsightExpanded: false })
      return
    }

    if (this.data.aiDiagnosisLoading || this.data.aiDiagnosisRefreshing) {
      wx.showToast({ title: 'AI 正在分析，请稍候', icon: 'none' })
      return
    }

    if (!this.data.aiDiagnosis) {
      wx.showLoading({ title: '正在生成洞察', mask: false })
      try {
        const diagnosis = await this.ensureAiDiagnosis({ force: false })
        if (!diagnosis) {
          wx.showToast({ title: '暂未生成有效洞察', icon: 'none' })
          return
        }
      } finally {
        wx.hideLoading()
      }
    }

    this.setData({ aiInsightExpanded: true })
  },

  noop() {},

  /**
   * 手动重新分析
   */
  refreshAiDiagnosis() {
    if (this._aiDiagnosisPromise || this.data.aiDiagnosisRefreshing || this.data.aiDiagnosisLoading) {
      wx.showToast({ title: this.data.aiDiagnosisRefreshing ? '正在更新中...' : '正在分析中...', icon: 'none' })
      return
    }
    if (this._aiStatsLoaded) {
      var total = (this.data.stats || {}).total
      if (total === 0) {
        wx.showToast({ title: '暂无错题数据', icon: 'none' })
        return
      }
    }
    this.ensureAiDiagnosis({ force: true })
  },

  onAiFeedback() {
    var types = ['分析不准确', '遗漏薄弱点', '建议不合理', '其他问题']
    wx.showActionSheet({
      itemList: types,
      success: function (res) {
        var feedbackType = types[res.tapIndex] || '其他问题'
        api.post('/ai/feedback', {
          source: 'wrong_book',
          feedback_type: feedbackType,
        }).then(function () {
          wx.showToast({ title: '反馈已提交，感谢您的帮助', icon: 'success' })
        }).catch(function () {
          wx.showToast({ title: '反馈提交失败，请稍后重试', icon: 'none' })
        })
      },
    })
  },

  // ════════════════════════════════════════════
  // Decorators & Analysis (unchanged)
  // ════════════════════════════════════════════

  _decorateItem(item) {
    const wrongCount = this._positiveNumber(
      item.wrong_count || item.error_count || item.mistake_count || item.incorrect_count,
      1
    )
    const reviewCountRaw = item.review_record_count !== undefined && item.review_record_count !== null
      ? item.review_record_count
      : item.review_count
    const reviewCount = this._positiveNumber(reviewCountRaw, 0)
    const lastErrorAt = item.last_wrong_at || item.last_error_at || item.updated_at || item.created_at
    const mastery = this._masteryProgress(item, reviewCount)
    const explicitMastered = item.is_mastered === true || item.status === 'mastered' || item.mastered === true
    // mastered 以服务端统一状态为准；百分比只负责展示，避免前端显示已掌握但后端仍调度。
    const isMastered = explicitMastered
    const dueInfo = this._reviewDueInfo(item, isMastered)
    const isRecent = this._isRecentDate(item.created_at || item.last_wrong_at || item.updated_at, 14)

    let taskStatusLabel = '待巩固'
    let statusTone = 'waiting'
    if (isMastered) {
      taskStatusLabel = '已掌握'
      statusTone = 'mastered'
    } else if (dueInfo.overdue) {
      taskStatusLabel = '已逾期'
      statusTone = 'overdue'
    } else if (dueInfo.today) {
      taskStatusLabel = '今天到期'
      statusTone = 'due'
    } else if (isRecent) {
      taskStatusLabel = '最近新增'
      statusTone = 'recent'
    } else if (dueInfo.date) {
      taskStatusLabel = this._shortDateLabel(dueInfo.date) + '复习'
    }

    const rawContent = item.content
    const contentText = typeof rawContent === 'string'
      ? rawContent
      : (rawContent && (rawContent.stem || rawContent.text)) || ''
    const cleanText = this._toCleanText(contentText)
    const hasImage = Array.isArray(item.image_url) ? item.image_url.length > 0 : !!item.image_url

    return {
      ...item,
      _subjectLabel: this._subjectLabel(item.subject_code, item.subject_name),
      _errorTypeLabel: this._errorTypeLabel(item.error_type),
      _timeLabel: this._timeLabel(item.created_at),
      _lastErrorLabel: this._timeLabel(lastErrorAt) || '待记录',
      _wrongCount: wrongCount,
      _reviewCount: reviewCount,
      _masteryPercent: mastery.percent,
      _masteryLabel: mastery.label,
      _cleanText: cleanText || (hasImage ? '图片题 · 点击查看完整题目' : ''),
      _isMastered: isMastered,
      _isTodayDue: dueInfo.today,
      _isOverdue: dueInfo.overdue,
      _isRecent: isRecent,
      _nextReviewAt: dueInfo.date ? dueInfo.date.toISOString() : '',
      _taskStatusLabel: taskStatusLabel,
      _statusTone: statusTone,
    }
  },

  _reviewDueInfo(item, isMastered) {
    if (isMastered) return { today: false, overdue: false, date: null }
    const raw = item.next_review_at || item.review_due_at || item.scheduled_at || item.due_at
    const dueMs = raw ? parseServerUtc(raw) : NaN
    const date = isFinite(dueMs) ? new Date(dueMs) : null

    const explicitToday = item.is_today_due === true || item.today_due === true || item.is_due === true
    if (!date && explicitToday) return { today: true, overdue: false, date: null }
    if (!date) return { today: false, overdue: false, date: null }

    const range = getChinaDayRangeUtcMs()
    return {
      today: dueMs < range.end,
      overdue: dueMs < range.start,
      date,
    }
  },

  _isRecentDate(raw, days) {
    if (!raw) return false
    const ms = parseServerUtc(raw)
    if (!isFinite(ms)) return false
    const diff = Date.now() - ms
    return diff >= 0 && diff <= days * 86400000
  },

  _shortDateLabel(date) {
    if (!date || Number.isNaN(date.getTime())) return ''
    return formatChinaMonthDayCn(date.getTime())
  },

  _buildTaskGroups(list = []) {
    const used = new Set()
    const take = predicate => {
      const rows = list.filter(item => !used.has(String(item.id)) && predicate(item))
      rows.forEach(item => used.add(String(item.id)))
      return rows
    }

    const today = take(item => !item._isMastered && item._isTodayDue)
      .sort((a, b) => Number(b._isOverdue) - Number(a._isOverdue) || b._wrongCount - a._wrongCount)
    const high = take(item => !item._isMastered && item._wrongCount >= 3)
      .sort((a, b) => b._wrongCount - a._wrongCount)
    const recent = take(item => !item._isMastered && item._isRecent)
      .sort((a, b) => (parseServerUtc(b.created_at) || 0) - (parseServerUtc(a.created_at) || 0))
    const waiting = take(item => !item._isMastered)
      .sort((a, b) => a._masteryPercent - b._masteryPercent || b._wrongCount - a._wrongCount)
    const mastered = take(item => item._isMastered)
      .sort((a, b) => (parseServerUtc(b.updated_at || b.created_at) || 0) - (parseServerUtc(a.updated_at || a.created_at) || 0))

    const maxPreview = 3
    const configs = [
      { key: 'today', title: '今日应复习', desc: '基于复习计划，今天最值得先做的题', icon: '今', tone: 'lime', rows: today },
      { key: 'high', title: '高频错题', desc: '重复出错次数较多，建议集中攻克', icon: '频', tone: 'orange', rows: high },
      { key: 'recent', title: '最近新增', desc: '近 14 天新加入错题本的题目', icon: '新', tone: 'blue', rows: recent },
      { key: 'waiting', title: '待巩固', desc: '尚未到复习日，但仍未完全掌握', icon: '固', tone: 'neutral', rows: waiting },
      { key: 'mastered', title: '已经掌握', desc: '已达到掌握标准，不再进入正常复习；再次答错会重新加入', icon: '✓', tone: 'green', rows: mastered },
    ]

    const groups = configs
      .filter(group => group.rows.length > 0)
      .map(group => ({
        key: group.key,
        title: group.title,
        desc: group.desc,
        icon: group.icon,
        tone: group.tone,
        total: group.rows.length,
        items: group.rows.slice(0, maxPreview),
      }))

    const visibleCount = groups.reduce((sum, group) => sum + group.items.length, 0)
    return {
      groups,
      ungroupedCount: Math.max(0, list.length - visibleCount),
    }
  },

  _oneLineInsight(text) {
    const cleaned = String(text || '').replace(/\s+/g, ' ').trim()
    if (!cleaned) return '错题数据积累后，AI 会自动发现最需要优先复盘的错误模式。'
    return cleaned.length > 70 ? `${cleaned.slice(0, 70)}…` : cleaned
  },

  _buildAnalysis(stats = {}, list = []) {
    stats = stats || {}
    const errorRows = this._rowsFromStats(stats, ['by_error_type', 'error_types', 'errors'])
    const subjectRows = this._rowsFromStats(stats, ['by_subject', 'subjects'])
    const errorCounts = errorRows.length ? errorRows : this._countsFromList(list, 'error_type')
    const subjectCounts = subjectRows.length ? subjectRows : this._countsFromList(list, 'subject_id')
    const sourceLabel = errorRows.length || subjectRows.length ? '按错因统计' : (list.length ? '按当前列表统计' : '待积累')

    const weaknessTags = this._topItems(errorCounts, 5).map(row => ({
      key: row.key,
      label: this._errorTypeLabel(row.key),
      count: row.count,
    }))
    const radarItems = this._toPercentItems(this._topItems(errorCounts, 4), this._errorTypeLabel.bind(this))
    const subjectItems = this._toPercentItems(this._topItems(subjectCounts, 4), this._subjectLabel.bind(this))

    return {
      sourceLabel,
      weaknessTags,
      radarItems,
      subjectItems,
      summaryCards: this._buildSummaryCards(stats, list, weaknessTags),
      actionPlan: this._buildActionPlan(weaknessTags, subjectItems, list),
      radarPolygonStyle: this._radarPolygonStyle(radarItems),
      radarAxisText: this._radarAxisText(radarItems),
      focusInsight: this._focusInsight(weaknessTags, subjectItems, list),
    }
  },

  _buildSummaryCards(stats = {}, list = [], weaknessTags = []) {
    stats = stats || {}
    const hasStats = Object.keys(stats).length > 0
    const unmastered = hasStats
      ? this._positiveNumber(stats.unmastered, stats.total || list.length || 0)
      : list.length
    const reviewed = list.filter(item => this._positiveNumber(item._reviewCount, 0) > 0).length
    const avgMastery = list.length
      ? Math.round(list.reduce((sum, item) => sum + this._positiveNumber(item._masteryPercent, 0), 0) / list.length)
      : 0
    const topWeakness = weaknessTags[0] ? weaknessTags[0].label : '待积累'

    return [
      { key: 'unmastered', value: unmastered, label: '待攻克', tone: 'danger' },
      { key: 'weakness', value: topWeakness, label: '首要弱项', tone: 'blue' },
      { key: 'reviewed', value: `${reviewed}/${list.length || 0}`, label: '已复盘', tone: 'success' },
      { key: 'mastery', value: `${avgMastery}%`, label: '平均掌握', tone: 'gold' },
    ]
  },

  _buildActionPlan(weaknessTags = [], subjectItems = [], list = []) {
    if (!list.length && !weaknessTags.length && !subjectItems.length) return []
    const firstWeakness = weaknessTags[0]
    const firstSubject = subjectItems[0]
    const lowMasteryCount = list.filter(item => this._positiveNumber(item._masteryPercent, 0) < 40).length
    return [
      {
        key: 'weakness',
        title: firstWeakness ? `优先复盘「${firstWeakness.label}」` : '先完成一组错题复盘',
        desc: firstWeakness ? `${firstWeakness.count} 道题集中暴露该问题` : '积累数据后会生成更明确的弱项计划',
      },
      {
        key: 'subject',
        title: firstSubject ? `重点看 ${firstSubject.label}` : '按学科建立错题节奏',
        desc: firstSubject ? `${firstSubject.count} 道错题集中在该方向` : '筛选学科后可缩小复盘范围',
      },
      {
        key: 'mastery',
        title: lowMasteryCount > 0 ? `先攻克 ${lowMasteryCount} 道低掌握题` : '保持复盘节奏',
        desc: lowMasteryCount > 0 ? '掌握进度低于 40% 的题建议优先重做' : '当前列表掌握度较稳定，适合做限时巩固',
      },
    ]
  },

  _rowsFromStats(stats, keys) {
    for (const key of keys) {
      const value = stats && stats[key]
      if (Array.isArray(value)) {
        return value.map(row => ({
          key: row.key || row.type || row.error_type || (row.subject_id != null ? row.subject_id : (row.name || row.label || '')),
          label: row.subject_name || row.name || row.label || '',
          count: this._positiveNumber(row.count || row.total || row.value, 0),
        })).filter(row => row.key !== '' && row.key != null && row.count > 0)
      }
      if (value && typeof value === 'object') {
        return Object.keys(value).map(k => ({ key: k, label: '', count: this._positiveNumber(value[k], 0) }))
          .filter(row => row.key !== '' && row.key != null && row.count > 0)
      }
    }
    return []
  },

  _countsFromList(list, field) {
    const counts = {}
    list.forEach(item => {
      const key = item[field] != null ? item[field] : 'unknown'
      if (!counts[key]) counts[key] = { key, label: item.subject_name || '', count: 0 }
      counts[key].count += 1
    })
    return Object.keys(counts).map(key => counts[key]).filter(row => row.key !== 'unknown')
  },

  _topItems(rows, limit) {
    return rows
      .filter(row => row.key && row.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, limit)
  },

  _toPercentItems(rows, labelFn) {
    const max = rows.reduce((m, row) => Math.max(m, row.count), 0) || 1
    return rows.map(row => ({
      key: row.key,
      label: row.label || labelFn(row.key),
      count: row.count,
      percent: Math.max(12, Math.round((row.count / max) * 100)),
      height: Math.max(46, Math.round((row.count / max) * 100) + 34),
    }))
  },

  _radarPolygonStyle(items = []) {
    if (!items.length) return ''
    const points = [
      [50, 50 - items[0].percent * 0.42],
      [50 + (items[1] ? items[1].percent : items[0].percent) * 0.42, 50],
      [50, 50 + (items[2] ? items[2].percent : items[0].percent) * 0.42],
      [50 - (items[3] ? items[3].percent : items[0].percent) * 0.42, 50],
    ]
    return `clip-path: polygon(${points.map(point => `${Math.round(point[0])}% ${Math.round(point[1])}%`).join(', ')});`
  },

  _radarAxisText(items = []) {
    if (!items.length) return '暂无能力图谱数据'
    return items.map(item => `${item.label}${item.count}题`).join('，')
  },

  _focusInsight(weaknessTags = [], subjectItems = [], list = []) {
    const weakness = weaknessTags[0]
    const subject = subjectItems[0]
    if (weakness && subject) return `${subject.label}的「${weakness.label}」最需要优先攻克`
    if (weakness) return `优先攻克「${weakness.label}」相关错题`
    if (list.length) return '当前错题已形成复盘样本，建议先完成一轮筛选复盘'
    return '错题数据积累后，将生成知识漏洞诊断。'
  },

  _masteryProgress(item, reviewCount) {
    const mastered = item.is_mastered === true || item.status === 'mastered' || item.mastered === true
    // “确认掌握”是明确的最终状态。即使灰度期间旧后端仍返回基于
    // repetitions 的 20%/45%，卡片也不能出现“已掌握 20%”的冲突展示。
    if (mastered) return { percent: 100, label: '已掌握' }

    const raw = item.mastery_progress || item.mastery_percent || item.mastery
    if (raw !== undefined && raw !== null && raw !== '') {
      const percent = Math.max(0, Math.min(100, Number(raw) > 1 ? Number(raw) : Number(raw) * 100))
      return { percent: Math.round(percent), label: percent >= 40 ? '巩固中' : '待攻克' }
    }

    const percent = Math.min(90, reviewCount * 20)
    return { percent, label: reviewCount > 0 ? '按复习次数估算' : '待复习' }
  },

  _positiveNumber(value, fallback) {
    const n = Number(value)
    if (!Number.isFinite(n) || n < 0) return fallback
    return Math.round(n)
  },

  _subjectLabel(code, name) {
    if (name) return name
    return getSubjectName(code)
  },

  _errorTypeLabel(t) {
    const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他', unknown: '未分类' }
    return map[t] || t || '未知'
  },

  _timeLabel(dateStr) {
    if (!dateStr) return ''
    const ms = parseServerUtc(dateStr)
    if (!isFinite(ms)) return ''
    const days = chinaCalendarDayDiff(ms, Date.now())
    if (days === 0) return '今天'
    if (days === 1) return '昨天'
    if (days > 1 && days <= 7) return `${days} 天前`
    return formatChinaMonthDayCn(ms)
  },

  _toCleanText(text) {
    if (!text || typeof text !== 'string') return ''
    const plain = toPlainInlineMathText(text)
    return plain !== null ? plain : String(text).replace(/\n/g, ' ')
  },
})
