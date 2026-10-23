const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createResumeSessionController } = require('../pages/pomodoro/utils/resume-session-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const timerState = {
    sessionStartTime: overrides.sessionStartTime ?? 90000,
    sessionId: overrides.sessionId ?? 's1',
    pauseStartTime: overrides.pauseStartTime ?? 95000,
    totalPausedMs: overrides.totalPausedMs ?? 3000,
  }
  const options = {
    getSessionStartTime: () => timerState.sessionStartTime,
    warn: () => { calls.push(['warn']) },
    resetToIdle: () => { calls.push(['resetToIdle']) },
    getSessionId: () => timerState.sessionId,
    isActionLoading: () => overrides.actionLoading ?? false,
    now: () => overrides.now ?? 100000,
    getPauseStartTime: () => timerState.pauseStartTime,
    getTotalPausedMs: () => timerState.totalPausedMs,
    isDebugPreset: () => overrides.debug ?? false,
    getWorkDurationMinutes: () => overrides.workDuration ?? 25,
    setPendingSync: () => { calls.push(['setPendingSync']); return overrides.setPendingSyncResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    safeSetStorage: (k, v) => { calls.push(['safeSetStorage', k]) },
    safeRemoveStorage: k => { calls.push(['safeRemoveStorage', k]) },
    setTimerFields: patch => { Object.assign(timerState, patch); calls.push(['setTimerFields']) },
    setData: d => { calls.push(['setData']) },
    startTimer: (totalSec, opts) => { calls.push(['startTimer', totalSec]) },
    retryPendingSync: () => { calls.push(['retryPendingSync']); return Promise.resolve(true) },
    showToast: () => { calls.push(['showToast']) },
  }
  return { options, calls, get timerState() { return timerState } }
}

test('resume resets to idle when sessionStartTime invalid', () => {
  const h = makeHarness({ sessionStartTime: 0 })
  createResumeSessionController(h.options).resume()
  assert.ok(h.calls.some(c => c[0] === 'resetToIdle'))
})

test('resume returns early when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createResumeSessionController(h.options).resume()
  assert.equal(h.calls.length, 0)
})

test('resume shows error when setPendingSync fails', () => {
  const h = makeHarness({ setPendingSyncResult: false })
  createResumeSessionController(h.options).resume()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('resume persists adjustment, removes pause, starts timer, and retries', () => {
  const h = makeHarness()
  createResumeSessionController(h.options).resume()
  assert.ok(h.calls.some(c => c[0] === 'safeSetStorage' && c[1] === 'pomodoro_pause_adjustment'))
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_pause'))
  assert.ok(h.calls.some(c => c[0] === 'startTimer'))
  assert.ok(h.calls.some(c => c[0] === 'retryPendingSync'))
})
