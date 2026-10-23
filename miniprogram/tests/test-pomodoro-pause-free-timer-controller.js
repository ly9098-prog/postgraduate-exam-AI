const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createPauseFreeTimerController } = require('../pages/pomodoro/utils/pause-free-timer-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let timerState = { pauseStartTime: null, freeFriendlyText: null }
  const options = {
    getSessionId: () => overrides.sessionId ?? 's1',
    isActionLoading: () => overrides.actionLoading ?? false,
    now: () => 100000,
    setPendingSync: () => { calls.push(['setPendingSync']); return overrides.setPendingSyncResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    updateFreeElapsed: () => { calls.push(['updateFreeElapsed']) },
    clearFreeTimerInterval: () => { calls.push(['clearFreeTimerInterval']) },
    setTimerFields: patch => { Object.assign(timerState, patch) },
    setData: () => { calls.push(['setData']) },
    getElapsedSec: () => overrides.elapsedSec ?? 120,
    getTotalPausedMs: () => overrides.totalPausedMs ?? 5000,
    safeSetStorage: (k, v) => { calls.push(['safeSetStorage', k]) },
    retryPendingSync: () => { calls.push(['retryPendingSync']); return Promise.resolve(true) },
    showToast: () => { calls.push(['showToast']) },
  }
  return { options, calls, get timerState() { return timerState } }
}

test('pause free returns early when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createPauseFreeTimerController(h.options).pause()
  assert.equal(h.calls.length, 0)
})

test('pause free shows error when setPendingSync fails', () => {
  const h = makeHarness({ setPendingSyncResult: false })
  createPauseFreeTimerController(h.options).pause()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('pause free updates elapsed, clears interval, persists, and retries', () => {
  const h = makeHarness()
  createPauseFreeTimerController(h.options).pause()
  assert.ok(h.calls.some(c => c[0] === 'updateFreeElapsed'))
  assert.ok(h.calls.some(c => c[0] === 'clearFreeTimerInterval'))
  assert.ok(h.calls.some(c => c[0] === 'safeSetStorage' && c[1] === 'pomodoro_free_pause'))
  assert.ok(h.calls.some(c => c[0] === 'retryPendingSync'))
})
