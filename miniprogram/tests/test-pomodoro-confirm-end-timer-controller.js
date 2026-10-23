const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createConfirmEndTimerController } = require('../pages/pomodoro/utils/confirm-end-timer-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const options = {
    isActionLoading: () => overrides.actionLoading ?? false,
    getEndConfirmMode: () => overrides.mode ?? 'free-complete',
    confirmEndFreeTimer: () => { calls.push(['confirmEndFreeTimer']) },
    confirmInterruptCountdown: () => { calls.push(['confirmInterruptCountdown']) },
    warn: () => { calls.push(['warn']) },
    getSessionId: () => overrides.sessionId ?? 's1',
    getSnapshotMode: () => overrides.snapshotMode ?? null,
    showToast: () => { calls.push(['showToast']) },
  }
  return { options, calls }
}

test('confirm returns early when actionLoading', () => {
  const h = makeHarness({ actionLoading: true })
  createConfirmEndTimerController(h.options).confirm()
  assert.equal(h.calls.length, 0)
})

test('confirm dispatches to free timer for free-complete mode', () => {
  const h = makeHarness({ mode: 'free-complete' })
  createConfirmEndTimerController(h.options).confirm()
  assert.ok(h.calls.some(c => c[0] === 'confirmEndFreeTimer'))
})

test('confirm dispatches to interrupt countdown for countdown-interrupt mode', () => {
  const h = makeHarness({ mode: 'countdown-interrupt' })
  createConfirmEndTimerController(h.options).confirm()
  assert.ok(h.calls.some(c => c[0] === 'confirmInterruptCountdown'))
})

test('confirm shows error toast for invalid mode', () => {
  const h = makeHarness({ mode: 'invalid' })
  createConfirmEndTimerController(h.options).confirm()
  assert.ok(h.calls.some(c => c[0] === 'warn'))
  assert.ok(h.calls.some(c => c[0] === 'showToast'))
})
