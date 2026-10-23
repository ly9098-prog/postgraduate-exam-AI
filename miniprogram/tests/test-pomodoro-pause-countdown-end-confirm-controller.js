/**
 * Independent regression for the pause-countdown-end-confirm controller.
 * Run: node --test miniprogram/tests/test-pomodoro-pause-countdown-end-confirm-controller.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createPauseCountdownEndConfirmController } = require('../pages/pomodoro/utils/pause-countdown-end-confirm-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let confirmSnapshot = null
  let confirmActionSeq = 0
  let countdownEndAt = overrides.countdownEndAt ?? 200000
  const timerState = {
    sessionId: overrides.sessionId ?? 's1',
    remainingSec: overrides.remainingSec ?? 180,
    totalPausedMs: overrides.totalPausedMs ?? 5000,
    pauseStartTime: overrides.pauseStartTime ?? null,
    sessionStartTime: overrides.sessionStartTime ?? 90000,
  }
  const data = { actionLoading: overrides.actionLoading ?? false, isPaused: overrides.isPaused ?? false, phase: overrides.phase ?? 'running' }

  const options = {
    getSessionId: () => timerState.sessionId,
    isActionLoading: () => data.actionLoading,
    now: () => overrides.now ?? 100000,
    getCurrentTotalSec: () => overrides.totalSec ?? 300,
    getCountdownEndAt: () => countdownEndAt,
    getRemainingSec: () => timerState.remainingSec,
    isPaused: () => data.isPaused,
    getPhase: () => data.phase,
    incrementConfirmActionSeq: () => { confirmActionSeq++; return confirmActionSeq },
    getSessionStartTime: () => timerState.sessionStartTime,
    getTotalPausedMs: () => timerState.totalPausedMs,
    getPauseStartTime: () => timerState.pauseStartTime,
    safeSetStorage: (key, value) => { calls.push(['safeSetStorage']); return overrides.safeSetStorageResult ?? true },
    showPersistenceError: () => { calls.push(['showPersistenceError']) },
    setPendingSync: (action, sid, now) => { calls.push(['setPendingSync']); return overrides.setPendingSyncResult ?? true },
    safeRemoveStorage: key => { calls.push(['safeRemoveStorage']) },
    setConfirmTimerSnapshot: v => { confirmSnapshot = v; calls.push(['setConfirmTimerSnapshot']) },
    clearTimer: () => { calls.push(['clearTimer']) },
    setCountdownEndAt: v => { countdownEndAt = v; calls.push(['setCountdownEndAt']) },
    formatCountdownDisplay: sec => ({ min: Math.floor(sec / 60), sec: sec % 60 }),
    setTimerFields: patch => { Object.assign(timerState, patch); calls.push(['setTimerFields']) },
    setData: d => { calls.push(['setData']) },
    drawRing: (total, isBreak) => { calls.push(['drawRing']) },
    postPauseWithRetry: snapshot => { calls.push(['postPauseWithRetry']); return Promise.resolve() },
    warn: (msg, e) => { calls.push(['warn']) },
  }
  return { options, calls, get confirmSnapshot() { return confirmSnapshot },
    get confirmActionSeq() { return confirmActionSeq }, get timerState() { return timerState },
    get countdownEndAt() { return countdownEndAt } }
}

test('pause returns false when no session id', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  const ctrl = createPauseCountdownEndConfirmController(h.options)
  assert.equal(ctrl.pause(), false)
  assert.equal(h.calls.length, 0)
})

test('pause returns false when actionLoading', () => {
  const h = makeHarness({ actionLoading: true })
  const ctrl = createPauseCountdownEndConfirmController(h.options)
  assert.equal(ctrl.pause(), false)
  assert.equal(h.calls.length, 0)
})

test('pause builds snapshot, persists, and updates view when not paused', () => {
  const h = makeHarness({ isPaused: false })
  const ctrl = createPauseCountdownEndConfirmController(h.options)
  assert.equal(ctrl.pause(), true)
  assert.ok(h.calls.some(c => c[0] === 'safeSetStorage'))
  assert.ok(h.calls.some(c => c[0] === 'setPendingSync'))
  assert.ok(h.calls.some(c => c[0] === 'clearTimer'))
  assert.ok(h.calls.some(c => c[0] === 'setData'))
  assert.ok(h.calls.some(c => c[0] === 'drawRing'))
  assert.ok(h.calls.some(c => c[0] === 'postPauseWithRetry'))
  assert.equal(h.confirmActionSeq, 1)
  assert.equal(h.countdownEndAt, 0)
})

test('pause skips backend pause when already paused', () => {
  const h = makeHarness({ isPaused: true })
  const ctrl = createPauseCountdownEndConfirmController(h.options)
  assert.equal(ctrl.pause(), true)
  assert.ok(!h.calls.some(c => c[0] === 'postPauseWithRetry'))
  assert.ok(!h.calls.some(c => c[0] === 'setPendingSync'))
})

test('pause returns false when storage fails', () => {
  const h = makeHarness({ safeSetStorageResult: false })
  const ctrl = createPauseCountdownEndConfirmController(h.options)
  assert.equal(ctrl.pause(), false)
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})

test('pause rolls back and returns false when setPendingSync fails', () => {
  const h = makeHarness({ isPaused: false, setPendingSyncResult: false })
  const ctrl = createPauseCountdownEndConfirmController(h.options)
  assert.equal(ctrl.pause(), false)
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage'))
  assert.ok(h.calls.some(c => c[0] === 'showPersistenceError'))
})
