const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLoadRequestController,
} = require('../subpackages/productivity/pomodoro-stats/load-request-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    requestId: 2,
    selectedDate: '2026-10-24',
    todayDate: '2026-10-24',
    dateSeq: 0,
    hasData: true,
    inFlight: 0,
    distributionPeriod: 'day',
    settingsEnsured: false,
    subjectMetaEnsured: false,
    patches: [],
    cancelledDeferred: false,
    cancelledDuration: false,
    resetPieCache: false,
    logs: [],
  }

  const overview = {
    stats: { week_duration_sec: 600 },
    summary: { sessions: 2, duration_sec: 300, subjects: [] },
    trends: [],
    lifetime: { start_date: '2026-01-01', sessions: 20 },
  }
  const viewState = {
    selectedDurationSec: 300,
    selectedSessionCount: 2,
    subjectBreakdown: [],
    daySessions: [{ id: 1 }],
    dataPatch: { loading: false },
  }

  const options = {
    isAlive: () => state.alive,
    ensureSettings: async () => { state.settingsEnsured = true },
    ensureSubjectMeta: async () => { state.subjectMetaEnsured = true; return {} },
    getRequestId: () => state.requestId,
    getSelectedDate: () => state.selectedDate,
    getTodayDate: () => state.todayDate,
    incrementDateRequestSeq: () => { state.dateSeq += 1 },
    getDateRequestSeq: () => state.dateSeq,
    hasData: () => state.hasData,
    setHasData: value => { state.hasData = value },
    cancelDeferredHistory: () => { state.cancelledDeferred = true },
    setData: patch => state.patches.push(patch),
    incrementStatsLoadInFlight: () => { state.inFlight += 1 },
    decrementStatsLoadInFlight: () => { state.inFlight = Math.max(0, state.inFlight - 1) },
    getInitialResponses: async () => [overview, { items: [{ id: 1 }], total: 1 }],
    getHistory: async date => {
      state.getHistoryDate = date
      return { date, items: [], total: 0 }
    },
    normalizeOverview: response => response,
    reconcileFromServer: () => ({ changedToday: false, today: state.todayDate }),
    logError: (message, error) => state.logs.push([message, error]),
    getDistributionPeriod: () => state.distributionPeriod,
    resetPieCache: () => { state.resetPieCache = true },
    cancelDurationAnimation: () => { state.cancelledDuration = true },
    buildLoadViewState: overrides => ({ ...viewState, ...overrides }),
    commitLoad: (view, context) => { state.commit = [view, context] },
    handleLoadFailure: (error, context) => { state.failure = [error, context] },
    ...overrides,
  }
  state.overview = overview
  return {
    controller: createLoadRequestController(options),
    options,
    state,
    viewState,
    context: null,
  }
}

test('loads the overview and delegates the normalized result to commit', async () => {
  const harness = createHarness()
  await harness.controller.load(false)

  assert.equal(harness.state.settingsEnsured, true)
  assert.equal(harness.state.subjectMetaEnsured, true)
  assert.equal(harness.state.dateSeq, 1)
  assert.equal(harness.state.cancelledDeferred, true)
  assert.deepEqual(harness.state.patches, [{ loading: true, errorText: '' }])
  assert.equal(harness.state.inFlight, 0)
  assert.equal(harness.state.hasData, true)
  assert.equal(harness.state.cancelledDuration, true)
  assert.equal(harness.state.resetPieCache, true)
  assert.ok(harness.state.commit)
  const [view, context] = harness.state.commit
  assert.deepEqual(view, {
    ...harness.viewState,
    ...harness.state.overview,
    effectiveHistory: { items: [{ id: 1 }], total: 1 },
    effectiveDate: '2026-10-24',
    authoritativeToday: '2026-10-24',
    willAnimate: false,
    displayDaySubjects: true,
  })
  assert.deepEqual(context, {
    reqId: 2,
    dateSeq: 1,
    effectiveDate: '2026-10-24',
    effectiveHistory: { items: [{ id: 1 }], total: 1 },
    willAnimate: false,
    displayDaySubjects: true,
    weekDurationSec: 600,
  })
  assert.equal(harness.state.failure, undefined)
})

test('marks first load for animation and skips the loading patch in the background', async () => {
  const harness = createHarness()
  harness.state.hasData = false
  await harness.controller.load(true)

  assert.deepEqual(harness.state.patches, [])
  assert.equal(harness.state.commit[1].willAnimate, true)
  assert.equal(harness.state.commit[1].displayDaySubjects, true)
})

test('refetches history after backend today correction', async () => {
  const harness = createHarness()
  let selectedDate = '2026-10-24'
  harness.options.getSelectedDate = () => selectedDate
  harness.options.reconcileFromServer = () => {
    selectedDate = '2026-10-25'
    harness.state.todayDate = '2026-10-25'
    return { changedToday: true, today: '2026-10-25' }
  }
  await harness.controller.load(false)

  assert.deepEqual(harness.state.commit[1].effectiveHistory, {
    date: '2026-10-25',
    items: [],
    total: 0,
  })
  assert.equal(harness.state.getHistoryDate, '2026-10-25')
})

test('falls back to empty history when the corrected-date refetch fails', async () => {
  const harness = createHarness()
  let selectedDate = '2026-10-24'
  harness.options.getSelectedDate = () => selectedDate
  harness.options.reconcileFromServer = () => {
    selectedDate = '2026-10-25'
    harness.state.todayDate = '2026-10-25'
    return { changedToday: true, today: '2026-10-25' }
  }
  const error = new Error('history failed')
  harness.options.getHistory = async () => { throw error }
  await harness.controller.load(false)

  assert.deepEqual(harness.state.logs, [['重取今日 history 失败', error]])
  assert.deepEqual(harness.state.commit[1].effectiveHistory, { items: [], total: 0 })
})

test('discards stale responses before reconcile and after refetch', async () => {
  const beforeReconcile = createHarness()
  beforeReconcile.options.getInitialResponses = async () => {
    beforeReconcile.state.requestId = 3
    return [{}, {}]
  }
  await beforeReconcile.controller.load(false)
  assert.equal(beforeReconcile.state.commit, undefined)

  const afterRefetch = createHarness()
  let selectedDate = '2026-10-24'
  afterRefetch.options.getSelectedDate = () => selectedDate
  afterRefetch.options.reconcileFromServer = () => {
    selectedDate = '2026-10-25'
    afterRefetch.state.todayDate = '2026-10-25'
    return { changedToday: true, today: '2026-10-25' }
  }
  afterRefetch.options.getHistory = async () => {
    afterRefetch.state.requestId = 3
    return { items: [], total: 0 }
  }
  await afterRefetch.controller.load(false)
  assert.equal(afterRefetch.state.commit, undefined)
})

test('delegates load failures and always clears the in-flight guard', async () => {
  const error = new Error('overview failed')
  const harness = createHarness()
  harness.options.getInitialResponses = async () => { throw error }
  await harness.controller.load(true)

  assert.deepEqual(harness.state.failure, [error, {
    background: true,
    reqId: 2,
    dateSeq: 1,
    requestedDate: '2026-10-24',
  }])
  assert.equal(harness.state.inFlight, 0)
})
