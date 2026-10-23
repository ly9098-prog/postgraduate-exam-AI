/**
 * Independent regression for the show-end-free-confirm controller.
 * Run: node --test miniprogram/tests/test-pomodoro-show-end-free-confirm-controller.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createShowEndFreeConfirmController } = require('../pages/pomodoro/utils/show-end-free-confirm-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let confirmSnapshot = null
  let confirmActionSeq = 0
  const timerState = {
    sessionId: overrides.sessionId ?? 's1',
    elapsedSec: overrides.elapsedSec ?? 120,
    totalPausedMs: overrides.totalPausedMs ?? 5000,
    pauseStartTime: overrides.pauseStartTime ?? null,
    sessionStartTime: overrides.sessionStartTime ?? 90000,
  }
  const data = { actionLoading: overrides.actionLoading ?? false, isPaused: overrides.isPaused ?? false }

  const options = {
    getSessionId: () => timerState.sessionId,
    isActionLoading: () => data.actionLoading,
    now: () => overrides.now ?? 100000,
    isPaused: () => data.isPaused,
    getElapsedSec: () => timerState.elapsedSec,
    formatElapsedSec: sec => ({ display: `${sec}s`, friendly: `${sec} seconds` }),
    incrementConfirmActionSeq: () => { confirmActionSeq++; return confirmActionSeq },
    getTotalPausedMs: () => timerState.totalPausedMs,
    getPauseStartTime: () => timerState.pauseStartTime,
    getSessionStartTime: () => timerState.sessionStartTime,
    safeSetStorage: (key, value) => { calls.push(['safeSetStorage', key]); return overrides.safeSetStorageResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    setPendingSync: (action, sid, now) => { calls.push(['setPendingSync', action, sid]); return overrides.setPendingSyncResult ?? true },
    safeRemoveStorage: key => { calls.push(['safeRemoveStorage', key]) },
    setConfirmTimerSnapshot: v => { confirmSnapshot = v; calls.push(['setConfirmTimerSnapshot']) },
    clearFreeTimerInterval: () => { calls.push(['clearFreeTimerInterval']) },
    setTimerFields: patch => { Object.assign(timerState, patch); calls.push(['setTimerFields']) },
    setData: d => { calls.push(['setData']) },
    postPauseWithRetry: snapshot => {
      calls.push(['postPauseWithRetry'])
      return Promise.resolve()
    },
    warn: (msg, e) => { calls.push(['warn', msg]) },
  }
  return { options, calls, get confirmSnapshot() { return confirmSnapshot },
    get confirmActionSeq() { return confirmActionSeq }, get timerState() { return timerState } }
}

test('show returns early when no session id', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  const ctrl = createShowEndFreeConfirmController(h.options)
  ctrl.show()
  assert.equal(h.calls.length, 0)
})

test('show returns early when actionLoading is true', () => {
  const h = makeHarness({ actionLoading: true })
  const ctrl = createShowEndFreeConfirmController(h.options)
  ctrl.show()
  assert.equal(h.calls.length, 0)
})

test('show persists snapshot and updates view when not paused', () => {
  const h = makeHarness({ isPaused: false })
  const ctrl = createShowEndFreeConfirmController(h.options)
  ctrl.show()
  assert.ok(h.calls.some(c => c[0] === 'safeSetStorage'))
  assert.ok(h.calls.some(c => c[0] === 'setPendingSync'))
  assert.ok(h.calls.some(c => c[0] === 'setData'))
  assert.ok(h.calls.some(c => c[0] === 'postPauseWithRetry'))
  assert.equal(h.confirmActionSeq, 1)
})

test('show skips backend pause when already paused', () => {
  const h = makeHarness({ isPaused: true })
  const ctrl = createShowEndFreeConfirmController(h.options)
  ctrl.show()
  assert.ok(!h.calls.some(c => c[0] === 'postPauseWithRetry'))
  assert.ok(!h.calls.some(c => c[0] === 'setPendingSync'))
})

test('show shows persistence error when storage fails', () => {
  const h = makeHarness({ safeSetStorageResult: false })
  const ctrl = createShowEndFreeConfirmController(h.options)
  ctrl.show()
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('show rolls back and shows error when setPendingSync fails', () => {
  const h = makeHarness({ isPaused: false, setPendingSyncResult: false })
  const ctrl = createShowEndFreeConfirmController(h.options)
  ctrl.show()
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage'))
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})
