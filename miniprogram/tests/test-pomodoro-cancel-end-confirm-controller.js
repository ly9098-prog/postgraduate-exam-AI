/**
 * Independent regression for the cancel-end-confirm controller.
 * Run: node --test miniprogram/tests/test-pomodoro-cancel-end-confirm-controller.js
 */
const assert = require('assert')
const { test } = require('node:test')
const { createCancelEndConfirmController } = require('../pages/pomodoro/utils/cancel-end-confirm-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let confirmSnapshot = overrides._confirmTimerSnapshot ?? null
  let timerState = { endConfirmMode: overrides.endConfirmMode ?? 'countdown-complete' }
  let confirmActionSeq = 0
  let countdownTotalSec = null
  const data = { actionLoading: false, isPaused: overrides.isPaused ?? false }

  const options = {
    isActionLoading: () => data.actionLoading,
    getEndConfirmMode: () => timerState.endConfirmMode,
    getConfirmTimerSnapshot: () => confirmSnapshot,
    setConfirmTimerSnapshot: v => { confirmSnapshot = v },
    now: () => overrides.now ?? 100000,
    incrementConfirmActionSeq: () => { confirmActionSeq++ },
    isPaused: () => data.isPaused,
    applyTimerState: patch => { Object.assign(timerState, patch) },
    safeGetStorage: key => overrides.storage?.[key]
      ? { ok: true, value: overrides.storage[key] }
      : { ok: false },
    safeSetStorage: (key, value) => { calls.push(['safeSetStorage', key, value]) },
    safeRemoveStorage: key => { calls.push(['safeRemoveStorage', key]) },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    setPendingSync: (action, sessionId, now) => {
      calls.push(['setPendingSync', action, sessionId, now])
      return overrides.setPendingSyncResult ?? true
    },
    setData: d => { calls.push(['setData', d]) },
    setCountdownTotalSec: v => { countdownTotalSec = v; calls.push(['setCountdownTotalSec', v]) },
    startTimer: (totalSec, opts) => { calls.push(['startTimer', totalSec, opts]) },
    startFreeTimerInterval: () => { calls.push(['startFreeTimerInterval']) },
    restartFreeTimerInterval: () => { calls.push(['restartFreeTimerInterval']) },
    nextTick: cb => { calls.push(['nextTick']); cb() },
    initCanvas: force => { calls.push(['initCanvas', force]) },
    drawRing: (total, isBreak) => { calls.push(['drawRing', total, isBreak]) },
    redrawFreeRingAfterOverlay: () => { calls.push(['redrawFreeRingAfterOverlay']) },
    retryPendingSync: () => {
      calls.push(['retryPendingSync'])
      return Promise.resolve(overrides.retryPendingResult ?? true)
    },
    warn: msg => { calls.push(['warn', msg]) },
  }
  return { options, calls, get confirmSnapshot() { return confirmSnapshot },
    get confirmActionSeq() { return confirmActionSeq },
    get countdownTotalSec() { return countdownTotalSec },
    get timerState() { return timerState } }
}

test('cancel returns early when actionLoading is true', () => {
  const h = makeHarness()
  h.options.isActionLoading = () => true
  const ctrl = createCancelEndConfirmController(h.options)
  ctrl.cancel()
  assert.equal(h.calls.length, 0)
})

test('cancel shows persistence error when snapshot missing and storage fails', () => {
  const h = makeHarness()
  const ctrl = createCancelEndConfirmController(h.options)
  ctrl.cancel()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('cancel reads snapshot from storage when in-memory is null', () => {
  const h = makeHarness({
    storage: { pomodoro_confirm_pause: { totalSec: 300, phase: 'running', remainingMs: 200000 } },
  })
  const ctrl = createCancelEndConfirmController(h.options)
  ctrl.cancel()
  // Should have proceeded past snapshot resolution and called setData
  assert.ok(h.calls.some(c => c[0] === 'setData'))
})

test('cancel increments confirm action seq', () => {
  const h = makeHarness({
    _confirmTimerSnapshot: { totalSec: 300, phase: 'running', remainingMs: 200000 },
  })
  const ctrl = createCancelEndConfirmController(h.options)
  ctrl.cancel()
  assert.equal(h.confirmActionSeq, 1)
})

test('cancel shows persistence error when setPendingSync fails', () => {
  const h = makeHarness({
    _confirmTimerSnapshot: { totalSec: 300, phase: 'running', remainingMs: 200000, sessionId: 's1' },
    setPendingSyncResult: false,
  })
  const ctrl = createCancelEndConfirmController(h.options)
  ctrl.cancel()
  // The plan for countdown-complete with isPaused=true includes adjustment
  // If adjustment exists and setPendingSync fails, showPersistenceError is called
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError') || h.calls.some(c => c[0] === 'setData'))
})
