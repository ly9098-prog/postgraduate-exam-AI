const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createReviewSessionController,
} = require('../subpackages/study/review-today/utils/review-session-controller')

function createHarness(overrides = {}) {
  const state = {
    session: { reviewRequestIds: {} },
    patches: [],
  }
  const controller = createReviewSessionController({
    getSession: () => state.session,
    setData: patch => { state.patches.push(patch) },
    ...overrides,
  })
  return { controller, state }
}

test('createSession returns a well-formed session object', () => {
  const { controller } = createHarness()
  const session = controller.createSession()

  assert.deepEqual(session.answers, {})
  assert.deepEqual(session.allTodayQuestionIds, [])
  assert.equal(session.totalCorrect, 0)
  assert.equal(session.safeModeActive, false)
  assert.deepEqual(session.reviewRequestIds, {})
  assert.equal(session.timerRunning, false)
  assert.ok(typeof session.taskDate === 'string')
})

test('setDateStr writes a formatted date string', () => {
  const { controller, state } = createHarness()
  controller.setDateStr()

  assert.equal(state.patches.length, 1)
  assert.ok(typeof state.patches[0]._dateStr === 'string')
  assert.ok(state.patches[0]._dateStr.includes('月'))
  assert.ok(state.patches[0]._dateStr.includes('星期'))
})

test('getRequestId generates a stable ID for the same question', () => {
  const { controller } = createHarness()
  const q = { schedule_id: 1, question_version_id: 2, occurrence_seq: 1 }
  const id1 = controller.getRequestId(q)
  const id2 = controller.getRequestId(q)

  assert.ok(id1.startsWith('review_'))
  assert.equal(id1, id2)
})

test('getRequestId returns empty for degenerate question', () => {
  const { controller } = createHarness()
  const q = { schedule_id: '', question_version_id: '', occurrence_seq: null }
  const id = controller.getRequestId(q)

  assert.equal(id, '')
})

test('getRequestId generates different IDs for different questions', () => {
  const { controller } = createHarness()
  const q1 = { schedule_id: 1, question_version_id: 2, occurrence_seq: 1 }
  const q2 = { schedule_id: 2, question_version_id: 3, occurrence_seq: 1 }
  const id1 = controller.getRequestId(q1)
  const id2 = controller.getRequestId(q2)

  assert.notEqual(id1, id2)
})

test('subjectLabel returns name when provided', () => {
  const { controller } = createHarness()
  assert.equal(controller.subjectLabel('数学', 'MATH'), '数学')
})

test('subjectLabel falls back to getSubjectName for code', () => {
  const { controller } = createHarness()
  const label = controller.subjectLabel('', 'MATH')
  assert.ok(typeof label === 'string')
})
