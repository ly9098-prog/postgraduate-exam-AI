const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { inspectSource } = require('./learning-controller-budgets')
const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const PAGE = 'miniprogram/subpackages/study/wrong-detail/wrong-detail.js'
const DIRECTORY = 'miniprogram/subpackages/study/wrong-detail/utils'
const PAGE_CEILING = 502
const MODULES = ['teacher-action-controller.js', 'wrong-detail-ai-state.js',
  'wrong-detail-question-view.js', 'wrong-detail-teacher-page-adapter.js',
  'wrong-detail-content-transition.js',
  'wrong-detail-navigation-data.js', 'wrong-detail-navigation-flow.js',
  'wrong-detail-ai-recovery.js', 'wrong-detail-ai-generation.js',
  'wrong-detail-ai-regeneration.js', 'wrong-detail-ai-request.js',
  'wrong-detail-ai-availability.js',
  'wrong-detail-diagnosis-flow.js', 'wrong-detail-load-flow.js',
  'wrong-detail-lifecycle.js', 'wrong-detail-master-flow.js', 'wrong-detail-master-undo.js', 'wrong-detail-remove-flow.js',
  'wrong-detail-render-safety.js', 'wrong-detail-teacher-interaction.js']
const DIRECT_HELPERS = ['_aiPollDelayMs', '_isTimeoutError', '_generationMarker',
  '_fallbackMessage', '_isWqMastered']
const TRANSITION_DELEGATES = {
  "onAiSwipeStart": "onAiSwipeStart(e) {\nreturn contentTransition.onAiSwipeStart(this, e)\n}",
  "onAiSwipeEnd": "onAiSwipeEnd(e) {\nreturn contentTransition.onAiSwipeEnd(this, e)\n}",
  "onAiSwipeCancel": "onAiSwipeCancel() {\nreturn contentTransition.onAiSwipeCancel(this)\n}",
  "_beginContentSwitchTransition": "_beginContentSwitchTransition(direction) {\nreturn contentTransition._beginContentSwitchTransition(this, direction)\n}",
  "_waitForContentSwitchOut": "async _waitForContentSwitchOut(direction, animMs) {\nreturn contentTransition._waitForContentSwitchOut(this, direction, animMs, { QUESTION_SWITCH_OUT_MS, _sleep })\n}",
  "_finishContentSwitchTransition": "_finishContentSwitchTransition(direction) {\nreturn contentTransition._finishContentSwitchTransition(this, direction, { QUESTION_SWITCH_IN_MS })\n}",
  "_cancelContentSwitchTransition": "_cancelContentSwitchTransition() {\nreturn contentTransition._cancelContentSwitchTransition(this)\n}",
  "_armSwitchWatchdog": "_armSwitchWatchdog(ms) {\nreturn contentTransition._armSwitchWatchdog(this, ms, { QUESTION_SWITCH_WATCHDOG_MS })\n}",
  "_clearSwitchWatchdog": "_clearSwitchWatchdog() {\nreturn contentTransition._clearSwitchWatchdog(this)\n}",
  "_forceResetSwitchLock": "_forceResetSwitchLock() {\nreturn contentTransition._forceResetSwitchLock(this)\n}"
}
const NAVIGATION_DELEGATES = {
  "_prepareNavigationData": "async _prepareNavigationData(idx, navigationSeq) {\nreturn navigationData._prepareNavigationData(this, idx, navigationSeq, { fetchWrongQuestion: wqId => api.get(`/wrong-questions/${wqId}`), _processWqData: (wq, safeMode) => _processWqData(wq, safeMode), _resolvePreferredAnalysis: wq => _resolvePreferredAnalysis(wq), _normalizeAiResult: result => _normalizeAiResult(result) })\n}",
  "_buildNavigateDataPatch": "_buildNavigateDataPatch(wq, raw, idx) {\nreturn navigationData._buildNavigateDataPatch(this, wq, raw, idx, { _isWqMastered, errorDiagnosis })\n}",
  "_dropQuestionFromNavigation": "_dropQuestionFromNavigation(wqId) {\nreturn navigationFlow._dropQuestionFromNavigation(this, wqId, { writeNavigation: value => wx.setStorageSync('wrong_detail_nav', value) })\n}",
  "_navigateTo": "async _navigateTo(idx, animMs, direction) {\nreturn navigationFlow._navigateTo(this, idx, animMs, direction)\n}",
  "_commitNavigation": "async _commitNavigation(ctx, switchDirection, animMs, navigationSeq) {\nreturn navigationFlow._commitNavigation(this, ctx, switchDirection, animMs, navigationSeq, { QUESTION_SWITCH_ANIM_WATCHDOG_MS })\n}",
  "_handleNavigateError": "_handleNavigateError(e, navigationSeq) {\nreturn navigationFlow._handleNavigateError(this, e, navigationSeq, { showToast: options => wx.showToast(options) })\n}"
}
const AI_RECOVERY_DELEGATES = {
  "_isCurrentAiRequest": "_isCurrentAiRequest(requestId, wqId) {\nreturn aiRecovery._isCurrentAiRequest(this, requestId, wqId)\n}",
  "_pollPersistedAiAnalysis": "async _pollPersistedAiAnalysis(wqId, requestId, options) {\nreturn aiRecovery._pollPersistedAiAnalysis(this, wqId, requestId, options, { AI_CACHE_POLL_ATTEMPTS, _sleep, _aiPollDelayMs, fetchStatus: id => api.get(`/ai/error-analysis/status/${id}`, {}, { timeout: 10000, suppressNetworkToast: true }), _normalizeAiPayload: value => _normalizeAiPayload(value), _hasAiContent: value => _hasAiContent(value) })\n}",
  "_applyRecoveredAiResult": "_applyRecoveredAiResult(recovered, options) {\nreturn aiRecovery._applyRecoveredAiResult(this, recovered, options, { _generationMarker, _normalizeAiResult: value => _normalizeAiResult(value) })\n}"
}
const AI_GENERATION_DELEGATES = {
  "loadAiAnalysis": "async loadAiAnalysis(wqId) {\nreturn aiGeneration.loadAiAnalysis(this, wqId, { _generationMarker })\n}",
  "_applyAiAnalysisResult": "async _applyAiAnalysisResult(result, wqId, requestId, baselineGeneratedAt) {\nreturn aiGeneration._applyAiAnalysisResult(this, result, wqId, requestId, baselineGeneratedAt, { _normalizeAiPayload: value => _normalizeAiPayload(value), _hasAiContent: value => _hasAiContent(value) })\n}",
  "_commitAiAnalysisSuccess": "_commitAiAnalysisSuccess(result, normalized, wqId) {\nreturn aiGeneration._commitAiAnalysisSuccess(this, result, normalized, wqId, { _normalizeAiResult: value => _normalizeAiResult(value) })\n}",
  "_handleAiAnalysisError": "async _handleAiAnalysisError(e, wqId, requestId, baselineGeneratedAt) {\nreturn aiGeneration._handleAiAnalysisError(this, e, wqId, requestId, baselineGeneratedAt, { _isTimeoutError, _shouldRecoverAiRequest: error => aiState._shouldRecoverAiRequest(error) })\n}"
}
const AI_REGENERATION_DELEGATES = {
  "regenerateAiAnalysis": "async regenerateAiAnalysis() {\nreturn aiRegeneration.regenerateAiAnalysis(this, { _generationMarker, runWhenAvailable: (wqId, action) => aiAvailability.runWhenAvailable(this, wqId, action) })\n}",
  "_applyRegenerateResult": "async _applyRegenerateResult(result, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {\nreturn aiRegeneration._applyRegenerateResult(this, result, wqId, requestId, baselineGeneratedAt, oldCards, oldResult, { _normalizeAiPayload: value => _normalizeAiPayload(value), _hasAiContent: value => _hasAiContent(value) })\n}",
  "_handleRegeneratingModel": "async _handleRegeneratingModel(wqId, requestId, baselineGeneratedAt) {\nreturn aiRegeneration._handleRegeneratingModel(this, wqId, requestId, baselineGeneratedAt, { showToast: options => wx.showToast(options) })\n}",
  "_commitRegenerateCachePreserved": "_commitRegenerateCachePreserved(result, normalized, wqId, baselineGeneratedAt) {\nreturn aiRegeneration._commitRegenerateCachePreserved(this, result, normalized, wqId, baselineGeneratedAt, { _normalizeAiResult: value => _normalizeAiResult(value), showToast: options => wx.showToast(options) })\n}",
  "_handleRegenerateFallback": "_handleRegenerateFallback(model, result, oldCards) {\nreturn aiRegeneration._handleRegenerateFallback(this, model, result, oldCards, { showToast: options => wx.showToast(options) })\n}",
  "_handleRegenerateEmpty": "_handleRegenerateEmpty(oldCards) {\nreturn aiRegeneration._handleRegenerateEmpty(this, oldCards, { showToast: options => wx.showToast(options) })\n}",
  "_commitRegenerateSuccess": "_commitRegenerateSuccess(result, normalized, wqId) {\nreturn aiRegeneration._commitRegenerateSuccess(this, result, normalized, wqId, { _normalizeAiResult: value => _normalizeAiResult(value), showToast: options => wx.showToast(options) })\n}",
  "_handleRegenerateError": "_handleRegenerateError(e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {\nreturn aiRegeneration._handleRegenerateError(this, e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult)\n}",
  "_handleRegenerateRecovery": "async _handleRegenerateRecovery(e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult) {\nreturn aiRegeneration._handleRegenerateRecovery(this, e, wqId, requestId, baselineGeneratedAt, oldCards, oldResult, { _shouldRecoverAiRequest: error => aiState._shouldRecoverAiRequest(error), showToast: options => wx.showToast(options) })\n}",
  "_handleRegenerateTimeout": "_handleRegenerateTimeout(e, oldCards, oldResult) {\nreturn aiRegeneration._handleRegenerateTimeout(this, e, oldCards, oldResult, { _isTimeoutError, showToast: options => wx.showToast(options) })\n}"
}
const AI_REQUEST_DELEGATES = {
  "_resetAiLoadingState": "_resetAiLoadingState() {\nreturn aiRequest._resetAiLoadingState(this)\n}",
  "_syncWqCacheAi": "_syncWqCacheAi(wqId, normalized, generatedAt) {\nreturn aiRequest._syncWqCacheAi(this, wqId, normalized, generatedAt)\n}",
  "_requestAiAnalysis": "async _requestAiAnalysis(wqId, forceRegenerate) {\nreturn aiRequest._requestAiAnalysis(wqId, forceRegenerate, { postAnalysis: (payload, options) => api.post('/ai/error-analysis', payload, options), AI_REQUEST_TIMEOUT_MS, applyAvailability: state => this._applyAiAvailability(state), waitForAvailability: action => aiAvailability.runWhenAvailable(this, wqId, action), isCurrent: this._isCurrentAiRequest.bind(this, this._aiRequestId, wqId) })\n}",
  "_enqueueAiRecovery": "async _enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt) {\nreturn aiRequest._enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt, { postRecovery: (payload, options) => api.post('/ai/error-analysis/recover', payload, options) })\n}",
  "_analysisFailureState": "_analysisFailureState(model, result) {\nreturn aiRequest._analysisFailureState(model, result, { _fallbackMessage })\n}",
  "onTapAiAnalysis": "onTapAiAnalysis() {\nreturn aiRequest.onTapAiAnalysis(this, { showToast: options => wx.showToast(options), runWhenAvailable: (wqId, action) => aiAvailability.runWhenAvailable(this, wqId, action) })\n}"
}
const AI_AVAILABILITY_DELEGATES = {
  "_initAiAvailabilityState": "_initAiAvailabilityState() { return aiAvailability._initAiAvailabilityState(this) }",
  "_applyAiAvailability": "_applyAiAvailability(state) { return aiAvailability._applyAvailability(this, state) }",
  "_availabilityFromAiError": "_availabilityFromAiError(error) { return aiAvailability._availabilityFromError(error) }",
  "_scheduleAiAvailabilityRetry": "_scheduleAiAvailabilityRetry(delay) { return aiAvailability._scheduleAiAvailabilityRetry(this, delay) }",
  "_clearAiAvailabilityRetry": "_clearAiAvailabilityRetry() { return aiAvailability._clearAiAvailabilityRetry(this) }",
  "_refreshAiAvailability": "async _refreshAiAvailability(options) { return aiAvailability._refreshAiAvailability(this, Object.assign({ requestClient: api }, options)) }",
  "_clearAiAvailabilityState": "_clearAiAvailabilityState() { return aiAvailability._clearAiAvailabilityState(this) }"
}
const DIAGNOSIS_DELEGATES = {
  "openDiagnosisSheet": "openDiagnosisSheet() {\nreturn diagnosisFlow.openDiagnosisSheet(this)\n}",
  "closeDiagnosisSheet": "closeDiagnosisSheet() {\nreturn diagnosisFlow.closeDiagnosisSheet(this)\n}",
  "selectDiagnosisPrimary": "selectDiagnosisPrimary(e) {\nreturn diagnosisFlow.selectDiagnosisPrimary(this, e)\n}",
  "toggleDiagnosisSecondary": "toggleDiagnosisSecondary(e) {\nreturn diagnosisFlow.toggleDiagnosisSecondary(this, e, { get platform() { return wx } })\n}",
  "saveDiagnosis": "async saveDiagnosis() {\nreturn diagnosisFlow.saveDiagnosis(this, { requestClient: api, errorDiagnosis, get platform() { return wx } })\n}",
  "openNextErrorAction": "openNextErrorAction() {\nreturn diagnosisFlow.openNextErrorAction(this, { get platform() { return wx } })\n}",
  "_refreshDiagnosisFromServer": "async _refreshDiagnosisFromServer(wqId, fallbackRaw) {\nreturn diagnosisFlow._refreshDiagnosisFromServer(this, wqId, fallbackRaw, { requestClient: api, errorDiagnosis })\n}"
}
const LOAD_DELEGATES = {
  "loadData": "async loadData(wqId) {\nreturn loadFlow.loadData(this, wqId, { requestClient: api })\n}",
  "_loadDataInitialPatch": "_loadDataInitialPatch() {\nreturn loadFlow._loadDataInitialPatch()\n}",
  "_buildLoadedDataPatch": "_buildLoadedDataPatch(wq, wqId, loadSeq) {\nreturn loadFlow._buildLoadedDataPatch(this, wq, wqId, loadSeq, { _processWqData: (wq, safeMode) => _processWqData(wq, safeMode), _generationMarker })\n}",
  "_buildLoadedDataFields": "_buildLoadedDataFields(wq, currentQuestion, wrongQuestions, raw, totalQ) {\nreturn loadFlow._buildLoadedDataFields(this, wq, currentQuestion, wrongQuestions, raw, totalQ, { _isWqMastered, errorDiagnosis })\n}",
  "_applyPreferredAnalysisToData": "_applyPreferredAnalysisToData(data, wq) {\nreturn loadFlow._applyPreferredAnalysisToData(this, data, wq, { _resolvePreferredAnalysis: wq => _resolvePreferredAnalysis(wq), _hasAiContent: value => _hasAiContent(value), _normalizeAiResult: value => _normalizeAiResult(value) })\n}",
  "_checkLoadedRenderInvariant": "_checkLoadedRenderInvariant(data) {\nreturn loadFlow._checkLoadedRenderInvariant(this, data)\n}",
  "_handleLoadDataError": "_handleLoadDataError(e, loadSeq) {\nreturn loadFlow._handleLoadDataError(this, e, loadSeq)\n}",
  "_prefetchWrongQuestion": "_prefetchWrongQuestion(idx) {\nreturn loadFlow._prefetchWrongQuestion(this, idx, { requestClient: api })\n}"
}
const LIFECYCLE_DELEGATES = {
  "onLoad": "onLoad(options) {\nreturn lifecycle.onLoad(this, options)\n}",
  "_initWrongDetailState": "_initWrongDetailState() {\nreturn lifecycle._initWrongDetailState(this, { setRenderGuardPage })\n}",
  "_initWrongDetailFromOptions": "_initWrongDetailFromOptions(options) {\nreturn lifecycle._initWrongDetailFromOptions(this, options)\n}",
  "_resolveQuestionIds": "_resolveQuestionIds(options, currentId) {\nreturn lifecycle._resolveQuestionIds(options, currentId, { get platform() { return wx } })\n}",
  "onShow": "onShow() {\nreturn lifecycle.onShow(this, { resumeAvailability: () => aiAvailability.resumeAvailability(this) })\n}",
  "onHide": "onHide() {\nreturn lifecycle.onHide(this, { pauseAvailability: () => aiAvailability.pauseAvailability(this) })\n}",
  "onPageScroll": "onPageScroll() {\nreturn lifecycle.onPageScroll(this)\n}",
  "onPageInteraction": "onPageInteraction() {\nreturn lifecycle.onPageInteraction(this)\n}",
  "_clearBottomActionsTimer": "_clearBottomActionsTimer() {\nreturn lifecycle._clearBottomActionsTimer(this)\n}",
  "_scheduleBottomActionsAutoHide": "_scheduleBottomActionsAutoHide() {\nreturn lifecycle._scheduleBottomActionsAutoHide(this)\n}",
  "_showBottomActions": "_showBottomActions() {\nreturn lifecycle._showBottomActions(this)\n}",
  "onUnload": "onUnload() {\nreturn lifecycle.onUnload(this, { resetRenderGuard })\n}"
}
const MASTER_DELEGATES = {
  "openMasterConfirm": "openMasterConfirm() {\nreturn masterFlow.openMasterConfirm(this)\n}",
  "closeMasterConfirm": "closeMasterConfirm() {\nreturn masterFlow.closeMasterConfirm(this)\n}",
  "openUnmasterConfirm": "openUnmasterConfirm() {\nreturn masterFlow.openUnmasterConfirm(this)\n}",
  "closeUnmasterConfirm": "closeUnmasterConfirm() {\nreturn masterFlow.closeUnmasterConfirm(this)\n}",
  "onMasterAction": "onMasterAction() {\nreturn masterFlow.onMasterAction(this)\n}",
  "confirmMastered": "async confirmMastered() {\nreturn masterFlow.confirmMastered(this, { requestClient: api })\n}",
  "_handleMasterResult": "async _handleMasterResult(masterResult, wqId) {\nreturn masterFlow._handleMasterResult(this, masterResult, wqId, { get platform() { return wx } })\n}",
  "_applyMasterChanged": "_applyMasterChanged(wqId) {\nreturn masterFlow._applyMasterChanged(this, wqId)\n}",
  "confirmUnmastered": "async confirmUnmastered() {\nreturn masterFlow.confirmUnmastered(this, { requestClient: api, get platform() { return wx } })\n}",
  "undoMastered": "async undoMastered() {\nreturn masterUndo.undoMastered(this, { get platform() { return wx } })\n}",
  "_clearMasterUndoTimers": "_clearMasterUndoTimers() {\nreturn masterUndo._clearMasterUndoTimers(this)\n}",
  "_performUndoMastered": "async _performUndoMastered(pending) {\nreturn masterUndo._performUndoMastered(this, pending, { requestClient: api })\n}",
  "_handleUndoRequestError": "async _handleUndoRequestError(freshError, pending) {\nreturn masterUndo._handleUndoRequestError(this, freshError, pending, { get platform() { return wx } })\n}",
  "_commitUndoMastered": "_commitUndoMastered(pending) {\nreturn masterUndo._commitUndoMastered(this, pending)\n}",
  "_handleUndoMasterError": "_handleUndoMasterError(e, pending) {\nreturn masterUndo._handleUndoMasterError(this, e, pending, { get platform() { return wx } })\n}",
  "_armMasterUndoExpiry": "_armMasterUndoExpiry(ms) {\nreturn masterUndo._armMasterUndoExpiry(this, ms)\n}",
  "_clearMasterUndo": "_clearMasterUndo() {\nreturn masterUndo._clearMasterUndo(this)\n}"
}
const REMOVE_DELEGATES = {
  "openMoreMenu": "openMoreMenu() {\nreturn removeFlow.openMoreMenu(this)\n}",
  "closeMoreMenu": "closeMoreMenu() {\nreturn removeFlow.closeMoreMenu(this)\n}",
  "openRemoveConfirm": "openRemoveConfirm() {\nreturn removeFlow.openRemoveConfirm(this)\n}",
  "closeRemoveConfirm": "closeRemoveConfirm() {\nreturn removeFlow.closeRemoveConfirm(this)\n}",
  "removeFromWrongBook": "async removeFromWrongBook() {\nreturn removeFlow.removeFromWrongBook(this, { requestClient: api, get platform() { return wx } })\n}"
}
const REMAINING_DELEGATES = {
  "toggleTeacherActions": "toggleTeacherActions() {\nreturn teacherInteraction.toggleTeacherActions(this)\n}",
  "_teacherCacheKeyForWrong": "_teacherCacheKeyForWrong(wq, diagnosis, action) {\nreturn teacherInteraction._teacherCacheKeyForWrong(wq, diagnosis, action)\n}",
  "close408TeacherSheet": "close408TeacherSheet() {\nreturn teacherInteraction.close408TeacherSheet(this)\n}",
  "feedback408Teacher": "async feedback408Teacher(e) {\nreturn teacherInteraction.feedback408Teacher(this, e, { requestClient: api, teacher: aiTeacher408, get platform() { return wx } })\n}",
  "_checkRenderInvariant": "_checkRenderInvariant(renderModel) {\nreturn renderSafety._checkRenderInvariant(this, renderModel)\n}",
  "_recordRenderTrace": "_recordRenderTrace(trace) {\nreturn renderSafety._recordRenderTrace(this, trace, { config })\n}",
  "_enterSafeMode": "_enterSafeMode() {\nreturn renderSafety._enterSafeMode(this, { _processWqData: (wq, safeMode) => _processWqData(wq, safeMode) })\n}"
}
const PAGE_GLUE = {
  "run408TeacherAction": "async run408TeacherAction(e) {\n    return this._teacherActionController().run(e)\n  }",
  "goPrevWrong": "goPrevWrong(e) {\nthis._navigateTo(e.detail.index, 150, 'right')\n}",
  "goNextWrong": "goNextWrong(e) {\nthis._navigateTo(e.detail.index, 150, 'left')\n}",
  "goWrongQuestion": "goWrongQuestion(e) {\nthis._navigateTo(e.detail.index, 150)\n}",
  "reloadData": "reloadData() {\nif (this.data.questionIds.length > 0) {\nthis.loadData(this.data.questionIds[this.data.currentIdx])\n} else if (this._currentWqId) {\nthis.loadData(this._currentWqId)\n} else {\nthis.goBack()\n}\n}",
  "goBack": "goBack() {\nconst pages = getCurrentPages()\nif (pages.length > 1) wx.navigateBack()\nelse wx.redirectTo({ url: '/subpackages/study/wrong-book/wrong-book' })\n}",
  "scrollToAiCard": "scrollToAiCard() {\nwx.pageScrollTo({ selector: '#ai-card', duration: 220 })\n}",
  "noop": "noop() {}"
}
const DELEGATES = {
  ...REMAINING_DELEGATES,
  ...PAGE_GLUE,
  ...REMOVE_DELEGATES,
  ...MASTER_DELEGATES,
  ...LIFECYCLE_DELEGATES,
  ...LOAD_DELEGATES,
  ...DIAGNOSIS_DELEGATES,
  ...AI_REQUEST_DELEGATES,
  ...AI_AVAILABILITY_DELEGATES,
  ...AI_REGENERATION_DELEGATES,
  ...AI_GENERATION_DELEGATES,
  ...AI_RECOVERY_DELEGATES,
  ...NAVIGATION_DELEGATES,
  ...TRANSITION_DELEGATES,
  "_processWqData": "function _processWqData(wq, safeMode) {\nreturn processWqData(wq, safeMode, { isTrueFalseType, config, buildRenderModel, adapter, _subjectLabel, _errorTypeLabel })\n}",
  "_normalizeAiResult": "function _normalizeAiResult(content) {\nreturn aiState._normalizeAiResult(content, _buildAiRichText)\n}",
  "_hasStoredAnalysisValue": "function _hasStoredAnalysisValue(raw) {\nreturn aiState._hasStoredAnalysisValue(raw, normalizeAiAnalysisPayload, hasAiAnalysisContent)\n}",
  "_resolvePreferredAnalysis": "function _resolvePreferredAnalysis(wq) {\nreturn aiState._resolvePreferredAnalysis(wq, _hasStoredAnalysisValue, _normalizeAiPayload)\n}",
  "_teacherActionController": "_teacherActionController() {\n    if (!this._teacherActionCtl) {\n      this._teacherActionCtl = createTeacherActionController(buildTeacherActionPageCapabilities(this, { api, aiTeacher408, presentTeacherResult, AI_REQUEST_TIMEOUT_MS }))\n    }\n    return this._teacherActionCtl\n  }"
}
const TEACHER_PORTS = {
  "getAiLoading": "getAiLoading: () => page.data.aiLoading",
  "getAiRegenerating": "getAiRegenerating: () => page.data.aiRegenerating",
  "getTeacherLoadingAction": "getTeacherLoadingAction: () => page.data.teacherLoadingAction",
  "getAiAvailabilityEnabled": "getAiAvailabilityEnabled: () => page.data.aiAvailabilityEnabled === true",
  "getAiAvailabilityMessage": "getAiAvailabilityMessage: () => page.data.aiAvailabilityMessage",
  "getWq": "getWq: () => page.data.wq",
  "getErrorDiagnosis": "getErrorDiagnosis: () => page.data.errorDiagnosis",
  "setData": "setData: patch => page.setData(patch)",
  "showToast": "showToast: options => wx.showToast(options)",
  "buildCacheKey": "buildCacheKey: (wq, diagnosis, action) => page._teacherCacheKeyForWrong(wq, diagnosis, action)",
  "getCacheEntry": "getCacheEntry: key => page._teacherCache && page._teacherCache[key]",
  "setCacheEntry": "setCacheEntry: (key, value) => {\n          if (!page._teacherCache) page._teacherCache = Object.create(null)\n          page._teacherCache[key] = value\n        }",
  "getFeedbackEntry": "getFeedbackEntry: key => (page._teacherFeedbackCache && page._teacherFeedbackCache[key]) || ''",
  "setActiveCacheKey": "setActiveCacheKey: key => { page._activeTeacherCacheKey = key }",
  "getInflight": "getInflight: key => {\n          if (!page._teacherInflight) page._teacherInflight = Object.create(null)\n          return page._teacherInflight[key]\n        }",
  "setInflight": "setInflight: (key, promise) => {\n          if (!page._teacherInflight) page._teacherInflight = Object.create(null)\n          page._teacherInflight[key] = promise\n        }",
  "deleteInflight": "deleteInflight: key => { delete page._teacherInflight[key] }",
  "nextRequestSequence": "nextRequestSequence: () => ++page._teacherRequestSeq",
  "getRequestSequence": "getRequestSequence: () => page._teacherRequestSeq",
  "isAlive": "isAlive: () => page._alive",
  "postTeacher": "postTeacher: payload => api.post('/ai/408-teacher', payload, { timeout: AI_REQUEST_TIMEOUT_MS })",
  "normalizeResult": "normalizeResult: raw => aiTeacher408.normalizeResult(raw)",
  "presentResult": "presentResult: normalized => presentTeacherResult(normalized)",
  "errorMessage": "errorMessage: error => aiTeacher408.errorMessage(error, api)",
  "getAvailabilityFromError": "getAvailabilityFromError: error => page._availabilityFromAiError(error)",
  "applyAvailability": "applyAvailability: state => page._applyAiAvailability(state)"
}

function compact(source) { return source.replace(/\s+/g, '') }

function pageViolations(source) {
  const parsed = ts.createSourceFile(PAGE, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const declarations = new Map()
  const unregistered = []
  function walk(node) {
    if (ts.isCallExpression(node) && node.expression.getText(parsed) === 'Page' &&
      node.arguments[0] && ts.isObjectLiteralExpression(node.arguments[0])) {
      for (const property of node.arguments[0].properties) {
        const callable = ts.isMethodDeclaration(property) || ts.isGetAccessor(property) ||
          ts.isSetAccessor(property) || (ts.isPropertyAssignment(property) &&
            (ts.isFunctionExpression(property.initializer) || ts.isArrowFunction(property.initializer)))
        if (ts.isSpreadAssignment(property)) unregistered.push('unregistered page spread')
        if (callable && property.name &&
          !Object.hasOwn(DELEGATES, property.name.getText(parsed))) {
          unregistered.push('unregistered page method: ' + property.name.getText(parsed))
        }
      }
    }
    if ((ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) && node.name) {
      declarations.set(node.name.getText(parsed), node.getText(parsed))
    }
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  const errors = [...unregistered]
  for (const [name, expected] of Object.entries(DELEGATES)) {
    if (compact(declarations.get(name) || '') !== compact(expected)) errors.push('delegate drift: ' + name)
  }
  for (const name of DIRECT_HELPERS) if (declarations.has(name)) errors.push('helper returned: ' + name)
  const helperImport = 'const { ' + DIRECT_HELPERS.join(', ') + ' } = aiState'
  if (!source.includes(helperImport)) errors.push('AI helper import drift')
  for (const module of MODULES) {
    const request = "require('./utils/" + module.replace(/\.js$/, '') + "')"
    if (source.split(request).length !== 2) errors.push('page import: ' + module)
  }
  errors.push(...inspectSource(source, PAGE).errors.filter(error => !error.includes('module has')))
  if (source.trimEnd().split('\n').length > PAGE_CEILING) errors.push('page budget')
  return errors
}

function teacherPortViolations(source) {
  const parsed = ts.createSourceFile('adapter.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const ports = {}
  function walk(node) {
    if (ts.isReturnStatement(node) && node.expression && ts.isObjectLiteralExpression(node.expression)) {
      for (const property of node.expression.properties) {
        if (property.name) ports[property.name.getText(parsed)] = property.getText(parsed)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  const errors = []
  if (Object.keys(ports).join(',') !== Object.keys(TEACHER_PORTS).join(',')) errors.push('teacher port keys drift')
  for (const [name, expected] of Object.entries(TEACHER_PORTS)) {
    if (compact(ports[name] || '') !== compact(expected)) errors.push('teacher port drift: ' + name)
  }
  return errors
}

function moduleViolations(name, source) {
  if (!MODULES.includes(name)) return ['unregistered module: ' + name]
  const errors = [...inspectSource(source, name).errors]
  const parsed = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function walk(node) {
    if (node.kind === ts.SyntaxKind.ThisKeyword) errors.push(name + ': raw page receiver')
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node) ||
      ((ts.isCallExpression(node) || ts.isNewExpression(node)) &&
        (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
          ['require', 'eval', 'Function'].includes(node.expression.getText(parsed))))) {
      errors.push(name + ': forbidden dependency or dynamic execution')
    }
    if (ts.isIdentifier(node) && ['storage', 'getApp', 'Page'].includes(node.text)) {
      errors.push(name + ': forbidden platform port')
    }
    if (name !== 'wrong-detail-teacher-page-adapter.js' && ts.isIdentifier(node) &&
      ['wx', 'api'].includes(node.text)) errors.push(name + ': forbidden network/platform port')
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  if (name === 'wrong-detail-teacher-page-adapter.js') errors.push(...teacherPortViolations(source))
  return errors
}

function scanWrongDetail(options = {}) {
  const source = options.pageSource === undefined ? fs.readFileSync(path.join(ROOT, PAGE), 'utf8') : options.pageSource
  const modules = options.modules || Object.fromEntries(
    fs.readdirSync(path.join(ROOT, DIRECTORY)).filter(name => name.endsWith('.js'))
      .map(name => [name, fs.readFileSync(path.join(ROOT, DIRECTORY, name), 'utf8')]))
  const errors = pageViolations(source)
  for (const name of MODULES) if (!(name in modules)) errors.push('missing module: ' + name)
  for (const [name, value] of Object.entries(modules)) errors.push(...moduleViolations(name, value))
  return { errors, pageLines: source.trimEnd().split('\n').length,
    modules: Object.keys(modules).length, teacherPorts: Object.keys(TEACHER_PORTS).length }
}

module.exports = { PAGE, DIRECTORY, PAGE_CEILING, MODULES, DIRECT_HELPERS,
  DELEGATES, TRANSITION_DELEGATES, NAVIGATION_DELEGATES, AI_RECOVERY_DELEGATES, AI_GENERATION_DELEGATES, AI_REGENERATION_DELEGATES, AI_REQUEST_DELEGATES, DIAGNOSIS_DELEGATES, LOAD_DELEGATES, TEACHER_PORTS, pageViolations, moduleViolations, teacherPortViolations, scanWrongDetail }

if (require.main === module) {
  const result = scanWrongDetail()
  if (result.errors.length) { console.error(result.errors.join('\n')); process.exitCode = 1 }
  else console.log('Wrong-detail boundaries passed: ' + result.pageLines + ' page lines, ' +
    result.modules + ' modules, ' + result.teacherPorts + ' teacher ports')
}
