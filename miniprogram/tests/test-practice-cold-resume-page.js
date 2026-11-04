const assert = require('node:assert/strict')
const { test } = require('node:test')
const memory = new Map()
let mono = 10000
let definition
const navigations = []
let pageStack = []
global.wx = {
  getStorageSync: key => memory.get(key),
  setStorageSync: (key, value) => memory.set(key, structuredClone(value)),
  removeStorageSync: key => memory.delete(key),
  getPerformance: () => ({ now: () => mono }),
  reLaunch: options => navigations.push(options.url),
  redirectTo: options => navigations.push(options.url),
  navigateBack: options => navigations.push({ delta: options.delta }),
  showToast() {}, pageScrollTo() {},
}
global.getCurrentPages = () => pageStack
global.Page = value => { definition = value }
require('../subpackages/study/practice/practice')
const store = require('../utils/launch-session-store')
const cold = require('../subpackages/study/practice/utils/cold-resume-controller')
const { resolveLaunchTarget } = require('../utils/launch-resume')
const questions = [
  { id: 1, question_version_id: 101, question_type: 'single_choice',
    subject_id: 9, content: { text: '测试一' }, options: { A: '甲', B: '乙' } },
  { id: 2, question_version_id: 102, question_type: 'multi_blank_choice',
    subject_id: 9, content: { text: '测试二', blank_option_groups: [
      { blank_id: '1', options: { A: '甲', B: '乙' } },
    ] } },
]

function page(options = {}) {
  const subject = { ...definition, data: structuredClone(definition.data) }
  subject.setData = (patch, callback) => {
    for (const [key, value] of Object.entries(patch)) {
      const match = /^questions\[(\d+)\]\._answered$/.exec(key)
      if (match) subject.data.questions[Number(match[1])]._answered = value
      else subject.data[key] = value
    }
    if (callback) callback()
  }
  subject._warmQuestionImages = () => {}
  subject._startTimer = () => { subject.timerStarted = true }
  subject._clearTimer = () => { subject.timerStarted = false }
  subject.loadPracticeSubjects = async options => {
    subject.subjectLoadOptions = options
    subject.setData({ subjectTree: [{ subject_id: 9, display_name: '科目' }] })
  }
  subject.onLoad(options)
  return subject
}

function activePage() {
  memory.clear()
  navigations.length = 0
  pageStack = []
  memory.set('user', { id: 11 })
  memory.set('token', 't')
  mono = 10000
  const subject = page()
  Object.assign(subject._practiceSession, { requestId: 'request', batchToken: 'batch',
    activeStartedMonoMs: 1000, startedAtMs: Date.now() - 9000 })
  Object.assign(subject.data, { started: true, selectedSubjectId: 9, questions: structuredClone(questions),
    totalQuestions: 2 })
  subject._showQuestion(0)
  return subject
}

test('real Page answer, question-change and onHide hooks survive process reconstruction', async () => {
  const subject = activePage()
  subject.selectOption({ detail: { option: 'A' } })
  mono = 13000
  subject.goNext({ detail: { index: 1 } })
  mono = 16000
  subject.onHide()
  const snapshot = store.readPractice()
  assert.deepEqual(snapshot.answerMap, { 1: 'A' })
  assert.equal(snapshot.currentIndex, 1)
  assert.equal(snapshot.elapsedMs, 15000)
  assert.equal(snapshot.questionTimeMap[1], 3)
  assert.equal(snapshot.questionTimeMap[2], 3)
  assert.ok(snapshot.createdAt <= Date.now())
  mono = 20
  const fresh = page({ resume: '1' })
  await fresh.onReady()
  assert.equal(fresh.data.started, true)
  assert.equal(fresh.data.currentQuestion.id, 2)
  assert.deepEqual(fresh._practiceSession.answerMap, { 1: 'A' })
  assert.equal(fresh._practiceSession.activeStartedMonoMs, -14980)
  assert.equal(fresh._practiceSession.currentQuestionStartedMonoMs, 20)
  assert.equal(fresh.data.elapsedText, '00:15')
  assert.equal(fresh.timerStarted, true)
  assert.deepEqual(fresh.subjectLoadOptions, {
    skipAutostart: true, preserveSelection: true, silent: true,
  })
  assert.equal(fresh.data.subjectTree.length, 1)
})

test('real confirmed exit removes snapshot and onHide cannot recreate it', async () => {
  const subject = activePage()
  subject._showSubmitConfirmPaused = async () => true
  await subject.requestExitPractice({ source: 'test' })
  subject.onHide()
  assert.equal(store.readPractice(), null)
  assert.equal(store.readActive(), null)
  assert.equal(subject.data.started, false)
})

test('confirmed submission hands off to pending storage; failed submit never resurrects snapshot', async () => {
  const subject = activePage()
  subject.selectOption({ detail: { option: 'A' } })
  subject._showSubmitConfirmPaused = async () => true
  subject._showSubmitConfirm = async () => true
  const submission = await subject._submitEntryController().prepare(true)
  assert.ok(submission)
  assert.equal(store.readPractice(), null)
  assert.equal(store.readPending().status, 'pending')
  await subject._submitErrorController().handle(submission, { statusCode: 0 })
  subject.onHide()
  assert.equal(store.readPractice(), null)
  assert.match(await resolveLaunchTarget(), /practice\?resume=1$/)
})

test('declining pending recovery keeps the existing setup flow without forcing home', async () => {
  activePage()
  cold.clear()
  memory.set('practice_pending_submission_v1:11', {
    version: 1, updatedAt: Date.now(), status: 'pending', submission: { requestId: 'r' },
  })
  const fresh = page({ resume: '1' })
  fresh._showSubmitConfirm = async () => false
  let loaded = false
  fresh.loadPracticeSubjects = () => { loaded = true }
  await fresh.onReady()
  assert.equal(loaded, true)
  assert.deepEqual(navigations, [])
})

test('real restored Page returns home after confirming exit, including repeated header taps', async () => {
  const previous = activePage()
  previous.selectOption({ detail: { option: 'A' } })
  const fresh = page({ resume: '1' })
  await fresh.onReady()
  pageStack = [fresh]
  fresh._showSubmitConfirmPaused = async () => true
  await fresh.requestExitPractice({ source: 'test' })
  fresh.goBack()
  fresh.goBack()
  await new Promise(resolve => setTimeout(resolve, 40))
  assert.deepEqual(navigations, ['/pages/home/home'])
  assert.equal(store.readPractice(), null)
})

test('real Page header preserves ordinary stack back and explicit launch-origin routing', async () => {
  for (const root of [false, true]) {
    const subject = activePage()
    subject._resetPracticeStateAfterExit()
    pageStack = root ? [subject] : [{ route: 'pages/home/home' }, subject]
    if (root) subject._launchReturnTo = '/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9'
    subject.goBack()
    await new Promise(resolve => setTimeout(resolve, 40))
    assert.deepEqual(navigations, root
      ? ['/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9']
      : [{ delta: 1 }])
  }
})

test('scheduled real Page back is ignored after unload', async () => {
  const subject = activePage()
  subject._resetPracticeStateAfterExit()
  pageStack = [subject]
  subject.goBack()
  subject.onUnload()
  await new Promise(resolve => setTimeout(resolve, 40))
  assert.deepEqual(navigations, [])
  assert.equal(subject._returnNavigationLocked, false)
})

test('restored active practice system back still confirms before discarding answers', async () => {
  const previous = activePage()
  previous.selectOption({ detail: { option: 'A' } })
  const fresh = page({ resume: '1' })
  await fresh.onReady()
  pageStack = [fresh]
  let confirmed = false
  fresh._showSubmitConfirmPaused = async () => confirmed
  fresh.onPracticeExitGuardLeave()
  await new Promise(resolve => setTimeout(resolve, 5))
  assert.equal(fresh.data.started, true)
  assert.equal(fresh.data.practiceExitGuardVisible, true)
  assert.deepEqual(fresh._practiceSession.answerMap, { 1: 'A' })
  confirmed = true
  fresh.onPracticeExitGuardLeave()
  await new Promise(resolve => setTimeout(resolve, 5))
  assert.equal(fresh.data.started, false)
  assert.equal(store.readPractice(), null)
  assert.deepEqual(navigations, [])
})
