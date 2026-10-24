const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildSubmitAnswers, buildSubmitSession } = require('../subpackages/study/practice/utils/submit-session-builder')

test('buildSubmitAnswers: maps completed questions to answer payloads', () => {
  const answers = buildSubmitAnswers({
    completedQuestions: [
      { id: 1 },
      { id: 2 },
    ],
    answerMap: { '1': 'A', '2': 'B,C' },
    questionTimeMap: { '1': 30, '2': 60 },
    recommendationRequestId: 'rec-1',
  })
  assert.equal(answers.length, 2)
  assert.equal(answers[0].question_id, 1)
  assert.equal(answers[0].user_answer, 'A')
  assert.equal(answers[0].used_time, 30)
  assert.equal(answers[0].request_id, 'rec-1')
  assert.equal(answers[1].user_answer, 'B,C')
})

test('buildSubmitAnswers: defaults missing answer to empty string', () => {
  const answers = buildSubmitAnswers({
    completedQuestions: [{ id: 1 }],
    answerMap: {},
    questionTimeMap: {},
  })
  assert.equal(answers[0].user_answer, '')
  assert.equal(answers[0].used_time, 0)
  assert.equal(answers[0].request_id, null)
})

test('buildSubmitAnswers: handles empty questions', () => {
  assert.deepEqual(buildSubmitAnswers({}), [])
})

test('buildSubmitSession: builds full session object', () => {
  const session = buildSubmitSession({
    requestId: 'req-1',
    subjectId: 12,
    mode: 'sequential',
    startedAtMs: 1000000,
    finishedAtMs: 1000120,
    duration: 120,
    total: 5,
    answeredCount: 3,
  })
  assert.equal(session.request_id, 'req-1')
  assert.equal(session.subject_id, 12)
  assert.equal(session.mode, 'sequential')
  assert.equal(session.duration_sec, 120)
  assert.equal(session.question_count, 5)
  assert.equal(session.answered_count, 3)
  assert.equal(session.status, 'completed')
  assert.ok(session.started_at)
  assert.ok(session.finished_at)
})

test('buildSubmitSession: defaults mode to random', () => {
  const session = buildSubmitSession({
    requestId: 'r',
    subjectId: 1,
    finishedAtMs: 1000,
    duration: 0,
    total: 0,
    answeredCount: 0,
  })
  assert.equal(session.mode, 'random')
})

test('buildSubmitSession: computes started_at from finishedAt - duration when startedAtMs missing', () => {
  const session = buildSubmitSession({
    requestId: 'r',
    subjectId: 1,
    startedAtMs: 0,
    finishedAtMs: 2000,
    duration: 2,
    total: 1,
    answeredCount: 1,
  })
  assert.ok(session.started_at)
})
