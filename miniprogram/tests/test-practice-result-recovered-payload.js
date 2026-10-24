const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildRecoveredResultPayload } = require('../subpackages/study/practice-result/utils/recovered-payload-builder')

const submission = {
  answerMap: { '1': 'A', '2': 'B' },
  partialQuestionIds: [2],
  total: 3,
  selectedSubjectId: 12,
  selectedSubjectName: '数据结构',
  duration: 120,
  traceId: 'trace-1',
  comboCount: 0,
  recoveryQuestions: [{ id: 1, stem: 'Q1', question_type: 'single_choice' }],
  knowledgeScope: { root_id: 34 },
  requestId: 'req-1',
}

const submitResult = {
  results: [
    { question_id: 1, status: 'correct', is_correct: true },
    { question_id: 2, status: 'skipped', is_correct: false },
  ],
  total_correct: 1,
  total_wrong: 0,
  total_skipped: 1,
  trace_id: 'trace-2',
}

test('buildRecoveredResultPayload: builds payload with correct counts', () => {
  const payload = buildRecoveredResultPayload(submission, submitResult, 'ck-1')
  assert.equal(payload.correct, 1)
  assert.equal(payload.wrong, 0)
  assert.equal(payload.skipped, 0) // 1 skipped - 1 partial = 0
  assert.equal(payload.partial, 1)
})

test('buildRecoveredResultPayload: reclassifies partial skipped results', () => {
  const payload = buildRecoveredResultPayload(submission, submitResult, 'ck-1')
  assert.equal(payload.results[1].status, 'partial')
  assert.equal(payload.results[1]._local_partial, true)
})

test('buildRecoveredResultPayload: maps recovery questions', () => {
  const payload = buildRecoveredResultPayload(submission, submitResult, 'ck-1')
  assert.equal(payload.questions.length, 1)
  assert.equal(payload.questions[0].id, 1)
  assert.equal(payload.questions[0].stem, 'Q1')
})

test('buildRecoveredResultPayload: includes metadata', () => {
  const payload = buildRecoveredResultPayload(submission, submitResult, 'ck-1')
  assert.equal(payload.subject_id, 12)
  assert.equal(payload.subject_name, '数据结构')
  assert.equal(payload.duration, 120)
  assert.equal(payload.traceId, 'trace-2')
  assert.equal(payload.request_id, 'req-1')
  assert.equal(payload._cacheKey, 'ck-1')
})

test('buildRecoveredResultPayload: falls back to session for subject_id', () => {
  const sub = Object.assign({}, submission, { selectedSubjectId: null, duration: null, session: { subject_id: 99, duration_sec: 60 } })
  const payload = buildRecoveredResultPayload(sub, submitResult, '')
  assert.equal(payload.subject_id, 99)
  assert.equal(payload.duration, 60)
})

test('buildRecoveredResultPayload: handles empty submitResult', () => {
  const payload = buildRecoveredResultPayload(submission, {}, '')
  assert.equal(payload.correct, 0)
  assert.equal(payload.wrong, 0)
  assert.equal(payload.results.length, 0)
})
