const api = require('../../../utils/api')
const config = require('../../../config')
const {
buildRenderModel, resetRenderGuard, setRenderGuardPage
} = require('../utils/stem-render')
const { isTrueFalseType } = require('../utils/answer')
const adapter = require('../utils/question-runner-adapter')
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../utils/ai-analysis-normalizer')
const { buildAiRichText } = require('../utils/ai-math-render')
const errorDiagnosis = require('../utils/error-diagnosis')
const aiTeacher408 = require('../utils/ai-teacher-408')
const { presentTeacherResult } = require('./teacher-presentation')
const { createTeacherActionController } = require('./utils/teacher-action-controller')
const AI_REQUEST_TIMEOUT_MS = 55000
const AI_CACHE_POLL_ATTEMPTS = 44
const QUESTION_SWITCH_OUT_MS = 150
const QUESTION_SWITCH_IN_MS = 170
const QUESTION_SWITCH_WATCHDOG_MS = 35000
const QUESTION_SWITCH_ANIM_WATCHDOG_MS = 5000
const aiState = require('./utils/wrong-detail-ai-state')
const { _aiPollDelayMs, _isTimeoutError, _generationMarker, _fallbackMessage, _isWqMastered } = aiState
const { processWqData } = require('./utils/wrong-detail-question-view')
const { buildTeacherActionPageCapabilities } = require('./utils/wrong-detail-teacher-page-adapter')
const contentTransition = require('./utils/wrong-detail-content-transition')
const navigationData = require('./utils/wrong-detail-navigation-data')
const navigationFlow = require('./utils/wrong-detail-navigation-flow')
const aiRecovery = require('./utils/wrong-detail-ai-recovery')
const aiGeneration = require('./utils/wrong-detail-ai-generation')
const aiRegeneration = require('./utils/wrong-detail-ai-regeneration')
const aiRequest = require('./utils/wrong-detail-ai-request')
const diagnosisFlow = require('./utils/wrong-detail-diagnosis-flow')
const loadFlow = require('./utils/wrong-detail-load-flow')
function _sleep(ms) {
return new Promise(resolve => setTimeout(resolve, ms))
}

function _subjectLabel(s) {
const { getSubjectName } = require('../utils/subject-meta')
return getSubjectName(s)
}
function _errorTypeLabel(t) {
const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
return map[t] || t
}
function _processWqData(wq, safeMode) {
return processWqData(wq, safeMode, { isTrueFalseType, config, buildRenderModel, adapter, _subjectLabel, _errorTypeLabel })
}
function _buildAiRichText(value) {
return buildAiRichText(value)
}
function _normalizeAiResult(content) {
return aiState._normalizeAiResult(content, _buildAiRichText)
}
function _normalizeAiPayload(result) {
if (!result) return null
return normalizeAiAnalysisPayload(result)
}
function _hasAiContent(content) {
return hasAiAnalysisContent(content)
}
function _hasStoredAnalysisValue(raw) {
return aiState._hasStoredAnalysisValue(raw, normalizeAiAnalysisPayload, hasAiAnalysisContent)
}
function _detectAiCache(wq) {
if (!wq) return false
if (wq.ai_analysis_status && wq.ai_analysis_status !== 'ready') return false
return _hasStoredAnalysisValue(wq.ai_analysis)
}
function _resolvePreferredAnalysis(wq) {
return aiState._resolvePreferredAnalysis(wq, _hasStoredAnalysisValue, _normalizeAiPayload)
}

Page({
data: {
wq: null,
aiLoading: false,
aiFallback: false,
aiErrorText: '',
aiRetryable: true,
aiRequested: false,
aiFromCache: false,
loading: true,
errorText: '',
questionIds: [],
currentIdx: 0,
totalQuestions: 0,
safeModeActive: false,
aiCards: null,
aiFromQuestionAnalysis: false,
aiRegenerating: false,
aiSkeletonVisible: false,
aiInlineNotice: '',
contentTransitionClass: '',
showSwitchMask: false,
renderTraces: [],
masterConfirmVisible: false,
unmasterConfirmVisible: false,
masterSubmitting: false,
isCurrentMastered: false,
masterUndoVisible: false,
moreMenuVisible: false,
removeConfirmVisible: false,
removeSubmitting: false,
errorDiagnosis: null,
diagnosisOptions: errorDiagnosis.TAXONOMY.filter(item => item.type !== 'unknown'),
diagnosisSheetVisible: false,
diagnosisPrimary: 'unknown',
diagnosisSecondaryMap: {},
diagnosisSaving: false,
diagnosisSyncing: false,
nextErrorAction: null,
teacherPrimaryActions: aiTeacher408.PRIMARY_ACTIONS,
teacherMoreActions: aiTeacher408.MORE_ACTIONS,
teacherActionsExpanded: false,
teacherLoadingAction: '',
teacherLastAction: '',
teacherResult: null,
teacherSheetVisible: false,
teacherErrorText: '',
teacherFeedbackSent: '',
bottomActionsVisible: true,
currentQuestion: null,
wrongQuestions: [],
runnerProgressPercent: 0,
skeletonOptions: [1, 2, 3, 4],
aiSkeletonSections: [1, 2, 3],
},
_alive: false,
_aiRequestId: 0,
_currentWqId: null,
_switching: false,
_navigationSeq: 0,
_aiResult: null,
_errorTypeLabelText: '',
_aiSwipeStart: null,
_contentTransitionStartedAt: 0,
_contentTransitionDirection: '',
_teacherRequestSeq: 0,
_diagnosisRequestSeq: 0,
_bottomActionsTimer: null,
_bottomActionsLastActiveAt: 0,
  onLoad(options) {
    this._initWrongDetailState()
    this._initWrongDetailFromOptions(options)
  },

  _initWrongDetailState() {
    setRenderGuardPage('wrong-detail')
    this._alive = true
    this._aiRequestId = 0
    this._currentWqId = null
    this._aiGenerationMarker = ''
    this._switching = false
    this._navigationSeq = 0
    this._aiSwipeStart = null
    this._contentTransitionStartedAt = 0
    this._contentTransitionDirection = ''
    this._teacherRequestSeq = 0
    this._diagnosisRequestSeq = 0
    this._teacherCache = Object.create(null)
    this._teacherInflight = Object.create(null)
    this._teacherFeedbackCache = Object.create(null)
    this._activeTeacherCacheKey = ''
    this._wqCache = {}
    this._switchMaskTimer = null
    this._contentTransitionTimer = null
    this._switchWatchdogTimer = null
    this._masterUndoTimer = null
    this._masterAdvanceTimer = null
    this._removeBackTimer = null
    this._bottomActionsTimer = null
    this._bottomActionsLastActiveAt = 0
    this._masterUndoInFlight = false
    this._pendingMasterUndo = null
  },

  _initWrongDetailFromOptions(options) {
    const currentId = Number(options.id)
    if (!Number.isFinite(currentId) || currentId <= 0) {
      this.setData({ loading: false, errorText: '错题ID无效', wq: null })
      return
    }
    const questionIds = this._resolveQuestionIds(options, currentId)
    const currentIdx = questionIds.indexOf(currentId)
    this.setData({
      questionIds,
      currentIdx: currentIdx >= 0 ? currentIdx : 0,
      totalQuestions: questionIds.length,
    })
    this.loadData(currentId)
    this._showBottomActions()
  },

  _resolveQuestionIds(options, currentId) {
    let questionIds = []
    try {
      if (options.source === 'wrong-book' || options.source === 'practice-result' || options.source === 'exam-result') {
        const nav = wx.getStorageSync('wrong_detail_nav')
        if (nav && Array.isArray(nav.ids) && Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000) {
          const normalized = nav.ids.map(Number).filter(Number.isFinite)
          const sourceMatches = !nav.source || nav.source === options.source
          if (sourceMatches && normalized.includes(currentId)) questionIds = normalized
        }
      }
    } catch (_) {}
    if (!questionIds.length) questionIds = [currentId]
    return questionIds
  },
onShow() {
if (this._alive && this.data.wq) this._showBottomActions()
},
onHide() {
this._clearBottomActionsTimer()
},
onPageScroll() {
this._showBottomActions()
},
onPageInteraction() {
this._showBottomActions()
},
_clearBottomActionsTimer() {
if (!this._bottomActionsTimer) return
clearTimeout(this._bottomActionsTimer)
this._bottomActionsTimer = null
},
_scheduleBottomActionsAutoHide() {
if (!this._alive || this._bottomActionsTimer) return
const tick = () => {
this._bottomActionsTimer = null
if (!this._alive) return
const idleFor = Date.now() - Number(this._bottomActionsLastActiveAt || 0)
const wait = Math.max(0, 3000 - idleFor)
if (wait > 0) {
this._bottomActionsTimer = setTimeout(tick, wait)
return
}
if (this.data.bottomActionsVisible) this.setData({ bottomActionsVisible: false })
}
this._bottomActionsTimer = setTimeout(tick, 3000)
},
_showBottomActions() {
if (!this._alive) return
this._bottomActionsLastActiveAt = Date.now()
if (!this.data.bottomActionsVisible) this.setData({ bottomActionsVisible: true })
this._scheduleBottomActionsAutoHide()
},
onUnload() {
this._alive = false
this._aiRequestId++
this._teacherRequestSeq++
this._diagnosisRequestSeq++
if (this._switchMaskTimer) {
clearTimeout(this._switchMaskTimer)
this._switchMaskTimer = null
}
if (this._contentTransitionTimer) {
clearTimeout(this._contentTransitionTimer)
this._contentTransitionTimer = null
}
if (this._switchWatchdogTimer) {
clearTimeout(this._switchWatchdogTimer)
this._switchWatchdogTimer = null
}
if (this._removeBackTimer) {
clearTimeout(this._removeBackTimer)
this._removeBackTimer = null
}
this._clearBottomActionsTimer()
this._clearMasterUndo()
this._wqCache = null
this._teacherCache = null
this._teacherInflight = null
this._teacherFeedbackCache = null
this._activeTeacherCacheKey = ''
this._aiGenerationMarker = ''
resetRenderGuard()
},
  async loadData(wqId) {
return loadFlow.loadData(this, wqId, { requestClient: api })
},

  _loadDataInitialPatch() {
return loadFlow._loadDataInitialPatch()
},

  _buildLoadedDataPatch(wq, wqId, loadSeq) {
return loadFlow._buildLoadedDataPatch(this, wq, wqId, loadSeq, { _processWqData: (wq, safeMode) => _processWqData(wq, safeMode), _generationMarker })
},

  _buildLoadedDataFields(wq, currentQuestion, wrongQuestions, raw, totalQ) {
return loadFlow._buildLoadedDataFields(this, wq, currentQuestion, wrongQuestions, raw, totalQ, { _isWqMastered, errorDiagnosis })
},

  _applyPreferredAnalysisToData(data, wq) {
return loadFlow._applyPreferredAnalysisToData(this, data, wq, { _resolvePreferredAnalysis: wq => _resolvePreferredAnalysis(wq), _hasAiContent: value => _hasAiContent(value), _normalizeAiResult: value => _normalizeAiResult(value) })
},

  _checkLoadedRenderInvariant(data) {
return loadFlow._checkLoadedRenderInvariant(this, data)
},

  _handleLoadDataError(e, loadSeq) {
return loadFlow._handleLoadDataError(this, e, loadSeq)
},
_resetAiLoadingState() {
return aiRequest._resetAiLoadingState(this)
},
_syncWqCacheAi(wqId, normalized, generatedAt) {
return aiRequest._syncWqCacheAi(this, wqId, normalized, generatedAt)
},
async _requestAiAnalysis(wqId, forceRegenerate) {
return aiRequest._requestAiAnalysis(wqId, forceRegenerate, { postAnalysis: (payload, options) => api.post('/ai/error-analysis', payload, options), AI_REQUEST_TIMEOUT_MS })
},
async _enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt) {
return aiRequest._enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt, { postRecovery: (payload, options) => api.post('/ai/error-analysis/recover', payload, options) })
},
_analysisFailureState(model, result) {
return aiRequest._analysisFailureState(model, result, { _fallbackMessage })
},
onTapAiAnalysis() {
return aiRequest.onTapAiAnalysis(this, { showToast: options => wx.showToast(options) })
},
toggleTeacherActions() {
if (this.data.teacherLoadingAction) return
this.setData({ teacherActionsExpanded: !this.data.teacherActionsExpanded })
},
_teacherCacheKeyForWrong(wq, diagnosis, action) {
const item = wq || {}
const d = diagnosis || {}
return [
Number(item.id || 0),
Number(item.question_id || item.questionId || 0),
Number(d.question_version_id || d.questionVersionId || item.question_version_id || item.questionVersionId || 0),
Number(d.id || 0),
String(action || ''),
String(item.wrong_answer || ''),
].join('|')
},
  async run408TeacherAction(e) {
    return this._teacherActionController().run(e)
  },

  _teacherActionController() {
    if (!this._teacherActionCtl) {
      this._teacherActionCtl = createTeacherActionController(buildTeacherActionPageCapabilities(this, { api, aiTeacher408, presentTeacherResult, AI_REQUEST_TIMEOUT_MS }))
    }
    return this._teacherActionCtl
  },
close408TeacherSheet() {
this.setData({ teacherSheetVisible: false })
},
async feedback408Teacher(e) {
if (this.data.teacherFeedbackSent || !this.data.teacherResult) return
const type = String(e.currentTarget.dataset.type || '')
const wq = this.data.wq || {}
const questionId = Number(wq.question_id || wq.questionId || 0)
if (!type || !questionId) return
try {
await aiTeacher408.submitFeedback(api, {
questionId,
feedbackType: type,
result: this.data.teacherResult,
})
if (this._activeTeacherCacheKey) {
if (!this._teacherFeedbackCache) this._teacherFeedbackCache = Object.create(null)
this._teacherFeedbackCache[this._activeTeacherCacheKey] = type
}
this.setData({ teacherFeedbackSent: type })
wx.showToast({ title: '反馈已记录', icon: 'success' })
} catch (error) {
wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
}
},
_isCurrentAiRequest(requestId, wqId) {
return aiRecovery._isCurrentAiRequest(this, requestId, wqId)
},
async _pollPersistedAiAnalysis(wqId, requestId, options) {
return aiRecovery._pollPersistedAiAnalysis(this, wqId, requestId, options, { AI_CACHE_POLL_ATTEMPTS, _sleep, _aiPollDelayMs, fetchStatus: id => api.get(`/ai/error-analysis/status/${id}`, {}, { timeout: 10000, suppressNetworkToast: true }), _normalizeAiPayload: value => _normalizeAiPayload(value), _hasAiContent: value => _hasAiContent(value) })
},
_applyRecoveredAiResult(recovered, options) {
return aiRecovery._applyRecoveredAiResult(this, recovered, options, { _generationMarker, _normalizeAiResult: value => _normalizeAiResult(value) })
},
  async loadAiAnalysis(wqId) {
return aiGeneration.loadAiAnalysis(this, wqId, { _generationMarker })
},

  async _applyAiAnalysisResult(result, wqId, requestId, baselineGeneratedAt) {
return aiGeneration._applyAiAnalysisResult(this, result, wqId, requestId, baselineGeneratedAt, { _normalizeAiPayload: value => _normalizeAiPayload(value), _hasAiContent: value => _hasAiContent(value) })
},

  _commitAiAnalysisSuccess(result, normalized, wqId) {
return aiGeneration._commitAiAnalysisSuccess(this, result, normalized, wqId, { _normalizeAiResult: value => _normalizeAiResult(value) })
},

  async _handleAiAnalysisError(e, wqId, requestId, baselineGeneratedAt) {
return aiGeneration._handleAiAnalysisError(this, e, wqId, requestId, baselineGeneratedAt, { _isTimeoutError })
},
  async regenerateAiAnalysis() {
return aiRegeneration.regenerateAiAnalysis(this, { _generationMarker })
},

  async _applyRegenerateResult(result, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {
return aiRegeneration._applyRegenerateResult(this, result, wqId, requestId, baselineGeneratedAt, oldCards, oldResult, { _normalizeAiPayload: value => _normalizeAiPayload(value), _hasAiContent: value => _hasAiContent(value) })
},

  async _handleRegeneratingModel(wqId, requestId, baselineGeneratedAt) {
return aiRegeneration._handleRegeneratingModel(this, wqId, requestId, baselineGeneratedAt, { showToast: options => wx.showToast(options) })
},

  _commitRegenerateCachePreserved(result, normalized, wqId, baselineGeneratedAt) {
return aiRegeneration._commitRegenerateCachePreserved(this, result, normalized, wqId, baselineGeneratedAt, { _normalizeAiResult: value => _normalizeAiResult(value), showToast: options => wx.showToast(options) })
},

  _handleRegenerateFallback(model, result, oldCards) {
return aiRegeneration._handleRegenerateFallback(this, model, result, oldCards, { showToast: options => wx.showToast(options) })
},

  _handleRegenerateEmpty(oldCards) {
return aiRegeneration._handleRegenerateEmpty(this, oldCards, { showToast: options => wx.showToast(options) })
},

  _commitRegenerateSuccess(result, normalized, wqId) {
return aiRegeneration._commitRegenerateSuccess(this, result, normalized, wqId, { _normalizeAiResult: value => _normalizeAiResult(value), showToast: options => wx.showToast(options) })
},

  _handleRegenerateError(e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {
return aiRegeneration._handleRegenerateError(this, e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult)
},

  async _handleRegenerateRecovery(e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {
return aiRegeneration._handleRegenerateRecovery(this, e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult, { showToast: options => wx.showToast(options) })
},

  _handleRegenerateTimeout(e, oldCards, oldResult) {
return aiRegeneration._handleRegenerateTimeout(this, e, oldCards, oldResult, { _isTimeoutError, showToast: options => wx.showToast(options) })
},
openMasterConfirm() {
if (this.data.masterSubmitting || this.data.isCurrentMastered) return
this.setData({ masterConfirmVisible: true })
},
closeMasterConfirm() {
if (this.data.masterSubmitting) return
this.setData({ masterConfirmVisible: false })
},
openUnmasterConfirm() {
if (this.data.masterSubmitting || !this.data.isCurrentMastered) return
this.setData({ unmasterConfirmVisible: true })
},
closeUnmasterConfirm() {
if (this.data.masterSubmitting) return
this.setData({ unmasterConfirmVisible: false })
},
onMasterAction() {
if (this.data.isCurrentMastered) {
this.openUnmasterConfirm()
} else {
this.openMasterConfirm()
}
},
  async confirmMastered() {
    const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
    if (!wqId || this.data.masterSubmitting) return
    this.setData({ masterSubmitting: true, masterConfirmVisible: false })
    try {
      const masterResult = await api.post('/wrong-questions/batch', {
        action: 'mark_mastered', ids: [wqId],
      })
      if (!this._alive) return
      await this._handleMasterResult(masterResult, wqId)
    } catch (e) {
      if (!this._alive) return
      console.error('标记已掌握失败', e)
      this.setData({ masterSubmitting: false })
    }
  },

  async _handleMasterResult(masterResult, wqId) {
    const masterSkipped = !!(
      masterResult && Array.isArray(masterResult.skipped_ids) &&
      masterResult.skipped_ids.some(id => String(id) === String(wqId))
    )
    const masterChanged = !masterSkipped && !(
      masterResult && masterResult.updated_count != null && Number(masterResult.updated_count) <= 0
    )
    if (!masterChanged) {
      this._clearMasterUndo()
      this.setData({ masterSubmitting: false })
      await this.loadData(wqId)
      if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
      return
    }
    this._applyMasterChanged(wqId)
  },

  _applyMasterChanged(wqId) {
    this._clearMasterUndo()
    this._pendingMasterUndo = { wqId, originalIdx: this.data.currentIdx }
    if (this._wqCache && this._wqCache[wqId]) {
      this._wqCache[wqId].data = Object.assign({}, this._wqCache[wqId].data, { is_mastered: true })
    }
    if (this.data.wq && String(this.data.wq.id) === String(wqId)) {
      this.setData({
        wq: Object.assign({}, this.data.wq, { is_mastered: true }),
        isCurrentMastered: true, masterSubmitting: false, masterUndoVisible: true,
      })
    } else {
      this.setData({ masterSubmitting: false, masterUndoVisible: true })
    }
    this._armMasterUndoExpiry(5000)
    if (this.data.currentIdx < this.data.questionIds.length - 1) {
      this._masterAdvanceTimer = setTimeout(() => {
        this._masterAdvanceTimer = null
        this._navigateTo(this.data.currentIdx + 1, 150)
      }, 120)
    }
  },
async confirmUnmastered() {
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId || this.data.masterSubmitting) return
this.setData({ masterSubmitting: true, unmasterConfirmVisible: false })
try {
const unmasterResult = await api.post('/wrong-questions/batch', {
action: 'unmark_mastered',
ids: [wqId],
})
if (!this._alive) return
const unmasterSkipped = !!(
unmasterResult && Array.isArray(unmasterResult.skipped_ids) &&
unmasterResult.skipped_ids.some(id => String(id) === String(wqId))
)
if (unmasterSkipped || (unmasterResult && unmasterResult.updated_count != null && Number(unmasterResult.updated_count) <= 0)) {
this._clearMasterUndo()
this.setData({ masterSubmitting: false })
await this.loadData(wqId)
if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
return
}
this._clearMasterUndo()
if (this._wqCache && this._wqCache[wqId]) {
this._wqCache[wqId].data = Object.assign({}, this._wqCache[wqId].data, { is_mastered: false })
}
if (this.data.wq && String(this.data.wq.id) === String(wqId)) {
this.setData({
wq: Object.assign({}, this.data.wq, { is_mastered: false }),
isCurrentMastered: false,
masterSubmitting: false,
})
} else {
this.setData({ masterSubmitting: false })
}
wx.showToast({ title: '已重新加入复习', icon: 'none' })
} catch (e) {
if (!this._alive) return
console.error('重新加入复习失败', e)
this.setData({ masterSubmitting: false })
wx.showToast({ title: '操作失败，请重试', icon: 'none' })
}
},
  async undoMastered() {
    const pending = this._pendingMasterUndo
    if (!pending || this._masterUndoInFlight) return
    this._masterUndoInFlight = true
    this._clearMasterUndoTimers()
    try {
      await this._performUndoMastered(pending)
      wx.showToast({ title: '已撤销掌握', icon: 'none' })
    } catch (e) {
      this._handleUndoMasterError(e, pending)
    } finally {
      this._masterUndoInFlight = false
    }
  },

  _clearMasterUndoTimers() {
    if (this._masterUndoTimer) { clearTimeout(this._masterUndoTimer); this._masterUndoTimer = null }
    if (this._masterAdvanceTimer) { clearTimeout(this._masterAdvanceTimer); this._masterAdvanceTimer = null }
  },

  async _performUndoMastered(pending) {
    try {
      await api.post('/wrong-questions/batch', {
        action: 'unmark_mastered', ids: [pending.wqId],
      })
    } catch (freshError) {
      await this._handleUndoRequestError(freshError, pending)
    }
    this._commitUndoMastered(pending)
  },

  async _handleUndoRequestError(freshError, pending) {
    const freshStatus = Number(freshError && (freshError.statusCode || freshError.status)) || 0
    if (freshStatus === 404 || freshStatus === 410) {
      this._clearMasterUndo()
      this._dropQuestionFromNavigation(pending.wqId)
      if (this._alive) wx.showToast({ title: '该错题已被移除，无法撤销', icon: 'none' })
      return
    }
    throw freshError
  },

  _commitUndoMastered(pending) {
    if (this._wqCache && this._wqCache[pending.wqId]) {
      this._wqCache[pending.wqId].data = Object.assign({}, this._wqCache[pending.wqId].data, { is_mastered: false })
    }
    const targetIdx = this.data.questionIds.findIndex(id => String(id) === String(pending.wqId))
    this._clearMasterUndo()
    if (targetIdx >= 0 && targetIdx !== this.data.currentIdx) {
      this._navigateTo(targetIdx, 150)
    } else if (this.data.wq && String(this.data.wq.id) === String(pending.wqId)) {
      this.setData({ wq: Object.assign({}, this.data.wq, { is_mastered: false }), isCurrentMastered: false })
    } else if (targetIdx >= 0) {
      this.loadData(pending.wqId)
    }
  },

  _handleUndoMasterError(e, pending) {
    if (!this._alive) return
    console.error('撤销已掌握失败', e)
    if (this._pendingMasterUndo === pending) {
      this.setData({ masterUndoVisible: true })
      this._armMasterUndoExpiry(5000)
    }
    wx.showToast({ title: '撤销失败，请重试', icon: 'none' })
  },
_armMasterUndoExpiry(ms) {
if (this._masterUndoTimer) clearTimeout(this._masterUndoTimer)
var duration = Number(ms) > 0 ? Number(ms) : 5000
this._masterUndoTimer = setTimeout(() => {
this._pendingMasterUndo = null
this._masterUndoTimer = null
if (this._alive) this.setData({ masterUndoVisible: false })
}, duration)
},
_clearMasterUndo() {
if (this._masterUndoTimer) {
clearTimeout(this._masterUndoTimer)
this._masterUndoTimer = null
}
if (this._masterAdvanceTimer) {
clearTimeout(this._masterAdvanceTimer)
this._masterAdvanceTimer = null
}
this._pendingMasterUndo = null
if (this._alive && this.data && this.data.masterUndoVisible) {
this.setData({ masterUndoVisible: false })
}
},
openMoreMenu() {
this.setData({ moreMenuVisible: true })
},
closeMoreMenu() {
this.setData({ moreMenuVisible: false })
},
openRemoveConfirm() {
this.setData({ moreMenuVisible: false, removeConfirmVisible: true })
},
closeRemoveConfirm() {
if (this.data.removeSubmitting) return
this.setData({ removeConfirmVisible: false })
},
async removeFromWrongBook() {
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId || this.data.removeSubmitting) return
this._clearMasterUndo()
this.setData({ removeSubmitting: true })
try {
await api.post('/wrong-questions/batch', {
action: 'remove_from_book',
ids: [wqId],
})
if (!this._alive) return
const oldIds = this.data.questionIds || []
const currentIdx = this.data.currentIdx
const nextIds = oldIds.filter(id => String(id) !== String(wqId))
if (this._wqCache) delete this._wqCache[wqId]
try {
wx.setStorageSync('wrong_detail_nav', { ids: nextIds, ts: Date.now() })
} catch (_) {}
this.setData({
questionIds: nextIds,
totalQuestions: nextIds.length,
removeConfirmVisible: false,
removeSubmitting: false,
})
if (!nextIds.length) {
wx.showToast({ title: '已移出错题本', icon: 'none' })
if (this._removeBackTimer) clearTimeout(this._removeBackTimer)
this._removeBackTimer = setTimeout(() => {
this._removeBackTimer = null
if (this._alive) this.goBack()
}, 220)
return
}
const nextIdx = Math.min(currentIdx, nextIds.length - 1)
this.setData({ currentIdx: nextIdx })
await this.loadData(nextIds[nextIdx])
wx.showToast({ title: '已移出错题本', icon: 'none' })
} catch (e) {
if (!this._alive) return
console.error('移出错题本失败', e)
this.setData({ removeSubmitting: false })
wx.showToast({ title: '移出失败，请重试', icon: 'none' })
}
},
_checkRenderInvariant(renderModel) {
if (!renderModel) return
if (renderModel.mode === 'CODE' && renderModel.rawText) {
var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
if (hasHtmlLeak) {
console.error('[CODE_HTML_LEAK] wrong-detail CODE rawText contains HTML entities')
}
var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
if (hasRenderViolation) {
console.error('[CODE_RENDER_VIOLATION] wrong-detail CODE mode leaked into html/richTextNodes')
}
if ((hasHtmlLeak || hasRenderViolation) && !this.data.safeModeActive) {
this._enterSafeMode()
}
}
if (renderModel.mode === 'MIXED') {
if (!renderModel.blocks || renderModel.blocks.length === 0) {
console.error('[MIXED_RENDER_VIOLATION] wrong-detail MIXED mode but blocks is empty')
return
}
for (var mi = 0; mi < renderModel.blocks.length; mi++) {
var mBlock = renderModel.blocks[mi]
if (mBlock.type === 'CODE' && mBlock.rawText) {
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
console.error('[CODE_HTML_LEAK] wrong-detail MIXED CODE block #' + mi + ' contains HTML entities')
}
}
}
}
},
_recordRenderTrace(trace) {
if (!trace || !config.debug) return
if (!Array.isArray(this.data.renderTraces)) return
var traces = this.data.renderTraces.concat([trace]).slice(-20)
this.setData({ renderTraces: traces })
},
_enterSafeMode() {
console.warn('[SELF_HEAL] wrong-detail CODE render violation — entering SAFE_MODE')
this.setData({ safeModeActive: true })
if (this.data.wq) {
var raw = _processWqData(this.data.wq, true)
if (raw._renderModel) {
var currentQuestion = Object.assign({}, this.data.wq, {
_optionList: raw._optionList,
_optionKeys: raw._optionKeys,
_opts: raw._opts,
_blankOptionGroups: raw._blankOptionGroups,
_hasBlankOptionGroups: raw._blankOptionGroups.length > 0,
_renderModel: raw._renderModel,
})
this._errorTypeLabelText = raw.errorTypeLabelText
this.setData({
currentQuestion,
subjectLabelText: raw.subjectLabelText,
})
console.warn('[SELF_HEAL] wrong-detail re-rendered in SAFE_MODE, mode=' + raw._renderModel.mode)
}
}
},
onAiSwipeStart(e) {
return contentTransition.onAiSwipeStart(this, e)
},
onAiSwipeEnd(e) {
return contentTransition.onAiSwipeEnd(this, e)
},
onAiSwipeCancel() {
return contentTransition.onAiSwipeCancel(this)
},
_beginContentSwitchTransition(direction) {
return contentTransition._beginContentSwitchTransition(this, direction)
},
async _waitForContentSwitchOut(direction, animMs) {
return contentTransition._waitForContentSwitchOut(this, direction, animMs, { QUESTION_SWITCH_OUT_MS, _sleep })
},
_finishContentSwitchTransition(direction) {
return contentTransition._finishContentSwitchTransition(this, direction, { QUESTION_SWITCH_IN_MS })
},
_cancelContentSwitchTransition() {
return contentTransition._cancelContentSwitchTransition(this)
},
_armSwitchWatchdog(ms) {
return contentTransition._armSwitchWatchdog(this, ms, { QUESTION_SWITCH_WATCHDOG_MS })
},
_clearSwitchWatchdog() {
return contentTransition._clearSwitchWatchdog(this)
},
_forceResetSwitchLock() {
return contentTransition._forceResetSwitchLock(this)
},
goPrevWrong(e) {
this._navigateTo(e.detail.index, 150, 'right')
},
goNextWrong(e) {
this._navigateTo(e.detail.index, 150, 'left')
},
goWrongQuestion(e) {
this._navigateTo(e.detail.index, 150)
},
reloadData() {
if (this.data.questionIds.length > 0) {
this.loadData(this.data.questionIds[this.data.currentIdx])
} else if (this._currentWqId) {
this.loadData(this._currentWqId)
} else {
this.goBack()
}
},
goBack() {
const pages = getCurrentPages()
if (pages.length > 1) wx.navigateBack()
else wx.redirectTo({ url: '/subpackages/study/wrong-book/wrong-book' })
},
_dropQuestionFromNavigation(wqId) {
return navigationFlow._dropQuestionFromNavigation(this, wqId, { writeNavigation: value => wx.setStorageSync('wrong_detail_nav', value) })
},
  async _navigateTo(idx, animMs, direction) {
return navigationFlow._navigateTo(this, idx, animMs, direction)
},

  async _prepareNavigationData(idx, navigationSeq) {
return navigationData._prepareNavigationData(this, idx, navigationSeq, { fetchWrongQuestion: wqId => api.get(`/wrong-questions/${wqId}`), _processWqData: (wq, safeMode) => _processWqData(wq, safeMode), _resolvePreferredAnalysis: wq => _resolvePreferredAnalysis(wq), _normalizeAiResult: result => _normalizeAiResult(result) })
},

  _buildNavigateDataPatch(wq, raw, idx) {
return navigationData._buildNavigateDataPatch(this, wq, raw, idx, { _isWqMastered, errorDiagnosis })
},

  async _commitNavigation(ctx, switchDirection, animMs, navigationSeq) {
return navigationFlow._commitNavigation(this, ctx, switchDirection, animMs, navigationSeq, { QUESTION_SWITCH_ANIM_WATCHDOG_MS })
},

  _handleNavigateError(e, navigationSeq) {
return navigationFlow._handleNavigateError(this, e, navigationSeq, { showToast: options => wx.showToast(options) })
},
openDiagnosisSheet() {
return diagnosisFlow.openDiagnosisSheet(this)
},
closeDiagnosisSheet() {
return diagnosisFlow.closeDiagnosisSheet(this)
},
selectDiagnosisPrimary(e) {
return diagnosisFlow.selectDiagnosisPrimary(this, e)
},
toggleDiagnosisSecondary(e) {
return diagnosisFlow.toggleDiagnosisSecondary(this, e, { get platform() { return wx } })
},
async saveDiagnosis() {
return diagnosisFlow.saveDiagnosis(this, { requestClient: api, errorDiagnosis, get platform() { return wx } })
},
openNextErrorAction() {
return diagnosisFlow.openNextErrorAction(this, { get platform() { return wx } })
},
async _refreshDiagnosisFromServer(wqId, fallbackRaw) {
return diagnosisFlow._refreshDiagnosisFromServer(this, wqId, fallbackRaw, { requestClient: api, errorDiagnosis })
},
scrollToAiCard() {
wx.pageScrollTo({ selector: '#ai-card', duration: 220 })
},
noop() {},
_prefetchWrongQuestion(idx) {
return loadFlow._prefetchWrongQuestion(this, idx, { requestClient: api })
},
})
