/**
 * Independent regression for the confirm-interrupt-countdown controller.
 * Run: node --test miniprogram/tests/test-pomodoro-confirm-interrupt-countdown-controller.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createConfirmInterruptCountdownController } = require('../pages/pomodoro/utils/confirm-interrupt-countdown-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let confirmSnapshot = overrides._confirmTimerSnapshot ?? null
  let totalPausedMs = overrides.totalPausedMs ?? 5000
  let confirmActionSeq = 0
  const timerState = { sessionId: overrides.sessionId ?? 's1' }
  const data = { actionLoading: overrides.actionLoading ?? false }

  const options = {
    getSessionId: () => timerState.sessionId,
    isActionLoading: () => data.actionLoading,
    getConfirmTimerSnapshot: () => confirmSnapshot,
    getTotalPausedMs: () => totalPausedMs,
    setTotalPausedMs: v => { totalPausedMs = v },
    now: () => overrides.now ?? 100000,
    incrementConfirmActionSeq: () => { confirmActionSeq++ },
    setPendingSync: (action, sid, now) => { calls.push(['setPendingSync', action]); return overrides.setPendingSyncResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    setData: d => { calls.push(['setData']) },
    retryPendingSync: () => { calls.push(['retryPendingSync']); return Promise.resolve(overrides.retryPendingResult ?? true) },
    consumeTerminalConflict: (sid, action) => { calls.push(['consumeTerminalConflict']); return overrides.conflict ?? null },
    handleTerminalConflict: (sid, conflict) => { calls.push(['handleTerminalConflict']) },
    showToast: toast => { calls.push(['showToast', toast.title]) },
    loadTodayStats: () => { calls.push(['loadTodayStats']) },
    safeRemoveStorage: key => { calls.push(['safeRemoveStorage', key]) },
    setConfirmTimerSnapshot: v => { confirmSnapshot = v },
    resetToIdle: () => { calls.push(['resetToIdle']) },
  }
  return { options, calls, get confirmActionSeq() { return confirmActionSeq },
    get totalPausedMs() { return totalPausedMs }, get confirmSnapshot() { return confirmSnapshot } }
}

test('confirm returns early when no session id', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  const ctrl = createConfirmInterruptCountdownController(h.options)
  ctrl.confirm()
  assert.equal(h.calls.length, 0)
})

test('confirm returns early when actionLoading', () => {
  const h = makeHarness({ actionLoading: true })
  const ctrl = createConfirmInterruptCountdownController(h.options)
  ctrl.confirm()
  assert.equal(h.calls.length, 0)
})

test('confirm accumulates pause from snapshot openedAt', () => {
  const h = makeHarness({
    _confirmTimerSnapshot: { openedAt: 95000, totalPausedMs: 3000 },
    totalPausedMs: 3000,
    now: 100000,
  })
  const ctrl = createConfirmInterruptCountdownController(h.options)
  ctrl.confirm()
  // totalPausedMs = max(0, 3000 + (100000 - 95000)) = 8000
  assert.equal(h.totalPausedMs, 8000)
})

test('confirm shows error and returns when setPendingSync fails', () => {
  const h = makeHarness({ setPendingSyncResult: false })
  const ctrl = createConfirmInterruptCountdownController(h.options)
  ctrl.confirm()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
  assert.ok(h.calls.some(c => c[0] === 'setData'))
  assert.ok(!h.calls.some(c => c[0] === 'resetToIdle'))
})

test('confirm cleans up storage, resets to idle, and shows toast on success', () => {
  const h = makeHarness()
  const ctrl = createConfirmInterruptCountdownController(h.options)
  ctrl.confirm()
  assert.ok(h.calls.some(c => c[0] === 'showToast' && c[1] === '已结束本次专注'))
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_pause_adjustment'))
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_confirm_pause'))
  assert.ok(h.calls.some(c => c[0] === 'resetToIdle'))
  assert.equal(h.confirmSnapshot, null)
})
