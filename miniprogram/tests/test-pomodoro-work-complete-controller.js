const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createWorkCompleteController,
} = require('../pages/pomodoro/utils/work-complete-controller')

function createHarness(overrides = {}) {
  const calls = { resetIdle: 0, clearTimer: 0, vibrate: 0, completeRetry: [], showCelebration: [], toasts: [], stats: 0 }
  const timer = overrides.timer || { sessionId: 5 }
  let resolveRetry
  const options = {
    timer: () => timer,
    resetIdle: () => { calls.resetIdle += 1 },
    now: () => overrides.now || 1000,
    clearTimer: () => { calls.clearTimer += 1 },
    vibrateLong: () => { calls.vibrate += 1 },
    completeWithRetry: (id, at) => { calls.completeRetry.push([id, at]); return new Promise(r => { resolveRetry = r }) },
    consumeTerminalConflict: () => overrides.conflict || null,
    handleTerminalConflict: (id, c) => { calls.handledConflict = [id, c] },
    loadStats: () => { calls.stats += 1 },
    showToast: toast => { calls.toasts.push(toast.title) },
    showCompletionCelebration: id => { calls.showCelebration.push(id) },
  }
  return { controller: createWorkCompleteController(options), calls, timer, resolve: v => resolveRetry(v) }
}

test('complete resets to idle when there is no session', async () => {
  const harness = createHarness({ timer: { sessionId: null } })
  await harness.controller.complete()
  assert.equal(harness.calls.resetIdle, 1)
  assert.equal(harness.calls.clearTimer, 0)
  assert.deepEqual(harness.calls.showCelebration, [])
})

test('complete vibrates, clears timer, shows celebration and syncs', async () => {
  const harness = createHarness()
  const p = harness.controller.complete()
  assert.equal(harness.calls.clearTimer, 1)
  assert.equal(harness.calls.vibrate, 1)
  assert.deepEqual(harness.calls.completeRetry, [[5, 1000]])
  assert.deepEqual(harness.calls.showCelebration, [5])
  harness.resolve(true)
  await p
  assert.equal(harness.calls.stats, 1)
})

test('complete shows a pending toast when sync fails', async () => {
  const harness = createHarness()
  const p = harness.controller.complete()
  harness.resolve(false)
  await p
  assert.deepEqual(harness.calls.toasts, ['已完成，网络恢复后自动同步'])
  assert.equal(harness.calls.stats, 0)
})

test('complete handles a terminal conflict instead of showing stats', async () => {
  const conflict = { sessionId: 5, requestedAction: 'complete' }
  const harness = createHarness({ conflict })
  const p = harness.controller.complete()
  harness.resolve(true)
  await p
  assert.deepEqual(harness.calls.handledConflict, [5, conflict])
  assert.equal(harness.calls.stats, 0)
})
