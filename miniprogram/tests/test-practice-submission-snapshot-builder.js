const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildSubmissionSnapshot } = require('../subpackages/study/practice/utils/submission-snapshot-builder')

const baseOptions = {
  requestId: 'req_1',
  traceId: 'trace_1',
  answers: [{ question_id: 1, user_answer: 'A' }],
  skippedQuestionIds: [3],
  partialQuestionIds: [4],
  session: { request_id: 'req_1', status: 'completed' },
  duration: 120,
  total: 5,
  unanswered: 2,
  selectedSubjectId: 12,
  selectedSubjectName: '数据结构',
  comboCount: 0,
  answerMap: { '1': 'A' },
  answeredFlags: { '1': true },
  recoveryQuestions: [{ id: 1 }],
  batchToken: 'batch_123',
  knowledgeScope: { root_id: 34 },
}

test('builds snapshot with all fields', () => {
  const snap = buildSubmissionSnapshot(baseOptions)
  assert.equal(snap.requestId, 'req_1')
  assert.equal(snap.traceId, 'trace_1')
  assert.deepEqual(snap.answers, [{ question_id: 1, user_answer: 'A' }])
  assert.deepEqual(snap.skippedQuestionIds, [3])
  assert.deepEqual(snap.partialQuestionIds, [4])
  assert.equal(snap.duration, 120)
  assert.equal(snap.total, 5)
  assert.equal(snap.unanswered, 2)
  assert.equal(snap.selectedSubjectId, 12)
  assert.equal(snap.selectedSubjectName, '数据结构')
  assert.equal(snap.batchToken, 'batch_123')
  assert.deepEqual(snap.knowledgeScope, { root_id: 34 })
})

test('initializes status flags as false', () => {
  const snap = buildSubmissionSnapshot(baseOptions)
  assert.equal(snap.retryBlocked, false)
  assert.equal(snap.serverAccepted, false)
  assert.equal(snap.pendingPersisted, false)
  assert.equal(snap.keepPendingUntilResult, false)
})

test('defensively copies answerMap', () => {
  const opts = { ...baseOptions, answerMap: { '1': 'A' } }
  const snap = buildSubmissionSnapshot(opts)
  snap.answerMap['2'] = 'B'
  assert.equal(opts.answerMap['2'], undefined)
})

test('defensively copies answeredFlags', () => {
  const opts = { ...baseOptions, answeredFlags: { '1': true } }
  const snap = buildSubmissionSnapshot(opts)
  snap.answeredFlags['2'] = true
  assert.equal(opts.answeredFlags['2'], undefined)
})

test('defensively copies skippedQuestionIds', () => {
  const opts = { ...baseOptions, skippedQuestionIds: [3] }
  const snap = buildSubmissionSnapshot(opts)
  snap.skippedQuestionIds.push(99)
  assert.equal(opts.skippedQuestionIds.length, 1)
})

test('defensively copies knowledgeScope', () => {
  const opts = { ...baseOptions, knowledgeScope: { root_id: 34 } }
  const snap = buildSubmissionSnapshot(opts)
  snap.knowledgeScope.extra = 'val'
  assert.equal(opts.knowledgeScope.extra, undefined)
})

test('handles null knowledgeScope', () => {
  const snap = buildSubmissionSnapshot({ ...baseOptions, knowledgeScope: null })
  assert.equal(snap.knowledgeScope, null)
})

test('handles empty traceId', () => {
  const snap = buildSubmissionSnapshot({ ...baseOptions, traceId: '' })
  assert.equal(snap.traceId, '')
})

test('handles empty batchToken', () => {
  const snap = buildSubmissionSnapshot({ ...baseOptions, batchToken: '' })
  assert.equal(snap.batchToken, '')
})
