const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildCumulativeSummaryPatch } = require('../subpackages/productivity/pomodoro-stats/cumulative-summary-patch')

const formatMin = sec => `${Math.floor(sec / 60)}分钟`

test('maps a summary into the cumulative view patch', () => {
  const patch = buildCumulativeSummaryPatch(
    { sessions: 10, duration_sec: 3600, active_days: 3 },
    '2024-01-01',
    '2024-06-01',
    formatMin,
  )
  assert.deepEqual(patch, {
    cumulativeStartDate: '2024-01-01',
    cumulativeSessions: 10,
    cumulativeDurationText: '60分钟',
    cumulativeAverageText: '20分钟',
    cumulativeActiveDays: 3,
    cumulativeLoading: false,
  })
})

test('falls back to summary.start_date then todayDate for the start', () => {
  const fromSummary = buildCumulativeSummaryPatch({ start_date: '2024-02-01' }, null, '2024-06-01', formatMin)
  assert.equal(fromSummary.cumulativeStartDate, '2024-02-01')

  const fromToday = buildCumulativeSummaryPatch({}, null, '2024-06-01', formatMin)
  assert.equal(fromToday.cumulativeStartDate, '2024-06-01')

  const empty = buildCumulativeSummaryPatch({}, null, '', formatMin)
  assert.equal(empty.cumulativeStartDate, '')
})

test('clamps negative numeric fields to zero', () => {
  const patch = buildCumulativeSummaryPatch(
    { sessions: -5, duration_sec: -100, active_days: -2 },
    '2024-01-01',
    '2024-06-01',
    formatMin,
  )
  assert.equal(patch.cumulativeSessions, 0)
  assert.equal(patch.cumulativeActiveDays, 0)
  assert.equal(patch.cumulativeDurationText, '0分钟')
  assert.equal(patch.cumulativeAverageText, '0分钟')
})

test('defaults average to zero when active days is zero', () => {
  const patch = buildCumulativeSummaryPatch(
    { sessions: 5, duration_sec: 3600, active_days: 0 },
    '2024-01-01',
    '2024-06-01',
    formatMin,
  )
  assert.equal(patch.cumulativeAverageText, '0分钟')
})

test('floors the average duration', () => {
  const patch = buildCumulativeSummaryPatch(
    { sessions: 5, duration_sec: 100, active_days: 3 },
    '2024-01-01',
    '2024-06-01',
    formatMin,
  )
  assert.equal(patch.cumulativeAverageText, '0分钟')
})

test('handles a null summary', () => {
  const patch = buildCumulativeSummaryPatch(null, '2024-01-01', '2024-06-01', formatMin)
  assert.equal(patch.cumulativeSessions, 0)
  assert.equal(patch.cumulativeActiveDays, 0)
  assert.equal(patch.cumulativeLoading, false)
})
