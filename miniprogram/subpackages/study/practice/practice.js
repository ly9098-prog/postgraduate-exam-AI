const subjectPage = require('./utils/practice-subject-page-adapter')
const exitPage = require('./utils/practice-exit-page-adapter')
const questionPage = require('./utils/practice-question-page-adapter')
const submitPage = require('./utils/practice-submit-page-adapter')
const lifecycleFlow = require('./utils/practice-lifecycle-flow')
const launchFlow = require('./utils/practice-launch-flow')
const api = require('../../../utils/api')
const config = require('../../../config')
const { debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../../utils/debug')
const { buildRenderModel, setRenderGuardPage, resetRenderGuard } = require('../utils/stem-render')
const adapter = require('../utils/question-runner-adapter')
const questionImageCache = require('../utils/question-image-cache')
const { filter408SubjectTree } = require('../utils/subject-scope')
const { safeDecodeURIComponent } = require('../utils/route-params')
const {
  normalizeSubjectTree,
  flattenSelectableSubjects,
  subjectMark,
  subjectIconMeta,
  decorateRecentSubjects,
  findParentSubjectId,
  subjectHasChildren,
  getPracticeSubjectScopeIds,
} = require('./utils/subject-tree')
const {
  parseLaunchPreset,
  launchPresetOverrides,
  fastLaunchPresetView,
  resolvedLaunchPresetView,
  applyLaunchOverrides,
} = require('./utils/launch-preset')
const {
  buildQuestionRequestParams,
  validateKnowledgeScope,
  findQuestionBatchError,
} = require('./utils/question-batch')
const {
  RECENT_SUBJECTS_STORAGE_KEY,
  selectDefaultSubject,
} = require('./utils/recent-subjects')
const { createRecentSubjectController } = require('./utils/recent-subject-controller')
const { createSubjectSheetController } = require('./utils/subject-sheet-controller')
const { createSubjectSelectionController } = require('./utils/subject-selection-controller')
const { createLaunchReturnController } = require('./utils/launch-return-controller')
const { createExitGuardController } = require('./utils/exit-guard-controller')
const { createExitRequestController } = require('./utils/exit-request-controller')
const { createPausedConfirmController } = require('./utils/paused-confirm-controller')
const { createSubmittedResultController } = require('./utils/submitted-result-controller')
const { createSubmitSuccessController } = require('./utils/submit-success-controller')
const { createSubmitFlowController } = require('./utils/submit-flow-controller')
const { createStartPracticeController } = require('./utils/start-practice-controller')
const { createImageWarmController } = require('./utils/image-warm-controller')
const { createSubmissionLockController } = require('./utils/submission-lock-controller')
const {
  buildResetView,
  applyBatchCredentials,
  hasMissingBatchCredentials,
  buildSequentialRestartView,
  resetSequentialTiming,
  buildLoadedView,
} = require('./utils/question-load-state')
const {
  createSequentialRestartController,
} = require('./utils/sequential-restart-controller')
const {
  createPracticeAnswerInteractionController,
} = require('./utils/answer-interaction-controller')
const {
  createPracticeQuestionDisplayController,
} = require('./utils/question-display-controller')
const {
  createComputedFieldsController,
} = require('./utils/computed-fields-controller')
const {
  createAnswerFeedbackController,
} = require('./utils/answer-feedback-controller')
const {
  createRenderInvariantController,
} = require('./utils/render-invariant-controller')
const {
  createQuestionTimerController,
} = require('./utils/question-timer-controller')
const {
  createPracticeLifecyclePageController,
} = require('./utils/practice-lifecycle-page-adapter')
const {
  createPracticeSessionTimerPageController,
} = require('./utils/practice-session-timer-page-adapter')
const {
  createPracticeSubjectLoadPageController,
} = require('./utils/practice-subject-load-page-adapter')
const {
  createQuestionLoadController,
} = require('./utils/question-load-controller')
const {
  createQuestionLoadWiring,
} = require('./utils/question-load-wiring')
const {
  createPendingSubmissionController,
} = require('./utils/pending-submission-controller')
const {
  monotonicNow,
} = require('./utils/monotonic-clock')
const {
  createSelfHealController,
} = require('./utils/self-heal-controller')
const {
  buildPracticeResultUrl,
} = require('./utils/result-url-builder')
const {
  buildStoredResults,
  buildLightQuestions,
  computeDisplaySkippedCount,
} = require('./utils/submit-result-builder')
const {
  buildSubmitResultPayload,
} = require('./utils/submit-result-payload')
const {
  createSubmitErrorController,
} = require('./utils/submit-error-controller')
const {
  createSubmitEntryController,
} = require('./utils/submit-entry-controller')
const {
  resolveBatchErrorRecovery,
} = require('./utils/batch-error-recovery')
const {
  buildRecoveryQuestions,
} = require('./utils/recovery-questions-builder')
const {
  buildSubmissionSnapshot,
} = require('./utils/submission-snapshot-builder')
const {
  buildSubmitPayload,
  isDeterministicReject,
  resolveRejectMessage,
} = require('./utils/submit-payload-builder')
const {
  classifyAnswers,
} = require('./utils/answer-classification')
const {
  buildSubmitAnswers,
  buildSubmitSession,
} = require('./utils/submit-session-builder')
const PRACTICE_PENDING_SUBMISSION_KEY_PREFIX = 'practice_pending_submission_v1'
const PRACTICE_PENDING_SUBMISSION_TTL_MS = 24 * 60 * 60 * 1000
const PRACTICE_ANSWERABLE_TYPES = new Set(['single_choice', 'multiple_choice', 'true_false', 'multi_blank_choice', 'multi_blank_multiple_choice'])
Page({
_pageAlive: false,
_practiceSession: {},
_lastSubjectOptionTap: null,
data: {
subjectTree: [],
selectedSubjectId: null,
selectedSubjectName: '',
selectedSubjectHasChildren: false,
expandedSubjectId: null,
selectedMode: 'random',
selectedModeLabel: '随机挑战',
count: 5,
countDisplay: '05',
estimatedMinutes: 10,
settingsExpanded: false,
subjectSheetVisible: false,
subjectSheetClosing: false,
recentSubjects: [],
statusBarHeight: 20,
navBarHeight: 44,
started: false,
loading: false,
launchingPreset: false,
entryResolved: false,
submitting: false,
practiceExitGuardVisible: false,
progressPercent: 0,
errorText: '',
sequentialProgress: null,
questions: [],
currentIndex: 0,
totalQuestions: 0,
currentQuestion: null,
currentAnswerState: null,
answeredCount: 0,
submitted: false,
feedbackVisible: false,
feedbackType: '',
feedbackTitle: '',
feedbackDetail: '',
feedbackComboText: '',
feedbackComboLevel: '',
feedbackStarCount: 0,
elapsedText: '00:00',
_timer: null,
enableMathImage: false,
},
onLoad(options) {
return lifecycleFlow.onLoad(this, options, { resetRenderGuard, setRenderGuardPage })
},
onUnload() {
return lifecycleFlow.onUnload(this, { getClearTimeout: () => clearTimeout, resetRenderGuard })
},
_resetSession() {
return lifecycleFlow._resetSession(this)
},
_getCurrentUserId() {
return lifecycleFlow._getCurrentUserId(this, { getPlatform: () => wx })
},
_pendingSubmissionStorageKey() {
return lifecycleFlow._pendingSubmissionStorageKey(this, { PRACTICE_PENDING_SUBMISSION_KEY_PREFIX })
},
_readPendingSubmission() {
return this._pendingSubmissionController().read()
},
_persistPendingSubmission(submission, status, resultUrl) {
return this._pendingSubmissionController().persist(submission, status, resultUrl)
},
_clearPendingSubmission(requestId) {
this._pendingSubmissionController().clear(requestId)
},
async _offerPendingSubmissionRecovery() {
return this._pendingSubmissionController().offerRecovery()
},
_pendingSubmissionController() {
return submitPage._pendingSubmissionController(this, { PRACTICE_PENDING_SUBMISSION_TTL_MS, createPendingSubmissionController, getConsole: () => console, getDate: () => Date, getPlatform: () => wx })
},
_openSubmittedResult(resultUrl, submission) {
  this._submittedResultController().open(resultUrl, submission)
},
_submittedResultController() {
return submitPage._submittedResultController(this, { createSubmittedResultController, getConsole: () => console, getPlatform: () => wx })
},
onShow() {
  this._practiceLifecycleController().show()
},
onHide() {
  this._practiceLifecycleController().hide()
},
_practiceLifecycleController() {
  return this._practiceLifecycleControllerInstance || (
    this._practiceLifecycleControllerInstance =
      createPracticeLifecyclePageController(this, monotonicNow)
  )
},
async onReady() {
return lifecycleFlow.onReady(this, { config, getConsole: () => console, getDate: () => Date })
},
async loadPracticeSubjects(options = {}) {
  return this._practiceSubjectLoadController().load(options)
},
_practiceSubjectLoadController() {
  return this._practiceSubjectLoadControllerInstance || (
    this._practiceSubjectLoadControllerInstance =
      createPracticeSubjectLoadPageController(this, {
        api,
        filterSubjectTree: filter408SubjectTree,
        normalizeSubjectTree,
        wx,
      })
  )
},
_parseLaunchPreset(options) {
return parseLaunchPreset(options, safeDecodeURIComponent)
},
async _applyFastLaunchPreset() {
return launchFlow._applyFastLaunchPreset(this, { applyLaunchOverrides, fastLaunchPresetView, launchPresetOverrides })
},
async _applyLaunchPreset(subjectTree) {
return launchFlow._applyLaunchPreset(this, subjectTree, { applyLaunchOverrides, getConsole: () => console, getPlatform: () => wx, launchPresetOverrides, resolvedLaunchPresetView })
},
normalizeSubjectTree(raw) {
  return normalizeSubjectTree(raw)
},
initDefaultSubject(subjectTree) {
return launchFlow.initDefaultSubject(this, subjectTree, { RECENT_SUBJECTS_STORAGE_KEY, getPlatform: () => wx, selectDefaultSubject })
},
_initCustomNavigation() {
return lifecycleFlow._initCustomNavigation(this, { getMath: () => Math, getPlatform: () => wx })
},
_flattenSelectableSubjects(subjectTree) {
  return flattenSelectableSubjects(subjectTree)
},
_subjectMark(name) {
  return subjectMark(name)
},
_subjectIconMeta(name, code) {
  return subjectIconMeta(name, code)
},
_decorateRecentSubjects(subjects) {
  return decorateRecentSubjects(subjects, id => this._subjectHasChildren(id))
},
_rememberSubject(subjectId, subjectName) {
this._recentSubjectController().remember(subjectId, subjectName)
},
_recentSubjectController() {
return subjectPage._recentSubjectController(this, { createRecentSubjectController, getConsole: () => console, getPlatform: () => wx })
},
_queueRememberSubject(subjectId, subjectName) {
this._recentSubjectController().queue(subjectId, subjectName)
},
_flushPendingRecentSubject() {
this._recentSubjectController().flush()
},
_findParentSubjectId(subjectId) {
  return findParentSubjectId(subjectId, this.data.subjectTree)
},
_subjectHasChildren(subjectId) {
  return subjectHasChildren(subjectId, this.data.subjectTree)
},
_getPracticeSubjectScopeIds(subjectId, includeChildren) {
  return getPracticeSubjectScopeIds(subjectId, includeChildren, this.data.subjectTree)
},
toggleSettings() {
return launchFlow.toggleSettings(this)
},
openSubjectSheet() {
this._subjectSheetController().open()
},
_subjectSheetController() {
return subjectPage._subjectSheetController(this, { createSubjectSheetController, getClearTimeout: () => clearTimeout, getDate: () => Date, getSetTimeout: () => setTimeout })
},
_hideSubjectSheet(afterClose) {
this._subjectSheetController().hide(afterClose)
},
closeSubjectSheet() {
this._subjectSheetController().hide()
},
_handleSubjectOptionTap(subjectId, source) {
this._subjectSheetController().handleOptionTap(subjectId, source)
},
_clearLaunchOverridesForManualConfig() {
return launchFlow._clearLaunchOverridesForManualConfig(this)
},
_selectSubject(subjectId, subjectName, expandedSubjectId, hasChildren) {
this._subjectSelectionController().select(subjectId, subjectName, expandedSubjectId, hasChildren)
},
_subjectSelectionController() {
return subjectPage._subjectSelectionController(this, { createSubjectSelectionController })
},
chooseRecentSubject(e) {
this._subjectSelectionController().chooseRecent(e)
},
_findLaunchReturnStackIndex(pages, returnTo) {
return this._launchReturnController().findStackIndex(pages, returnTo)
},
_launchReturnController() {
return exitPage._launchReturnController(this, { createLaunchReturnController, getPagesFunction: () => getCurrentPages, getPlatform: () => wx, getSetTimeout: () => setTimeout, safeDecodeURIComponent })
},
_navigateBackToLaunchTarget(returnTo, attempt = 0) {
this._launchReturnController().navigateBack(returnTo, attempt)
},
_returnToLaunchOrigin() {
this._launchReturnController().returnToOrigin()
},
goBack() {
this._returnToLaunchOrigin()
},
chooseParentSubject(e) {
this._subjectSelectionController().chooseParent(e)
},
toggleParentExpansion(e) {
this._subjectSelectionController().toggleExpansion(e)
},
chooseChildSubject(e) {
this._subjectSelectionController().chooseChild(e)
},
chooseMode(e) {
this._subjectSelectionController().chooseMode(e)
},
setCount(e) {
this._subjectSelectionController().setCount(e)
},
async startPractice() {
return this._startPracticeController().start()
},
_startPracticeController() {
return questionPage._startPracticeController(this, { api, createStartPracticeController, getPlatform: () => wx })
},
_startTimer() {
    this._practiceSessionTimerController().start()
},
_fmt(sec) {
return lifecycleFlow._fmt(this, sec, { getMath: () => Math })
},
_clearTimer() {
    this._practiceSessionTimerController().stop()
  },
  _practiceSessionTimerController() {
    return this._practiceSessionTimerControllerInstance || (
      this._practiceSessionTimerControllerInstance =
        createPracticeSessionTimerPageController(this, monotonicNow)
    )
},
_setPracticeUnloadGuard(enabled, message) {
  this._exitGuardController().setUnloadGuard(enabled, message)
},
_shouldInterceptSystemBack() {
  return this._exitGuardController().shouldInterceptSystemBack()
},
_rearmPracticeExitGuard() {
  this._exitGuardController().rearm()
},
onPracticeExitGuardLeave() {
  this._exitGuardController().handleGuardLeave()
},
_exitGuardController() {
return exitPage._exitGuardController(this, { createExitGuardController, getClearTimeout: () => clearTimeout, getConsole: () => console, getPlatform: () => wx, getSetTimeout: () => setTimeout })
},
  async _loadQuestions() {
    return this._questionLoadController().load()
  },
  _questionLoadController() {
    return questionPage._questionLoadController(this, {
      createQuestionLoadController, createQuestionLoadWiring,
      api, validateKnowledgeScope, findQuestionBatchError, resolveBatchErrorRecovery,
      adapter, debugLog, saveDebugSnapshot, applyBatchCredentials, hasMissingBatchCredentials,
      monotonicNow, buildLoadedView, buildResetView, practiceAnswerableTypes: PRACTICE_ANSWERABLE_TYPES,
      getPlatform: () => wx,
    })
  },

  _buildQuestionRequestParams() {
return launchFlow._buildQuestionRequestParams(this, { buildQuestionRequestParams })
},
_getQuestionRenderView(q, forceRebuild) {
return this._questionDisplayController().getRenderView(q, forceRebuild)
},
_buildQuestionAnswerState(renderView, answer) {
return this._questionDisplayController().buildAnswerState(renderView, answer)
},
_buildQuestionViewModel(q, forceRebuild) {
return this._questionDisplayController().buildViewModel(q, forceRebuild)
},
_warmQuestionImages(questions, index) {
this._imageWarmController().warm(questions, index)
},
_imageWarmController() {
return questionPage._imageWarmController(this, { adapter, config, createImageWarmController, getConsole: () => console, questionImageCache })
},
_settleQuestionTime(pause) {
this._questionTimerController().settle(pause)
},
_showQuestion(index) {
this._questionDisplayController().showQuestion(index)
},
goQuestion(e) {
return questionPage.goQuestion(this, e)
},
goNext(e) {
this._showQuestion(e.detail.index)
},
goPrev(e) {
this._showQuestion(e.detail.index)
},
async requestExitPractice(source) {
  return this._exitRequestController().request(source)
},
_exitRequestController() {
return exitPage._exitRequestController(this, { createExitRequestController, getClearTimeout: () => clearTimeout, getPlatform: () => wx })
},
_resetPracticeStateAfterExit() {
return lifecycleFlow._resetPracticeStateAfterExit(this)
},
_questionDisplayController() {
return questionPage._questionDisplayController(this, { config, createPracticeQuestionDisplayController, getPlatform: () => wx, monotonicNow })
},
_computedFieldsController() {
return questionPage._computedFieldsController(this, { createComputedFieldsController })
},
_answerFeedbackController() {
return questionPage._answerFeedbackController(this, { createAnswerFeedbackController, getClearTimeout: () => clearTimeout, getSetTimeout: () => setTimeout })
},
_renderInvariantController() {
return questionPage._renderInvariantController(this, { createRenderInvariantController })
},
_questionTimerController() {
return questionPage._questionTimerController(this, { createQuestionTimerController, monotonicNow })
},
_sequentialRestartController() {
return questionPage._sequentialRestartController(this, { api, buildResetView, buildSequentialRestartView, createSequentialRestartController, getConsole: () => console, getPlatform: () => wx, resetSequentialTiming })
},
_selfHealController() {
return questionPage._selfHealController(this, { createSelfHealController })
},
_answerInteractionController() {
return questionPage._answerInteractionController(this, { createPracticeAnswerInteractionController, debugLog, saveDebugSnapshot, shouldDebugQuestion })
},
_isSubmissionLocked() {
return this._submissionLockController().isLocked()
},
_submissionLockController() {
return questionPage._submissionLockController(this, { createSubmissionLockController, getPlatform: () => wx })
},
selectOption(e) {
this._answerInteractionController().selectOption(e)
},
selectBlankOption(e) {
this._answerInteractionController().selectBlankOption(e)
},
_modeLabel: function(m) {
return this._computedFieldsController().modeLabel(m)
},
_updateComputedFields: function(extras) {
this._computedFieldsController().update(extras)
},
noop() {},
_showAnswerFeedback(q, answer) {
this._answerFeedbackController().show(q, answer)
},
_checkRenderInvariant(renderModel) {
this._renderInvariantController().check(renderModel)
},
_enterSafeMode() {
this._selfHealController().enterSafeMode()
},
_reRenderCurrentQuestion() {
this._selfHealController().reRenderCurrentQuestion()
},
_showSubmitConfirm(opts) {
return exitPage._showSubmitConfirm(this, opts, { getPlatform: () => wx })
},
async _showSubmitConfirmPaused(opts) {
  return this._pausedConfirmController().show(opts)
},
_pausedConfirmController() {
return exitPage._pausedConfirmController(this, { createPausedConfirmController, monotonicNow })
},
async doSubmit(skipConfirm) {
return this._submitFlowController().submit(skipConfirm)
},
_submitFlowController() {
return submitPage._submitFlowController(this, { api, buildSubmitPayload, createSubmitFlowController })
},
_submitSuccessController() {
return submitPage._submitSuccessController(this, { buildLightQuestions, buildPracticeResultUrl, buildStoredResults, buildSubmitResultPayload, computeDisplaySkippedCount, createSubmitSuccessController, getConsole: () => console, getDate: () => Date, getMath: () => Math, getPlatform: () => wx })
},
_submitErrorController() {
return submitPage._submitErrorController(this, { createSubmitErrorController, getConsole: () => console, isDeterministicReject, resolveRejectMessage })
},
_submitEntryController() {
return submitPage._submitEntryController(this, { adapter, api, buildRecoveryQuestions, buildSubmissionSnapshot, buildSubmitAnswers, buildSubmitSession, classifyAnswers, createSubmitEntryController, getDate: () => Date, getMath: () => Math, getPlatform: () => wx, monotonicNow })
},
})
