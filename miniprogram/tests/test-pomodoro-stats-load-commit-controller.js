const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLoadCommitController,
} = require('../subpackages/productivity/pomodoro-stats/load-commit-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    requestId: 9,
    dateSeq: 4,
    effectiveDate: '2026-10-24',
    willAnimate: true,
    displayDaySubjects: true,
    weekDurationSec: 3600,
    historyTotal: 2,
    chartMode: 'pie',
    barMounted: false,
    cumulativeCustomized: false,
    cumulativeStartDate: '',
    distributionPeriod: 'day',
    pieCanvasNode: null,
    timers: [],
    patches: [],
    initPieCallbacks: [],
    initTrendCallbacks: [],
  }

  const viewState = {
    selectedDurationSec: 300,
    selectedSessionCount: 2,
    subjectBreakdown: [{ duration_sec: 300 }],
    daySessions: [{ id: 1 }, { id: 2 }],
    dataPatch: { loading: false },
  }

  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getRequestId: () => state.requestId,
    setDisplayTodayDurationSec: value => { state.displayTodayDurationSec = value },
    setDaySubjectsRaw: value => { state.daySubjectsRaw = value },
    setRawTodayDuration: value => { state.rawTodayDuration = value },
    setRawWeekDuration: value => { state.rawWeekDuration = value },
    setData: (patch, callback) => {
      state.patches.push(patch)
      callback()
    },
    queueDeferredHistory: (reqId, dateSeq, selectedDate, sessions, total) => {
      state.deferredHistory = { reqId, dateSeq, selectedDate, sessions, total }
    },
    isCumulativeCustomized: () => state.cumulativeCustomized,
    getCumulativeStartDate: () => state.cumulativeStartDate,
    refreshCumulativeSummary: (startDate, silent) => {
      state.cumulativeRefresh = { startDate, silent }
    },
    getDistributionPeriod: () => state.distributionPeriod,
    loadDistributionForPeriod: (period, animate) => {
      state.distributionLoad = { period, animate }
    },
    getChartMode: () => state.chartMode,
    initCanvases: callback => state.initPieCallbacks.push(callback),
    renderPie: (progress, includeLabels) => {
      state.pieRenders.push([progress, includeLabels])
    },
    getPieCanvasNode: () => state.pieCanvasNode,
    setTimeout: callback => {
      const handle = { callback }
      state.timers.push(handle)
      return handle
    },
    startAnimations: requestId => { state.startedAnimations = requestId },
    isBarMounted: () => state.barMounted,
    initTrendCanvas: callback => state.initTrendCallbacks.push(callback),
    renderTrendBars: progress => { state.barRenders.push(progress) },
    ...overrides,
  }

  state.pieRenders = []
  state.barRenders = []
  const context = {
    reqId: state.requestId,
    dateSeq: state.dateSeq,
    effectiveDate: state.effectiveDate,
    effectiveHistory: { total: state.historyTotal },
    willAnimate: state.willAnimate,
    displayDaySubjects: state.displayDaySubjects,
    weekDurationSec: state.weekDurationSec,
  }
  return { controller: createLoadCommitController(options), options, state, viewState, context }
}

function fireLatestPieInit(state) {
  const callback = state.initPieCallbacks.at(-1)
  callback()
}

function fireTimers(state) {
  while (state.timers.length) state.timers.shift().callback()
}

test('commits load state and starts the deferred first-load animation', () => {
  const harness = createHarness()
  harness.controller.commit(harness.viewState, harness.context)

  assert.equal(harness.state.displayTodayDurationSec, 0)
  assert.deepEqual(harness.state.daySubjectsRaw, [{ duration_sec: 300 }])
  assert.equal(harness.state.rawTodayDuration, 300)
  assert.equal(harness.state.rawWeekDuration, 3600)
  assert.deepEqual(harness.state.patches, [{ loading: false }])
  assert.deepEqual(harness.state.deferredHistory, {
    reqId: 9,
    dateSeq: 4,
    selectedDate: '2026-10-24',
    sessions: [{ id: 1 }, { id: 2 }],
    total: 2,
  })

  fireLatestPieInit(harness.state)
  assert.deepEqual(harness.state.pieRenders, [[0, false]])
  fireTimers(harness.state)
  assert.equal(harness.state.startedAnimations, 9)
})

test('renders the final pie immediately on refresh', () => {
  const harness = createHarness({ willAnimate: false })
  harness.context.willAnimate = false
  harness.controller.commit(harness.viewState, harness.context)
  assert.equal(harness.state.displayTodayDurationSec, 300)
  assert.equal(harness.state.deferredHistory, undefined)

  fireLatestPieInit(harness.state)
  assert.deepEqual(harness.state.pieRenders, [[1, true]])
})

test('refreshes custom cumulative summaries and non-day distributions', () => {
  const harness = createHarness()
  harness.state.displayDaySubjects = false
  harness.state.distributionPeriod = 'week'
  harness.state.cumulativeCustomized = true
  harness.state.cumulativeStartDate = '2026-10-01'
  harness.context.displayDaySubjects = false
  harness.context.willAnimate = false

  harness.controller.commit(harness.viewState, harness.context)
  assert.deepEqual(harness.state.cumulativeRefresh, { startDate: '2026-10-01', silent: true })
  assert.deepEqual(harness.state.distributionLoad, { period: 'week', animate: true })
  assert.equal(harness.state.initPieCallbacks.length, 0)
})

test('renders an already mounted bar chart for daily distributions', () => {
  const harness = createHarness()
  harness.state.chartMode = 'bar'
  harness.state.barMounted = true
  harness.controller.commit(harness.viewState, harness.context)
  harness.state.initTrendCallbacks.at(-1)()
  assert.deepEqual(harness.state.barRenders, [1])
  assert.equal(harness.state.initPieCallbacks.length, 0)
})

test('stops stale or dead commits before side effects', () => {
  for (const key of ['alive', 'visible', 'requestId']) {
    const harness = createHarness()
    if (key === 'requestId') harness.state.requestId = 10
    else harness.state[key] = false
    harness.controller.commit(harness.viewState, harness.context)
    assert.equal(harness.state.deferredHistory, undefined)
    assert.equal(harness.state.cumulativeRefresh, undefined)
    assert.equal(harness.state.distributionLoad, undefined)
    assert.equal(harness.state.initPieCallbacks.length, 0)
  }
})

test('skips pie and bar callbacks when the page dies, hides, or changes mode', () => {
  const dead = createHarness()
  dead.controller.commit(dead.viewState, dead.context)
  dead.state.alive = false
  fireLatestPieInit(dead.state)
  assert.deepEqual(dead.state.pieRenders, [])

  const hidden = createHarness()
  hidden.controller.commit(hidden.viewState, hidden.context)
  hidden.state.visible = false
  fireLatestPieInit(hidden.state)
  assert.deepEqual(hidden.state.pieRenders, [])

  const modeChanged = createHarness()
  modeChanged.controller.commit(modeChanged.viewState, modeChanged.context)
  modeChanged.state.chartMode = 'bar'
  fireLatestPieInit(modeChanged.state)
  assert.deepEqual(modeChanged.state.pieRenders, [])
})
