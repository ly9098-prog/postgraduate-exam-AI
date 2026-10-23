const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDateRequestController,
} = require('../subpackages/productivity/pomodoro-stats/date-request-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    dateSeq: 0,
    selectedDate: '2026-10-24',
    todayDate: '2026-10-24',
    distributionPeriod: 'day',
    patches: [],
    resetPieCache: false,
    logs: [],
  }
  const summary = { sessions: 2, duration_sec: 300, subjects: [] }
  const viewState = {
    selectedDurationSec: 300,
    selectedSessionCount: 2,
    subjectBreakdown: [],
    dataPatch: { pieLoading: false },
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getDateRequestSeq: () => state.dateSeq,
    incrementDateRequestSeq: () => { state.dateSeq += 1 },
    getSelectedDate: () => state.selectedDate,
    getTodayDate: () => state.todayDate,
    getDistributionPeriod: () => state.distributionPeriod,
    setData: patch => state.patches.push(patch),
    getInitialResponses: async () => [summary, { items: [{ id: 1 }], total: 1 }],
    getHistory: async date => ({ date, items: [], total: 0 }),
    getHistoryDate: state.getHistoryDate,
    reconcileFromServer: () => ({ changedToday: false, today: state.todayDate }),
    logError: (message, error) => state.logs.push([message, error]),
    buildDateViewState: overrides => ({ ...viewState, ...overrides }),
    setRawTodayDuration: value => { state.rawTodayDuration = value },
    setDaySubjectsRaw: value => { state.daySubjectsRaw = value },
    resetPieCache: () => { state.resetPieCache = true },
    commitDate: (view, context) => { state.commit = [view, context] },
    handleDateFailure: (error, context) => { state.failure = [error, context] },
    ...overrides,
  }
  return { controller: createDateRequestController(options), options, state, viewState }
}

test('loads the selected date and delegates the view to commit', async () => {
  const harness = createHarness()
  await harness.controller.load('2026-10-24')

  assert.equal(harness.state.dateSeq, 1)
  assert.deepEqual(harness.state.patches, [{ pieLoading: true }])
  assert.equal(harness.state.rawTodayDuration, 300)
  assert.deepEqual(harness.state.daySubjectsRaw, [])
  assert.equal(harness.state.resetPieCache, true)
  assert.deepEqual(harness.state.commit[1], { seq: 1, showDayDistribution: true })
  assert.equal(harness.state.failure, undefined)
})

test('skips empty dates and the pie patch for non-day distributions', async () => {
  const empty = createHarness()
  await empty.controller.load(' ')
  assert.equal(empty.state.dateSeq, 0)
  assert.equal(empty.state.commit, undefined)

  const nonDay = createHarness()
  nonDay.state.distributionPeriod = 'week'
  nonDay.options.getSelectedDate = () => '2026-10-23'
  await nonDay.controller.load('2026-10-23')
  assert.deepEqual(nonDay.state.patches, [])
  assert.equal(nonDay.state.resetPieCache, false)
  assert.deepEqual(nonDay.state.commit[1], { seq: 1, showDayDistribution: false })
})

test('refetches history after backend today correction', async () => {
  const harness = createHarness()
  let selectedDate = '2026-10-24'
  harness.options.getSelectedDate = () => selectedDate
  harness.options.getHistory = async date => {
    harness.state.getHistoryDate = date
    return { date, items: [], total: 0 }
  }
  harness.options.reconcileFromServer = () => {
    selectedDate = '2026-10-25'
    harness.state.todayDate = '2026-10-25'
    return { changedToday: true, today: '2026-10-25' }
  }
  await harness.controller.load('2026-10-24')

  assert.equal(harness.state.getHistoryDate, '2026-10-25')
  assert.deepEqual(harness.state.commit[0].effectiveHistory, {
    date: '2026-10-25',
    items: [],
    total: 0,
  })
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
  await harness.controller.load('2026-10-24')

  assert.deepEqual(harness.state.logs, [['重取今日 history 失败', error]])
  assert.deepEqual(harness.state.commit[0].effectiveHistory, { items: [], total: 0 })
})

test('discards stale responses before reconcile and after refetch', async () => {
  const beforeReconcile = createHarness()
  beforeReconcile.options.getInitialResponses = async () => {
    beforeReconcile.state.dateSeq = 2
    return [{}, {}]
  }
  await beforeReconcile.controller.load('2026-10-24')
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
    afterRefetch.state.dateSeq = 2
    return { items: [], total: 0 }
  }
  await afterRefetch.controller.load('2026-10-24')
  assert.equal(afterRefetch.state.commit, undefined)
})

test('delegates date failures', async () => {
  const harness = createHarness()
  const error = new Error('date summary failed')
  harness.options.getInitialResponses = async () => { throw error }
  await harness.controller.load('2026-10-24')

  assert.deepEqual(harness.state.failure, [error, { seq: 1 }])
})
