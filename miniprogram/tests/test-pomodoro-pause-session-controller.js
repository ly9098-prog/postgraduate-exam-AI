const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createPauseSessionController } = require('../pages/pomodoro/utils/pause-session-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const options = {
    getSessionId: () => overrides.sessionId ?? 's1',
    isActionLoading: () => overrides.actionLoading ?? false,
    now: () => overrides.now ?? 100000,
    setPendingSync: () => { calls.push(['setPendingSync']); return overrides.setPendingSyncResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    clearTimer: () => { calls.push(['clearTimer']) },
    setPauseStartTime: v => { calls.push(['setPauseStartTime', v]) },
    setData: d => { calls.push(['setData']) },
    getTotalPausedMs: () => overrides.totalPausedMs ?? 5000,
    safeSetStorage: (k, v) => { calls.push(['safeSetStorage', k]) },
    retryPendingSync: () => { calls.push(['retryPendingSync']); return Promise.resolve(true) },
    showToast: () => { calls.push(['showToast']) },
  }
  return { options, calls }
}

test('pause returns early when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createPauseSessionController(h.options).pause()
  assert.equal(h.calls.length, 0)
})

test('pause shows error when setPendingSync fails', () => {
  const h = makeHarness({ setPendingSyncResult: false })
  createPauseSessionController(h.options).pause()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('pause clears timer, sets paused, persists, and retries', () => {
  const h = makeHarness()
  createPauseSessionController(h.options).pause()
  assert.ok(h.calls.some(c => c[0] === 'clearTimer'))
  assert.ok(h.calls.some(c => c[0] === 'safeSetStorage' && c[1] === 'pomodoro_pause'))
  assert.ok(h.calls.some(c => c[0] === 'retryPendingSync'))
})
