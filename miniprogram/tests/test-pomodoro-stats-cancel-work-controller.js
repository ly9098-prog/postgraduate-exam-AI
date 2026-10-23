const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCancelWorkController,
} = require('../subpackages/productivity/pomodoro-stats/cancel-work-controller')

function createHarness(overrides = {}) {
  const state = {
    dynamicRefreshCleared: false,
    durationResetStates: [],
    deferredHistoryClearPending: [],
    animActive: true,
    finalDrawn: true,
    requestId: 7,
    mainRafId: { name: 'main' },
    pieDateRafId: { name: 'pie-date' },
    pieLabelRafId: { name: 'pie-label' },
    barRafId: { name: 'bar' },
    pieCanvasNode: { cancelled: [] },
    trendCanvasNode: { cancelled: [] },
    pieAnimationToken: 1,
    pieLabelToken: 2,
    barAnimationToken: 3,
    animTimer: { name: 'anim' },
    clearedTimers: [],
  }
  const options = {
    clearDynamicRefresh: () => { state.dynamicRefreshCleared = true },
    cancelDurationAnimation: resetState => { state.durationResetStates.push(resetState) },
    cancelDeferredHistory: clearPending => { state.deferredHistoryClearPending.push(clearPending) },
    setAnimActive: value => { state.animActive = value },
    setFinalDrawn: value => { state.finalDrawn = value },
    incrementRequestId: () => { state.requestId += 1 },
    getMainRafId: () => state.mainRafId,
    getPieDateRafId: () => state.pieDateRafId,
    getPieLabelRafId: () => state.pieLabelRafId,
    getBarRafId: () => state.barRafId,
    getPieCanvasNode: () => state.pieCanvasNode,
    getTrendCanvasNode: () => state.trendCanvasNode,
    cancelFrame: (id, node) => { node.cancelled.push(id) },
    setMainRafId: id => { state.mainRafId = id },
    setPieDateRafId: id => { state.pieDateRafId = id },
    setPieLabelRafId: id => { state.pieLabelRafId = id },
    setBarRafId: id => { state.barRafId = id },
    incrementPieAnimationToken: () => { state.pieAnimationToken += 1 },
    incrementPieLabelToken: () => { state.pieLabelToken += 1 },
    incrementBarAnimationToken: () => { state.barAnimationToken += 1 },
    clearAnimTimer: () => {
      if (state.animTimer) {
        state.clearedTimers.push(state.animTimer)
        state.animTimer = null
      }
    },
    ...overrides,
  }
  return { controller: createCancelWorkController(options), options, state }
}

test('cancels all animation state and invalidates pending work', () => {
  const harness = createHarness()
  harness.controller.cancel()

  assert.equal(harness.state.dynamicRefreshCleared, true)
  assert.deepEqual(harness.state.durationResetStates, [false])
  assert.deepEqual(harness.state.deferredHistoryClearPending, [true])
  assert.equal(harness.state.animActive, false)
  assert.equal(harness.state.finalDrawn, false)
  assert.equal(harness.state.requestId, 8)
  assert.deepEqual(harness.state.pieCanvasNode.cancelled, [
    { name: 'main' },
    { name: 'pie-date' },
    { name: 'pie-label' },
  ])
  assert.deepEqual(harness.state.trendCanvasNode.cancelled, [{ name: 'bar' }])
  assert.equal(harness.state.mainRafId, null)
  assert.equal(harness.state.pieDateRafId, null)
  assert.equal(harness.state.pieLabelRafId, null)
  assert.equal(harness.state.barRafId, null)
  assert.equal(harness.state.pieAnimationToken, 2)
  assert.equal(harness.state.pieLabelToken, 3)
  assert.equal(harness.state.barAnimationToken, 4)
  assert.deepEqual(harness.state.clearedTimers, [{ name: 'anim' }])
  assert.equal(harness.state.animTimer, null)
})

test('skips frame cancellation for missing frames or canvas cancel support', () => {
  const harness = createHarness()
  harness.options.cancelFrame = (id, node) => {
    if (id && node && node.cancelAnimationFrame) node.cancelAnimationFrame(id)
  }
  harness.state.pieCanvasNode = {}
  harness.state.trendCanvasNode = {
    cancelled: [],
    cancelAnimationFrame(id) { this.cancelled.push(id) },
  }
  harness.controller.cancel()

  assert.deepEqual(harness.state.trendCanvasNode.cancelled, [{ name: 'bar' }])
  assert.deepEqual(harness.state.pieCanvasNode, {})
  assert.equal(harness.state.mainRafId, null)
})

test('keeps a missing animation timer untouched except for the clear request', () => {
  const harness = createHarness()
  let clearCalls = 0
  harness.state.animTimer = null
  harness.options.clearAnimTimer = () => { clearCalls += 1 }
  harness.controller.cancel()

  assert.equal(clearCalls, 1)
  assert.deepEqual(harness.state.clearedTimers, [])
})
