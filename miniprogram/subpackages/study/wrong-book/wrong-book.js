const api = require('../../../utils/api')
const config = require('../../../config')
const { safeDecodeURIComponent } = require('../utils/route-params')
const { toPlainInlineMathText } = require('../utils/stem-render')
const storage = require('../../../utils/storage')
const aiCache = require('../utils/ai-diagnosis-cache')
const errorDiagnosis = require('../utils/error-diagnosis')
const { getSubjectName, getSubjectShortName } = require('../utils/subject-meta')
const exportApi = require('../utils/export-capability')
const dateFilter = require('../../../components/question-filter-panel/date-range')
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
const { masteryProgress, positiveNumber, subjectLabel, errorTypeLabel, timeLabel, toCleanText, reviewDueInfo, isRecentDate, shortDateLabel, oneLineInsight } = require('./utils/wrong-book-value-view')
const { decorateItem, resolveReviewCount, resolveItemStatus, resolveItemContent, buildDecoratedItem, flattenSubjectOptions, buildTaskGroups } = require('./utils/wrong-book-item-view')
const { buildAnalysis, buildSummaryCards, buildActionPlan, rowsFromStats, countsFromList, topItems, toPercentItems, radarPolygonStyle, radarAxisText, focusInsight } = require('./utils/wrong-book-analysis-view')
const { buildItemViewCapabilities, buildAnalysisViewCapabilities } = require('./utils/wrong-book-view-page-adapter')
const requestFlow = require('./utils/wrong-book-request-flow')
const selectionFlow = require('./utils/wrong-book-selection-flow')
const batchFlow = require('./utils/wrong-book-batch-flow')
const batchUndo = require('./utils/wrong-book-batch-undo')
const lifecycle = require('./utils/wrong-book-lifecycle')
const navigationFlow = require('./utils/wrong-book-navigation-flow')
const aiState = require('./utils/wrong-book-ai-state')
const aiPersistence = require('./utils/wrong-book-ai-persistence')
Page({
data: {
list: [],
listTotal: 0,
stats: { total: 0 },
primaryStatCount: 0,
masteredCount: 0,
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
exportAvailable: false,
exportCapabilityChecked: false,
exportUnavailableText: '当前导出功能不可用',
selectedSubjectId: null,
selectedErrorType: '',
selectedTopic: '',
selectedDatePreset: '',
dateFrom: '',
dateTo: '',
listError: '',
showFilter: false,
filterCount: 0,
subjects: [{ value: '', label: '全部' }],
subjectsLoading: false,
subjectsError: false,
subjectsLoaded: false,
errorTypes: ERROR_TYPES,
},
_updateFilterCount() {
const count = (this.data.selectedSubjectId ? 1 : 0) + (this.data.selectedErrorType ? 1 : 0) + (this.data.selectedTopic ? 1 : 0) + (this.data.dateFrom || this.data.dateTo ? 1 : 0)
this.setData({ filterCount: count })
},
_hasFilters() {
return !!(this.data.selectedSubjectId || this.data.selectedErrorType || this.data.selectedTopic || this.data.dateFrom || this.data.dateTo)
},
_syncDateFilter() {
const now = api.now()
const patch = {}
if (this.data.selectedDatePreset !== 'custom') {
Object.assign(patch, dateFilter.presetRange(this.data.selectedDatePreset, now))
}
this.setData(patch)
},
_filterParams() {
const params = { product_scope: 'exam408' }
if (this.data.selectedSubjectId) params.subject_id = this.data.selectedSubjectId
if (this.data.selectedErrorType) params.error_type = this.data.selectedErrorType
if (this.data.selectedTopic) params.topic = this.data.selectedTopic
if (this.data.dateFrom) params.date_from = this.data.dateFrom
if (this.data.dateTo) params.date_to = this.data.dateTo
return params
},
_beginFilterReload(patch) {
return requestFlow._beginFilterReload(this, patch)
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
_subjectsRequestSeq: 0,
_taskFlowRequestSeq: 0,
_destroyed: false,
onLoad(options) {
return lifecycle.onLoad(this, options, { settings: config, safeDecodeURIComponent })
},
onReady() {
return lifecycle.onReady(this)
},
onShow() {
return lifecycle.onShow(this)
},
onHide() {
return lifecycle.onHide(this)
},
onUnload() {
return lifecycle.onUnload(this)
},
async _checkExportCapability() {
return navigationFlow._checkExportCapability(this, { settings: config, exportClient: exportApi })
},
async _loadPage() {
return requestFlow._loadPage(this)
},
_getAiAutoSettingKey() {
return aiPersistence._getAiAutoSettingKey(this, { settingPrefix: AI_AUTO_SETTING_PREFIX })
},
_getAiInsightIdleText(enabled) {
return aiState._getAiInsightIdleText(enabled)
},
_restoreAiAutoSetting() {
return aiPersistence._restoreAiAutoSetting(this, { storageClient: storage })
},
toggleAiAutoAnalysis() {
return aiPersistence.toggleAiAutoAnalysis(this, { storageClient: storage, getPlatform: () => wx })
},
_restoreAiDiagnosisFromCache() {
return aiPersistence._restoreAiDiagnosisFromCache(this, { diagnosisCache: aiCache })
},
async loadStats() {
return requestFlow.loadStats(this, { requestClient: api })
},
async loadList(reset = false) {
return requestFlow.loadList(this, reset, { requestClient: api })
},
async loadTaskFlow() {
return requestFlow.loadTaskFlow(this, { requestClient: api })
},
async loadSubjects() {
return requestFlow.loadSubjects(this, { requestClient: api })
},
_flattenSubjectOptions(raw) {
return flattenSubjectOptions(raw)
},
goBack() {
return navigationFlow.goBack({ getPlatform: () => wx })
},
toggleFilter() {
this._syncDateFilter()
if (!this.data.subjectsLoaded && !this.data.subjectsLoading) this.loadSubjects()
this.setData({ showFilter: !this.data.showFilter })
},
selectSubject(e) {
const val = e.detail.value
const subjectId = (val === '' || val === null || val === undefined) ? null : Number(val)
this._beginFilterReload({ selectedSubjectId: subjectId })
},
selectErrorType(e) {
const val = e.detail.value
this._beginFilterReload({ selectedErrorType: val })
},
onDateFilterChange(e) {
const range = e.detail || {}
this._beginFilterReload({ selectedDatePreset: range.preset || '', dateFrom: range.dateFrom || '', dateTo: range.dateTo || '' })
},
retryList() {
return this.loadList(this.data.list.length === 0)
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
selectedDatePreset: '',
dateFrom: '',
dateTo: '',
filterCount: 0,
})
},
switchView(e) {
return selectionFlow.switchView(this, e)
},
openAllQuestions() {
return selectionFlow.openAllQuestions(this)
},
toggleBatchMode() {
return selectionFlow.toggleBatchMode(this)
},
onPageInteraction() {
return selectionFlow.onPageInteraction(this)
},
onPageScroll() {
return selectionFlow.onPageScroll(this)
},
_clearBatchCapsuleIdleTimer() {
return selectionFlow._clearBatchCapsuleIdleTimer(this)
},
_scheduleBatchCapsuleAutoHide() {
return selectionFlow._scheduleBatchCapsuleAutoHide(this, BATCH_CAPSULE_IDLE_MS)
},
_showBatchCapsuleAndRefreshTimer() {
return selectionFlow._showBatchCapsuleAndRefreshTimer(this)
},
onQuestionTap(e) {
return selectionFlow.onQuestionTap(this, e)
},
onSelectControlTap(e) {
return selectionFlow.onSelectControlTap(this, e)
},
onQuestionLongPress(e) {
return selectionFlow.onQuestionLongPress(this, e, { getPlatform: () => wx })
},
_navigateToDetail(id) {
return navigationFlow._navigateToDetail(this, id, { getPlatform: () => wx })
},
_toggleQuestionSelection(id) {
return selectionFlow._toggleQuestionSelection(this, id)
},
_pulseSelectionBadge() {
return selectionFlow._pulseSelectionBadge(this)
},
_getVisibleIds() {
return selectionFlow._getVisibleIds(this)
},
toggleSelectAll() {
return selectionFlow.toggleSelectAll(this)
},
_syncSelectionState() {
return selectionFlow._syncSelectionState(this)
},
_showAppOptions(opts) {
return batchFlow._showAppOptions(this, opts)
},
async openBatchMore() {
return batchFlow.openBatchMore(this, { getPlatform: () => wx })
},
closeBatchMore() {},
noop() {},
  async onBatchAction(e) {
return batchFlow.onBatchAction(this, e, { requestClient: api, getPlatform: () => wx })
},

  _resolveBatchIds() {
return batchFlow._resolveBatchIds(this)
},

  _batchActionLabels() {
return batchFlow._batchActionLabels()
},

  _isDangerousBatchAction(action) {
return batchFlow._isDangerousBatchAction(action)
},

  _batchConfirmMessage(action, count) {
return batchFlow._batchConfirmMessage(action, count)
},

  async _handleBatchMastered(result, ids) {
return batchUndo._handleBatchMastered(this, result, ids, { getPlatform: () => wx })
},

  _handleBatchSuccess(result, labels, action) {
return batchFlow._handleBatchSuccess(this, result, labels, action, { getPlatform: () => wx })
},

  _handleBatchError(err) {
return batchFlow._handleBatchError(this, err, { getPlatform: () => wx })
},

  async _showBatchMissingEndpoint() {
return batchFlow._showBatchMissingEndpoint(this, { getPlatform: () => wx })
},
_reloadAfterBatch() {
return batchFlow._reloadAfterBatch(this)
},
onExportSelected() {
return navigationFlow.onExportSelected(this, { getPlatform: () => wx, getApplication: () => getApp() })
},
onViewExportRecords() {
return navigationFlow.onViewExportRecords({ getPlatform: () => wx })
},
undoBatchMaster() {
return batchUndo.undoBatchMaster(this, { requestClient: api, getPlatform: () => wx })
},
_clearBatchMasterUndo(skipSetData) {
return batchUndo._clearBatchMasterUndo(this, skipSetData)
},
_confirmBatchAction(title, content) {
return batchFlow._confirmBatchAction(this, title, content)
},
goDetail(e) {
return navigationFlow.goDetail(this, e)
},
_getUser() {
return aiPersistence._getUser({ storageClient: storage })
},
_getUserId() {
return aiPersistence._getUserId(this)
},
_normalizeAiDiagnosis(raw) {
return aiState._normalizeAiDiagnosis(raw)
},
_buildAiDiagnosisSourceSignature() {
return aiPersistence._buildAiDiagnosisSourceSignature(this, { diagnosisCache: aiCache })
},
async _checkAiDiagnosis() {
if (this._destroyed) return null
var stats = this.data.stats || {}
var total = stats.total
if (!this._aiStatsLoaded) {
return this.data.aiDiagnosis || null
}
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
return aiState._hasAiDiagnosisContent(this, value)
},
_isAiDiagnosisPending(value) {
return aiState._isAiDiagnosisPending(value)
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
async ensureAiDiagnosis(options) {
options = options || {}
if (this._aiStatsLoaded) {
var total = (this.data.stats || {}).total
if (total === 0) return null
}
if (this._aiDiagnosisPromise) return this._aiDiagnosisPromise
if (options.force) {
return this._requestAiDiagnosis({ force: true })
}
var hasData = !!this.data.aiDiagnosis
if (hasData && !options.background) {
return this.data.aiDiagnosis
}
var needRefresh = false
var sourceChanged = false
if (!hasData) {
needRefresh = true
} else {
var cachedAt = this._aiDiagnosisCachedAt
var isStale = this.data.aiDiagnosisCacheStale || aiCache.isExpired(cachedAt, this.data.aiDiagnosis)
if (isStale) {
needRefresh = true
} else {
var currentSig = this._buildAiDiagnosisSourceSignature()
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
  async _requestAiDiagnosis(opts) {
    opts = opts || {}
    var hasData = !!this.data.aiDiagnosis
    var requestId = ++this._aiDiagnosisRequestId
    this.setData(hasData ? { aiDiagnosisRefreshing: true, aiDiagnosisError: false } : { aiDiagnosisLoading: true, aiDiagnosisError: false })
    this._aiDiagnosisPromise = this._executeAiDiagnosisRequest(opts, hasData, requestId)
    return this._aiDiagnosisPromise
  },

  async _executeAiDiagnosisRequest(opts, hasData, requestId) {
    try {
      var diagnosis = await this._fetchAiDiagnosisData(opts, requestId)
      if (requestId !== this._aiDiagnosisRequestId || !this._alive) return this.data.aiDiagnosis
      return this._applyAiDiagnosisResult(diagnosis, hasData)
    } catch (e) {
      return this._handleAiDiagnosisError(e, opts, hasData, requestId)
    } finally {
      this._aiDiagnosisPromise = null
    }
  },

  async _fetchAiDiagnosisData(opts, requestId) {
    var params = (opts.force || opts.refresh) ? { refresh: true } : {}
    var diagnosis = await api.get('/stats/ai-diagnosis', params, { timeout: AI_DIAGNOSIS_HTTP_TIMEOUT_MS })
    if (this._isAiDiagnosisPending(diagnosis)) {
      diagnosis = await this._pollAiDiagnosis(diagnosis, requestId)
    }
    if (this._isAiDiagnosisPending(diagnosis)) {
      throw new Error(String((diagnosis && (diagnosis.detail || diagnosis.message)) || 'AI 解析仍在生成，请稍后重试'))
    }
    return diagnosis
  },

  _applyAiDiagnosisResult(diagnosis, hasData) {
    var normalized = this._normalizeAiDiagnosis(diagnosis)
    var hasContent = this._hasAiDiagnosisContent(normalized)
    if (hasContent) return this._commitAiDiagnosisContent(normalized)
    if (hasData) {
      this.setData({ aiDiagnosisLoading: false, aiDiagnosisRefreshing: false })
      return this.data.aiDiagnosis
    }
    this.setData({ aiDiagnosis: null, aiDiagnosisLoading: false, aiDiagnosisRefreshing: false, aiDiagnosisError: true })
    return null
  },

  _commitAiDiagnosisContent(normalized) {
return aiPersistence._commitAiDiagnosisContent(this, normalized, { diagnosisCache: aiCache })
},

  _handleAiDiagnosisError(e, opts, hasData, requestId) {
    console.error('加载 AI 诊断失败', e)
    if (requestId !== this._aiDiagnosisRequestId || !this._alive) return this.data.aiDiagnosis
    if (hasData) {
      this.setData({ aiDiagnosisLoading: false, aiDiagnosisRefreshing: false })
      if (opts.force) {
        wx.showToast({ title: (e && typeof e.message === 'string' && e.message) || '更新失败，请稍后重试', icon: 'none' })
      }
      return this.data.aiDiagnosis
    }
    this.setData({ aiDiagnosis: null, aiDiagnosisLoading: false, aiDiagnosisRefreshing: false, aiDiagnosisError: true })
    return null
  },
_buildAiInsightDetails(diagnosis) {
return aiState._buildAiInsightDetails(diagnosis)
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
async onAiFeedback() {
const types = ['分析不准确', '遗漏薄弱点', '建议不合理', '其他问题']
const index = await this._showAppOptions({ title: '反馈这次分析', items: types })
if (index < 0) return
const feedbackType = types[index] || '其他问题'
try {
await api.post('/ai/feedback', { source: 'wrong_book', feedback_type: feedbackType })
wx.showToast({ title: '反馈已提交，感谢您的帮助', icon: 'success' })
} catch (_) {
wx.showToast({ title: '反馈提交失败，请稍后重试', icon: 'none' })
}
},
  _decorateItem(item) {
return decorateItem(item, buildItemViewCapabilities(this))
},

  _resolveReviewCount(item) {
return resolveReviewCount(item, buildItemViewCapabilities(this))
},

  _resolveItemStatus(isMastered, dueInfo, isRecent) {
return resolveItemStatus(isMastered, dueInfo, isRecent, buildItemViewCapabilities(this))
},

  _resolveItemContent(item) {
return resolveItemContent(item, buildItemViewCapabilities(this))
},

  _buildDecoratedItem(item, ctx) {
return buildDecoratedItem(item, ctx, buildItemViewCapabilities(this))
},
_reviewDueInfo(item, isMastered) {
return reviewDueInfo(item, isMastered, parseServerUtc, getChinaDayRangeUtcMs)
},
_isRecentDate(raw, days) {
return isRecentDate(raw, days, parseServerUtc)
},
_shortDateLabel(date) {
return shortDateLabel(date, formatChinaMonthDayCn)
},
_buildTaskGroups(list = []) {
return buildTaskGroups(list, parseServerUtc)
},
_oneLineInsight(text) {
return oneLineInsight(text)
},
_buildAnalysis(stats = {}, list = []) {
return buildAnalysis(stats, list, buildAnalysisViewCapabilities(this))
},
_buildSummaryCards(stats = {}, list = [], weaknessTags = []) {
return buildSummaryCards(stats, list, weaknessTags, buildAnalysisViewCapabilities(this))
},
_buildActionPlan(weaknessTags = [], subjectItems = [], list = []) {
return buildActionPlan(weaknessTags, subjectItems, list, buildAnalysisViewCapabilities(this))
},
_rowsFromStats(stats, keys) {
return rowsFromStats(stats, keys, buildAnalysisViewCapabilities(this))
},
_countsFromList(list, field) {
return countsFromList(list, field)
},
_topItems(rows, limit) {
return topItems(rows, limit)
},
_toPercentItems(rows, labelFn) {
return toPercentItems(rows, labelFn)
},
_radarPolygonStyle(items = []) {
return radarPolygonStyle(items)
},
_radarAxisText(items = []) {
return radarAxisText(items)
},
_focusInsight(weaknessTags = [], subjectItems = [], list = []) {
return focusInsight(weaknessTags, subjectItems, list)
},
_masteryProgress(item, reviewCount) {
return masteryProgress(item, reviewCount)
},
_positiveNumber(value, fallback) {
return positiveNumber(value, fallback)
},
_subjectLabel(code, name) {
return subjectLabel(code, name, getSubjectName)
},
_errorTypeLabel(t) {
return errorTypeLabel(t, errorDiagnosis)
},
_timeLabel(dateStr) {
return timeLabel(dateStr, parseServerUtc, chinaCalendarDayDiff, formatChinaMonthDayCn)
},
_toCleanText(text) {
return toCleanText(text, toPlainInlineMathText)
},
})
