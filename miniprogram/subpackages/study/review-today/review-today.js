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
var KF = 'schedule_id'
var REVIEW_BATCH_SIZE_OPTIONS = [5, 10, 20, 30]
var REVIEW_DRAFT_PREFIX = 'review_today_draft_v1'
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
function normalizeReviewBatchSize(value) {
var num = Number(value)
if (isNaN(num) || num <= 0) return 10
for (var i = 0; i < REVIEW_BATCH_SIZE_OPTIONS.length; i++) {
if (num === REVIEW_BATCH_SIZE_OPTIONS[i]) return num
}
return 10
}
function formatReviewElapsed(sec) {
var s = Math.max(0, sec || 0)
var m = Math.floor(s / 60)
var ss = s % 60
return (m < 10 ? '0' : '') + m + ':' + (ss < 10 ? '0' : '') + ss
}
function _reviewFailureNeedsRefresh(result) {
if (!result || result.success !== false) return false
if (result.refresh_required === true) return true
if (result.retryable === false && result.retryable !== undefined && result.retryable !== null) return true
var text = String(result.error || '')
return /刷新|已失效|已经提交|已标记掌握|复习记录不存在|版本.*(?:更新|不存在)|不匹配|request_id.*不同提交/.test(text)
}
function normalizeReviewQuestion(raw) {
if (!raw || typeof raw !== 'object') return null
var content = raw.content
if (typeof content === 'string') {
content = { text: content }
} else if (!content || typeof content !== 'object') {
content = { text: raw.stem || '' }
}
var opts = raw.options
if (!opts || typeof opts !== 'object' || Array.isArray(opts)) {
opts = {}
}
return {
schedule_id: raw.schedule_id,
question_id: raw.question_id,
question_version_id: raw.question_version_id,
occurrence_seq: raw.occurrence_seq,
id: raw.id || raw.question_id,
subject_id: raw.subject_id != null ? raw.subject_id : null,
subject_code: raw.subject_code || '',
subject_name: raw.subject_name || '',
question_type: raw.question_type || '',
stem: raw.stem || '',
options: opts,
content: content,
image_url: raw.image_url || null,
interval: raw.interval || 0,
repetitions: raw.repetitions || 0,
ease_factor: raw.ease_factor || 2.5,
}
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
this._reviewDraft = createReviewDraftController({
getDraftKey: () => {
const session = this._reviewSession || (this._reviewSession = this._createReviewSession())
const user = storage.get(storage.KEYS.USER) || {}
const userId = user.id != null ? user.id : (user.user_id != null ? user.user_id : 'current')
const taskDate = String(session.taskDate || getChinaDate(0))
return REVIEW_DRAFT_PREFIX + ':' + String(userId) + ':' + taskDate
},
readStorage: key => storage.get(key),
writeStorage: (key, value) => storage.set(key, value),
removeStorage: key => storage.remove(key),
getSession: () => this._reviewSession,
getCurrentDate: () => getChinaDate(0),
getPhase: () => this.data.phase,
getGroupQuestions: () => this.data.groupQuestions,
getCurrentQuestion: () => this.data.currentQuestion,
now: () => Date.now(),
})
)
},
_answerInteractionController() {
return this._answerInteraction || (
this._answerInteraction = createAnswerInteractionController({
isSubmitting: () => this.data.submittingGroup,
getCurrentQuestion: () => this.data.currentQuestion,
getAnswers: () => this._reviewSession.answers,
setAnswers: answers => { this._reviewSession.answers = answers },
getGroupQuestions: () => this.data.groupQuestions,
getKeyField: () => KF,
setData: patch => this.setData(patch),
persistDraft: () => this._persistReviewDraft(),
syncAnsweredFlags: () => this._syncAnsweredFlags(),
updateRunnerFields: () => this._updateRunnerFields(),
buildRunnerSubtitle: () => '第 ' + (this.data.currentBatchNo || this.data.currentGroupIdx + 1) + ' / ' + (this.data.totalBatchCount || 1) + ' 组',
})
)
},
_questionDisplayController() {
return this._questionDisplay || (
this._questionDisplay = createQuestionDisplayController({
getGroupQuestions: () => this.data.groupQuestions,
getAnswers: () => this._reviewSession.answers,
setOptionKeys: keys => { this._reviewSession.optionKeys = keys },
getKeyField: () => KF,
getAnsweredCount: () => this.data._answeredCount,
getCurrentQuestion: () => this.data.currentQuestion,
enrichQuestion: q => this._enrichQuestion(q),
setData: patch => this.setData(patch),
checkSetDataSize: data => this._checkSetDataSize(data),
checkRenderInvariant: model => this._checkRenderInvariant(model),
recordRenderTrace: trace => this._recordRenderTrace(trace),
buildRunnerSubtitle: () => '第 ' + (this.data.currentBatchNo || this.data.currentGroupIdx + 1) + ' / ' + (this.data.totalBatchCount || 1) + ' 组',
})
)
},
_overviewVMController() {
return this._overviewVM || (
this._overviewVM = createOverviewVMController({
getBatchSizeOptions: () => REVIEW_BATCH_SIZE_OPTIONS,
getDefaultBatchSize: () => 10,
isUserBatchSizeSelected: () => this._userSelectedReviewBatchSize,
getCurrentUserBatchSize: () => this.data.reviewBatchSize,
})
)
},
_renderSafetyController() {
return this._renderSafety || (
this._renderSafety = createRenderSafetyController({
isSafeModeActive: () => this._reviewSession.safeModeActive,
enterSafeMode: () => this._enterSafeMode(),
getRenderTraces: () => this._reviewSession.renderTraces,
setRenderTraces: traces => { this._reviewSession.renderTraces = traces },
isDev: () => config.DEV,
})
)
},
_batchSizeSheetController() {
return this._batchSizeSheet || (
this._batchSizeSheet = createBatchSizeSheetController({
getPhase: () => this.data.phase,
isStarting: () => this.data.isStarting,
isContinuing: () => this.data.isContinuing,
getReviewBatchSize: () => this.data.reviewBatchSize,
getPendingBatchSize: () => this.data.pendingBatchSize,
getBatchSizeOptions: () => REVIEW_BATCH_SIZE_OPTIONS,
normalizeBatchSize: v => normalizeReviewBatchSize(v),
markUserSelected: () => { this._userSelectedReviewBatchSize = true },
setData: patch => this.setData(patch),
})
)
},
_questionEnrichmentController() {
return this._questionEnrichment || (
this._questionEnrichment = createQuestionEnrichmentController({
isDev: () => config.DEV,
isSafeModeActive: () => this._reviewSession.safeModeActive,
isTrueFalse: t => isTrueFalseType(t),
subjectLabel: (name, code) => this.subjectLabel(name, code),
})
)
},
_reviewSessionController() {
return this._reviewSessionCtl || (
this._reviewSessionCtl = createReviewSessionController({
getSession: () => this._reviewSession,
setData: patch => this.setData(patch),
})
)
},
_navBackController() {
return this._navBack || (
this._navBack = createNavBackController({
getPhase: () => this.data.phase,
setData: patch => this.setData(patch),
clearMasterUndo: () => this._clearMasterUndo(),
clearReviewTimer: () => this._clearReviewTimer(),
getCurrentPages: () => getCurrentPages(),
navigateBack: () => wx.navigateBack(),
reLaunch: options => wx.reLaunch(options),
})
)
},
_reviewSelfHealController() {
return this._reviewSelfHeal || (
this._reviewSelfHeal = createReviewSelfHealController({
setSafeModeActive: v => { this._reviewSession.safeModeActive = v },
getCurrentQuestion: () => this.data.currentQuestion,
getCurrentIndex: () => this.data.currentIndex,
getGroupQuestions: () => this.data.groupQuestions,
enrichQuestion: q => this._enrichQuestion(q),
setData: patch => this.setData(patch),
showQuestion: idx => this._showQuestion(idx),
})
)
},
_overviewSyncController() {
return this._overviewSync || (
this._overviewSync = createOverviewSyncController({
getSession: () => this._reviewSession,
getPhase: () => this.data.phase,
getTodayDueCount: () => this.data.todayDueCount,
})
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

this._alive = true
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
  await this._overviewLoadController().load()
},
async refreshOverviewStatsSilently() {
  await this._overviewLoadController().refreshSilently()
},

  _overviewLoadController() {
    return this._overviewLoad || (
      this._overviewLoad = createOverviewLoadController({
        nextRequestSeq: () => ++this._overviewRequestSeq,
        isRequestCurrent: seq => seq === this._overviewRequestSeq,
        isPageAlive: () => this._alive,
        isAutoStartPending: () => this._autoStartPending,
        setAutoStartPending: value => { this._autoStartPending = value },
        setOverviewLoading: value => { this._reviewSession.overviewLoading = value },
        getOverview: () => api.get('/review/today/overview'),
        buildOverviewVM: overview => this.buildReviewOverviewVM(overview),
        applyOverviewToSession: (overview, vm) => this._overviewSyncController().applyOverviewToSession(overview, vm),
        adjustVmForActiveSession: vm => this._overviewSyncController().adjustVmForActiveSession(vm),
        setData: (patch, callback) => this.setData(patch, callback),
        startReview: () => this.startTodayReview(),
        logError: (...args) => console.error(...args),
      })
    )
  },
async _syncReviewSessionDayIfNeeded() {
const session = this._reviewSession
const currentDate = getChinaDate(0)
if (!session || !session.taskDate || String(session.taskDate) === currentDate) return true
try {
const overview = await api.get('/review/today/overview')
if (!this._alive) return false
const vm = this.buildReviewOverviewVM(overview || {})
this._overviewSyncController().applyOverviewWithDayReset(overview, vm)
this._setDateStr()
this.setData({
...vm,
})
wx.showToast({ title: '日期已切换，已同步今日复习进度', icon: 'none' })
return true
} catch (e) {
if (!this._alive) return false
console.error('跨天同步复习进度失败', e)
wx.showToast({ title: '日期已切换，请联网同步后继续', icon: 'none' })
return false
}
},
buildReviewOverviewVM(overview) {
return this._overviewVMController().buildVM(overview)
},
async startTodayReview() {
await this._startBatchController().start()
},
_startBatchController() {
return this._startBatchControllerInstance || (
this._startBatchControllerInstance = createStartBatchController({
getTodayRemainingCount: () => this.data.todayRemainingCount,
isStarting: () => this.data.isStarting,
isContinuing: () => this.data.isContinuing,
nextFlowSeq: () => ++this._flowRequestSeq,
getCurrentFlowSeq: () => this._flowRequestSeq,
isFlowCurrent: seq => seq === this._flowRequestSeq,
isPageAlive: () => this._alive,
setData: patch => this.setData(patch),
getBatchSize: () => this.data.reviewBatchSize,
postNextBatch: payload => api.post('/review/today/next-batch', payload),
loadOverview: () => this.loadTodayReviewOverview(),
normalizeQuestion: question => normalizeReviewQuestion(question),
restoreDraft: questions => this._restoreReviewDraft(questions),
getSession: () => this._reviewSession,
getData: () => this.data,
enrichQuestion: question => this._enrichQuestion(question),
buildOptionList: (question, answers) => adapter.buildOptionList(question, answers, KF),
getBlankOptionGroups: question => adapter.getBlankOptionGroups(question),
enrichBlankOptionGroups: (groups, answer) => adapter.enrichBlankOptionGroups(groups, answer),
computeAnsweredCount: (questions, answers) => adapter.computeAnsweredCount(questions, answers, KF),
getTotalBatchCount: () => this.data.totalBatchCount,
checkSetDataSize: data => this._checkSetDataSize(data),
syncAnsweredFlags: () => this._syncAnsweredFlags(),
updateRunnerFields: () => this._updateRunnerFields(),
checkRenderInvariant: renderModel => this._checkRenderInvariant(renderModel),
recordRenderTrace: trace => this._recordRenderTrace(trace),
startReviewTimer: () => this._startReviewTimer(),
showToast: options => wx.showToast(options),
logError: (...args) => console.error(...args),
})
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
this._reviewMaster = createReviewMasterController({
getData: () => this.data,
getSession: () => this._reviewSession,
setData: patch => this.setData(patch),
isPageAlive: () => this._alive,
isMasterSubmitting: () => this.data.masterSubmitting,
isSubmittingGroup: () => this.data.submittingGroup,
isMasterUndoInFlight: () => this._masterUndoInFlight,
getPendingMasterUndo: () => this._pendingMasterUndo,
setPendingMasterUndo: value => { this._pendingMasterUndo = value },
setMasterUndoInFlight: value => { this._masterUndoInFlight = value },
getMasterUndoTimer: () => this._masterUndoTimer,
setMasterUndoTimer: timer => { this._masterUndoTimer = timer },
incrementMasteredCount: () => { this._masteredCount = (this._masteredCount || 0) + 1 },
decrementMasteredCount: () => { this._masteredCount = Math.max(0, (this._masteredCount || 1) - 1) },
syncReviewSessionDay: () => this._syncReviewSessionDayIfNeeded(),
postMaster: scheduleId => api.post(`/review/${scheduleId}/master`),
postUnmaster: scheduleId => api.post(`/review/${scheduleId}/unmaster`),
refreshOverviewStatsSilently: () => this.refreshOverviewStatsSilently(),
clearUndo: () => this._clearMasterUndo(),
armUndoExpiry: ms => this._armMasterUndoExpiry(ms),
clearReviewTimer: () => this._clearReviewTimer(),
getTodayRemainingCount: () => this.data.todayRemainingCount,
syncAnsweredFlags: () => this._syncAnsweredFlags(),
showQuestion: index => this._showQuestion(index),
startReviewTimer: () => this._startReviewTimer(),
showToast: options => wx.showToast(options),
logError: (message, error) => console.error(message, error),
setTimeout,
clearTimeout,
})
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
const { groupQuestions } = this.data
const groupSubmitEntryController = this._groupSubmitEntryController || (
this._groupSubmitEntryController = createGroupSubmitEntryController({
getData: () => this.data,
getSession: () => this._reviewSession,
isConfirmPending: () => this._submitConfirmPending,
isMasterUndoInFlight: () => this._masterUndoInFlight,
isPageAlive: () => this._alive,
computeAnsweredCount: (questions, answers) => adapter.computeAnsweredCount(questions, answers, KF),
confirmController: this._groupSubmitConfirmController || (
this._groupSubmitConfirmController = createGroupSubmitConfirmController({
getConfirm: () => this.selectComponent('#submitConfirm'),
setPending: value => { this._submitConfirmPending = value },
isPageAlive: () => this._alive,
getPhase: () => this.data.phase,
findUnansweredIndex: () => this.data.groupQuestions.findIndex(q => !adapter.isQuestionAnswered(q, this._reviewSession.answers, KF)),
showQuestion: index => this._showQuestion(index),
})
),
showToast: options => wx.showToast(options),
clearMasterUndo: () => this._clearMasterUndo(),
setSubmitting: value => this.setData({ submittingGroup: value }),
syncReviewSessionDay: () => this._syncReviewSessionDayIfNeeded(),
})
)
if (!await groupSubmitEntryController.confirm(groupQuestions)) return
const answers = await groupSubmitEntryController.begin(groupQuestions)
if (!answers) return
const groupSubmitRequestController = this._groupSubmitRequestController || (
this._groupSubmitRequestController = createGroupSubmitRequestController({
postGrade: payload => api.post('/review/grade-batch', payload),
showToast: options => wx.showToast(options),
setSubmitting: value => this.setData({ submittingGroup: value }),
isPageAlive: () => this._alive,
})
)
const submission = await groupSubmitRequestController.submit({
groupQuestions,
answers,
isQuestionAnswered: (question, answerMap) => adapter.isQuestionAnswered(question, answerMap, KF),
getRequestId: question => this._getReviewRequestId(question),
buildTimingSession: () => this._buildReviewTimingSession(),
enrichForResult: question => this._enrichForResult(question),
failureNeedsRefresh: result => _reviewFailureNeedsRefresh(result),
})
if (submission.status !== 'submitted') return
const groupSubmitResultController = this._groupSubmitResultController || (
this._groupSubmitResultController = createGroupSubmitResultController({
getGroups: () => this.data.groups,
getSession: () => this._reviewSession,
getTodayDueCount: () => this.data.todayDueCount,
getTodayCompletedCount: () => this.data.todayCompletedCount,
getCurrentGroupIdx: () => this.data.currentGroupIdx,
clearSubmittedDraft: (questions, results) => this._clearSubmittedReviewDraft(questions, results),
showToast: options => wx.showToast(options),
pauseTimer: () => this._pauseReviewTimer(),
setData: patch => this.setData(patch),
showResultDockAndRefreshTimer: () => this._showResultDockAndRefreshTimer(),
})
)
try {
groupSubmitResultController.apply({
groupQuestions,
groupResults: submission.groupResults,
})
} catch (e) {
if (!this._alive) return
console.error('提交失败', e)
wx.showToast({ title: '提交失败，请重试', icon: 'none' })
this.setData({ submittingGroup: false })
}
},
async nextGroup() {
const nextGroupController = this._nextGroupController || (
this._nextGroupController = createNextGroupController({
getData: () => this.data,
setData: (patch, callback) => this.setData(patch, callback),
clearMasterUndo: () => this._clearMasterUndo(),
clearResultDockFadeTimer: () => this._clearResultDockFadeTimer(),
nextFlowSeq: () => ++this._flowRequestSeq,
isPageAlive: () => this._alive,
isFlowCurrent: seq => seq === this._flowRequestSeq,
syncReviewSessionDay: () => this._syncReviewSessionDayIfNeeded(),
getCurrentGroupIdx: () => this.data.currentGroupIdx,
getTodayRemainingCount: () => this.data.todayRemainingCount,
retryGroupController: this._nextRetryGroupController || (
this._nextRetryGroupController = createNextRetryGroupController({
getGroups: () => this.data.groups,
getSession: () => this._reviewSession,
setData: patch => this.setData(patch),
syncAnsweredFlags: () => this._syncAnsweredFlags(),
showQuestion: index => this._showQuestion(index),
startReviewTimer: () => this._startReviewTimer(),
})
),
remoteBatchController: this._nextRemoteBatchController || (
this._nextRemoteBatchController = createNextRemoteBatchController({
getBatchSize: () => this.data.reviewBatchSize,
postNextBatch: payload => api.post('/review/today/next-batch', payload),
isPageAlive: () => this._alive,
isFlowCurrent: seq => seq === this._flowRequestSeq,
normalizeQuestion: question => normalizeReviewQuestion(question),
restoreDraft: questions => this._restoreReviewDraft(questions),
getSession: () => this._reviewSession,
setData: patch => this.setData(patch),
getCurrentBatchNo: () => this.data.currentBatchNo,
getTotalBatchCount: () => this.data.totalBatchCount,
getTodayDueCount: () => this.data.todayDueCount,
getTodayCompletedCount: () => this.data.todayCompletedCount,
getTodayRemainingCount: () => this.data.todayRemainingCount,
syncAnsweredFlags: () => this._syncAnsweredFlags(),
showQuestion: index => this._showQuestion(index),
startReviewTimer: () => this._startReviewTimer(),
showToast: options => wx.showToast(options),
refreshOverviewStatsSilently: () => this.refreshOverviewStatsSilently(),
})
),
logError: (message, error) => console.error(message, error),
showToast: options => wx.showToast(options),
showResultDockAndRefreshTimer: () => this._showResultDockAndRefreshTimer(),
})
)
await nextGroupController.next()
},
_clearResultDockFadeTimer() {
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
_showResultDockAndRefreshTimer() {
const resultDockController = this._resultDockController || (
this._resultDockController = createResultDockController({
getPhase: () => this.data.phase,
getTodayRemainingCount: () => this.data.todayRemainingCount,
getResultDockVisible: () => this.data.resultDockVisible,
setData: patch => this.setData(patch),
clearFadeTimer: () => this._clearResultDockFadeTimer(),
setFadeTimer: timer => { this._resultDockFadeTimer = timer },
setTimeout,
clearTimeout,
isPageAlive: () => this._alive,
getFadeDelay: () => 5000,
})
)
resultDockController.show()
},
onResultPageInteraction() {
this._showResultDockAndRefreshTimer()
},
onPageScroll() {
this._showResultDockAndRefreshTimer()
},
goWrongBook() {
wx.navigateTo({ url: '/subpackages/study/wrong-book/wrong-book' })
},
goPractice() {
wx.navigateTo({ url: '/subpackages/study/practice/practice' })
},
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
this._reviewTimer = createReviewTimerController({
getSession: () => this._reviewSession,
isPageAlive: () => this._alive,
monotonicNow: () => _reviewMonotonicNow(),
serverNow: () => _reviewServerNow(),
getTimerId: () => this._timerInterval,
setTimerId: id => { this._timerInterval = id },
setInterval,
clearInterval,
setData: patch => this.setData(patch),
formatElapsed: seconds => formatReviewElapsed(seconds),
createRequestId: () => (typeof api.createRequestId === 'function' ? api.createRequestId() : undefined),
})
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
