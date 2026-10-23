const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildLoadViewState } = require('../subpackages/productivity/pomodoro-stats/load-view-state')

function createHarness(overrides = {}) {
  const options = {
    stats: { week_sessions: 4, week_duration_sec: 600 },
    summary: {
      sessions: 2,
      duration_sec: 300,
      subjects: [{ duration_sec: 300, sessions: 2 }],
    },
    lifetime: { sessions: 20, duration_sec: 7200, active_days: 2 },
    trends: [{ date: '2026-10-01', duration_sec: 120, _shortDate: '10-01' }],
    effectiveHistory: { items: [{ id: 1 }, { id: 2 }], total: 2 },
    effectiveDate: '2026-10-01',
    authoritativeToday: '2026-10-02',
    willAnimate: true,
    displayDaySubjects: true,
    currentLifetimeStartDate: '2026-01-01',
    currentSubjects: [],
    currentDistributionHasData: false,
    currentRangeStart: '2026-09-01',
    currentRangeEnd: '2026-09-30',
    hasCrossDayBleedInSubjects: subjects => subjects.some(
      item => Number(item.duration_sec) > 0 && Number(item.sessions) === 0
    ),
    formatSession: item => ({ id: item.id }),
    formatMin: sec => `${Math.floor(sec / 60)}分钟`,
    formatSelectedDurationLabel: date => `${date}学习`,
    hasDistributionData: items => (items || []).length > 0,
    buildSubjectItems: subjects => subjects.map(item => ({ ...item, _color: '#fff' })),
    formatPieDateLabel: date => date.slice(5),
    getDurationDisplayPatch: text => ({ durationText: text }),
    buildCumulativePatch: (lifetime, lifetimeStart) => ({
      lifetimeStartDate: lifetimeStart,
      cumulativeSessions: lifetime.sessions,
    }),
    ...overrides,
  }
  return { options, state: buildLoadViewState(options) }
}

test('builds the first-load animation view patch', () => {
  const { state } = createHarness()

  assert.deepEqual(state.daySessions, [{ id: 1 }, { id: 2 }])
  assert.equal(state.selectedDurationSec, 300)
  assert.equal(state.selectedSessionCount, 2)
  assert.equal(state.hasBleedInSubjects, false)
  assert.equal(state.lifetimeStart, '2026-01-01')
  assert.deepEqual(state.historyPatch, { history: [], historyTotal: 2, historyReady: false })
  assert.equal(state.dataPatch._dispTodaySessions, 0)
  assert.equal(state.dataPatch.durationValueAnimating, true)
  assert.equal(state.dataPatch.durationText, '0分钟')
  assert.deepEqual(state.dataPatch.history, [])
  assert.equal(state.dataPatch.trends[0]._shortDate, '10-01')
  assert.equal(state.dataPatch.subjects[0]._color, '#fff')
})

test('builds the refresh view patch with immediate history and counters', () => {
  const { state } = createHarness({
    willAnimate: false,
    lifetime: { start_date: '2026-01-02', sessions: 21 },
  })

  assert.equal(state.lifetimeStart, '2026-01-02')
  assert.equal(state.dataPatch._dispTodaySessions, 2)
  assert.equal(state.dataPatch._dispWeekSessions, 4)
  assert.equal(state.dataPatch.durationValueAnimating, false)
  assert.deepEqual(state.dataPatch.history, [{ id: 1 }, { id: 2 }])
  assert.equal(state.dataPatch.historyReady, true)
})

test('preserves non-day distribution view state', () => {
  const { state } = createHarness({
    displayDaySubjects: false,
    summary: { sessions: 0, duration_sec: 0, subjects: [] },
    currentDistributionHasData: true,
  })

  assert.deepEqual(state.dataPatch.subjects, [])
  assert.equal(state.dataPatch.distributionHasData, true)
  assert.equal(state.dataPatch.distributionRangeStart, '2026-09-01')
  assert.equal(state.dataPatch.distributionRangeEnd, '2026-09-30')
})

test('detects cross-day bleed-in and disables next-day navigation at today', () => {
  const bleeding = createHarness({
    summary: { sessions: 0, duration_sec: 30, subjects: [{ duration_sec: 30, sessions: 0 }] },
  })
  assert.equal(bleeding.state.hasBleedInSubjects, true)
  assert.equal(bleeding.state.dataPatch._crossDayBleedIn, true)

  const today = createHarness({ effectiveDate: '2026-10-02' })
  assert.equal(today.state.dataPatch.canGoNextDate, false)
})
