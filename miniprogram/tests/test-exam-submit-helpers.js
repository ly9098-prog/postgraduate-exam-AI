const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildFinalSubmitAnswers, isRetryableSubmitError } = require('../subpackages/exam/utils/submit-helpers')

test('buildFinalSubmitAnswers: maps pending items to submit format', () => {
  const answers = buildFinalSubmitAnswers(['1', '2'], {
    '1': { selected_answer: 'a', marked_for_review: true, used_time: 30 },
    '2': { selected_answer: 'B', marked_for_review: false, used_time: 60 },
  })
  assert.equal(answers.length, 2)
  assert.equal(answers[0].item_id, 1)
  assert.equal(answers[0].selected_answer, 'A')
  assert.equal(answers[0].marked_for_review, true)
  assert.equal(answers[0].used_time, 30)
  assert.equal(answers[1].selected_answer, 'B')
})

test('buildFinalSubmitAnswers: null selected_answer when empty', () => {
  const answers = buildFinalSubmitAnswers(['1'], { '1': {} })
  assert.equal(answers[0].selected_answer, null)
})

test('buildFinalSubmitAnswers: trims and uppercases answer', () => {
  const answers = buildFinalSubmitAnswers(['1'], { '1': { selected_answer: '  abc  ' } })
  assert.equal(answers[0].selected_answer, 'ABC')
})

test('buildFinalSubmitAnswers: clamps used_time to 6 hours max', () => {
  const answers = buildFinalSubmitAnswers(['1'], { '1': { used_time: 99999 } })
  assert.equal(answers[0].used_time, 6 * 60 * 60)
})

test('buildFinalSubmitAnswers: clamps used_time to 0 min', () => {
  const answers = buildFinalSubmitAnswers(['1'], { '1': { used_time: -100 } })
  assert.equal(answers[0].used_time, 0)
})

test('buildFinalSubmitAnswers: defaults marked_for_review to false', () => {
  const answers = buildFinalSubmitAnswers(['1'], { '1': {} })
  assert.equal(answers[0].marked_for_review, false)
})

test('buildFinalSubmitAnswers: handles missing pending entry', () => {
  const answers = buildFinalSubmitAnswers(['1'], {})
  assert.equal(answers[0].selected_answer, null)
  assert.equal(answers[0].used_time, 0)
})

test('buildFinalSubmitAnswers: handles empty itemIds', () => {
  assert.deepEqual(buildFinalSubmitAnswers([], {}), [])
  assert.deepEqual(buildFinalSubmitAnswers(null, null), [])
})

test('isRetryableSubmitError: status 0 (network)', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 0 }), true)
})

test('isRetryableSubmitError: 408 timeout', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 408 }), true)
})

test('isRetryableSubmitError: 425 too early', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 425 }), true)
})

test('isRetryableSubmitError: 429 rate limit', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 429 }), true)
})

test('isRetryableSubmitError: 500 server error', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 500 }), true)
})

test('isRetryableSubmitError: 503 server error', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 503 }), true)
})

test('isRetryableSubmitError: 400 is not retryable', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 400 }), false)
})

test('isRetryableSubmitError: 404 is not retryable', () => {
  assert.equal(isRetryableSubmitError({ statusCode: 404 }), false)
})

test('isRetryableSubmitError: null error', () => {
  assert.equal(isRetryableSubmitError(null), true)
})
