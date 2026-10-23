const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDateCommitController,
} = require('../subpackages/productivity/pomodoro-stats/date-commit-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    dateSeq: 6,
    showDayDistribution: true,
    chartMode: 'pie',
    pieReady: true,
    distributionPeriod: 'day',
    patches: [],
    initPieCallbacks: [],
  }

  const viewState = {
    selectedDurationSec: 600,
    selectedSessionCount: 4,
    previousDurationSec: 300,
    previousSessionCount: 2,
    subjectBreakdown: [{ duration_sec: 600 }],
    dataPatch: { pieLoading: false },
  }

  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getDateRequestSeq: () => state.dateSeq,
    setRawTodayDuration: value => { state.rawTodayDuration = value },
    setDaySubjectsRaw: value => { state.daySubjectsRaw = value },
    resetPieCache: () => { state.pieCacheReset = true },
    setData: (patch, callback) => {
      state.patches.push(patch)
      callback()
    },
    animateSelectedDuration: (fromSec, toSec, fromSessions, toSessions) => {
      state.durationAnimation = { fromSec, toSec, fromSessions, toSessions }
    },
    getDistributionPeriod: () => state.distributionPeriod,
    loadDistributionForPeriod: (period, animate) => {
      state.distributionLoad = { period, animate }
    },
    getChartMode: () => state.chartMode,
    isPieReady: () => state.pieReady,
    initCanvases: callback => state.initPieCallbacks.push(callback),
    animatePieOnly: () => { state.pieAnimation = true },
    ...overrides,
  }

  const context = { seq: state.dateSeq, showDayDistribution: state.showDayDistribution }
  const { pieReady = state.pieReady, ...controllerOverrides } = overrides
  const harness = {
    controller: createDateCommitController({ ...options, isPieReady: () => pieReady, ...controllerOverrides }),
    options,
    state,
    viewState,
    context,
  }
  return harness
}

test('commits date state and starts the duration and pie animations', () => {
  const harness = createHarness()
  harness.controller.commit(harness.viewState, harness.context)

  assert.equal(harness.state.rawTodayDuration, 600)
  assert.deepEqual(harness.state.daySubjectsRaw, [{ duration_sec: 600 }])
  assert.equal(harness.state.pieCacheReset, true)
  assert.deepEqual(harness.state.patches, [{ pieLoading: false }])
  assert.deepEqual(harness.state.durationAnimation, {
    fromSec: 300,
    toSec: 600,
    fromSessions: 2,
    toSessions: 4,
  })
  assert.equal(harness.state.pieAnimation, true)
  assert.equal(harness.state.initPieCallbacks.length, 0)
})

test('initializes a missing pie canvas before animating', () => {
  const harness = createHarness({ pieReady: false })
  harness.controller.commit(harness.viewState, harness.context)
  assert.equal(harness.state.pieAnimation, undefined) // Canvas callback has not run yet.

  harness.state.initPieCallbacks.at(-1)()
  assert.equal(harness.state.pieAnimation, true)
})

test('skips pie initialization callbacks when the page dies, hides, or leaves pie mode', () => {
  const dead = createHarness({ pieReady: false })
  dead.controller.commit(dead.viewState, dead.context)
  dead.state.alive = false
  dead.state.initPieCallbacks.at(-1)()
  assert.equal(dead.state.pieAnimation, undefined)

  const hidden = createHarness({ pieReady: false })
  hidden.controller.commit(hidden.viewState, hidden.context)
  hidden.state.visible = false
  hidden.state.initPieCallbacks.at(-1)()
  assert.equal(hidden.state.pieAnimation, undefined)

  const modeChanged = createHarness({ pieReady: false })
  modeChanged.controller.commit(modeChanged.viewState, modeChanged.context)
  modeChanged.state.chartMode = 'bar'
  modeChanged.state.initPieCallbacks.at(-1)()
  assert.equal(modeChanged.state.pieAnimation, undefined)
})

test('reloads non-day distributions and preserves their view state', () => {
  const harness = createHarness()
  harness.state.showDayDistribution = false
  harness.state.distributionPeriod = 'month'
  harness.context.showDayDistribution = false
  harness.controller.commit(harness.viewState, harness.context)

  assert.deepEqual(harness.state.distributionLoad, { period: 'month', animate: true })
  assert.equal(harness.state.pieCacheReset, undefined)
  assert.equal(harness.state.pieAnimation, undefined)
})

test('stops stale, dead, or hidden commits before side effects', () => {
  for (const key of ['alive', 'visible', 'dateSeq']) {
    const harness = createHarness()
    if (key === 'dateSeq') harness.state.dateSeq = 7
    else harness.state[key] = false
    harness.controller.commit(harness.viewState, harness.context)
    assert.equal(harness.state.durationAnimation, undefined)
    assert.equal(harness.state.distributionLoad, undefined)
    assert.equal(harness.state.pieAnimation, undefined)
    assert.equal(harness.state.initPieCallbacks.length, 0)
  }
})
