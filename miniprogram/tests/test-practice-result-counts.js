const assert = require('node:assert/strict')
const { test } = require('node:test')
const { resolveResultCounts } = require('../subpackages/study/practice-result/utils/result-counts')

test('uses explicit counts when provided', () => {
  const result = resolveResultCounts(
    { total_correct: 3, total_wrong: 1, total_skipped: 1, total_partial: 0, total: 5 },
    []
  )
  assert.equal(result.correctCount, 3)
  assert.equal(result.wrongCount, 1)
  assert.equal(result.skippedCount, 1)
  assert.equal(result.partialCount, 0)
  assert.equal(result.totalCount, 5)
})

test('falls back to counting by status', () => {
  const result = resolveResultCounts({}, [
    { status: 'correct' },
    { status: 'correct' },
    { status: 'wrong' },
    { status: 'skipped' },
  ])
  assert.equal(result.correctCount, 2)
  assert.equal(result.wrongCount, 1)
  assert.equal(result.skippedCount, 1)
  assert.equal(result.totalCount, 4)
})

test('recomputes from items when all explicit counts are zero', () => {
  const result = resolveResultCounts(
    { total_correct: 0, total_wrong: 0, total_skipped: 0, total_partial: 0 },
    [
      { status: 'correct' },
      { status: 'wrong' },
    ]
  )
  assert.equal(result.correctCount, 1)
  assert.equal(result.wrongCount, 1)
  assert.equal(result.totalCount, 2)
})

test('handles camelCase field names', () => {
  const result = resolveResultCounts(
    { totalCorrect: 5, totalWrong: 2, totalSkipped: 1, totalPartial: 0, totalCount: 8 },
    []
  )
  assert.equal(result.correctCount, 5)
  assert.equal(result.wrongCount, 2)
  assert.equal(result.totalCount, 8)
})

test('computes total from sum when total missing', () => {
  const result = resolveResultCounts(
    { total_correct: 3, total_wrong: 2 },
    []
  )
  assert.equal(result.totalCount, 5)
})

test('handles empty source and items', () => {
  const result = resolveResultCounts({}, [])
  assert.equal(result.correctCount, 0)
  assert.equal(result.wrongCount, 0)
  assert.equal(result.totalCount, 0)
})

test('handles partial counts', () => {
  const result = resolveResultCounts(
    { total_correct: 2, total_wrong: 1, total_partial: 1, total: 4 },
    []
  )
  assert.equal(result.partialCount, 1)
  assert.equal(result.totalCount, 4)
})
