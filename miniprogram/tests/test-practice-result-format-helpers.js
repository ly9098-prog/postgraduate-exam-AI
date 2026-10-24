const assert = require('node:assert/strict')
const { test } = require('node:test')
const { normalizePercent, getQuestionListHeightRpx, formatDuration, buildErrorDonutGradient } = require('../subpackages/study/practice-result/utils/format-helpers')

test('normalizePercent: scales 0-1 to 0-100', () => {
  assert.equal(normalizePercent(0.75), 75)
})

test('normalizePercent: clamps 0-100 values', () => {
  assert.equal(normalizePercent(50), 50)
  assert.equal(normalizePercent(150), 100)
  assert.equal(normalizePercent(-10), 0)
})

test('normalizePercent: returns 0 for non-finite', () => {
  assert.equal(normalizePercent(NaN), 0)
  assert.equal(normalizePercent(Infinity), 0)
})

test('getQuestionListHeightRpx: scales with count', () => {
  assert.equal(getQuestionListHeightRpx(5), 430)
})

test('getQuestionListHeightRpx: default for 0', () => {
  assert.equal(getQuestionListHeightRpx(0), 96)
})

test('getQuestionListHeightRpx: handles null', () => {
  assert.equal(getQuestionListHeightRpx(null), 96)
})

test('formatDuration: formats seconds', () => {
  assert.equal(formatDuration(65), '01分05秒')
})

test('formatDuration: formats hours', () => {
  assert.equal(formatDuration(3661), '01:01:01')
})

test('formatDuration: handles 0', () => {
  assert.equal(formatDuration(0), '00分00秒')
})

test('formatDuration: clamps negative', () => {
  assert.equal(formatDuration(-10), '00分00秒')
})

test('buildErrorDonutGradient: returns default for empty', () => {
  assert.equal(buildErrorDonutGradient([]), '#EEF2EF')
})

test('buildErrorDonutGradient: builds gradient string', () => {
  const result = buildErrorDonutGradient([
    { label: 'A', count: 2, color: '#ff0000' },
    { label: 'B', count: 2, color: '#00ff00' },
  ])
  assert.ok(result.startsWith('conic-gradient('))
  assert.ok(result.includes('#ff0000'))
  assert.ok(result.includes('#00ff00'))
})
