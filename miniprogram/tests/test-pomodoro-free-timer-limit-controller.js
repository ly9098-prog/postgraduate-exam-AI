const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createFreeTimerLimitController } = require('../pages/pomodoro/utils/free-timer-limit-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let finalizing = overrides.finalizing ?? false
  const options = {
    finalizing: () => finalizing,
    setFinalizing: value => { finalizing = value },
    autoFinish: () => { calls.push(['autoFinish']) },
    isFreeTimer: () => overrides.isFreeTimer ?? true,
    isPaused: () => overrides.isPaused ?? false,
    getEffectiveFreeElapsedMs: () => overrides.effectiveMs ?? 0,
    maxMs: () => overrides.maxMs ?? 18000000,
    clearFreeTimerInterval: () => { calls.push(['clearFreeTimerInterval']) },
    formatElapsedSec: sec => ({ display: `${sec}s`, friendly: `${sec} seconds` }),
    setElapsedSec: sec => { calls.push(['setElapsedSec', sec]) },
    setData: data => { calls.push(['setData', data]) },
    showToast: toast => { calls.push(['showToast', toast.title]) },
    getSessionId: () => overrides.sessionId ?? 's1',
    now: () => 100000,
    completeWithRetry: () => { calls.push(['completeWithRetry']); return Promise.resolve(overrides.synced ?? true) },
    consumeTerminalConflict: () => { calls.push(['consumeTerminalConflict']); return overrides.conflict ?? null },
    handleTerminalConflict: () => { calls.push(['handleTerminalConflict']) },
    loadTodayStats: () => { calls.push(['loadTodayStats']) },
    resetToIdle: () => { calls.push(['resetToIdle']) },
  }
  return { options, calls, get finalizing() { return finalizing } }
}

test('check returns false when not free timer', () => {
  const h = makeHarness({ isFreeTimer: false })
  assert.equal(createFreeTimerLimitController(h.options).check(), false)
  assert.equal(h.calls.length, 0)
})

test('check returns false when paused or already finalizing', () => {
  const paused = makeHarness({ isPaused: true })
  assert.equal(createFreeTimerLimitController(paused.options).check(), false)
  const finalizing = makeHarness({ finalizing: true })
  assert.equal(createFreeTimerLimitController(finalizing.options).check(), false)
})

test('check triggers auto finish at the limit and returns true', () => {
  const h = makeHarness({ effectiveMs: 18000000 })
  assert.equal(createFreeTimerLimitController(h.options).check(), true)
  assert.ok(h.calls.some(c => c[0] === 'autoFinish'))
})

test('auto finish fixes elapsed and clears interval', async () => {
  const h = makeHarness()
  await createFreeTimerLimitController(h.options).autoFinish()
  assert.ok(h.calls.some(c => c[0] === 'clearFreeTimerInterval'))
  assert.ok(h.calls.some(c => c[0] === 'setElapsedSec' && c[1] === 18000))
  assert.ok(h.calls.some(c => c[0] === 'showToast' && c[1].includes('5小时上限')))
})

test('auto finish ignores reentry while finalizing', async () => {
  const h = makeHarness({ finalizing: true })
  await createFreeTimerLimitController(h.options).autoFinish()
  assert.equal(h.calls.length, 0)
})

test('complete uses retryable completion, clears interval, and resets idle', async () => {
  const h = makeHarness()
  createFreeTimerLimitController(h.options).complete()
  await new Promise(resolve => setTimeout(resolve, 20))
  assert.ok(h.calls.some(c => c[0] === 'completeWithRetry'))
  assert.ok(h.calls.some(c => c[0] === 'resetToIdle'))
  assert.ok(h.calls.some(c => c[0] === 'loadTodayStats'))
})

test('complete returns early without a session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createFreeTimerLimitController(h.options).complete()
  assert.equal(h.calls.length, 0)
})
