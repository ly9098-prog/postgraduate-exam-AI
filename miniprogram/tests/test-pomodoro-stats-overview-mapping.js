const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  normalizeOverview,
  hasCrossDayBleedInSubjects,
  buildTrendItems,
} = require('../subpackages/productivity/pomodoro-stats/overview-mapping')

test('normalizes missing overview fields to stable empty objects', () => {
  assert.deepEqual(normalizeOverview(null), {
    stats: {},
    trends: [],
    summary: {},
    lifetime: {},
  })
  assert.deepEqual(normalizeOverview({}), {
    stats: {},
    trends: [],
    summary: {},
    lifetime: {},
  })
})

test('keeps backend overview sections and formats trend short dates', () => {
  const normalized = normalizeOverview({
    stats: { week_sessions: 2 },
    trends: [
      { date: '2026-10-01', duration_sec: 120 },
      { date: '', duration_sec: 30 },
    ],
    daily_summary: { duration_sec: 300 },
    lifetime_summary: { sessions: 9 },
  })

  assert.equal(normalized.stats.week_sessions, 2)
  assert.deepEqual(normalized.trends, [
    { date: '2026-10-01', duration_sec: 120, _shortDate: '10-01' },
    { date: '', duration_sec: 30, _shortDate: '' },
  ])
  assert.equal(normalized.summary.duration_sec, 300)
  assert.equal(normalized.lifetime.sessions, 9)
})

test('detects cross-day bleed-in only for positive duration with zero sessions', () => {
  assert.equal(hasCrossDayBleedInSubjects(null), false)
  assert.equal(hasCrossDayBleedInSubjects([
    { duration_sec: 0, sessions: 0 },
    { duration_sec: 20, sessions: 1 },
  ]), false)
  assert.equal(hasCrossDayBleedInSubjects([
    null,
    { duration_sec: '20', sessions: 0 },
  ]), true)
})

test('buildTrendItems returns an empty array without trends', () => {
  assert.deepEqual(buildTrendItems(null), [])
  assert.deepEqual(buildTrendItems(undefined), [])
  assert.deepEqual(buildTrendItems([]), [])
})
