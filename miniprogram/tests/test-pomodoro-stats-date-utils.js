const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  parseDateStr,
  formatDateParts,
  shiftDate,
  startOfWeek,
  monthStart,
  monthEnd,
  minDate,
  resolveDistributionRange,
} = require('../subpackages/productivity/pomodoro-stats/date-utils')

test('parseDateStr parses valid date', () => {
  assert.deepEqual(parseDateStr('2026-10-23'), [2026, 10, 23])
})

test('parseDateStr returns null for invalid date', () => {
  assert.equal(parseDateStr('bad'), null)
  assert.equal(parseDateStr('2026/10/23'), null)
  assert.equal(parseDateStr(''), null)
})

test('formatDateParts pads month and day', () => {
  assert.equal(formatDateParts([2026, 1, 5]), '2026-01-05')
  assert.equal(formatDateParts(null), '')
})

test('shiftDate adds days across month boundary', () => {
  assert.equal(shiftDate('2026-10-31', 1), '2026-11-01')
  assert.equal(shiftDate('2026-01-01', -1), '2025-12-31')
  assert.equal(shiftDate('bad', 1), 'bad')
})

test('startOfWeek returns Monday', () => {
  // 2026-10-23 is Friday, Monday is 2026-10-19
  assert.equal(startOfWeek('2026-10-23'), '2026-10-19')
  // 2026-10-25 is Sunday, Monday is 2026-10-19
  assert.equal(startOfWeek('2026-10-25'), '2026-10-19')
  // 2026-10-19 is Monday, should stay
  assert.equal(startOfWeek('2026-10-19'), '2026-10-19')
})

test('monthStart returns first day of month', () => {
  assert.equal(monthStart('2026-10-23'), '2026-10-01')
  assert.equal(monthStart('bad'), 'bad')
})

test('monthEnd returns last day of month', () => {
  assert.equal(monthEnd('2026-10-23'), '2026-10-31')
  assert.equal(monthEnd('2026-02-15'), '2026-02-28')
  assert.equal(monthEnd('2024-02-15'), '2024-02-29') // leap year
})

test('minDate returns earlier date', () => {
  assert.equal(minDate('2026-01-01', '2026-02-01'), '2026-01-01')
  assert.equal(minDate('', '2026-02-01'), '2026-02-01')
  assert.equal(minDate('2026-01-01', ''), '2026-01-01')
})

test('resolveDistributionRange handles day period', () => {
  const result = resolveDistributionRange('day', '2026-10-23', { todayDate: '2026-10-23' })
  assert.deepEqual(result, { start: '2026-10-23', end: '2026-10-23' })
})

test('resolveDistributionRange handles week period clamped to today', () => {
  const result = resolveDistributionRange('week', '2026-10-23', { todayDate: '2026-10-23' })
  assert.equal(result.start, '2026-10-19')
  assert.equal(result.end, '2026-10-23') // clamped to today, not Sunday
})

test('resolveDistributionRange handles month period', () => {
  const result = resolveDistributionRange('month', '2026-10-23', { todayDate: '2026-10-23' })
  assert.equal(result.start, '2026-10-01')
  assert.equal(result.end, '2026-10-23') // clamped to today
})

test('resolveDistributionRange handles custom period', () => {
  const result = resolveDistributionRange('custom', '2026-10-23', {
    todayDate: '2026-10-23',
    customRangeStartDate: '2026-10-01',
  })
  assert.deepEqual(result, { start: '2026-10-01', end: '2026-10-23' })
})

test('resolveDistributionRange handles custom period with start after anchor', () => {
  const result = resolveDistributionRange('custom', '2026-10-23', {
    todayDate: '2026-10-23',
    customRangeStartDate: '2026-11-01',
  })
  assert.deepEqual(result, { start: '2026-10-23', end: '2026-10-23' })
})
