const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture } = require('./helpers/practice-page-fixture')
const plain = value => JSON.parse(JSON.stringify(value))
const GETTERS = [
  '_recentSubjectController', '_subjectSheetController', '_subjectSelectionController',
  '_launchReturnController', '_exitGuardController', '_exitRequestController', '_pausedConfirmController',
  '_startPracticeController', '_imageWarmController', '_questionDisplayController',
  '_computedFieldsController', '_answerFeedbackController', '_renderInvariantController',
  '_questionTimerController', '_sequentialRestartController', '_selfHealController',
  '_answerInteractionController', '_submissionLockController', '_pendingSubmissionController',
  '_submittedResultController', '_submitFlowController', '_submitSuccessController',
  '_submitErrorController', '_submitEntryController',
]

for (const name of GETTERS) {
  test(name + ' retains one lazy instance per page and live session/data/platform ports', () => {
    const f = fixture(), other = fixture()
    f.page._resetSession()
    const controller = f.page[name]()
    assert.equal(f.page[name](), controller)
    assert.equal(f.instances.length, 1)
    assert.notEqual(other.page[name](), controller)
    const options = controller.options
    const replacement = { traceId: 'later', answerMap: { later: true }, questionTimeMap: { later: true } }
    f.page._practiceSession = replacement
    f.page.data = { ...f.page.data, selectedSubjectId: 97, count: 13, submitting: true }
    if (options.getSession) assert.equal(options.getSession(), replacement)
    if (options.getAnswerMap) assert.equal(options.getAnswerMap(), replacement.answerMap)
    if (options.getQuestionTimeMap) assert.equal(options.getQuestionTimeMap(), replacement.questionTimeMap)
    if (options.getSelectedSubjectId) assert.equal(options.getSelectedSubjectId(), 97)
    if (options.getCount) assert.equal(options.getCount(), 13)
    if (options.isSubmitting) assert.equal(options.isSubmitting(), true)
    if (options.showToast) {
      const toast = {}
      const wx = { showToast(value) { assert.equal(this, wx); assert.equal(value, toast); return 73 } }
      f.context.wx = wx
      assert.equal(options.showToast(toast), 73)
    }
  })
}

test('session reset allocates fresh maps and a null-prototype render cache', () => {
  const f = fixture()
  f.page._resetSession()
  const first = f.page._practiceSession
  first.answerMap.old = true
  f.page._resetSession()
  assert.notEqual(f.page._practiceSession, first)
  assert.deepEqual(plain(f.page._practiceSession.answerMap), {})
  assert.equal(Object.getPrototypeOf(f.page._practiceSession.questionRenderCache), null)
  assert.equal(f.page._practiceSession.exitGuardActive, false)
})

test('load resets navigation/request state and configures render guard before navigation/computed hooks', () => {
  const f = fixture()
  f.page._parseLaunchPreset = () => ({ source: 'knowledge_map', autostart: true, subjectId: 1, knowledgePointId: 2 })
  f.page._initCustomNavigation = () => f.calls.push(['navigation'])
  f.page._updateComputedFields = () => f.calls.push(['computed'])
  assert.equal(f.page.onLoad({}), undefined)
  assert.equal(f.page._fastLaunchEligible, true)
  assert.equal(f.page._pageAlive, true)
  assert.equal(f.page._questionsRequestSeq, 0)
  assert.deepEqual(f.calls.slice(-4).map(row => row[0]), ['guard', 'resetGuard', 'navigation', 'computed'])
})

test('unload preserves timer cleanup order and stops at a synchronous cleanup failure', () => {
  const f = fixture()
  Object.assign(f.page, { _practiceSession: {}, _systemBackRearmTimer: 1, _feedbackTimer: 2,
    _subjectSheetCloseTimer: 3, _subjectsRequestSeq: 4, _questionsRequestSeq: 6 })
  f.page._clearTimer = () => f.calls.push(['timer'])
  f.page.onUnload()
  assert.deepEqual(f.calls.map(row => row[0]), ['clearTimeout', 'resetGuard', 'timer', 'clearTimeout', 'clearTimeout'])
  assert.equal(f.page._questionsRequestSeq, 7)
  const error = Error('timer')
  f.page._systemBackRearmTimer = 1
  f.context.clearTimeout = () => { throw error }
  assert.throws(() => f.page.onUnload(), value => value === error)
  assert.equal(f.page._systemBackRearmTimer, 1)
})

test('ready waits for recovery and calls current late helpers in fast-launch order', async () => {
  const f = fixture()
  let resolve
  f.page._pageAlive = true
  f.page._fastLaunchEligible = true
  f.page._offerPendingSubmissionRecovery = () => new Promise(done => { resolve = done })
  const result = f.page.onReady()
  f.page._applyFastLaunchPreset = async () => { f.calls.push(['fast']); return true }
  f.page.startPractice = async () => f.calls.push(['start'])
  f.page.loadPracticeSubjects = options => { f.calls.push(['subjects', options]); return Promise.resolve() }
  resolve(false)
  await result
  assert.deepEqual(f.calls.slice(-3).map(row => row[0]), ['fast', 'start', 'subjects'])
  assert.deepEqual(plain(f.calls.at(-1)[1]), { skipAutostart: true, preserveSelection: true, silent: true })
})

test('fast launch preserves overrides before callback and remembers subject after current computed hook', async () => {
  const f = fixture()
  f.page._launchPreset = { subjectId: 7, autostart: true, subjectName: 'subject', mode: 'random', count: 5 }
  f.page._updateComputedFields = () => f.calls.push(['computed', f.page._launchSource])
  f.page._queueRememberSubject = (...args) => f.calls.push(['remember', ...args])
  assert.equal(await f.page._applyFastLaunchPreset(), true)
  assert.deepEqual(f.calls.map(row => row[0]), ['setData', 'computed', 'remember'])
  assert.deepEqual(f.calls.at(-1), ['remember', 7, 'subject'])
})

test('unavailable launch subject toasts only for autostart and never applies overrides', async () => {
  const f = fixture()
  f.page._launchPreset = { subjectId: 7, autostart: true }
  f.page._flattenSelectableSubjects = () => []
  assert.equal(await f.page._applyLaunchPreset([]), false)
  assert.deepEqual(f.calls.map(row => row[0]), ['warn', 'showToast'])
  assert.equal(f.page._launchKnowledgePointId, undefined)
})

test('user storage identity retains field priority, trimming, namespace and caught failures', () => {
  const f = fixture()
  f.platform.getStorageSync = () => ({ id: ' ', user_id: ' 9 ', openid: 'open' })
  assert.equal(f.page._getCurrentUserId(), '9')
  assert.equal(f.page._pendingSubmissionStorageKey(), 'practice_pending_submission_v1:9')
  f.platform.getStorageSync = () => { throw Error('storage') }
  assert.equal(f.page._getCurrentUserId(), '')
  assert.equal(f.page._pendingSubmissionStorageKey(), '')
})

test('submit confirmation preserves component receiver/return identity and missing-component fallback', async () => {
  const f = fixture(), result = Promise.resolve(true)
  const component = { show(options) { assert.equal(this, component); assert.equal(options.title, 'title'); return result } }
  f.page.selectComponent = selector => { assert.equal(selector, '#submitConfirm'); return component }
  assert.equal(f.page._showSubmitConfirm({ title: 'title' }), result)
  f.page.selectComponent = () => null
  assert.equal(await f.page._showSubmitConfirm({ title: 'fallback' }), false)
  assert.equal(f.calls.at(-1)[1].title, 'fallback')
})

test('exit reset preserves hook order, fresh session and setup-only patch', () => {
  const f = fixture()
  f.page._resetPracticeStateAfterExit()
  assert.equal(f.page._launchReturnTo, '')
  assert.equal(f.page._launchIncludeDescendants, false)
  assert.equal(f.page.data.started, false)
  assert.equal(f.page.data.elapsedText, '00:00')
  assert.equal(f.page._pendingResultUrl, '')
  assert.equal(f.calls.length, 1)
})

test('exit callbacks use current hooks, preserve feedback cleanup and increment the live sequence', () => {
  const f = fixture()
  const options = f.page._exitRequestController().options
  f.page._questionsRequestSeq = 8
  options.incrementQuestionRequestSeq()
  assert.equal(f.page._questionsRequestSeq, 9)
  f.page._feedbackTimer = 19
  options.clearFeedbackTimer()
  assert.equal(f.page._feedbackTimer, null)
  assert.deepEqual(f.calls[0], ['clearTimeout', 19])
  f.page._resetPracticeStateAfterExit = function () { assert.equal(this, f.page); return 71 }
  assert.equal(options.resetPracticeState(), 71)
})

test('pending resume retains await-late page state and original false fallback order', async () => {
  const f = fixture()
  f.page._resetSession()
  f.page._pageAlive = true
  f.page._setPracticeUnloadGuard = (...args) => f.calls.push(['guard', ...args])
  let done
  f.page.doSubmit = () => new Promise(resolve => { done = resolve })
  const result = f.page._pendingSubmissionController().options.resumePendingSubmission({ requestId: 'req', traceId: 'trace' })
  assert.equal(f.page._practiceSession.requestId, 'req')
  done()
  assert.equal(await result, false)
  assert.deepEqual(f.calls.slice(-2).map(row => row[0]), ['guard', 'setData'])
  assert.equal(f.page.data.started, false)
})

test('question navigation retains bounds and does not return helper result', () => {
  const f = fixture()
  f.page.data.totalQuestions = 2
  f.page._showQuestion = index => { f.calls.push(['show', index]); return 89 }
  assert.equal(f.page.goQuestion({ detail: { index: 1 } }), undefined)
  f.page.goQuestion({ detail: { index: 2 } })
  f.page.goQuestion({ detail: { index: -1 } })
  assert.deepEqual(f.calls, [['show', 1]])
})

test('question load wiring captures its original platform once and retains the cached controller', () => {
  const f = fixture(), platform = f.context.wx
  const first = f.page._questionLoadController()
  assert.equal(first.type, 'createQuestionLoadController')
  assert.equal(f.page._questionLoadController(), first)
  assert.equal(f.instances.length, 1)
  const later = { showToast() { throw Error('unexpected new platform') } }
  f.context.wx = later
  assert.equal(f.page._questionLoadController(), first)
  assert.equal(typeof first.options.showToast, 'function')
  platform.showToast = function (options) { assert.equal(this, platform); return options.title }
  assert.equal(first.options.showToast({ title: 'original' }), 'original')
})
