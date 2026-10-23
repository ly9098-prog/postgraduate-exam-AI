const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDynamicRefreshController,
} = require('../subpackages/productivity/pomodoro-stats/dynamic-refresh-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    viewReady: true,
    timer: null,
    defaultDelayMs: 30000,
    statsLoadInFlight: 0,
    cumulativeLoading: false,
    requestIds: [7],
    timers: [],
    loads: [],
    reschedules: [],
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    isViewReady: () => state.viewReady,
    getTimer: () => state.timer,
    setTimer: timer => { state.timer = timer },
    clearTimeout: timer => { state.cleared = timer },
    setTimeout: (callback, delay) => {
      const timer = { callback, delay }
      state.timers.push(timer)
      state.timer = timer
      return timer
    },
    getDefaultDelayMs: () => state.defaultDelayMs,
    getStatsLoadInFlight: () => state.statsLoadInFlight,
    isCumulativeLoading: () => state.cumulativeLoading,
    incrementRequestId: () => { state.requestIds.push(state.requestIds.at(-1) + 1) },
    loadBackground: async () => { state.loads.push('background') },
    schedule: delay => { state.reschedules.push(delay) },
    ...overrides,
  }
  return { controller: createDynamicRefreshController(options), options, state }
}

test('schedules a background refresh and always reschedules after completion', async () => {
  const harness = createHarness()
  harness.controller.schedule()

  assert.equal(harness.state.timers.length, 1)
  assert.equal(harness.state.timers[0].delay, 30000)
  await harness.state.timers[0].callback()
  assert.deepEqual(harness.state.loads, ['background'])
  assert.deepEqual(harness.state.reschedules, [undefined])
  assert.equal(harness.state.requestIds.at(-1), 8)
})

test('clamps custom delays to at least one second', () => {
  const harness = createHarness()
  harness.state.defaultDelayMs = 500
  harness.controller.schedule()
  assert.equal(harness.state.timers[0].delay, 1000)

  harness.controller.schedule(5000)
  assert.equal(harness.state.timers[1].delay, 5000)
})

test('skips scheduling when the page is dead, hidden, or not ready', () => {
  const dead = createHarness()
  dead.state.alive = false
  dead.controller.schedule()
  assert.equal(dead.state.timers.length, 0)

  const hidden = createHarness()
  hidden.state.visible = false
  hidden.controller.schedule()
  assert.equal(hidden.state.timers.length, 0)

  const notReady = createHarness()
  notReady.state.viewReady = false
  notReady.controller.schedule()
  assert.equal(notReady.state.timers.length, 0)
})

test('defers refresh while another load or cumulative refresh is running', async () => {
  const harness = createHarness()
  harness.state.statsLoadInFlight = 1
  harness.controller.schedule()
  await harness.state.timers[0].callback()

  assert.deepEqual(harness.state.loads, [])
  assert.deepEqual(harness.state.reschedules, [3000])

  const cumulative = createHarness()
  cumulative.state.cumulativeLoading = true
  cumulative.controller.schedule()
  await cumulative.state.timers[0].callback()
  assert.deepEqual(cumulative.state.loads, [])
})

test('does not load or reschedule after the page becomes unusable', async () => {
  const harness = createHarness()
  harness.controller.schedule()
  harness.state.alive = false
  await harness.state.timers[0].callback()

  assert.deepEqual(harness.state.loads, [])
  assert.deepEqual(harness.state.reschedules, [])
})

test('cancel clears only an existing timer', () => {
  const harness = createHarness()
  harness.controller.cancel()
  assert.equal(harness.state.cleared, undefined)

  harness.controller.schedule()
  const timer = harness.state.timer
  harness.controller.cancel()
  assert.equal(harness.state.cleared, timer)
  assert.equal(harness.state.timer, null)
})
