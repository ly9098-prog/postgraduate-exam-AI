const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildDateViewState } = require('../subpackages/productivity/pomodoro-stats/date-view-state')

function createHarness(overrides = {}) {
  const options = {
    summary: {
      sessions: 3,
      duration_sec: 480,
      subjects: [{ duration_sec: 480, sessions: 3 }],
    },
    effectiveHistory: {
      items: [{ id: 1 }, { id: 2 }, { id: 3 }],
      total: 25,
    },
    effectiveDate: '2026-10-01',
    todayDate: '2026-10-02',
    showDayDistribution: true,
    currentDisplayDurationSec: 300,
    currentRawDurationSec: 360,
    currentDisplaySessions: 2,
    currentSubjects: [],
    currentDistributionHasData: false,
    currentRangeStart: '2026-09-01',
    currentRangeEnd: '2026-09-30',
    hasCrossDayBleedInSubjects: subjects => subjects.some(
      item => Number(item.duration_sec) > 0 && Number(item.sessions) === 0
    ),
    buildSubjectItems: subjects => subjects.map(item => ({ ...item, _color: '#fff' })),
    hasDistributionData: items => (items || []).length > 0,
    formatMin: sec => `${Math.floor(sec / 60)}分钟`,
    formatSelectedDurationLabel: date => `${date}学习`,
    formatSession: item => ({ id: item.id }),
    formatPieDateLabel: date => date.slice(5),
    ...overrides,
  }
  return { options, state: buildDateViewState(options) }
}

test('builds the selected-date view and animation transition', () => {
  const { state } = createHarness()

  assert.equal(state.selectedDurationSec, 480)
  assert.equal(state.selectedSessionCount, 3)
  assert.equal(state.previousDurationSec, 300)
  assert.equal(state.previousSessionCount, 2)
  assert.deepEqual(state.dataPatch, {
    todaySessions: 3,
    subjects: [{ duration_sec: 480, sessions: 3, _color: '#fff' }],
    distributionHasData: true,
    todayDurationText: '8分钟',
    selectedDurationLabel: '2026-10-01学习',
    history: [{ id: 1 }, { id: 2 }, { id: 3 }],
    historyTotal: 25,
    historyReady: true,
    pieDateLabel: '10-01',
    distributionRangeStart: '2026-10-01',
    distributionRangeEnd: '2026-10-01',
    canGoNextDate: true,
    _crossDayBleedIn: false,
    pieLoading: false,
    selectedSubjectDetail: null,
    _selectedSubject: null,
  })
})

test('falls back to the raw duration and clamps previous sessions', () => {
  const { state } = createHarness({
    currentDisplayDurationSec: undefined,
    currentRawDurationSec: 600,
    currentDisplaySessions: -1,
  })

  assert.equal(state.previousDurationSec, 600)
  assert.equal(state.previousSessionCount, 0)
})

test('preserves non-day distribution state', () => {
  const { state } = createHarness({
    showDayDistribution: false,
    summary: { sessions: 0, duration_sec: 0, subjects: [] },
    currentDistributionHasData: true,
  })

  assert.deepEqual(state.dataPatch.subjects, [])
  assert.equal(state.dataPatch.distributionHasData, true)
  assert.equal(state.dataPatch.distributionRangeStart, '2026-09-01')
  assert.equal(state.dataPatch.distributionRangeEnd, '2026-09-30')
})

test('detects cross-day bleed-in and disables navigation at today', () => {
  const bleeding = createHarness({
    summary: { sessions: 0, duration_sec: 30, subjects: [{ duration_sec: 30, sessions: 0 }] },
  })
  assert.equal(bleeding.state.dataPatch._crossDayBleedIn, true)

  const today = createHarness({ effectiveDate: '2026-10-02' })
  assert.equal(today.state.dataPatch.canGoNextDate, false)
})
