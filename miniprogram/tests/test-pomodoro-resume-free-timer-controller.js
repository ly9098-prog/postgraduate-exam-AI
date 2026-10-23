const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createResumeFreeTimerController } = require('../pages/pomodoro/utils/resume-free-timer-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const options = {
    getSessionId: () => overrides.sessionId ?? 's1',
    isActionLoading: () => overrides.actionLoading ?? false,
    now: () => 100000,
    getPauseStartTime: () => overrides.pauseStartTime ?? 95000,
    getTotalPausedMs: () => overrides.totalPausedMs ?? 3000,
    setPendingSync: () => { calls.push(['setPendingSync']); return overrides.setPendingSyncResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    safeSetStorage: (k, v) => { calls.push(['safeSetStorage', k]) },
    safeRemoveStorage: k => { calls.push(['safeRemoveStorage', k]) },
    setTimerFields: () => { calls.push(['setTimerFields']) },
    setData: () => { calls.push(['setData']) },
    startFreeTimerInterval: () => { calls.push(['startFreeTimerInterval']) },
    retryPendingSync: () => { calls.push(['retryPendingSync']); return Promise.resolve(true) },
    showToast: () => { calls.push(['showToast']) },
  }
  return { options, calls }
}

test('resume free returns early when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createResumeFreeTimerController(h.options).resume()
  assert.equal(h.calls.length, 0)
})

test('resume free shows error when setPendingSync fails', () => {
  const h = makeHarness({ setPendingSyncResult: false })
  createResumeFreeTimerController(h.options).resume()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('resume free persists adjustment, removes pause, starts interval, and retries', () => {
  const h = makeHarness()
  createResumeFreeTimerController(h.options).resume()
  assert.ok(h.calls.some(c => c[0] === 'safeSetStorage' && c[1] === 'pomodoro_pause_adjustment'))
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_free_pause'))
  assert.ok(h.calls.some(c => c[0] === 'startFreeTimerInterval'))
  assert.ok(h.calls.some(c => c[0] === 'retryPendingSync'))
})
