const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createNextRetryGroupController,
} = require('../subpackages/study/review-today/utils/next-retry-group-controller')

function createHarness() {
  const state = {
    groups: [
      [{ schedule_id: 1 }],
      [{ schedule_id: 2 }, { schedule_id: '3' }],
    ],
    session: {
      answers: { 1: 'A', 2: 'B', 3: 'C', unrelated: 'D' },
      allQuestions: [{ schedule_id: 1 }],
    },
    data: {},
    synced: false,
    shownQuestion: null,
    timerStarted: false,
  }
  const controller = createNextRetryGroupController({
    getGroups: () => state.groups,
    getSession: () => state.session,
    setData: patch => { Object.assign(state.data, patch) },
    syncAnsweredFlags: () => { state.synced = true },
    showQuestion: index => { state.shownQuestion = index },
    startReviewTimer: () => { state.timerStarted = true },
  })
  return { controller, state }
}

test('enters an existing retry group and restores only its answers', () => {
  const { controller, state } = createHarness()
  const questions = controller.enter(1)

  assert.deepEqual(questions, [{ schedule_id: 2 }, { schedule_id: '3' }])
  assert.deepEqual(state.session.answers, { 2: 'B', 3: 'C' })
  assert.deepEqual(state.session.allQuestions, questions)
  assert.deepEqual(state.data, {
    phase: 'reviewing',
    currentGroupIdx: 1,
    groupQuestions: questions,
    currentIndex: 0,
    groupResults: [],
    groupWrongResults: [],
    groupCorrect: 0,
    groupWrong: 0,
    groupAccuracyPercent: 0,
    showGroupDetails: false,
    resultTransitioning: false,
  })
  assert.equal(state.synced, true)
  assert.equal(state.shownQuestion, 0)
  assert.equal(state.timerStarted, true)
})

test('rejects missing and empty retry groups', () => {
  const { controller } = createHarness()
  assert.equal(controller.enter(2), null)

  const empty = createHarness()
  empty.state.groups.push([])
  assert.equal(empty.controller.enter(2), null)
})

test('falls back to the original answer key when ids are numeric', () => {
  const { controller, state } = createHarness()
  state.session.answers = { 2: 'B', unrelated: 'D' }
  controller.enter(1)
  assert.deepEqual(state.session.answers, { 2: 'B' })
})
