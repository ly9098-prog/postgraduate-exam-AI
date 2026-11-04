const assert = require('node:assert/strict')
const { test } = require('node:test')
const memory = new Map()
global.wx = {
  getStorageSync: key => memory.get(key),
  setStorageSync: (key, value) => memory.set(key, structuredClone(value)),
  removeStorageSync: key => memory.delete(key),
  reLaunch: () => {},
}
const store = require('../utils/launch-session-store')
function controller() {
  try { return require('../subpackages/study/practice/utils/cold-resume-controller') } catch { return {} }
}
function page() {
  memory.clear()
  memory.set('user', { id: 1 })
  memory.set('token', 't')
  return {
    _pageAlive: true,
    _practiceSession: {
      requestId: 'request', batchToken: 'batch', startedAtMs: 100,
      activeStartedMonoMs: 500, backgroundMs: 100, _backgroundStartedMonoMs: null,
      questionTimeMap: { 1: 3 }, answerMap: { 1: 'A' }, answeredFlags: { 1: true },
    },
    data: { started: true, questions: [
      { id: 1, question_version_id: 10, question_type: 'single_choice', content: { text: '题目' }, answer: 'A' },
      { id: 2, question_version_id: 20, question_type: 'single_choice', content: { text: '另一题' } },
    ], currentIndex: 1, selectedSubjectId: 9, selectedMode: 'sequential' },
    _launchSource: 'knowledge_map', _launchKnowledgePointId: 4, _launchReturnTo: '/pages/home/home',
    setData(patch) { Object.assign(this.data, patch) },
    _resetSession() { this._practiceSession = { questionRenderCache: {}, questionTimeMap: {} } },
    _settleQuestionTime() {},
    _showQuestion(index) {
      this.data.currentIndex = index
      this.data.currentQuestion = this.data.questions[index]
      this.shown = index
    },
    _startTimer() { this.timerStarted = true },
    _updateComputedFields() {},
    _setPracticeUnloadGuard(value) { this.guard = value },
    _fmt(seconds) { return String(seconds) },
  }
}

test('practice snapshot restores original credentials, answers, index and foreground time', () => {
  const subject = page(), cold = controller()
  assert.equal(typeof cold.persist, 'function')
  cold.persist(subject, () => 5500)
  const saved = store.readPractice()
  assert.equal(saved.elapsedMs, 4900)
  assert.equal(saved.questions[0].answer, undefined)
  subject._resetSession()
  subject.data = { started: false }
  subject._coldResumeRequested = true
  assert.equal(cold.restore(subject, () => 20), true)
  assert.equal(subject._practiceSession.batchToken, 'batch')
  assert.equal(subject._practiceSession.requestId, 'request')
  assert.deepEqual(subject._practiceSession.answerMap, { 1: 'A' })
  assert.equal(subject._practiceSession.activeStartedMonoMs, -4880)
  assert.equal(subject._practiceSession.backgroundMs, 0)
  assert.equal(subject.data.currentIndex, 1)
  assert.equal(subject.data.selectedMode, 'sequential')
  assert.equal(subject._launchKnowledgePointId, 4)
  assert.equal(subject.timerStarted, true)
})

test('background time is excluded and pending submission prevents snapshot resurrection', () => {
  const subject = page(), cold = controller()
  assert.equal(typeof cold.persist, 'function')
  subject._practiceSession._backgroundStartedMonoMs = 3500
  cold.persist(subject, () => 9000)
  assert.equal(store.readPractice().elapsedMs, 2900)
  subject._practiceSession.submissionSnapshot = {}
  store.clearPractice()
  cold.persist(subject, () => 10000)
  assert.equal(store.readPractice(), null)
})

test('a broken restore clears state and silently returns home', () => {
  const subject = page(), cold = controller()
  assert.equal(typeof cold.persist, 'function')
  cold.persist(subject, () => 5500)
  subject._coldResumeRequested = true
  subject._showQuestion = () => { throw Error('render failed') }
  assert.equal(cold.restore(subject, () => 20), true)
  assert.equal(store.readPractice(), null)
  assert.equal(subject.data.started, false)
  cold.persist(subject, () => 20000)
  assert.equal(store.readPractice(), null)
})

test('an old page cannot save or clear another owner snapshot after an account switch', () => {
  const subject = page(), cold = controller()
  subject._coldResumeOwner = '1'
  cold.persist(subject, () => 5500)
  memory.set('user', { id: 2 })
  store.savePractice({ requestId: 'new', batchToken: 'b', questions: [{ id: 2 }],
    currentIndex: 0, elapsedMs: 1 })
  cold.persist(subject, () => 6500)
  cold.clear(subject)
  assert.equal(store.readPractice().requestId, 'new')
})

test('timing paused for a confirmation is not added to the saved foreground duration', () => {
  const subject = page(), cold = controller()
  subject._practiceSession._timingPauseActive = true
  subject._practiceSession._timingPauseStartedMonoMs = 3500
  cold.persist(subject, () => 9000)
  assert.equal(store.readPractice().elapsedMs, 2900)
})

test('question time keeps the integer-second submission contract at a fractional clock boundary', () => {
  const subject = page(), cold = controller()
  subject._practiceSession.currentQuestionStartedMonoMs = 1200
  cold.persist(subject, () => 5555)
  assert.equal(store.readPractice().questionTimeMap[2], 4)
  assert.equal(store.readPractice().elapsedMs, 4955)
})
