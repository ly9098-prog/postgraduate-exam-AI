const api = require('../../../utils/api')
const config = require('../../../config')
const storage = require('../../../utils/storage')
const {
buildRenderModel, resetRenderGuard, setRenderGuardPage,
stripLeadingOptionLabel, toPlainInlineMathText, needsRichRender,
textToHtml
} = require('../utils/stem-render')
const {
isTrueFalseType,
} = require('../utils/answer')
const adapter = require('../utils/question-runner-adapter')
const { getSubjectName } = require('../utils/subject-meta')
const { getChinaWallParts, getChinaDate } = require('../../../utils/china-time')
const {
REVIEW_BATCH_SIZE_OPTIONS,
REVIEW_DRAFT_PREFIX,
normalizeReviewBatchSize,
formatReviewElapsed,
normalizeReviewQuestion,
} = require('./utils/review-runner-support')
const {
buildReviewDraftPageCapabilities,
} = require('./utils/review-draft-page-adapter')
const {
buildAnswerInteractionPageCapabilities,
buildQuestionDisplayPageCapabilities,
buildQuestionEnrichmentPageCapabilities,
buildRenderSafetyPageCapabilities,
} = require('./utils/review-answer-page-adapter')
const {
buildOverviewVMPageCapabilities,
buildBatchSizeSheetPageCapabilities,
buildOverviewLoadPageCapabilities,
buildReviewDaySyncPageCapabilities,
buildOverviewSyncPageCapabilities,
} = require('./utils/review-overview-page-adapter')
const {
buildReviewSessionPageCapabilities,
buildStartBatchPageCapabilities,
buildNavBackPageCapabilities,
buildReviewSelfHealPageCapabilities,
} = require('./utils/review-session-page-adapter')
const {
buildGroupSubmitFlowPageCapabilities,
buildGroupSubmitEntryPageCapabilities,
buildGroupSubmitRequestPageCapabilities,
buildGroupSubmitResultPageCapabilities,
buildResultDockPageCapabilities,
} = require('./utils/review-submit-page-adapter')
const {
buildReviewMasterPageCapabilities,
buildNextGroupPageCapabilities,
buildNextRetryGroupPageCapabilities,
buildNextRemoteBatchPageCapabilities,
buildReviewTimerPageCapabilities,
} = require('./utils/review-progress-page-adapter')
const {
  createGroupSubmitConfirmController,
} = require('./utils/submit-confirm-controller')
const {
  createGroupSubmitRequestController,
} = require('./utils/submit-request-controller')
const {
  createGroupSubmitResultController,
} = require('./utils/submit-result-controller')
const {
  createGroupSubmitEntryController,
} = require('./utils/submit-entry-controller')
const {
  createNextRetryGroupController,
} = require('./utils/next-retry-group-controller')
const {
  createNextRemoteBatchController,
} = require('./utils/next-remote-batch-controller')
const {
  createNextGroupController,
} = require('./utils/next-group-controller')
const {
  createResultDockController,
} = require('./utils/result-dock-controller')
const {
  createReviewTimerController,
  safeReviewTickDelta,
} = require('./utils/review-timer-controller')
const {
  createReviewMasterController,
} = require('./utils/master-controller')
const {
  createStartBatchController,
} = require('./utils/start-batch-controller')
const {
  createReviewDraftController,
} = require('./utils/draft-controller')
const {
  createAnswerInteractionController,
} = require('./utils/answer-interaction-controller')
const {
  createQuestionDisplayController,
} = require('./utils/question-display-controller')
const {
  createOverviewVMController,
} = require('./utils/overview-vm-controller')
const {
  createRenderSafetyController,
} = require('./utils/render-safety-controller')
const {
  createBatchSizeSheetController,
} = require('./utils/batch-size-sheet-controller')
const {
  createQuestionEnrichmentController,
} = require('./utils/question-enrichment-controller')
const {
  createReviewSessionController,
} = require('./utils/review-session-controller')
const {
  createNavBackController,
} = require('./utils/nav-back-controller')
const {
  createReviewSelfHealController,
} = require('./utils/self-heal-controller')
const {
  createOverviewSyncController,
} = require('./utils/overview-sync-controller')
const {
  createOverviewLoadController,
} = require('./utils/overview-load-controller')
const {
  createReviewDaySyncController,
} = require('./utils/day-sync-controller')
const {
  createGroupSubmitFlowController,
} = require('./utils/group-submit-flow-controller')
var _reviewPerformanceClock = null
function _reviewMonotonicNow() {
try {
if (!_reviewPerformanceClock && typeof wx !== 'undefined' && typeof wx.getPerformance === 'function') {
_reviewPerformanceClock = wx.getPerformance()
}
if (_reviewPerformanceClock && typeof _reviewPerformanceClock.now === 'function') {
return _reviewPerformanceClock.now()
}
} catch (_) {}
return Date.now()
}
// 服务端校准后的绝对时间，用于上报复习时长窗口
function _reviewServerNow() {
return typeof api.now === 'function' ? api.now() : Date.now()
}
Page({
data: {
reviewNavigationHeight: 64,
phase: 'loading',
elapsedText: '00:00',
todayDueCount: 0,
todayCompletedCount: 0,
todayRemainingCount: 0,
todayOverdueCount: 0,
todayNewDueCount: 0,
estimatedMinutes: 0,
reviewBatchSize: 10,
currentBatchNo: 0,
totalBatchCount: 0,
remainingBatchCount: 0,
todayProgressPercent: 0,
isStarting: false,
isContinuing: false,
batchLoading: false,
errorText: '',
groups: [],
currentGroupIdx: 0,
groupQuestions: [],
currentIndex: 0,
currentQuestion: null,
masterConfirmId: null,
masterSubmitting: false,
runnerProgressPercent: 0,
runnerSubtitle: '',
runnerSubjectName: '',
submittingGroup: false,
resultTransitioning: false,
groupResults: [],
groupWrongResults: [],
groupCorrect: 0,
groupWrong: 0,
_groupSkipped: 0,
groupAccuracyPercent: 0,
showGroupDetails: false,
resultDockVisible: true,
exitConfirmVisible: false,
masterUndoVisible: false,
masterUndoText: '',
_dateStr: '',
_groupProgressStyle: '',
batchSizeOptions: [5, 10, 20, 30],
showBatchSizeSheet: false,
pendingBatchSize: 10,
skeletonOptions: [1, 2, 3, 4],
},
_createReviewSession() {
return this._reviewSessionController().createSession()
},
_readReviewDraft() {
return this._reviewDraftController().read()
},
_writeReviewDraft(payload) {
this._reviewDraftController().write(payload)
},
_persistReviewDraft() {
this._reviewDraftController().persist()
},
_restoreReviewDraft(questions) {
return this._reviewDraftController().restore(questions)
},
_clearSubmittedReviewDraft(groupQuestions, groupResults) {
this._reviewDraftController().clearSubmitted(groupQuestions, groupResults)
},
_reviewDraftController() {
return this._reviewDraft || (
this._reviewDraft = createReviewDraftController(
buildReviewDraftPageCapabilities(this, { storage })
)
)
},
_answerInteractionController() {
return this._answerInteraction || (
this._answerInteraction = createAnswerInteractionController(
buildAnswerInteractionPageCapabilities(this, {})
)
)
},
_questionDisplayController() {
return this._questionDisplay || (
this._questionDisplay = createQuestionDisplayController(
buildQuestionDisplayPageCapabilities(this, {})
)
)
},
_overviewVMController() {
return this._overviewVM || (
this._overviewVM = createOverviewVMController(
buildOverviewVMPageCapabilities(this, {})
)
)
},
_renderSafetyController() {
return this._renderSafety || (
this._renderSafety = createRenderSafetyController(
buildRenderSafetyPageCapabilities(this, { config })
)
)
},
_batchSizeSheetController() {
return this._batchSizeSheet || (
this._batchSizeSheet = createBatchSizeSheetController(
buildBatchSizeSheetPageCapabilities(this, {})
)
)
},
_questionEnrichmentController() {
return this._questionEnrichment || (
this._questionEnrichment = createQuestionEnrichmentController(
buildQuestionEnrichmentPageCapabilities(this, { config })
)
)
},
_reviewSessionController() {
return this._reviewSessionCtl || (
this._reviewSessionCtl = createReviewSessionController(
buildReviewSessionPageCapabilities(this, {})
)
)
},
_navBackController() {
return this._navBack || (
this._navBack = createNavBackController(
buildNavBackPageCapabilities(this, {})
)
)
},
_reviewSelfHealController() {
return this._reviewSelfHeal || (
this._reviewSelfHeal = createReviewSelfHealController(
buildReviewSelfHealPageCapabilities(this, {})
)
)
},
_overviewSyncController() {
return this._overviewSync || (
this._overviewSync = createOverviewSyncController(
buildOverviewSyncPageCapabilities(this, {})
)
)
},
onLoad(options) {
let statusBar = 20
try {
  const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
  statusBar = Number(info.statusBarHeight || 20)
} catch (_) {}
let menu = null
try { menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect() } catch (_) {}
const menuTop = menu && menu.top ? Number(menu.top) : statusBar + 6
const menuHeight = menu && menu.height ? Number(menu.height) : 32
this.setData({ reviewNavigationHeight: statusBar + menuHeight + Math.max(4, menuTop - statusBar) * 2 })

this._alive = true; this._guestMode = Boolean(options && String(options.guest) === '1')
this._overviewRequestSeq = 0
this._flowRequestSeq = 0
this._masterUndoInFlight = false
this._autoStartPending = !!(
options && (
String(options.autostart || '') === '1' ||
String(options.autostart || '').toLowerCase() === 'true'
)
)
this._reviewSession = this._createReviewSession()
this._timerInterval = null
this._resultDockFadeTimer = null
this._userSelectedReviewBatchSize = false
setRenderGuardPage('review-today')
this._setDateStr()
this.loadTodayReviewOverview()
},
onShow() {
this._setDateStr()
const phase = this.data.phase
if (phase === 'overview' || phase === 'empty') {
this.loadTodayReviewOverview()
}
if (phase === 'reviewing' && this._reviewSession && this._reviewSession.timerStartedAt > 0 && !this._reviewSession.timerRunning) {
this._resumeReviewTimer()
}
if (phase === 'group-result' && this.data.todayRemainingCount <= 0) {
this._showResultDockAndRefreshTimer()
}
},
onHide() {
if (typeof this._persistReviewDraft === 'function') this._persistReviewDraft()
this._pauseReviewTimer()
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
onUnload() {
if (typeof this._persistReviewDraft === 'function') this._persistReviewDraft()
this._alive = false
this._overviewRequestSeq++
this._flowRequestSeq++
this._autoStartPending = false
resetRenderGuard()
this._clearMasterUndo()
this._clearReviewTimer()
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
_setDateStr() {
this._reviewSessionController().setDateStr()
},
async loadTodayReviewOverview() {
if (this._guestMode) { this.setData({ guestMode: true, phase: 'empty' }); return }
  await this._overviewLoadController().load()
},
async refreshOverviewStatsSilently() {
  await this._overviewLoadController().refreshSilently()
},

  _overviewLoadController() {
return this._overviewLoad || (
this._overviewLoad = createOverviewLoadController(
buildOverviewLoadPageCapabilities(this, { api })
)
)
},
async _syncReviewSessionDayIfNeeded() {
  return this._reviewDaySyncController().syncIfNeeded()
},

  _reviewDaySyncController() {
return this._reviewDaySync || (
this._reviewDaySync = createReviewDaySyncController(
buildReviewDaySyncPageCapabilities(this, { api })
)
)
},
buildReviewOverviewVM(overview) {
return this._overviewVMController().buildVM(overview)
},
async startTodayReview() {
await this._startBatchController().start()
},
_startBatchController() {
return this._startBatchControllerInstance || (
this._startBatchControllerInstance = createStartBatchController(
buildStartBatchPageCapabilities(this, { api })
)
)
},
_splitGroups(questions, size) {
return this._questionEnrichmentController().splitGroups(questions, size)
},
_enrichQuestion(q) {
return this._questionEnrichmentController().enrich(q)
},
_enrichForResult(q) {
return this._questionEnrichmentController().enrichForResult(q)
},
_checkRenderInvariant(renderModel) {
this._renderSafetyController().checkInvariant(renderModel)
},
_recordRenderTrace(trace) {
this._renderSafetyController().recordTrace(trace)
},
_enterSafeMode() {
this._reviewSelfHealController().enterSafeMode()
},
_checkSetDataSize(data) {
this._renderSafetyController().checkSetDataSize(data)
},
_syncAnsweredFlags() {
this._questionDisplayController().syncAnsweredFlags()
},
_showQuestion(index) {
this._questionDisplayController().showQuestion(index)
},
_updateRunnerFields() {
this._questionDisplayController().updateRunnerFields()
},
selectOption(e) {
this._answerInteractionController().selectOption(e)
},
selectBlankOption(e) {
this._answerInteractionController().selectBlankOption(e)
},
goQuestion(e) {
var index = e.detail.index
if (index === this.data.currentIndex) return
this._showQuestion(index)
this._persistReviewDraft()
},
goNext(e) {
this._showQuestion(e.detail.index)
this._persistReviewDraft()
},
goPrev(e) {
this._showQuestion(e.detail.index)
this._persistReviewDraft()
},
tapMaster(e) {
this._reviewMasterController().tap(e)
},
cancelMaster() {
this._reviewMasterController().cancel()
},
async confirmMaster() {
await this._reviewMasterController().confirm()
},
async undoMaster() {
await this._reviewMasterController().undo()
},
_reviewMasterController() {
return this._reviewMaster || (
this._reviewMaster = createReviewMasterController(
buildReviewMasterPageCapabilities(this, { api })
)
)
},
_armMasterUndoExpiry(ms) {
this._reviewMasterController().armUndoExpiry(ms)
},
_clearMasterUndo() {
this._reviewMasterController().clearUndo()
},
_getReviewRequestId(question) {
return this._reviewSessionController().getRequestId(question)
},
async submitGroup() {
await this._groupSubmitFlowController().submit()
},

  _groupSubmitFlowController() {
return this._groupSubmitFlow || (
this._groupSubmitFlow = createGroupSubmitFlowController(
buildGroupSubmitFlowPageCapabilities(this, {})
)
)
},
  _groupSubmitEntryController() {
return this._groupSubmitEntry || (
this._groupSubmitEntry = createGroupSubmitEntryController(
buildGroupSubmitEntryPageCapabilities(this, {})
)
)
},
  _groupSubmitRequestController() {
return this._groupSubmitRequest || (
this._groupSubmitRequest = createGroupSubmitRequestController(
buildGroupSubmitRequestPageCapabilities(this, { api })
)
)
},
  _groupSubmitResultController() {
return this._groupSubmitResult || (
this._groupSubmitResult = createGroupSubmitResultController(
buildGroupSubmitResultPageCapabilities(this, {})
)
)
},
async nextGroup() {
return this._nextGroupController().next()
},
_nextGroupController() {
return this._nextGroup || (
this._nextGroup = createNextGroupController(
buildNextGroupPageCapabilities(this, {})
)
)
},
_nextRetryGroupController() {
return this._nextRetryGroup || (
this._nextRetryGroup = createNextRetryGroupController(
buildNextRetryGroupPageCapabilities(this, {})
)
)
},
_nextRemoteBatchController() {
return this._nextRemoteBatch || (
this._nextRemoteBatch = createNextRemoteBatchController(
buildNextRemoteBatchPageCapabilities(this, { api })
)
)
},
_clearResultDockFadeTimer() {
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
_showResultDockAndRefreshTimer() {
this._resultDockController().show()
},
_resultDockController() {
return this._resultDockControllerInstance || (
this._resultDockControllerInstance = createResultDockController(
buildResultDockPageCapabilities(this, {})
)
)
},
onResultPageInteraction() {
this._showResultDockAndRefreshTimer()
},
onPageScroll() {
this._showResultDockAndRefreshTimer()
},
goWrongBook() { wx.navigateTo({ url: `/subpackages/study/wrong-book/wrong-book${this._guestMode ? '?guest=1' : ''}` }) },
goPractice() { wx.navigateTo({ url: `/subpackages/study/practice/practice${this._guestMode ? '?guest=1' : ''}` }) },
onNavBack() {
this._navBackController().onNavBack()
},
closeExitConfirm() {
this._navBackController().closeExitConfirm()
},
confirmExitReview() {
this._navBackController().confirmExitReview()
},
toggleGroupDetails() {
this._showResultDockAndRefreshTimer()
this.setData({ showGroupDetails: !this.data.showGroupDetails })
},
retryLoad() {
this.loadTodayReviewOverview()
},
noop() {},
subjectLabel(name, code) {
return this._reviewSessionController().subjectLabel(name, code)
},
_safeTickDelta(rawMs) {
return safeReviewTickDelta(rawMs)
},
_reviewTimerController() {
return this._reviewTimer || (
this._reviewTimer = createReviewTimerController(
buildReviewTimerPageCapabilities(this, { api, _reviewMonotonicNow, _reviewServerNow })
)
)
},
_startReviewTimer() {
this._reviewTimerController().start()
},
// 本组前台计时快照（不修改计时状态）：提交失败重试沿用同一分段 id，
// 服务端按 request_id 幂等，只记录首次成功的一次。
_buildReviewTimingSession() {
return this._reviewTimerController().buildTimingSession()
},
_pauseReviewTimer() {
this._reviewTimerController().pause()
},
_resumeReviewTimer() {
this._reviewTimerController().resume()
},
_resetReviewTimer() {
this._reviewTimerController().reset()
},
_clearReviewTimer() {
this._reviewTimerController().clear()
},
showBatchSizeSelector() {
this._batchSizeSheetController().show()
},
handleBatchSheetMaskTap() {
this.closeBatchSizeSheet()
},
stopBatchSheetPropagation() {
},
closeBatchSizeSheet() {
this._batchSizeSheetController().close()
},
selectPendingBatchSize(e) {
this._batchSizeSheetController().selectPending(e)
},
confirmBatchSize() {
this._batchSizeSheetController().confirm()
},
})
if (typeof module !== 'undefined' && module.exports) {
module.exports = {
normalizeReviewBatchSize,
formatReviewElapsed,
normalizeReviewQuestion,
REVIEW_BATCH_SIZE_OPTIONS,
REVIEW_DRAFT_PREFIX,
BATCH_SIZE_OPTIONS_META: [
{ value: 5, label: '快速复习' },
{ value: 10, label: '推荐' },
{ value: 20, label: '集中巩固' },
{ value: 30, label: '深度复习' },
],
}
}
