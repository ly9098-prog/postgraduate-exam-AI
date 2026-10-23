const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createReviewDraftController,
} = require('../subpackages/study/review-today/utils/draft-controller')

function createHarness(overrides = {}) {
  const state = {
    draftKey: 'review_today_draft_v1:user:2026-10-23',
    storage: {},
    session: {
      answers: {},
      taskDate: '2026-10-23',
    },
    data: {
      phase: 'reviewing',
      groupQuestions: [],
      currentQuestion: null,
    },
    now: 123456789,
    writes: [],
    removals: [],
  }
  const controller = createReviewDraftController({
    getDraftKey: () => state.draftKey,
    readStorage: key => state.storage[key],
    writeStorage: (key, value) => {
      state.writes.push([key, value])
      state.storage[key] = value
    },
    removeStorage: key => {
      state.removals.push(key)
      delete state.storage[key]
    },
    getSession: () => state.session,
    getCurrentDate: () => '2026-10-23',
    getPhase: () => state.data.phase,
    getGroupQuestions: () => state.data.groupQuestions,
    getCurrentQuestion: () => state.data.currentQuestion,
    now: () => state.now,
    ...overrides,
  })
  return { controller, state }
}

test('reads malformed storage as an empty draft', () => {
  const { controller, state } = createHarness()
  state.storage[state.draftKey] = null
  assert.deepEqual(controller.read(), { answers: {}, position: null })

  state.storage[state.draftKey] = { answers: [], position: 'bad' }
  assert.deepEqual(controller.read(), { answers: {}, position: null })
})

test('persists only valid current answers and position', () => {
  const { controller, state } = createHarness()
  state.storage[state.draftKey] = {
    answers: {
      1: { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1, answer: 'old' },
      stale: { schedule_id: 'stale', question_id: 99, question_version_id: 99, occurrence_seq: 9, answer: 'old' },
    },
    position: { schedule_id: 'stale', question_version_id: 99, occurrence_seq: 9 },
  }
  state.session.answers = { 2: 'B', 3: '' }
  state.data.groupQuestions = [
    { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1 },
    { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 1 },
    { schedule_id: 3, question_id: 13, question_version_id: 23, occurrence_seq: 1 },
  ]
  state.data.currentQuestion = {
    schedule_id: 2,
    question_version_id: 22,
    occurrence_seq: 1,
  }

  controller.persist()

  assert.equal(state.writes.length, 1)
  assert.equal(state.writes[0][0], state.draftKey)
  assert.deepEqual(state.writes[0][1].answers, {
    2: {
      schedule_id: 2,
      question_id: 12,
      question_version_id: 22,
      occurrence_seq: 1,
      answer: 'B',
    },
    stale: {
      schedule_id: 'stale',
      question_id: 99,
      question_version_id: 99,
      occurrence_seq: 9,
      answer: 'old',
    },
  })
  assert.equal(state.writes[0][1].date, '2026-10-23')
  assert.equal(state.writes[0][1].updated_at, 123456789)
  assert.deepEqual(state.writes[0][1].position, {
    schedule_id: 2,
    question_version_id: 22,
    occurrence_seq: 1,
  })
})

test('skips persistence outside the review phase or with no questions', () => {
  const wrongPhase = createHarness()
  wrongPhase.state.data.phase = 'overview'
  wrongPhase.controller.persist()
  assert.deepEqual(wrongPhase.state.writes, [])

  const noQuestions = createHarness()
  noQuestions.controller.persist()
  assert.deepEqual(noQuestions.state.writes, [])
})

test('writing an empty draft removes storage and preserves absence', () => {
  const { controller, state } = createHarness()
  state.storage[state.draftKey] = { answers: { 1: { answer: 'A' } }, position: null }
  controller.write({ answers: {}, position: null })

  assert.deepEqual(state.removals, [state.draftKey])
  assert.equal(state.storage[state.draftKey], undefined)
})

test('restores only version-matched answers and the exact position', () => {
  const { controller, state } = createHarness()
  const questions = [
    { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1 },
    { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 1 },
    { schedule_id: 3, question_id: 13, question_version_id: 23, occurrence_seq: 2 },
  ]
  state.storage[state.draftKey] = {
    answers: {
      1: { question_id: 11, question_version_id: 21, occurrence_seq: 1, answer: 'A' },
      2: { question_id: 12, question_version_id: 999, occurrence_seq: 1, answer: 'B' },
      3: { question_id: 13, question_version_id: 23, occurrence_seq: 2, answer: '' },
    },
    position: {
      schedule_id: 3,
      question_version_id: 23,
      occurrence_seq: 2,
    },
  }

  const restored = controller.restore(questions)
  assert.deepEqual(restored, {
    answers: { 1: 'A' },
    currentIndex: 2,
    restoredCount: 1,
  })
})

test('clears submitted answers and resets a submitted position', () => {
  const { controller, state } = createHarness()
  state.storage[state.draftKey] = {
    answers: {
      1: { question_id: 11, question_version_id: 21, occurrence_seq: 1, answer: 'A' },
      2: { question_id: 12, question_version_id: 22, occurrence_seq: 1, answer: 'B' },
    },
    position: { schedule_id: 1, question_version_id: 21, occurrence_seq: 1 },
  }

  controller.clearSubmitted([], [
    { schedule_id: 1, wasSubmitted: true },
    { schedule_id: 'missing', wasSubmitted: true },
    { schedule_id: 2, wasSubmitted: false },
  ])

  assert.deepEqual(state.writes, [[
    state.draftKey,
    {
      version: 1,
      date: '2026-10-23',
      updated_at: 123456789,
      answers: {
        2: { question_id: 12, question_version_id: 22, occurrence_seq: 1, answer: 'B' },
      },
      position: null,
    },
  ]])
})
