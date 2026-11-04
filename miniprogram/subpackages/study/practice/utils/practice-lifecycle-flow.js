const coldResume = require('./cold-resume-controller')

function onLoad(page, options, dependencies) {
const { resetRenderGuard, setRenderGuardPage } = dependencies
page._pageAlive = true
page._coldResumeRequested = Boolean(options && String(options.resume) === '1')
page._coldResumeOwner = coldResume.userId()
page._coldResumeCreatedAt = undefined
page._subjectsRequestSeq = 0
page._questionsRequestSeq = 0
page._lastSubjectOptionTap = null
page._exitConfirmInFlight = false
page._systemBackPromptQueued = false
page._systemBackRearming = false
page._systemBackRearmTimer = null
page._returnNavigationLocked = false
page._launchPreset = page._parseLaunchPreset(options || {})
const fastKnowledgeSources = new Set(['knowledge_map', 'knowledge_diagnosis'])
page._fastLaunchEligible = Boolean(
page._launchPreset &&
fastKnowledgeSources.has(page._launchPreset.source) &&
page._launchPreset.autostart &&
page._launchPreset.subjectId &&
page._launchPreset.knowledgePointId
)
page.setData({
entryResolved: true,
launchingPreset: Boolean(page._fastLaunchEligible),
})
page._launchKnowledgePoint = ''
page._launchKnowledgePointId = null
page._launchIncludeDescendants = false
page._launchQuestionIds = ''
page._launchAllowRepeat = false
page._launchSource = ''
page._launchPlanToken = ''
page._launchReturnTo = ''
page._resetSession()
page._pendingResultUrl = ''
page._submittedResultPayload = null
setRenderGuardPage('practice')
resetRenderGuard()
page._initCustomNavigation()
page._updateComputedFields()
}

function onUnload(page, dependencies) {
const { getClearTimeout, resetRenderGuard } = dependencies
page._pageAlive = false
if (page._practiceSession) page._practiceSession.exitGuardActive = false
page._exitConfirmInFlight = false
page._systemBackPromptQueued = false
page._systemBackRearming = false
if (page._systemBackRearmTimer) {
getClearTimeout()(page._systemBackRearmTimer)
page._systemBackRearmTimer = null
}
page._subjectsRequestSeq++
page._questionsRequestSeq++
page._lastSubjectOptionTap = null
resetRenderGuard()
page._clearTimer()
if (page._feedbackTimer) {
getClearTimeout()(page._feedbackTimer)
page._feedbackTimer = null
}
if (page._subjectSheetCloseTimer) {
getClearTimeout()(page._subjectSheetCloseTimer)
page._subjectSheetCloseTimer = null
}
}

function _resetSession(page) {
page._coldResumeCreatedAt = undefined
page._practiceSession = {
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
}

async function onReady(page, dependencies) {
const { config, getConsole, getDate } = dependencies
if (config.DEV) getConsole().log('[LAYER6_ONREADY]', getDate().now())
page.setData({ enableMathImage: config.enableMathImage || false })
if (page._coldResumeRequested && coldResume.hasPending()) page._coldResumeRequested = false
const recoveryHandled = await page._offerPendingSubmissionRecovery()
if (recoveryHandled || !page._pageAlive) {
if (page.data.launchingPreset) page.setData({ launchingPreset: false })
return
}
if (coldResume.restore(page)) {
if (page.data.started && page._pageAlive) {
page.loadPracticeSubjects({ skipAutostart: true, preserveSelection: true, silent: true }).catch(() => {})
}
return
}
if (page._fastLaunchEligible) {
const applied = await page._applyFastLaunchPreset()
if (applied && page._pageAlive) {
await page.startPractice()
if (page._pageAlive) {
page.loadPracticeSubjects({ skipAutostart: true, preserveSelection: true, silent: true }).catch(() => {})
}
return
}
}
if (page.data.launchingPreset) page.setData({ launchingPreset: false })
page.loadPracticeSubjects()
}

function _initCustomNavigation(page, dependencies) {
const { getMath, getPlatform } = dependencies
try {
const windowInfo = getPlatform().getWindowInfo ? getPlatform().getWindowInfo() : {}
const statusBarHeight = Number(windowInfo.statusBarHeight || 20)
let navBarHeight = 44
if (getPlatform().getMenuButtonBoundingClientRect) {
const capsule = getPlatform().getMenuButtonBoundingClientRect()
if (capsule && capsule.height && capsule.top) {
navBarHeight = (capsule.top - statusBarHeight) * 2 + capsule.height
}
}
page.setData({
statusBarHeight: getMath().max(20, statusBarHeight),
navBarHeight: getMath().max(40, navBarHeight),
})
} catch (e) {
page.setData({ statusBarHeight: 20, navBarHeight: 44 })
}
}

function _resetPracticeStateAfterExit(page) {
  coldResume.clear(page)
  page._resetSession()
  page._pendingResultUrl = ''
  page._submittedResultPayload = null
  // The runner lives inside this page. Restore its setup surface rather than
  // popping the page back to home (or a knowledge-map launch origin).
  page._launchPreset = null
  page._fastLaunchEligible = false
  page._launchKnowledgePoint = ''
  page._launchKnowledgePointId = null
  page._launchIncludeDescendants = false
  page._launchQuestionIds = ''
  page._launchAllowRepeat = false
  page._launchSource = ''
  page._launchPlanToken = ''
  page._launchReturnTo = ''
  page.setData({
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
}

function _getCurrentUserId(page, dependencies) {
const { getPlatform } = dependencies
try {
const user = getPlatform().getStorageSync('user')
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
}

function _pendingSubmissionStorageKey(page, dependencies) {
const { PRACTICE_PENDING_SUBMISSION_KEY_PREFIX } = dependencies
const userId = page._getCurrentUserId()
return userId ? `${PRACTICE_PENDING_SUBMISSION_KEY_PREFIX}:${userId}` : ''
}

function _fmt(page, sec, dependencies) {
const { getMath } = dependencies
const s = getMath().max(0, sec || 0)
const m = getMath().floor(s / 60)
const ss = s % 60
return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

module.exports = { onLoad, onUnload, _resetSession, onReady, _initCustomNavigation, _resetPracticeStateAfterExit, _getCurrentUserId, _pendingSubmissionStorageKey, _fmt }
