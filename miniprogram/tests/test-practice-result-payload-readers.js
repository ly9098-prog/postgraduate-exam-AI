const assert = require('node:assert/strict')
const { test } = require('node:test')
const { hasDetailedPracticePayload, readSummaryFromOptions } = require('../subpackages/study/practice-result/utils/payload-readers')

test('hasDetailedPracticePayload: detects results array', () => {
  assert.equal(hasDetailedPracticePayload({ results: [{ id: 1 }] }), true)
})

test('hasDetailedPracticePayload: detects submitResults array', () => {
  assert.equal(hasDetailedPracticePayload({ submitResults: [{ id: 1 }] }), true)
})

test('hasDetailedPracticePayload: detects resultList array', () => {
  assert.equal(hasDetailedPracticePayload({ resultList: [{ id: 1 }] }), true)
})

test('hasDetailedPracticePayload: unwraps data property', () => {
  assert.equal(hasDetailedPracticePayload({ data: { results: [{ id: 1 }] } }), true)
})

test('hasDetailedPracticePayload: false for empty results', () => {
  assert.equal(hasDetailedPracticePayload({ results: [] }), false)
})

test('hasDetailedPracticePayload: false for null', () => {
  assert.equal(hasDetailedPracticePayload(null), false)
})

test('hasDetailedPracticePayload: false for empty object', () => {
  assert.equal(hasDetailedPracticePayload({}), false)
})

test('readSummaryFromOptions: reads all fields', () => {
  const summary = readSummaryFromOptions({
    correct: '3', wrong: '1', skipped: '1', partial: '0',
    total: '5', duration: '120', subject_id: '12', subject_name: '数据结构',
  })
  assert.equal(summary.total_correct, 3)
  assert.equal(summary.total_wrong, 1)
  assert.equal(summary.total_skipped, 1)
  assert.equal(summary.total_partial, 0)
  assert.equal(summary.total, 5)
  assert.equal(summary.duration, 120)
  assert.equal(summary.subject_id, 12)
  assert.equal(summary.subject_name, '数据结构')
})

test('readSummaryFromOptions: decodes subject_name', () => {
  const summary = readSummaryFromOptions({
    correct: 0, subject_name: encodeURIComponent('操作系统'),
  })
  assert.equal(summary.subject_name, '操作系统')
})

test('readSummaryFromOptions: returns null when no keys present', () => {
  assert.equal(readSummaryFromOptions({}), null)
})

test('readSummaryFromOptions: returns null for empty options', () => {
  assert.equal(readSummaryFromOptions({ foo: 'bar' }), null)
})

test('readSummaryFromOptions: defaults missing numeric fields to 0', () => {
  const summary = readSummaryFromOptions({ correct: '1' })
  assert.equal(summary.total_correct, 1)
  assert.equal(summary.total_wrong, 0)
  assert.equal(summary.total, 0)
  assert.equal(summary.duration, 0)
})

test('readSummaryFromOptions: subject_id null when not provided', () => {
  const summary = readSummaryFromOptions({ correct: 0 })
  assert.equal(summary.subject_id, null)
})
