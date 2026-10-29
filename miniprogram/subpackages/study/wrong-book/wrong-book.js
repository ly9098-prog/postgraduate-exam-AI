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
this._destroyed = false
this._statsRequestSeq = 0
this._subjectsRequestSeq = 0
this._taskFlowRequestSeq = 0
this._batchMasterUndoInFlight = false
this.setData({ enableMathImage: config.enableMathImage || false })
this._syncDateFilter()
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
this._restoreAiAutoSetting()
this._restoreAiDiagnosisFromCache()
},
onReady() {
this._ready = true
this.loadSubjects()
this._loadPage()
},
onShow() {
this._alive = true
this._syncDateFilter()
if (this.data.batchMode) this._showBatchCapsuleAndRefreshTimer()
if (!this._ready) return
Promise.all([
this.loadStats(),
this.loadList(true),
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
async _loadPage() {
return requestFlow._loadPage(this)
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
wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/home/home' }) })
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
const view = e.currentTarget.dataset.view === 'all' ? 'all' : 'task'
this.setData({ activeView: view })
this._syncSelectionState()
},
openAllQuestions() {
this.setData({ activeView: 'all' })
this._syncSelectionState()
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
_showAppOptions(opts) {
const dialog = this.selectComponent('#appDialog')
if (!dialog || typeof dialog.showOptions !== 'function') return Promise.resolve(-1)
return dialog.showOptions(opts || {})
},
async openBatchMore() {
if (!this.data.selectedCount) {
wx.showToast({ title: '请先选择错题', icon: 'none' })
return
}
const index = await this._showAppOptions({
title: '批量处理',
message: `将作用于已选择的 ${this.data.selectedCount} 道错题`,
items: ['移出错题本', '永久删除'],
dangerIndexes: [1],
})
if (index < 0) return
const action = index === 0 ? 'remove_from_book' : 'delete'
this.onBatchAction({ currentTarget: { dataset: { action } } })
},
closeBatchMore() {},
noop() {},
  async onBatchAction(e) {
    if (this.data.batchSubmitting || this._batchMasterUndoInFlight) return
    const action = e.currentTarget.dataset.action
    if (this.data.batchMoreVisible) this.setData({ batchMoreVisible: false })
    const ids = this._resolveBatchIds()
    if (!ids.length) { wx.showToast({ title: '请先选择错题', icon: 'none' }); return }
    const labels = this._batchActionLabels()
    if (this._isDangerousBatchAction(action)) {
      const confirmed = await this._confirmBatchAction(labels[action], this._batchConfirmMessage(action, ids.length))
      if (!confirmed) return
    }
    this.setData({ batchSubmitting: true })
    wx.showLoading({ title: '正在处理', mask: true })
    try {
      const result = await api.post('/wrong-questions/batch', { action, ids })
      wx.hideLoading()
      if (this._destroyed) return
      if (action === 'mark_mastered') {
        await this._handleBatchMastered(result, ids)
        return
      }
      this._handleBatchSuccess(result, labels, action)
      await this._reloadAfterBatch()
    } catch (err) {
      this._handleBatchError(err)
    }
  },

  _resolveBatchIds() {
    return (this.data.selectedIds || []).map(id => {
      const n = Number(id)
      return Number.isFinite(n) && String(n) === String(id) ? n : id
    })
  },

  _batchActionLabels() {
    return {
      add_to_review: '加入今日复习', mark_mastered: '标记为已掌握',
      remove_from_book: '移出错题本', delete: '永久删除',
    }
  },

  _isDangerousBatchAction(action) {
    return action === 'delete' || action === 'remove_from_book'
  },

  _batchConfirmMessage(action, count) {
    return action === 'delete'
      ? `将永久删除已选择的 ${count} 道错题记录，是否继续？`
      : `将把已选择的 ${count} 道题移出错题本，是否继续？`
  },

  async _handleBatchMastered(result, ids) {
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
      batchSubmitting: false, batchMasterUndoVisible: canUndo,
      _batchMasterUndoCount: canUndo ? undoIds.length : 0,
      selectionPulse: false, selectedIds: [], selectedIdMap: {},
      selectedCount: 0, allVisibleSelected: false,
    })
    if (canUndo) {
      this._batchMasterUndoTimer = setTimeout(() => { this._clearBatchMasterUndo() }, 5000)
    } else {
      wx.showToast({ title: updatedCount > 0 ? `已标记掌握 ${updatedCount} 项` : '所选题目状态未变化', icon: 'none' })
    }
    await this._reloadAfterBatch()
  },

  _handleBatchSuccess(result, labels, action) {
    wx.showToast({
      title: `${labels[action]}成功 ${result.updated_count != null ? result.updated_count : ids.length} 项`,
      icon: 'success',
    })
    this._clearBatchCapsuleIdleTimer()
    this.setData({
      batchSubmitting: false, batchMode: false, batchCapsuleVisible: true,
      batchMoreVisible: false, selectionPulse: false, selectedIds: [],
      selectedIdMap: {}, selectedCount: 0, allVisibleSelected: false,
    })
  },

  _handleBatchError(err) {
    wx.hideLoading()
    if (this._destroyed) return
    this.setData({ batchSubmitting: false })
    const isMissingEndpoint = err && (err.statusCode === 404 || err.statusCode === 405)
    if (isMissingEndpoint) {
      this._showBatchMissingEndpoint()
    } else {
      wx.showToast({ title: (err && err.message) || '批量操作失败', icon: 'none' })
    }
  },

  async _showBatchMissingEndpoint() {
    const modal = this.selectComponent('#actionConfirm')
    if (modal) {
      await modal.show({
        scenario: 'info', eyebrow: 'NOTICE', title: '批量接口尚未接入',
        message: '当前页面交互已经完成，但后端暂不支持该批量操作。',
        confirmText: '知道了', hideCancel: true,
      })
    } else {
      wx.showToast({ title: '批量接口尚未接入', icon: 'none' })
    }
  },
_reloadAfterBatch() {
if (this._destroyed) return Promise.resolve([])
return Promise.all([this.loadStats(), this.loadList(true)])
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
_getUser() {
try { return storage.get(storage.KEYS.USER) } catch (_) { return null }
},
_getUserId() {
var user = this._getUser()
return user && (user.id || user.user_id || user.openid || '')
},
_normalizeAiDiagnosis(raw) {
if (!raw) return null
var copy = JSON.parse(JSON.stringify(raw))
var diagnosisListKeys = ['weak_points', 'strong_points', 'learning_suggestions']
for (var listKeyIndex = 0; listKeyIndex < diagnosisListKeys.length; listKeyIndex++) {
var listKey = diagnosisListKeys[listKeyIndex]
if (!Array.isArray(copy[listKey])) copy[listKey] = []
}
var diagnosisPointKeys = ['weak_points', 'strong_points']
for (var diagnosisKeyIndex = 0; diagnosisKeyIndex < diagnosisPointKeys.length; diagnosisKeyIndex++) {
var key = diagnosisPointKeys[diagnosisKeyIndex]
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
_buildAiDiagnosisSourceSignature() {
var stats = this.data.stats || {}
var list = this.data.list || []
var firstItem = list[0] || {}
return aiCache.buildSignature(stats, list)
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
    var sig = this._buildAiDiagnosisSourceSignature()
    var uid = this._getUserId()
    var now = Date.now()
    this._aiDiagnosisCachedAt = now
    aiCache.save(uid, normalized, sig)
    var detailState = this._buildAiInsightDetails(normalized)
    this.setData({
      aiDiagnosis: normalized, aiDiagnosisLoading: false, aiDiagnosisRefreshing: false,
      aiDiagnosisCacheTimeLabel: aiCache.formatCacheTime(now), aiDiagnosisCacheStale: false,
      aiDiagnosisError: false,
      aiInsightText: this._oneLineInsight(normalized.summary) || this.data.aiInsightText,
      ...detailState,
    })
    return normalized
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
