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
const lifecycle = require('./utils/wrong-detail-lifecycle')
const masterFlow = require('./utils/wrong-detail-master-flow')
const masterUndo = require('./utils/wrong-detail-master-undo')
const removeFlow = require('./utils/wrong-detail-remove-flow')
const renderSafety = require('./utils/wrong-detail-render-safety')
const teacherInteraction = require('./utils/wrong-detail-teacher-interaction')
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
return lifecycle.onLoad(this, options)
},

  _initWrongDetailState() {
return lifecycle._initWrongDetailState(this, { setRenderGuardPage })
},

  _initWrongDetailFromOptions(options) {
return lifecycle._initWrongDetailFromOptions(this, options)
},

  _resolveQuestionIds(options, currentId) {
return lifecycle._resolveQuestionIds(options, currentId, { get platform() { return wx } })
},
onShow() {
return lifecycle.onShow(this)
},
onHide() {
return lifecycle.onHide(this)
},
onPageScroll() {
return lifecycle.onPageScroll(this)
},
onPageInteraction() {
return lifecycle.onPageInteraction(this)
},
_clearBottomActionsTimer() {
return lifecycle._clearBottomActionsTimer(this)
},
_scheduleBottomActionsAutoHide() {
return lifecycle._scheduleBottomActionsAutoHide(this)
},
_showBottomActions() {
return lifecycle._showBottomActions(this)
},
onUnload() {
return lifecycle.onUnload(this, { resetRenderGuard })
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
return teacherInteraction.toggleTeacherActions(this)
},
_teacherCacheKeyForWrong(wq, diagnosis, action) {
return teacherInteraction._teacherCacheKeyForWrong(wq, diagnosis, action)
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
return teacherInteraction.close408TeacherSheet(this)
},
async feedback408Teacher(e) {
return teacherInteraction.feedback408Teacher(this, e, { requestClient: api, teacher: aiTeacher408, get platform() { return wx } })
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
return masterFlow.openMasterConfirm(this)
},
closeMasterConfirm() {
return masterFlow.closeMasterConfirm(this)
},
openUnmasterConfirm() {
return masterFlow.openUnmasterConfirm(this)
},
closeUnmasterConfirm() {
return masterFlow.closeUnmasterConfirm(this)
},
onMasterAction() {
return masterFlow.onMasterAction(this)
},
  async confirmMastered() {
return masterFlow.confirmMastered(this, { requestClient: api })
},

  async _handleMasterResult(masterResult, wqId) {
return masterFlow._handleMasterResult(this, masterResult, wqId, { get platform() { return wx } })
},

  _applyMasterChanged(wqId) {
return masterFlow._applyMasterChanged(this, wqId)
},
async confirmUnmastered() {
return masterFlow.confirmUnmastered(this, { requestClient: api, get platform() { return wx } })
},
  async undoMastered() {
return masterUndo.undoMastered(this, { get platform() { return wx } })
},

  _clearMasterUndoTimers() {
return masterUndo._clearMasterUndoTimers(this)
},

  async _performUndoMastered(pending) {
return masterUndo._performUndoMastered(this, pending, { requestClient: api })
},

  async _handleUndoRequestError(freshError, pending) {
return masterUndo._handleUndoRequestError(this, freshError, pending, { get platform() { return wx } })
},

  _commitUndoMastered(pending) {
return masterUndo._commitUndoMastered(this, pending)
},

  _handleUndoMasterError(e, pending) {
return masterUndo._handleUndoMasterError(this, e, pending, { get platform() { return wx } })
},
_armMasterUndoExpiry(ms) {
return masterUndo._armMasterUndoExpiry(this, ms)
},
_clearMasterUndo() {
return masterUndo._clearMasterUndo(this)
},
openMoreMenu() {
return removeFlow.openMoreMenu(this)
},
closeMoreMenu() {
return removeFlow.closeMoreMenu(this)
},
openRemoveConfirm() {
return removeFlow.openRemoveConfirm(this)
},
closeRemoveConfirm() {
return removeFlow.closeRemoveConfirm(this)
},
async removeFromWrongBook() {
return removeFlow.removeFromWrongBook(this, { requestClient: api, get platform() { return wx } })
},
_checkRenderInvariant(renderModel) {
return renderSafety._checkRenderInvariant(this, renderModel)
},
_recordRenderTrace(trace) {
return renderSafety._recordRenderTrace(this, trace, { config })
},
_enterSafeMode() {
return renderSafety._enterSafeMode(this, { _processWqData: (wq, safeMode) => _processWqData(wq, safeMode) })
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
