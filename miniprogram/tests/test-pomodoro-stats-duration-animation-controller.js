const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDurationAnimationController,
} = require('../subpackages/productivity/pomodoro-stats/duration-animation-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    token: 0,
    timer: null,
    timeoutSeq: 0,
    displayDurationSec: null,
    displaySessions: 0,
    data: [],
    timers: [],
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getToken: () => state.token,
    incrementToken: () => { state.token += 1 },
    getTimer: () => state.timer,
    setTimer: timer => { state.timer = timer },
    clearTimeout: timer => { state.timers.push(['clear', timer]) },
    setTimeout: (callback, delay) => {
      const handle = { callback, delay, seq: ++state.timeoutSeq }
      state.timers.push(['set', handle])
      state.timer = handle
      return handle
    },
    getDisplaySessions: () => state.displaySessions,
    setDisplayDurationSec: value => { state.displayDurationSec = value },
    getDurationDisplayPatch: text => ({
      _dispTodayDurationText: text,
      _dispTodayDurationSegments: [{ type: 'num', text }],
    }),
    setData: patch => { state.data.push(patch) },
    ...overrides,
  }
  return { controller: createDurationAnimationController(options), options, state }
}

function flushTimers(state) {
  for (let timer = takeTimer(state); timer; timer = takeTimer(state)) timer.callback()
}

function takeTimer(state) {
  const timer = state.timer
  state.timer = null
  return timer
}

test('cancel invalidates the old timer and optionally resets view state', () => {
  const h = createHarness()
  h.controller.animate(0, 600, 0, 1)
  const oldTimer = h.state.timer
  h.controller.cancel(true)

  assert.equal(h.state.token, 2)
  assert.ok(h.state.timers.some(entry => entry[0] === 'clear' && entry[1] === oldTimer))
  assert.equal(h.state.timer, null)
  assert.deepEqual(h.state.data.at(-1), { durationValueAnimating: false })
})

test('equal formatted values commit immediately without animation', () => {
  const h = createHarness()
  h.controller.animate(60, 61, 2, 2)

  assert.equal(h.state.displayDurationSec, 61)
  assert.deepEqual(h.state.data, [{
    _dispTodaySessions: 2,
    _dispTodayDurationText: '1分钟',
    _dispTodayDurationSegments: [{ type: 'num', text: '1分钟' }],
    durationValueAnimating: false,
  }])
  assert.equal(h.state.timer, null)
})

test('animation ends at the target and updates only changed display ticks', () => {
  const h = createHarness()
  h.controller.animate(0, 1200, 1, 3)
  flushTimers(h.state)

  assert.equal(h.state.displayDurationSec, 1200)
  assert.equal(h.state.data[0].durationValueAnimating, true)
  assert.equal(h.state.data.at(-1).durationValueAnimating, false)
  assert.equal(h.state.data.at(-1)._dispTodaySessions, 3)
  assert.equal(h.state.data.at(-1)._dispTodayDurationText, '20分钟')
  assert.equal(h.state.timer, null)
  assert.equal(h.state.data.length, 13)
})

test('late ticks are ignored after token cancellation', () => {
  const h = createHarness()
  h.controller.animate(0, 600, 0, 1)
  const first = takeTimer(h.state)
  h.controller.cancel(false)
  const dataCount = h.state.data.length
  first.callback()

  assert.equal(h.state.data.length, dataCount)
  assert.equal(h.state.timer, null)
})

test('hidden or dead pages stop future ticks', () => {
  const hidden = createHarness()
  hidden.controller.animate(0, 600, 0, 1)
  hidden.state.visible = false
  const before = hidden.state.data.length
  takeTimer(hidden.state).callback()

  assert.equal(hidden.state.data.length, before)
  assert.equal(hidden.state.timer, null)

  const dead = createHarness()
  dead.controller.animate(0, 600, 0, 1)
  dead.state.alive = false
  takeTimer(dead.state).callback()
  assert.equal(dead.state.timer, null)
})
