const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamReconnectController,
} = require('../subpackages/exam/utils/exam-reconnect-controller')

function createHarness(overrides = {}) {
  const state = {
    pageAlive: true,
    attemptLoaded: true,
    reconnectSyncing: false,
    attemptTerminal: false,
    terminalNavigation: false,
    timeExpired: false,
    submitting: false,
    ticks: 0,
    submits: [],
    flushes: [],
  }
  const controller = createExamReconnectController({
    isPageAlive: () => state.pageAlive,
    isAttemptLoaded: () => state.attemptLoaded,
    isReconnectSyncing: () => state.reconnectSyncing,
    isAttemptTerminal: () => state.attemptTerminal,
    isTerminalNavigation: () => state.terminalNavigation,
    setReconnectSyncing: value => { state.reconnectSyncing = value },
    tickTimer: () => { state.ticks += 1 },
    isTimeExpired: () => state.timeExpired,
    isSubmitting: () => state.submitting,
    submitExam: options => {
      state.submits.push(options)
      return Promise.resolve(true)
    },
    flushAllPending: options => {
      state.flushes.push(options)
      return Promise.resolve(true)
    },
    ...overrides,
  })
  return { controller, state }
}

test('reconnect flushes pending answers while the attempt is active', async () => {
  const { controller, state } = createHarness()

  await controller.recoverPending()

  assert.equal(state.ticks, 1)
  assert.deepEqual(state.flushes, [{ quiet: true }])
  assert.deepEqual(state.submits, [])
  assert.equal(state.reconnectSyncing, false)
})

test('reconnect auto-submits an expired attempt unless submission is already running', async () => {
  const { controller, state } = createHarness()
  state.timeExpired = true

  await controller.recoverPending()

  assert.equal(state.ticks, 1)
  assert.deepEqual(state.submits, [{ auto: true }])
  assert.deepEqual(state.flushes, [])
  assert.equal(state.reconnectSyncing, false)
})

test('reconnect does not duplicate a running submission', async () => {
  const { controller, state } = createHarness()
  state.timeExpired = true
  state.submitting = true

  await controller.recoverPending()

  assert.equal(state.ticks, 1)
  assert.deepEqual(state.submits, [])
  assert.deepEqual(state.flushes, [])
  assert.equal(state.reconnectSyncing, false)
})

test('reconnect is single-flight and blocked after page or attempt closure', async () => {
  const blocked = [
    { pageAlive: false },
    { attemptLoaded: false },
    { attemptTerminal: true },
    { terminalNavigation: true },
  ]
  for (const patch of blocked) {
    const { controller, state } = createHarness()
    Object.assign(state, patch)
    await controller.recoverPending()
    assert.equal(state.ticks, 0)
    assert.deepEqual(state.flushes, [])
    assert.equal(state.reconnectSyncing, false)
  }

  const { controller, state } = createHarness()
  state.reconnectSyncing = true
  await controller.recoverPending()
  assert.equal(state.ticks, 0)
  assert.deepEqual(state.flushes, [])
  assert.equal(state.reconnectSyncing, true)

  let releaseFlush
  const concurrent = createHarness({
    flushAllPending: options => new Promise(resolve => {
      concurrent.flushOptions = options
      releaseFlush = resolve
    }),
  })
  const first = concurrent.controller.recoverPending()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(concurrent.state.reconnectSyncing, true)
  const second = concurrent.controller.recoverPending()
  assert.equal(concurrent.state.ticks, 1)
  assert.equal(concurrent.state.flushes.length, 0)
  releaseFlush(true)
  assert.equal(await first, undefined)
  assert.equal(await second, undefined)
  assert.equal(concurrent.state.reconnectSyncing, false)
})

test('reconnect keeps pending and clears the busy flag after a flush failure', async () => {
  const { controller, state } = createHarness()
  const error = new Error('network unavailable')
  state.flushAllPending = () => Promise.reject(error)

  await controller.recoverPending()

  assert.equal(state.ticks, 1)
  assert.equal(state.reconnectSyncing, false)
})

test('reconnect keeps pending and clears the busy flag after auto-submit failure', async () => {
  const { controller, state } = createHarness()
  const error = new Error('submit unavailable')
  state.timeExpired = true
  state.submitExam = () => Promise.reject(error)

  await controller.recoverPending()

  assert.equal(state.ticks, 1)
  assert.deepEqual(state.flushes, [])
  assert.equal(state.reconnectSyncing, false)
})
