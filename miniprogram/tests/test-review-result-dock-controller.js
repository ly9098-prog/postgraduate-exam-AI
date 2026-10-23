const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createResultDockController,
} = require('../subpackages/study/review-today/utils/result-dock-controller')

function createHarness() {
  const state = {
    phase: 'group-result',
    remaining: 0,
    visible: false,
    alive: true,
    data: {},
    clearCount: 0,
    fadeTimer: null,
    requestedDelay: null,
  }
  const controller = createResultDockController({
    getPhase: () => state.phase,
    getTodayRemainingCount: () => state.remaining,
    getResultDockVisible: () => state.visible,
    setData: patch => {
      state.data = { ...state.data, ...patch }
      state.visible = patch.resultDockVisible !== undefined ? patch.resultDockVisible : state.visible
    },
    clearFadeTimer: () => {
      state.clearCount++
      state.fadeTimer = null
    },
    setFadeTimer: timer => { state.fadeTimer = timer },
    setTimeout: (callback, delay) => {
      state.fadeCallback = callback
      state.requestedDelay = delay
      return Symbol('fade-timer')
    },
    isPageAlive: () => state.alive,
    getFadeDelay: () => 5000,
  })
  return { controller, state }
}

test('shows the dock, clears old fade timers, and schedules hiding', () => {
  const { controller, state } = createHarness()
  assert.equal(controller.show(), true)

  assert.equal(state.visible, true)
  assert.equal(state.clearCount, 1)
  assert.deepEqual(state.data, { resultDockVisible: true })
  assert.equal(state.requestedDelay, 5000)
  assert.equal(typeof state.fadeCallback, 'function')

  state.fadeTimer = Symbol('old')
  assert.equal(controller.show(), true)
  assert.equal(state.clearCount, 2)
  assert.deepEqual(state.data, { resultDockVisible: true })
})

test('hides the dock after the fade when completion remains valid', () => {
  const { controller, state } = createHarness()
  controller.show()
  state.fadeCallback()

  assert.equal(state.visible, false)
  assert.deepEqual(state.data, { resultDockVisible: false })
})

test('rejects invalid phase and incomplete groups', () => {
  const reviewing = createHarness()
  reviewing.state.phase = 'reviewing'
  assert.equal(reviewing.controller.show(), false)

  const remaining = createHarness()
  remaining.state.remaining = 1
  assert.equal(remaining.controller.show(), false)

  assert.equal(reviewing.state.clearCount, 0)
  assert.equal(remaining.state.clearCount, 0)
})

test('keeps the dock visible when the fade fires after page or task changes', () => {
  const stale = createHarness()
  stale.controller.show()
  stale.state.alive = false
  stale.state.fadeCallback()
  assert.equal(stale.state.visible, true)

  const phaseChanged = createHarness()
  phaseChanged.controller.show()
  phaseChanged.state.phase = 'reviewing'
  phaseChanged.state.fadeCallback()
  assert.equal(phaseChanged.state.visible, true)

  const refilled = createHarness()
  refilled.controller.show()
  refilled.state.remaining = 1
  refilled.state.fadeCallback()
  assert.equal(refilled.state.visible, true)
})
