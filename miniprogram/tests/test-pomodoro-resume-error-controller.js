const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createResumeErrorController,
} = require('../pages/pomodoro/utils/resume-error-controller')

function createHarness(overrides = {}) {
  const calls = {
    toasts: [], resetIdle: 0, setData: [], startFree: 0, startTimer: [],
    removes: [], timer: { sessionStartTime: 0, totalPausedMs: 0, pauseStartTime: 1,
      elapsedSec: 0, remainingSec: 0, progress: 0 },
  }
  const options = {
    getActive: overrides.getActive || (async () => overrides.active || null),
    parseServerTime: () => overrides.serverStart || 1000,
    showToast: toast => calls.toasts.push(toast.title),
    resetIdle: () => { calls.resetIdle += 1 },
    timer: () => calls.timer,
    isFreeTimer: () => overrides.isFreeTimer || false,
    mergeLocalPauseAdjustment: (id, value) => overrides.mergeResult === undefined ? value : overrides.mergeResult,
    getEffectiveFreeElapsedMs: () => overrides.freeElapsedMs || 30000,
    formatElapsedSec: sec => ({ display: `d${sec}`, friendly: `f${sec}` }),
    setData: data => calls.setData.push(data),
    startFreeTimerInterval: () => { calls.startFree += 1 },
    removeStorage: (key, context) => calls.removes.push([key, context]),
    now: () => overrides.now || 100000,
    getCurrentTotalSec: () => overrides.totalSec || 1500,
    startTimer: totalSec => calls.startTimer.push(totalSec),
  }
  return { controller: createResumeErrorController(options), calls }
}

test('non-404 errors show a retry toast and do nothing else', async () => {
  const harness = createHarness()
  await harness.controller.reconcile({ code: 500 }, 5)
  assert.deepEqual(harness.calls.toasts, ['继续失败，请重试'])
  assert.equal(harness.calls.resetIdle, 0)
})

test('null error shows a retry toast', async () => {
  const harness = createHarness()
  await harness.controller.reconcile(null, 5)
  assert.deepEqual(harness.calls.toasts, ['继续失败，请重试'])
})

test('a vanished session resets to idle', async () => {
  const harness = createHarness({ active: null })
  await harness.controller.reconcile({ code: 404 }, 5)
  assert.deepEqual(harness.calls.toasts, ['当前专注已结束或失效'])
  assert.equal(harness.calls.resetIdle, 1)
})

test('a mismatched session id resets to idle', async () => {
  const harness = createHarness({ active: { id: 99, status: 'running' } })
  await harness.controller.reconcile({ code: 404 }, 5)
  assert.deepEqual(harness.calls.toasts, ['当前专注已结束或失效'])
  assert.equal(harness.calls.resetIdle, 1)
})

test('a non-running server session shows a retry toast', async () => {
  const harness = createHarness({ active: { id: 5, status: 'paused' } })
  await harness.controller.reconcile({ code: 404 }, 5)
  assert.deepEqual(harness.calls.toasts, ['继续失败，请稍后重试'])
  assert.equal(harness.calls.resetIdle, 0)
})

test('a running free session is reconciled and the free interval restarted', async () => {
  const harness = createHarness({
    active: { id: 5, status: 'running', start_time: 'x', total_paused_sec: 3 },
    isFreeTimer: true,
  })
  await harness.controller.reconcile({ code: 404 }, 5)
  assert.equal(harness.calls.timer.sessionStartTime, 1000)
  assert.equal(harness.calls.timer.totalPausedMs, 3000)
  assert.equal(harness.calls.timer.pauseStartTime, null)
  assert.equal(harness.calls.startFree, 1)
  assert.deepEqual(harness.calls.removes, [['pomodoro_free_pause', 'best-effort cleanup']])
  assert.deepEqual(harness.calls.toasts, ['已恢复计时'])
})

test('a running countdown session is reconciled and the timer restarted', async () => {
  const harness = createHarness({
    active: { id: 5, status: 'running', start_time: 'x', total_paused_sec: 10 },
    isFreeTimer: false,
    now: 200000,
    totalSec: 1500,
  })
  await harness.controller.reconcile({ code: 404 }, 5)
  assert.equal(harness.calls.timer.sessionStartTime, 1000)
  assert.equal(harness.calls.timer.totalPausedMs, 10000)
  assert.equal(harness.calls.timer.pauseStartTime, null)
  assert.deepEqual(harness.calls.startTimer, [1500])
  assert.deepEqual(harness.calls.removes, [['pomodoro_pause', 'best-effort cleanup']])
  assert.deepEqual(harness.calls.toasts, ['已恢复计时'])
})

test('a network failure during active fetch shows a retry toast', async () => {
  const harness = createHarness({
    getActive: async () => { throw new Error('offline') },
  })
  await harness.controller.reconcile({ code: 404 }, 5)
  assert.deepEqual(harness.calls.toasts, ['继续失败，请重试'])
})
