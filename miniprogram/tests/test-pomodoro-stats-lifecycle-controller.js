const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLifecycleController,
} = require('../subpackages/productivity/pomodoro-stats/lifecycle-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: false,
    viewReady: false,
    requestId: 0,
  }
  const calls = []
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    isViewReady: () => state.viewReady,
    setVisible: value => {
      state.visible = value
      calls.push(['setVisible', value])
    },
    setViewReady: () => {
      state.viewReady = true
      calls.push(['setViewReady'])
    },
    setAlive: value => {
      state.alive = value
      calls.push(['setAlive', value])
    },
    incrementRequestId: () => {
      state.requestId += 1
      calls.push(['incrementRequestId'])
    },
    syncTheme: () => calls.push(['syncTheme']),
    loadData: () => calls.push(['loadData']),
    scheduleDynamicRefresh: () => calls.push(['scheduleDynamicRefresh']),
    clearDynamicRefresh: () => calls.push(['clearDynamicRefresh']),
    cancelDurationAnimation: resetState => calls.push(['cancelDurationAnimation', resetState]),
    cancelDeferredHistory: clearPending => calls.push(['cancelDeferredHistory', clearPending]),
    cancelPendingWork: () => calls.push(['cancelPendingWork']),
    initCanvases: callback => {
      calls.push(['initCanvases'])
      if (callback) callback()
    },
    nextTick: callback => {
      calls.push(['nextTick'])
      callback()
    },
    ...overrides,
  }
  return { controller: createLifecycleController(options), options, state, calls }
}

test('show restores visibility and refreshes after the view is ready', () => {
  const harness = createHarness()
  harness.state.viewReady = true
  harness.controller.show()

  assert.deepEqual(harness.calls, [
    ['setVisible', true],
    ['syncTheme'],
    ['incrementRequestId'],
    ['loadData'],
    ['scheduleDynamicRefresh'],
  ])
  assert.equal(harness.state.requestId, 1)
})

test('show only restores visibility before the view is ready', () => {
  const harness = createHarness()
  harness.controller.show()

  assert.deepEqual(harness.calls, [['setVisible', true], ['syncTheme']])
  assert.equal(harness.state.requestId, 0)
})

test('ready initializes the view, refreshes data and warms canvases', () => {
  const harness = createHarness()
  harness.controller.ready()

  assert.deepEqual(harness.calls, [
    ['setViewReady'],
    ['setVisible', true],
    ['incrementRequestId'],
    ['loadData'],
    ['scheduleDynamicRefresh'],
    ['nextTick'],
    ['initCanvases'],
  ])
  assert.equal(harness.state.viewReady, true)
  assert.equal(harness.state.visible, true)
  assert.equal(harness.state.requestId, 1)
})

test('ready skips canvas warming after the page dies or hides', () => {
  const dead = createHarness()
  dead.controller.ready()
  dead.state.alive = false
  let warmed = false
  dead.options.initCanvases = () => { warmed = true }
  dead.options.nextTick = callback => callback()
  dead.controller.ready()
  assert.equal(warmed, false)

  const hidden = createHarness()
  let hiddenWarmed = false
  hidden.options.setVisible = value => {
    hidden.state.visible = value && hidden.state.visible
    hidden.calls.push(['setVisible', value])
  }
  hidden.options.initCanvases = () => { hiddenWarmed = true }
  hidden.options.nextTick = callback => callback()
  hidden.controller.ready()
  assert.equal(hiddenWarmed, false)
})

test('hide clears background work and animation state', () => {
  const harness = createHarness()
  harness.controller.hide()

  assert.deepEqual(harness.calls, [
    ['setVisible', false],
    ['clearDynamicRefresh'],
    ['cancelDurationAnimation', false],
    ['cancelDeferredHistory', true],
  ])
  assert.equal(harness.state.visible, false)
})

test('unload marks the page dead and cancels all pending work', () => {
  const harness = createHarness()
  harness.controller.unload()

  assert.deepEqual(harness.calls, [
    ['setAlive', false],
    ['setVisible', false],
    ['cancelPendingWork'],
  ])
  assert.equal(harness.state.alive, false)
  assert.equal(harness.state.visible, false)
})
