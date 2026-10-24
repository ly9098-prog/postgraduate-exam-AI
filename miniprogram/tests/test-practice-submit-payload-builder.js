const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildSubmitPayload,
  isDeterministicReject,
  resolveRejectMessage,
} = require('../subpackages/study/practice/utils/submit-payload-builder')

test('buildSubmitPayload: builds full payload', () => {
  const payload = buildSubmitPayload(
    {
      answers: [{ question_id: 1 }],
      skippedQuestionIds: [2],
      session: { request_id: 'r1' },
      traceId: 'trace-1',
      batchToken: 'batch-1',
    },
    'fallback-trace'
  )
  assert.deepEqual(payload.answers, [{ question_id: 1 }])
  assert.deepEqual(payload.skipped_question_ids, [2])
  assert.equal(payload._traceId, 'trace-1')
  assert.equal(payload.batch_token, 'batch-1')
})

test('buildSubmitPayload: falls back to provided traceId', () => {
  const payload = buildSubmitPayload(
    { answers: [], skippedQuestionIds: [], session: {}, traceId: '', batchToken: '' },
    'fallback-trace'
  )
  assert.equal(payload._traceId, 'fallback-trace')
})

test('buildSubmitPayload: empty trace when neither provided', () => {
  const payload = buildSubmitPayload(
    { answers: [], skippedQuestionIds: [], session: {}, traceId: '', batchToken: '' },
    ''
  )
  assert.equal(payload._traceId, '')
})

test('isDeterministicReject: conflict code', () => {
  assert.equal(isDeterministicReject({ code: 'PRACTICE_SUBMISSION_CONFLICT' }), true)
})

test('isDeterministicReject: version conflict code', () => {
  assert.equal(isDeterministicReject({ code: 'PRACTICE_QUESTION_VERSION_CONFLICT' }), true)
})

test('isDeterministicReject: batch invalid code', () => {
  assert.equal(isDeterministicReject({ code: 'PRACTICE_BATCH_INVALID' }), true)
})

test('isDeterministicReject: payload invalid code', () => {
  assert.equal(isDeterministicReject({ code: 'PRACTICE_PAYLOAD_INVALID' }), true)
})

test('isDeterministicReject: 404 status', () => {
  assert.equal(isDeterministicReject({ statusCode: 404 }), true)
})

test('isDeterministicReject: 401 is retryable', () => {
  assert.equal(isDeterministicReject({ statusCode: 401 }), false)
})

test('isDeterministicReject: 408 is retryable', () => {
  assert.equal(isDeterministicReject({ statusCode: 408 }), false)
})

test('isDeterministicReject: 429 is retryable', () => {
  assert.equal(isDeterministicReject({ statusCode: 429 }), false)
})

test('isDeterministicReject: 500 is retryable', () => {
  assert.equal(isDeterministicReject({ statusCode: 500 }), false)
})

test('isDeterministicReject: network error is retryable', () => {
  assert.equal(isDeterministicReject({}), false)
  assert.equal(isDeterministicReject(null), false)
})

test('resolveRejectMessage: conflict', () => {
  const msg = resolveRejectMessage('PRACTICE_SUBMISSION_CONFLICT')
  assert.equal(msg.title, '交卷标识冲突')
  assert.ok(msg.content.includes('request_id'))
})

test('resolveRejectMessage: version conflict', () => {
  const msg = resolveRejectMessage('PRACTICE_QUESTION_VERSION_CONFLICT')
  assert.equal(msg.title, '题目版本无法恢复')
})

test('resolveRejectMessage: batch invalid', () => {
  const msg = resolveRejectMessage('PRACTICE_BATCH_INVALID')
  assert.equal(msg.title, '练习批次已失效')
})

test('resolveRejectMessage: default for unknown code', () => {
  const msg = resolveRejectMessage('UNKNOWN')
  assert.equal(msg.title, '交卷内容未通过校验')
})

test('resolveRejectMessage: default for empty', () => {
  const msg = resolveRejectMessage('')
  assert.equal(msg.title, '交卷内容未通过校验')
})
