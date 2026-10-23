const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createConfirmEndFreeTimerController } = require('../pages/pomodoro/utils/confirm-end-free-timer-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const options = {
    isActionLoading: () => overrides.actionLoading ?? false,
    getSessionId: () => overrides.sessionId ?? 's1',
    incrementConfirmActionSeq: () => { calls.push(['incrementConfirmActionSeq']) },
    setConfirmTimerSnapshot: v => { calls.push(['setConfirmTimerSnapshot', v]) },
    safeRemoveStorage: k => { calls.push(['safeRemoveStorage', k]) },
    setData: d => { calls.push(['setData']) },
    clearFreeTimerInterval: () => { calls.push(['clearFreeTimerInterval']) },
    completeFreeTimerSession: () => { calls.push(['completeFreeTimerSession']) },
  }
  return { options, calls }
}

test('confirm returns early when actionLoading', () => {
  const h = makeHarness({ actionLoading: true })
  createConfirmEndFreeTimerController(h.options).confirm()
  assert.equal(h.calls.length, 0)
})

test('confirm cleans up when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createConfirmEndFreeTimerController(h.options).confirm()
  assert.ok(h.calls.some(c => c[0] === 'setConfirmTimerSnapshot' && c[1] === null))
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_confirm_pause'))
  assert.ok(h.calls.some(c => c[0] === 'setData'))
})

test('confirm clears interval and completes session when session exists', () => {
  const h = makeHarness()
  createConfirmEndFreeTimerController(h.options).confirm()
  assert.ok(h.calls.some(c => c[0] === 'clearFreeTimerInterval'))
  assert.ok(h.calls.some(c => c[0] === 'completeFreeTimerSession'))
  assert.ok(!h.calls.some(c => c[0] === 'safeRemoveStorage'))
})
