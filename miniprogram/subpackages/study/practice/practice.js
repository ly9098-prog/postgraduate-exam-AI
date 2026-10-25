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
  createQuestionLoadController,
} = require('./utils/question-load-controller')
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
this._pageAlive = true
this._subjectsRequestSeq = 0
this._questionsRequestSeq = 0
this._lastSubjectOptionTap = null
this._exitConfirmInFlight = false
this._systemBackPromptQueued = false
this._systemBackRearming = false
this._systemBackRearmTimer = null
this._returnNavigationLocked = false
this._launchPreset = this._parseLaunchPreset(options || {})
const fastKnowledgeSources = new Set(['knowledge_map', 'knowledge_diagnosis'])
this._fastLaunchEligible = Boolean(
this._launchPreset &&
fastKnowledgeSources.has(this._launchPreset.source) &&
this._launchPreset.autostart &&
this._launchPreset.subjectId &&
this._launchPreset.knowledgePointId
)
this.setData({
entryResolved: true,
launchingPreset: Boolean(this._fastLaunchEligible),
})
this._launchKnowledgePoint = ''
this._launchKnowledgePointId = null
this._launchIncludeDescendants = false
this._launchQuestionIds = ''
this._launchAllowRepeat = false
this._launchSource = ''
this._launchPlanToken = ''
this._launchReturnTo = ''
this._resetSession()
this._pendingResultUrl = ''
this._submittedResultPayload = null
setRenderGuardPage('practice')
resetRenderGuard()
this._initCustomNavigation()
this._updateComputedFields()
},
onUnload() {
this._pageAlive = false
if (this._practiceSession) this._practiceSession.exitGuardActive = false
this._exitConfirmInFlight = false
this._systemBackPromptQueued = false
this._systemBackRearming = false
if (this._systemBackRearmTimer) {
clearTimeout(this._systemBackRearmTimer)
this._systemBackRearmTimer = null
}
this._subjectsRequestSeq++
this._questionsRequestSeq++
this._lastSubjectOptionTap = null
resetRenderGuard()
this._clearTimer()
if (this._feedbackTimer) {
clearTimeout(this._feedbackTimer)
this._feedbackTimer = null
}
if (this._subjectSheetCloseTimer) {
clearTimeout(this._subjectSheetCloseTimer)
this._subjectSheetCloseTimer = null
}
},
_resetSession() {
this._practiceSession = {
traceId: '',
safeModeActive: false,
answerMap: {},
answeredFlags: {},
correctCount: 0,
comboCount: 0,
elapsedSec: 0,
activeStartedMonoMs: 0,
startedAtMs: 0,
questionTimeMap: {},
currentQuestionStartedMonoMs: 0,
requestId: '',
recommendationRequestId: '',
batchToken: '',
batchMode: '',
knowledgeScope: null,
submissionSnapshot: null,
backgroundMs: 0,
_backgroundStartedMonoMs: null,
_timingPauseActive: false,
optionKeys: [],
questionRenderCache: Object.create(null),
exitGuardActive: false,
exitGuardMessage: '',
}
},
_getCurrentUserId() {
try {
const user = wx.getStorageSync('user')
if (!user || typeof user !== 'object') return ''
const candidates = [user.id, user.user_id, user.openid]
for (let candidateIndex = 0; candidateIndex < candidates.length; candidateIndex++) {
const candidate = candidates[candidateIndex]
if (candidate === undefined || candidate === null) continue
const value = String(candidate).trim()
if (value) return value
}
return ''
} catch (_) {
return ''
}
},
_pendingSubmissionStorageKey() {
const userId = this._getCurrentUserId()
return userId ? `${PRACTICE_PENDING_SUBMISSION_KEY_PREFIX}:${userId}` : ''
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
return this._pendingSubmission || (
this._pendingSubmission = createPendingSubmissionController({
getStorageKey: () => this._pendingSubmissionStorageKey(),
readStorage: key => wx.getStorageSync(key),
writeStorage: (key, value) => wx.setStorageSync(key, value),
removeStorage: key => wx.removeStorageSync(key),
now: () => Date.now(),
getTtlMs: () => PRACTICE_PENDING_SUBMISSION_TTL_MS,
isPageAlive: () => this._pageAlive,
showConfirm: options => this._showSubmitConfirm(options),
logWarn: (...args) => console.warn(...args),
restoreSubmittedSnapshot: (submission, resultUrl) => {
this._practiceSession.submissionSnapshot = submission
this._practiceSession.requestId = submission.requestId || ''
this._pendingResultUrl = resultUrl
this.setData({ submitted: true, submitting: false })
this._setPracticeUnloadGuard(false)
this._openSubmittedResult(resultUrl, submission)
},
resumePendingSubmission: async submission => {
this._resetSession()
this._practiceSession.submissionSnapshot = submission
this._practiceSession.requestId = submission.requestId || ''
this._practiceSession.traceId = submission.traceId || ''
this.setData({ started: true, submitted: false, submitting: false })
this._setPracticeUnloadGuard(true, '交卷仍在确认中。')
await this.doSubmit(true)
if (!this.data.submitted && this._pageAlive) {
this._setPracticeUnloadGuard(false)
this.setData({ started: false })
return false
}
return true
},
})
)
},
_openSubmittedResult(resultUrl, submission) {
  this._submittedResultController().open(resultUrl, submission)
},
_submittedResultController() {
  return this._submittedResultControllerInstance || (
    this._submittedResultControllerInstance = createSubmittedResultController({
      isPageAlive: () => this._pageAlive,
      getSubmittedResultPayload: () => this._submittedResultPayload,
      writeResultCache: payload => wx.setStorageSync('lastPracticeResult', payload),
      logWarn: (...args) => console.warn(...args),
      logError: (...args) => console.error(...args),
      showConfirm: options => this._showSubmitConfirm(options),
      getSession: () => this._practiceSession,
      setPendingResultUrl: value => { this._pendingResultUrl = value },
      setData: patch => this.setData(patch),
      setUnloadGuard: enabled => this._setPracticeUnloadGuard(enabled),
      redirectTo: options => wx.redirectTo(options),
    })
  )
},
onShow() {
const s = this._practiceSession
if (s && s._timingPauseActive) return
if (s && s.activeStartedMonoMs && s._backgroundStartedMonoMs !== null) {
s.backgroundMs = (s.backgroundMs || 0) + (monotonicNow() - s._backgroundStartedMonoMs)
s._backgroundStartedMonoMs = null
}
if (s && s.activeStartedMonoMs && this.data.started && !this.data.loading && !this.data.submitting && !s.submissionSnapshot) {
s.currentQuestionStartedMonoMs = monotonicNow()
}
},
onHide() {
const s = this._practiceSession
if (s && s._timingPauseActive) return
if (s && s.activeStartedMonoMs && s._backgroundStartedMonoMs === null) {
if (this.data.started && !this.data.loading && !this.data.submitting && !s.submissionSnapshot) {
this._settleQuestionTime(true)
}
s._backgroundStartedMonoMs = monotonicNow()
}
},
async onReady() {
if (config.DEV) console.log('[LAYER6_ONREADY]', Date.now())
this.setData({ enableMathImage: config.enableMathImage || false })
const recoveryHandled = await this._offerPendingSubmissionRecovery()
if (recoveryHandled || !this._pageAlive) {
if (this.data.launchingPreset) this.setData({ launchingPreset: false })
return
}
if (this._fastLaunchEligible) {
const applied = await this._applyFastLaunchPreset()
if (applied && this._pageAlive) {
await this.startPractice()
if (this._pageAlive) {
this.loadPracticeSubjects({ skipAutostart: true, preserveSelection: true, silent: true }).catch(() => {})
}
return
}
}
if (this.data.launchingPreset) this.setData({ launchingPreset: false })
this.loadPracticeSubjects()
},
async loadPracticeSubjects(options = {}) {
const requestSeq = ++this._subjectsRequestSeq
try {
const res = await api.get('/practice/subjects')
if (!this._pageAlive || requestSeq !== this._subjectsRequestSeq) return
const subjectTree = this.normalizeSubjectTree(filter408SubjectTree(res || []))
this.setData({ subjectTree })
if (options.preserveSelection && this.data.selectedSubjectId) {
const available = this._flattenSelectableSubjects(subjectTree || [])
const target = available.find(item => Number(item.subject_id) === Number(this.data.selectedSubjectId))
if (target) {
this.setData({
selectedSubjectName: this.data.selectedSubjectName || target.display_name,
selectedSubjectHasChildren: Boolean(target.has_children),
expandedSubjectId: target.parent_subject_id || target.subject_id,
})
}
} else {
this.initDefaultSubject(subjectTree)
}
if (!options.skipAutostart) {
const presetApplied = await this._applyLaunchPreset(subjectTree)
if (presetApplied && this._launchPreset && this._launchPreset.autostart && this._pageAlive) {
await this.startPractice()
}
}
} catch (e) {
if (!this._pageAlive || requestSeq !== this._subjectsRequestSeq) return
console.error('加载科目树失败', e)
if (!options.silent) wx.showToast({ title: '加载科目失败', icon: 'none' })
}
},
_parseLaunchPreset(options) {
return parseLaunchPreset(options, safeDecodeURIComponent)
},
async _applyFastLaunchPreset() {
const preset = this._launchPreset
if (!preset || !preset.subjectId || !preset.autostart) return false
const subjectName = preset.subjectName || this.data.selectedSubjectName || '专项练习'
applyLaunchOverrides(this, launchPresetOverrides(preset))
await new Promise(resolve => {
const view = fastLaunchPresetView(preset, this.data.selectedMode, this.data.count)
view.selectedSubjectName = subjectName
this.setData(view, () => {
this._updateComputedFields()
resolve()
})
})
this._queueRememberSubject(Number(preset.subjectId), subjectName)
return true
},
async _applyLaunchPreset(subjectTree) {
const preset = this._launchPreset
const available = this._flattenSelectableSubjects(subjectTree || [])
if (preset && preset.subjectCode && !preset.subjectId) {
const byCode = available.find(item => String(item.subject_code || '') === String(preset.subjectCode || ''))
if (byCode) preset.subjectId = Number(byCode.subject_id)
}
if (!preset || !preset.subjectId) return false
const target = available.find(item => Number(item.subject_id) === Number(preset.subjectId))
if (!target) {
console.warn('[PRACTICE_LAUNCH_PRESET] subject unavailable', preset.subjectId)
if (preset.autostart) wx.showToast({ title: '推荐科目已不可用，请重新选择', icon: 'none' })
return false
}
if (preset.questionIds && preset.mode && preset.mode !== 'random') {
console.warn('[PRACTICE_LAUNCH_PRESET] targeted questions require random mode')
return false
}
applyLaunchOverrides(this, launchPresetOverrides(preset))
await new Promise((resolve) => {
const view = resolvedLaunchPresetView(preset, target, this.data.selectedMode, this.data.count)
this.setData(view, () => {
this._updateComputedFields()
resolve()
})
})
this._queueRememberSubject(Number(target.subject_id), target.display_name)
return true
},
normalizeSubjectTree(raw) {
  return normalizeSubjectTree(raw)
},
initDefaultSubject(subjectTree) {
if (!subjectTree || subjectTree.length === 0) {
this.setData({
selectedSubjectId: null,
selectedSubjectName: '',
selectedSubjectHasChildren: false,
expandedSubjectId: null,
recentSubjects: [],
})
return
}
let stored = []
try {
const value = wx.getStorageSync(RECENT_SUBJECTS_STORAGE_KEY)
stored = Array.isArray(value) ? value : []
} catch (e) {
stored = []
}
const selection = selectDefaultSubject({
subjectTree,
storedSubjects: stored,
flattenSelectableSubjects: tree => this._flattenSelectableSubjects(tree),
decorateRecentSubjects: subjects => this._decorateRecentSubjects(subjects),
})
if (selection) this.setData(selection.view)
},
_initCustomNavigation() {
try {
const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
const statusBarHeight = Number(windowInfo.statusBarHeight || 20)
let navBarHeight = 44
if (wx.getMenuButtonBoundingClientRect) {
const capsule = wx.getMenuButtonBoundingClientRect()
if (capsule && capsule.height && capsule.top) {
navBarHeight = (capsule.top - statusBarHeight) * 2 + capsule.height
}
}
this.setData({
statusBarHeight: Math.max(20, statusBarHeight),
navBarHeight: Math.max(40, navBarHeight),
})
} catch (e) {
this.setData({ statusBarHeight: 20, navBarHeight: 44 })
}
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
return this._recentSubjectControllerInstance || (
this._recentSubjectControllerInstance = createRecentSubjectController({
findParentSubjectId: id => this._findParentSubjectId(id),
subjectHasChildren: id => this._subjectHasChildren(id),
getRecentSubjects: () => this.data.recentSubjects || [],
decorateRecentSubjects: subjects => this._decorateRecentSubjects(subjects),
setData: patch => this.setData(patch),
setStorage: (key, value) => wx.setStorageSync(key, value),
logWarn: (...args) => console.warn(...args),
getPending: () => this._pendingRememberSubject,
setPending: value => { this._pendingRememberSubject = value },
})
)
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
this.setData({ settingsExpanded: !this.data.settingsExpanded })
},
openSubjectSheet() {
this._subjectSheetController().open()
},
_subjectSheetController() {
return this._subjectSheetControllerInstance || (
this._subjectSheetControllerInstance = createSubjectSheetController({
getCloseTimer: () => this._subjectSheetCloseTimer,
setCloseTimer: timer => { this._subjectSheetCloseTimer = timer },
clearTimeout: timer => clearTimeout(timer),
setData: (patch, callback) => this.setData(patch, callback),
isVisible: () => this.data.subjectSheetVisible,
isClosing: () => this.data.subjectSheetClosing,
isPageAlive: () => this._pageAlive,
setTimeout: (callback, delay) => setTimeout(callback, delay),
getLastTap: () => this._lastSubjectOptionTap,
setLastTap: value => { this._lastSubjectOptionTap = value },
now: () => Date.now(),
closeSheet: () => this.closeSubjectSheet(),
})
)
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
// Home/Study Hub route params are setup defaults, not invisible constraints.
// Once the user changes subject/mode/count, continuing to send the original KP or
// targeted-question scope can silently pin a parent-subject practice to one child
// subject and can also make the signed batch impossible to submit.
this._launchKnowledgePoint = ''
this._launchKnowledgePointId = null
this._launchIncludeDescendants = false
this._launchQuestionIds = ''
this._launchAllowRepeat = false
this._launchPlanToken = ''
},
_selectSubject(subjectId, subjectName, expandedSubjectId, hasChildren) {
this._subjectSelectionController().select(subjectId, subjectName, expandedSubjectId, hasChildren)
},
_subjectSelectionController() {
return this._subjectSelectionControllerInstance || (
this._subjectSelectionControllerInstance = createSubjectSelectionController({
getSelectedSubjectId: () => this.data.selectedSubjectId,
getSelectedMode: () => this.data.selectedMode,
getCount: () => this.data.count,
getExpandedSubjectId: () => this.data.expandedSubjectId,
findParentSubjectId: id => this._findParentSubjectId(id),
subjectHasChildren: id => this._subjectHasChildren(id),
clearLaunchOverrides: () => this._clearLaunchOverridesForManualConfig(),
queueRememberSubject: (id, name) => this._queueRememberSubject(id, name),
handleSubjectOptionTap: (id, source) => this._handleSubjectOptionTap(id, source),
setData: (patch, callback) => this.setData(patch, callback),
updateComputedFields: () => this._updateComputedFields(),
})
)
},
chooseRecentSubject(e) {
this._subjectSelectionController().chooseRecent(e)
},
_findLaunchReturnStackIndex(pages, returnTo) {
return this._launchReturnController().findStackIndex(pages, returnTo)
},
_launchReturnController() {
return this._launchReturnControllerInstance || (
this._launchReturnControllerInstance = createLaunchReturnController({
safeDecodeURIComponent,
isPageAlive: () => this._pageAlive,
getCurrentPages: () => (getCurrentPages ? getCurrentPages() : []),
setNavigationLocked: value => { this._returnNavigationLocked = value },
isNavigationLocked: () => this._returnNavigationLocked,
redirectTo: options => wx.redirectTo(options),
reLaunch: options => wx.reLaunch(options),
navigateBack: options => wx.navigateBack(options),
showToast: options => wx.showToast(options),
setTimeout: (callback, delay) => setTimeout(callback, delay),
hasNextTick: () => typeof wx.nextTick === 'function',
nextTick: callback => wx.nextTick(callback),
getReturnTo: () => this._launchReturnTo || (this._launchPreset && this._launchPreset.returnTo) || '',
isExitGuardVisible: () => this.data.practiceExitGuardVisible,
setData: (patch, callback) => this.setData(patch, callback),
})
)
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
return this._startPracticeControllerInstance || (
this._startPracticeControllerInstance = createStartPracticeController({
isLoading: () => this.data.loading,
isSubmitting: () => this.data.submitting,
readPendingSubmission: () => this._readPendingSubmission(),
offerPendingSubmissionRecovery: () => this._offerPendingSubmissionRecovery(),
getSelectedSubjectId: () => this.data.selectedSubjectId,
openSubjectSheet: () => this.openSubjectSheet(),
getSelectedMode: () => this.data.selectedMode,
isSelectedSubjectHasChildren: () => this.data.selectedSubjectHasChildren,
showToast: options => wx.showToast(options),
createTraceId: () => api.createTraceId(),
setSubmittedResultPayload: value => { this._submittedResultPayload = value },
resetSession: () => this._resetSession(),
setTraceId: traceId => { this._practiceSession.traceId = traceId },
setData: patch => this.setData(patch),
setUnloadGuard: enabled => this._setPracticeUnloadGuard(enabled),
flushPendingRecentSubject: () => this._flushPendingRecentSubject(),
loadQuestions: () => this._loadQuestions(),
})
)
},
_startTimer() {
this._clearTimer()
this._timer = setInterval(() => {
if (!this._pageAlive || !this._practiceSession.activeStartedMonoMs) return
const now = monotonicNow()
const backgroundMs = (this._practiceSession.backgroundMs || 0) + (
this._practiceSession._backgroundStartedMonoMs !== null
? Math.max(0, now - this._practiceSession._backgroundStartedMonoMs)
: 0
)
const sec = Math.max(0, Math.floor((now - this._practiceSession.activeStartedMonoMs - backgroundMs) / 1000))
this._practiceSession.elapsedSec = sec
this.setData({ elapsedText: this._fmt(sec) })
}, 1000)
},
_fmt(sec) {
const s = Math.max(0, sec || 0)
const m = Math.floor(s / 60)
const ss = s % 60
return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
},
_clearTimer() {
if (this._timer) {
clearInterval(this._timer)
this._timer = null
}
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
  return this._exitGuardControllerInstance || (
    this._exitGuardControllerInstance = createExitGuardController({
      getSession: () => this._practiceSession,
      hasDisableAlertBeforeUnload: () => !!wx.disableAlertBeforeUnload,
      disableAlertBeforeUnload: () => wx.disableAlertBeforeUnload(),
      isPageAlive: () => this._pageAlive,
      isGuardVisible: () => this.data.practiceExitGuardVisible,
      isStarted: () => this.data.started,
      isSubmitted: () => this.data.submitted,
      isRearming: () => this._systemBackRearming,
      setRearming: value => { this._systemBackRearming = value },
      getRearmTimer: () => this._systemBackRearmTimer,
      setRearmTimer: timer => { this._systemBackRearmTimer = timer },
      clearTimeout: timer => clearTimeout(timer),
      isPromptQueued: () => this._systemBackPromptQueued,
      setPromptQueued: value => { this._systemBackPromptQueued = value },
      isExitConfirmInFlight: () => this._exitConfirmInFlight,
      hasNextTick: () => typeof wx.nextTick === 'function',
      nextTick: callback => wx.nextTick(callback),
      setData: (patch, callback) => this.setData(patch, callback),
      setTimeout: (callback, delay) => setTimeout(callback, delay),
      queueMicrotask: callback => Promise.resolve().then(callback),
      requestExit: options => this.requestExitPractice(options),
      logWarn: (...args) => console.warn(...args),
    })
  )
},
async _loadQuestions() {
return this._questionLoadController().load()
},
_questionLoadController() {
return this._questionLoad || (
this._questionLoad = createQuestionLoadController({
nextRequestSeq: () => ++this._questionsRequestSeq,
getRequestSeq: () => this._questionsRequestSeq,
isPageAlive: () => this._pageAlive,
isLoading: () => this.data.loading,
setData: (data, cb) => this.setData(data, cb),
getSubjectId: () => this.data.selectedSubjectId,
getSelectedMode: () => this.data.selectedMode,
buildRequestParams: () => this._buildQuestionRequestParams(),
requestQuestions: params => api.get('/practice/questions', params),
validateKnowledgeScope: res => {
if (!this._launchIncludeDescendants) return null
const scope = res && res.knowledge_scope
if (validateKnowledgeScope(scope, this._launchKnowledgePointId)) return null
return {
logTag: '[PRACTICE_KNOWLEDGE_SCOPE_MISMATCH]',
logDetail: {
requestedRootId: this._launchKnowledgePointId,
requestedIncludeDescendants: true,
receivedScope: scope || null,
traceId: res && (res.trace_id || this._practiceSession.traceId),
},
resetMessage: '章节专项范围校验失败，请更新后端服务后重试。',
toastTitle: '章节专项暂不可用',
}
},
applyKnowledgeScope: res => {
this._practiceSession.knowledgeScope = res && res.knowledge_scope
? Object.assign({}, res.knowledge_scope)
: null
},
findBatchError: res => findQuestionBatchError(
Array.isArray(res.questions) ? res.questions : [],
{
answerableTypes: PRACTICE_ANSWERABLE_TYPES,
allowedScopeIds: new Set(
this._getPracticeSubjectScopeIds(
this.data.selectedSubjectId,
this._buildQuestionRequestParams().include_children
).map(Number)
),
}
),
resolveBatchErrorRecovery: (batchError, res) => resolveBatchErrorRecovery(batchError, {
subjectId: this.data.selectedSubjectId,
includeChildren: this._buildQuestionRequestParams().include_children,
traceId: res.trace_id || this._practiceSession.traceId,
}),
applyAnsweredFlags: res => adapter.applyAnsweredFlags(
Array.isArray(res.questions) ? res.questions : [],
{},
'id'
),
restartSequential: (progress, subjectId, loadSeq) => this._sequentialRestartController().restart(
progress,
subjectId,
this.data.selectedSubjectName,
loadSeq
),
debugAfterApi: (res, questions) => {
debugLog(this._practiceSession.traceId, 'STATE_AFTER_API', {
total: questions.length,
responseTraceId: res.trace_id,
})
saveDebugSnapshot(this._practiceSession.traceId, 'state_after_api', {
total: questions.length,
questionIds: questions.map(q => q.id),
})
},
applyBatchCredentials: (res, mode) => applyBatchCredentials(this._practiceSession, res, mode),
hasMissingBatchCredentials: count => hasMissingBatchCredentials(this._practiceSession, count),
warmQuestionImages: (questions, index) => this._warmQuestionImages(questions, index),
buildFirstViewModel: q => this._buildQuestionViewModel(q),
buildLoadedView: (questions, viewModel) => buildLoadedView(questions, viewModel),
startLoadedSession: viewModel => {
if (!this._practiceSession.activeStartedMonoMs) {
this._practiceSession.activeStartedMonoMs = monotonicNow()
this._practiceSession.startedAtMs = api.now()
this._practiceSession.backgroundMs = 0
this._practiceSession._backgroundStartedMonoMs = null
this._practiceSession.elapsedSec = 0
}
this._practiceSession.optionKeys = viewModel.optionKeys
this._practiceSession.currentQuestionStartedMonoMs = monotonicNow()
this._setPracticeUnloadGuard(true)
this._startTimer()
this._updateComputedFields()
},
checkRenderInvariant: model => this._checkRenderInvariant(model),
showNoQuestions: subjectId => {
this._clearTimer()
this._setPracticeUnloadGuard(false)
const name = this.data.selectedSubjectName || String(subjectId)
this.setData(buildResetView())
this._showSubmitConfirm({
scenario: 'info',
eyebrow: 'NO QUESTIONS',
title: '该科目暂无可练题目',
message: `「${name}」目前没有可在本页作答的已发布题目。\n可检查导入审核状态、题型与科目分类，或选择其他科目。`,
confirmText: '返回选择科目',
hideCancel: true,
})
},
resetToSetup: errorText => {
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView(errorText))
},
logError: (...args) => console.error(...args),
showToast: options => wx.showToast(options),
})
)
},
_buildQuestionRequestParams() {
return buildQuestionRequestParams({
subjectId: this.data.selectedSubjectId,
selectedMode: this.data.selectedMode,
selectedSubjectHasChildren: this.data.selectedSubjectHasChildren,
count: this.data.count,
traceId: this._practiceSession.traceId,
launchQuestionIds: this._launchQuestionIds,
launchAllowRepeat: this._launchAllowRepeat,
launchPlanToken: this._launchPlanToken,
launchKnowledgePointId: this._launchKnowledgePointId,
launchIncludeDescendants: this._launchIncludeDescendants,
launchKnowledgePoint: this._launchKnowledgePoint,
})
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
if (!Array.isArray(questions) || !questions.length) return
const current = questions[index]
if (!current || typeof adapter.getQuestionPrefetchUrls !== 'function') return
const currentId = String(current.id == null ? '' : current.id)
const currentUrls = adapter.getQuestionPrefetchUrls(current)
if (currentUrls.length) {
questionImageCache.preloadMany(currentUrls, 3).then(() => {
if (!this._pageAlive || this.data.currentIndex !== index) return
const visible = this.data.questions[index]
if (!visible || String(visible.id == null ? '' : visible.id) !== currentId) return
try {
const refreshed = this._buildQuestionViewModel(visible, true)
if (!refreshed) return
this._practiceSession.optionKeys = refreshed.optionKeys
this.setData({
currentQuestion: refreshed.question,
currentAnswerState: refreshed.answerState,
})
} catch (err) {
if (config.DEV) console.warn('[practice] image cache refresh failed', err)
}
})
}
const neighborIndexes = [index + 1, index + 2, index - 1]
const neighborUrls = []
for (let i = 0; i < neighborIndexes.length; i++) {
const q = questions[neighborIndexes[i]]
if (!q) continue
const urls = adapter.getQuestionPrefetchUrls(q)
for (let j = 0; j < urls.length; j++) neighborUrls.push(urls[j])
}
if (neighborUrls.length) questionImageCache.preloadMany(neighborUrls, 2)
},
_settleQuestionTime(pause) {
this._questionTimerController().settle(pause)
},
_showQuestion(index) {
this._questionDisplayController().showQuestion(index)
},
goQuestion(e) {
const idx = e.detail.index
if (idx >= 0 && idx < this.data.totalQuestions) {
this._showQuestion(idx)
}
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
  return this._exitRequestControllerInstance || (
    this._exitRequestControllerInstance = createExitRequestController({
      isExitConfirmInFlight: () => this._exitConfirmInFlight,
      setExitConfirmInFlight: value => { this._exitConfirmInFlight = value },
      isSubmitting: () => this.data.submitting,
      isSubmitted: () => this.data.submitted,
      getPendingResultUrl: () => this._pendingResultUrl,
      getSubmissionSnapshot: () => this._practiceSession && this._practiceSession.submissionSnapshot,
      showConfirm: options => this._showSubmitConfirm(options),
      showPausedConfirm: options => this._showSubmitConfirmPaused(options),
      openSubmittedResult: (resultUrl, submission) => this._openSubmittedResult(resultUrl, submission),
      isPageAlive: () => this._pageAlive,
      clearPendingSubmission: requestId => this._clearPendingSubmission(requestId),
      setUnloadGuard: enabled => this._setPracticeUnloadGuard(enabled),
      incrementQuestionRequestSeq: () => { this._questionsRequestSeq++ },
      clearTimer: () => this._clearTimer(),
      clearFeedbackTimer: () => {
        if (this._feedbackTimer) {
          clearTimeout(this._feedbackTimer)
          this._feedbackTimer = null
        }
      },
      resetPracticeState: () => this._resetPracticeStateAfterExit(),
      setLastExitSource: value => { this._lastExitSource = value || '' },
      scrollToSetupTop: () => {
        if (typeof wx.pageScrollTo === 'function') wx.pageScrollTo({ scrollTop: 0, duration: 0 })
      },
    })
  )
},
_resetPracticeStateAfterExit() {
  this._resetSession()
  this._pendingResultUrl = ''
  this._submittedResultPayload = null
  // The runner lives inside this page. Restore its setup surface rather than
  // popping the page back to home (or a knowledge-map launch origin).
  this._launchPreset = null
  this._fastLaunchEligible = false
  this._launchKnowledgePoint = ''
  this._launchKnowledgePointId = null
  this._launchIncludeDescendants = false
  this._launchQuestionIds = ''
  this._launchAllowRepeat = false
  this._launchSource = ''
  this._launchPlanToken = ''
  this._launchReturnTo = ''
  this.setData({
    started: false,
    loading: false,
    launchingPreset: false,
    submitting: false,
    submitted: false,
    practiceExitGuardVisible: false,
    questions: [],
    currentQuestion: null,
    currentAnswerState: null,
    currentIndex: 0,
    totalQuestions: 0,
    answeredCount: 0,
    progressPercent: 0,
    elapsedText: '00:00',
    errorText: '',
    feedbackVisible: false,
  })
},
_questionDisplayController() {
return this._questionDisplay || (
this._questionDisplay = createPracticeQuestionDisplayController({
getSession: () => this._practiceSession,
getAnswerMap: () => this._practiceSession.answerMap,
getQuestions: () => this.data.questions,
isMathImageEnabled: () => config.enableMathImage,
isDev: () => config.DEV,
setData: (patch, cb) => this.setData(patch, cb),
updateComputedFields: () => this._updateComputedFields(),
checkRenderInvariant: model => this._checkRenderInvariant(model),
showToast: options => wx.showToast(options),
settleQuestionTime: () => this._settleQuestionTime(),
warmQuestionImages: index => this._warmQuestionImages(this.data.questions, index),
setOptionKeys: keys => { this._practiceSession.optionKeys = keys },
setCurrentQuestionStartedMono: () => { this._practiceSession.currentQuestionStartedMonoMs = monotonicNow() },
getTraceId: q => this._practiceSession.traceId || q.trace_id,
})
)
},
_computedFieldsController() {
return this._computedFields || (
this._computedFields = createComputedFieldsController({
getSelectedMode: () => this.data.selectedMode,
getCount: () => this.data.count,
getTotalQuestions: () => this.data.totalQuestions,
getAnsweredCount: () => this.data.answeredCount,
setData: patch => this.setData(patch),
})
)
},
_answerFeedbackController() {
return this._answerFeedback || (
this._answerFeedback = createAnswerFeedbackController({
getComboCount: () => this._practiceSession.comboCount,
setComboCount: count => { this._practiceSession.comboCount = count },
setData: patch => this.setData(patch),
clearFeedbackTimer: () => { if (this._feedbackTimer) { clearTimeout(this._feedbackTimer); this._feedbackTimer = null } },
setFeedbackTimer: (cb, ms) => { this._feedbackTimer = setTimeout(cb, ms) },
})
)
},
_renderInvariantController() {
return this._renderInvariant || (
this._renderInvariant = createRenderInvariantController({
isSafeModeActive: () => this._practiceSession.safeModeActive,
enterSafeMode: () => this._enterSafeMode(),
})
)
},
_questionTimerController() {
return this._questionTimer || (
this._questionTimer = createQuestionTimerController({
getCurrentIndex: () => this.data.currentIndex,
getQuestions: () => this.data.questions,
getCurrentQuestionStartedMonoMs: () => this._practiceSession.currentQuestionStartedMonoMs,
getQuestionTimeMap: () => this._practiceSession.questionTimeMap,
setQuestionTimeMap: map => { this._practiceSession.questionTimeMap = map },
setCurrentQuestionStartedMonoMs: ms => { this._practiceSession.currentQuestionStartedMonoMs = ms },
monotonicNow: () => monotonicNow(),
})
)
},
_sequentialRestartController() {
return this._sequentialRestart || (
this._sequentialRestart = createSequentialRestartController({
clearTimer: () => this._clearTimer(),
setUnloadGuard: value => this._setPracticeUnloadGuard(value),
setData: data => this.setData(data),
buildResetView: () => buildResetView(),
showRestartConfirm: options => this._showSubmitConfirm(options),
isPageAlive: () => this._pageAlive,
getRequestSeq: () => this._questionsRequestSeq,
getTraceId: () => this._practiceSession.traceId,
resetSequentialProgress: payload => api.post('/practice/sequential/reset', payload),
logError: (...args) => console.error(...args),
showToast: options => wx.showToast(options),
getSession: () => this._practiceSession,
resetSequentialTiming: session => resetSequentialTiming(session),
buildSequentialRestartView: () => buildSequentialRestartView(),
reloadQuestions: () => this._loadQuestions(),
})
)
},
_selfHealController() {
return this._selfHeal || (
this._selfHeal = createSelfHealController({
setSafeModeActive: v => { this._practiceSession.safeModeActive = v },
getQuestions: () => this.data.questions,
getCurrentIndex: () => this.data.currentIndex,
clearRenderCache: () => { this._practiceSession.questionRenderCache = Object.create(null) },
buildViewModel: (q, force) => this._buildQuestionViewModel(q, force),
setData: patch => this.setData(patch),
})
)
},
_answerInteractionController() {
return this._answerInteraction || (
this._answerInteraction = createPracticeAnswerInteractionController({
isSubmitted: () => this.data.submitted,
isSubmissionLocked: () => this._isSubmissionLocked(),
getCurrentQuestion: () => this.data.currentQuestion,
getAnswerMap: () => this._practiceSession.answerMap,
setAnswerMap: map => { this._practiceSession.answerMap = map },
getAnsweredFlags: () => this._practiceSession.answeredFlags,
setAnsweredFlags: flags => { this._practiceSession.answeredFlags = flags },
getQuestions: () => this.data.questions,
getCurrentIndex: () => this.data.currentIndex,
getTotalQuestions: () => this.data.totalQuestions,
getQuestionRenderView: q => this._getQuestionRenderView(q),
buildQuestionAnswerState: (renderView, answer) => this._buildQuestionAnswerState(renderView, answer),
setData: (patch, cb) => this.setData(patch, cb),
updateComputedFields: () => this._updateComputedFields(),
debugStateChange: (q, prev, next, count) => {
if (shouldDebugQuestion(q.id)) {
debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
questionId: q.id, previousAnswer: prev, nextAnswer: next, answeredCount: count,
})
saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
questionId: q.id, previousAnswer: prev, nextAnswer: next, answeredCount: count,
})
}
},
})
)
},
_isSubmissionLocked() {
if (!this._practiceSession || !this._practiceSession.submissionSnapshot) return false
const submission = this._practiceSession.submissionSnapshot
wx.showToast({
title: submission.serverAccepted
? '本次已交卷，请查看结果'
: (submission.retryBlocked ? '提交已被拒绝，请退出后重试' : '交卷内容已锁定，请确认提交'),
icon: 'none',
})
return true
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
var comp = this.selectComponent('#submitConfirm')
if (!comp || typeof comp.show !== 'function') {
wx.showToast({ title: opts.title || '请稍后重试', icon: 'none' })
return Promise.resolve(false)
}
return comp.show(opts)
},
async _showSubmitConfirmPaused(opts) {
  return this._pausedConfirmController().show(opts)
},
_pausedConfirmController() {
  return this._pausedConfirmControllerInstance || (
    this._pausedConfirmControllerInstance = createPausedConfirmController({
      getSession: () => this._practiceSession,
      monotonicNow,
      settleQuestionTime: pause => this._settleQuestionTime(pause),
      clearTimer: () => this._clearTimer(),
      showConfirm: options => this._showSubmitConfirm(options),
      isPageAlive: () => this._pageAlive,
      isStarted: () => this.data.started,
      isSubmitted: () => this.data.submitted,
      isSubmitting: () => this.data.submitting,
      startTimer: () => this._startTimer(),
    })
  )
},
async doSubmit(skipConfirm) {
return this._submitFlowController().submit(skipConfirm)
},
_submitFlowController() {
return this._submitFlowControllerInstance || (
this._submitFlowControllerInstance = createSubmitFlowController({
isSubmitting: () => this.data.submitting,
getSubmissionSnapshot: () => this._practiceSession.submissionSnapshot,
isSubmitted: () => this.data.submitted,
getPendingResultUrl: () => this._pendingResultUrl,
openSubmittedResult: (resultUrl, submission) => this._openSubmittedResult(resultUrl, submission),
showConfirm: options => this._showSubmitConfirm(options),
getQuestions: () => this.data.questions || [],
prepareSubmission: skipConfirm => this._submitEntryController().prepare(skipConfirm),
clearTimer: () => this._clearTimer(),
persistPendingSubmission: (submission, status, resultUrl) => this._persistPendingSubmission(submission, status, resultUrl),
setData: patch => this.setData(patch),
buildSubmitPayload,
getTraceId: () => this._practiceSession.traceId,
requestSubmit: payload => api.post('/practice/batch-submit', payload),
isPageAlive: () => this._pageAlive,
handleSubmitError: (submission, error) => this._submitErrorController().handle(submission, error),
completeSubmit: (submission, submitResult, questions) => this._submitSuccessController().complete(submission, submitResult, questions),
})
)
},
_submitSuccessController() {
return this._submitSuccessControllerInstance || (
this._submitSuccessControllerInstance = createSubmitSuccessController({
getCurrentUserId: () => this._getCurrentUserId(),
now: () => Date.now(),
buildCacheKey: createdAt => 'pr_' + createdAt + '_' + Math.random().toString(36).slice(2, 8),
getTraceId: () => this._practiceSession.traceId,
buildResultPayload: options => buildSubmitResultPayload({
...options,
buildStoredResults,
buildLightQuestions,
computeDisplaySkippedCount,
}),
setSubmittedResultPayload: payload => { this._submittedResultPayload = payload },
writeResultCache: payload => wx.setStorageSync('lastPracticeResult', payload),
logWarn: (...args) => console.warn(...args),
buildResultUrl: options => buildPracticeResultUrl(options),
getLaunchSource: () => this._launchSource || '',
getLaunchReturnTo: () => this._launchReturnTo || '',
setPendingResultUrl: value => { this._pendingResultUrl = value },
persistPendingSubmission: (submission, status, resultUrl) => this._persistPendingSubmission(submission, status, resultUrl),
setUnloadGuard: enabled => this._setPracticeUnloadGuard(enabled),
setData: patch => this.setData(patch),
openSubmittedResult: (resultUrl, submission) => this._openSubmittedResult(resultUrl, submission),
})
)
},
_submitErrorController() {
return this._submitError || (
this._submitError = createSubmitErrorController({
isPageAlive: () => this._pageAlive,
logError: (...args) => console.error(...args),
pauseQuestionTiming: () => { this._practiceSession.currentQuestionStartedMonoMs = 0 },
setData: patch => this.setData(patch),
isDeterministicReject,
persistPendingSubmission: (submission, status, resultUrl) => this._persistPendingSubmission(submission, status, resultUrl),
setUnloadGuard: (enabled, message) => this._setPracticeUnloadGuard(enabled, message),
resolveRejectMessage,
showConfirm: options => this._showSubmitConfirm(options),
})
)
},
_submitEntryController() {
return this._submitEntry || (
this._submitEntry = createSubmitEntryController({
getQuestions: () => this.data.questions || [],
getSelectedSubjectId: () => this.data.selectedSubjectId,
getSelectedSubjectName: () => this.data.selectedSubjectName,
getAnswerMap: () => this._practiceSession.answerMap,
getActiveStartedMonoMs: () => this._practiceSession.activeStartedMonoMs,
getComboCount: () => this._practiceSession.comboCount,
buildAnsweredFlags: adapter.buildAnsweredFlags,
classifyAnswers,
isMultiBlank: adapter.isMultiBlankChoice,
showToast: options => wx.showToast(options),
showPausedConfirm: options => this._showSubmitConfirmPaused(options),
showConfirm: options => this._showSubmitConfirm(options),
clearTimer: () => this._clearTimer(),
settleQuestionTime: pause => this._settleQuestionTime(pause),
monotonicNow,
now: () => api.now(),
getBackgroundMs: () => this._practiceSession.backgroundMs,
getRequestId: () => this._practiceSession.requestId,
buildRequestId: () => 'req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
setRequestId: requestId => { this._practiceSession.requestId = requestId },
buildSubmitAnswers,
getQuestionTimeMap: () => this._practiceSession.questionTimeMap,
getRecommendationRequestId: () => this._practiceSession.recommendationRequestId,
buildSubmitSession,
getBatchMode: () => this._practiceSession.batchMode,
getSelectedMode: () => this.data.selectedMode,
getStartedAtMs: () => this._practiceSession.startedAtMs,
buildRecoveryQuestions,
getBatchToken: () => this._practiceSession.batchToken,
buildSubmissionSnapshot,
getTraceId: () => this._practiceSession.traceId,
getKnowledgeScope: () => this._practiceSession.knowledgeScope,
setSubmissionSnapshot: submission => { this._practiceSession.submissionSnapshot = submission },
persistPendingSubmission: (submission, status, resultUrl) => this._persistPendingSubmission(submission, status, resultUrl),
setUnloadGuard: (enabled, message) => this._setPracticeUnloadGuard(enabled, message),
})
)
},
})
