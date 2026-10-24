const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamTimerController,
} = require('../subpackages/exam/utils/exam-timer-controller')

function harness(overrides = {}) {
  const state = {
    now: 1000,
    baseRemaining: null,
    startedAt: 0,
    timer: null,
    intervalId: 1,
    views: [],
    pageAlive: true,
    attemptTerminal: false,
    terminalNavigation: false,
    timeExpired: false,
    remainingText: '',
    expired: false,
  }
  const options = {
    now: () => state.now,
    formatClock: seconds => `clock-${seconds}`,
    isPageAlive: () => state.pageAlive,
    isAttemptTerminal: () => state.attemptTerminal,
    isTerminalNavigation: () => state.terminalNavigation,
    isTimeExpired: () => state.timeExpired,
    getRemainingText: () => state.remainingText,
    setData: patch => { state.views.push(patch); Object.assign(state, patch) },
    getBaseRemaining: () => state.baseRemaining,
    setBaseRemaining: value => { state.baseRemaining = value },
    getStartedAt: () => state.startedAt,
    setStartedAt: value => { state.startedAt = value },
    getTimer: () => state.timer,
    setTimer: timer => { state.timer = timer },
    setInterval: callback => {
      state.interval = callback
      return state.intervalId
    },
    clearInterval: id => { state.cleared = id },
    onExpired: () => { state.expired = true },
    ...overrides,
  }
  return { options, state, get controller() { return createExamTimerController(options) } }
}

test('starts a countdown, updates text, and stores the interval', () => {
  const h = harness()
  h.controller.start(90)
  assert.equal(h.state.baseRemaining, 90)
  assert.equal(h.state.startedAt, 1000)
  assert.equal(h.state.timer, 1)
  assert.equal(h.state.remainingText, '剩余 clock-90')

  h.state.now = 2000
  h.controller.tick()
  assert.equal(h.state.remainingText, '剩余 clock-89')
  assert.equal(h.state.views.length, 2)
})

test('unlimited exams only set the unlimited label and create no interval', () => {
  const h = harness()
  h.controller.start(null)
  assert.equal(h.state.baseRemaining, null)
  assert.equal(h.state.timer, null)
  assert.deepEqual(h.state.views, [{ remainingText: '不限时' }])
  h.controller.tick()
  assert.equal(h.state.views.length, 1)
})

test('expiry clears the timer, freezes input, and triggers auto submit', () => {
  const h = harness()
  h.controller.start(10)
  assert.equal(h.state.cleared, undefined)
  h.state.now = 11000
  h.controller.tick()
  assert.equal(h.state.cleared, 1)
  assert.equal(h.state.timer, null)
  assert.equal(h.state.timeExpired, true)
  assert.equal(h.state.remainingText, '已到时 · 正在交卷')
  assert.equal(h.state.expired, true)

  h.state.now = 6000
  h.controller.tick()
  assert.equal(h.state.views.length, 3)
  assert.equal(h.state.expired, true)
})

test('terminal and detached states stop ticking without side effects', () => {
  const detached = harness()
  detached.state.pageAlive = false
  detached.controller.start(10)
  detached.state.now = 5000
  detached.controller.tick()
  assert.equal(detached.state.timeExpired, false)
  assert.equal(detached.state.expired, false)

  const terminal = harness()
  terminal.state.attemptTerminal = true
  terminal.controller.start(10)
  terminal.state.now = 5000
  terminal.controller.tick()
  assert.equal(terminal.state.expired, false)
})
