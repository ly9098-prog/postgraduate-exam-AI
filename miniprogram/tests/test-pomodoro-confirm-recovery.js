const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildConfirmRecovery, restoreConfirmSnapshot } = require('../pages/pomodoro/utils/confirm-recovery')

function fixture() {
  const calls = []
  const state = { seq: 4, visible: true, timer: { unrelated: 10 }, view: {} }
  const options = {
    nextSequence: () => ++state.seq,
    setSnapshot: snapshot => { state.snapshot = snapshot },
    sessionStartTime: () => 100,
    applyTimer: patch => Object.assign(state.timer, patch),
    buildView: (mode, snapshot) => { calls.push(['build', mode, snapshot.sessionId]); return { showEndConfirm: true } },
    applyView: patch => { calls.push('view'); Object.assign(state.view, patch) },
    nextTick: callback => { calls.push('tick'); callback() },
    draw: snapshot => calls.push(['draw', snapshot.totalSec, snapshot.phase]),
    pause: async (id, opened) => { calls.push(['pause', id, opened]) },
    currentSequence: () => state.seq,
    isConfirmVisible: () => state.visible,
    persist: snapshot => calls.push(['persist', snapshot.confirmActionSeq]),
    deferStats: () => calls.push('stats'),
  }
  return { calls, state, options }
}
const flush = () => new Promise(resolve => setImmediate(resolve))

test('free recovery restores elapsed fields and preserves the start fallback', () => {
  const recovery = buildConfirmRecovery({ mode: 'free-complete', sessionId: 1, elapsedSec: 65 }, 100)
  assert.deepEqual(recovery.timer, {
    sessionId: 1, sessionStartTime: 100, endConfirmMode: 'free-complete', totalPausedMs: 0,
    elapsedSec: 65, freeFriendlyText: '1分05秒', freeDisplayOffsetMs: 0,
  })
  assert.deepEqual(recovery.view, {
    phase: 'running', isPaused: true, ringCanvasVisible: true,
    isFreeTimer: true, freeDisplayTime: '00:01:05',
  })
  assert.equal(recovery.free, true)
})

test('countdown recovery retains phase, progress and paused time without free fields', () => {
  const recovery = buildConfirmRecovery({
    sessionId: 2, mode: 'countdown-interrupt', sessionStartTime: 200,
    phase: 'break', remainingSec: 75, progress: 0.5, totalPausedMs: 300,
  }, 100)
  assert.deepEqual(recovery.timer, {
    sessionId: 2, sessionStartTime: 200, endConfirmMode: 'countdown-interrupt',
    remainingSec: 75, progress: 0.5, totalPausedMs: 300,
  })
  assert.deepEqual(recovery.view, {
    phase: 'break', isPaused: true, ringCanvasVisible: true, displayMin: '01', displaySec: '15',
  })
  assert.equal(recovery.free, false)
})

test('restores snapshot identity and sequence; countdown draws before pause retry', async () => {
  const f = fixture()
  const snapshot = { sessionId: 2, remainingSec: 10, totalSec: 20, pausedByConfirm: true, openedAt: 80 }
  restoreConfirmSnapshot(f.options, snapshot)
  assert.equal(f.state.snapshot, snapshot)
  assert.equal(snapshot.confirmActionSeq, 5)
  assert.equal(f.state.timer.unrelated, 10)
  assert.deepEqual(f.calls, [
    ['build', 'countdown-interrupt', 2], 'view', 'tick',
    ['draw', 20, undefined], ['pause', 2, 80], 'stats',
  ])
  await flush()
  assert.equal(snapshot.backendPauseDone, true)
  assert.deepEqual(f.calls.at(-1), ['persist', 5])
})

test('free recovery skips canvas redraw and pause when already paused', async () => {
  for (const extra of [{ pausedByConfirm: false }, { pausedByConfirm: true, backendPauseDone: true }]) {
    const f = fixture()
    restoreConfirmSnapshot(f.options, { sessionId: 3, mode: 'free-complete', ...extra })
    await flush()
    assert.deepEqual(f.calls, [['build', 'free-complete', 3], 'view', 'stats'])
  }
})

test('pause acknowledgement cannot rewrite a superseded or closed confirmation', async () => {
  for (const stale of ['sequence', 'visibility']) {
    const f = fixture()
    let resolve
    f.options.pause = () => new Promise(done => { resolve = done })
    const snapshot = { sessionId: 4, mode: 'free-complete', pausedByConfirm: true }
    restoreConfirmSnapshot(f.options, snapshot)
    if (stale === 'sequence') f.state.seq++
    else f.state.visible = false
    resolve()
    await flush()
    assert.equal(snapshot.backendPauseDone, undefined)
    assert.ok(!f.calls.some(call => Array.isArray(call) && call[0] === 'persist'))
  }
})

test('failed pause remains retryable and does not prevent initial view or stats', async () => {
  const f = fixture()
  f.options.pause = async () => { throw new Error('synthetic pause failure') }
  const snapshot = { sessionId: 5, mode: 'free-complete', pausedByConfirm: true }
  restoreConfirmSnapshot(f.options, snapshot)
  await flush()
  assert.equal(snapshot.backendPauseDone, undefined)
  assert.deepEqual(f.calls, [['build', 'free-complete', 5], 'view', 'stats'])
})

test('pure model accepts frozen input and preserves legacy fallback coercions', () => {
  const snapshot = Object.freeze({
    sessionId: 6, mode: 'free-complete', sessionStartTime: 0, elapsedSec: null, totalPausedMs: null,
  })
  const result = buildConfirmRecovery(snapshot, 100)
  assert.equal(result.timer.sessionStartTime, 100)
  assert.equal(result.timer.elapsedSec, 0)
  assert.equal(result.timer.totalPausedMs, 0)
  assert.equal(result.view.freeDisplayTime, '00:00:00')
})
