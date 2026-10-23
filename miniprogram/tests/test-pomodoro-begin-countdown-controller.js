/**
 * Independent regression for the begin-countdown controller.
 * Run: node --test miniprogram/tests/test-pomodoro-begin-countdown-controller.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createBeginCountdownController } = require('../pages/pomodoro/utils/begin-countdown-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const timerState = {}
  const options = {
    parseServerTime: t => t,
    isDebugPreset: () => overrides.debug ?? false,
    getWorkDurationMinutes: () => overrides.workDuration ?? 25,
    now: () => overrides.now ?? 100000,
    setTimerFields: patch => { Object.assign(timerState, patch); calls.push(['setTimerFields']) },
    runningPhase: () => 'running',
    setData: data => { calls.push(['setData', data]) },
    updateComputedFields: () => { calls.push(['updateComputedFields']) },
    onWorkComplete: () => { calls.push(['onWorkComplete']) },
    startTimer: (totalSec, opts) => { calls.push(['startTimer', totalSec, opts]) },
  }
  return { options, calls, get timerState() { return timerState } }
}

test('begin sets timer fields and starts countdown when time remains', () => {
  const h = makeHarness({ now: 100000 })
  const ctrl = createBeginCountdownController(h.options)
  ctrl.begin({ id: 's1', start_time: 90000, total_paused_sec: 0 })
  assert.equal(h.timerState.sessionId, 's1')
  assert.ok(h.calls.some(c => c[0] === 'startTimer'))
  assert.ok(!h.calls.some(c => c[0] === 'onWorkComplete'))
})

test('begin auto-completes when time already elapsed', () => {
  const h = makeHarness({ now: 100000, workDuration: 0.01 })
  const ctrl = createBeginCountdownController(h.options)
  ctrl.begin({ id: 's1', start_time: 0, total_paused_sec: 0 })
  assert.ok(h.calls.some(c => c[0] === 'onWorkComplete'))
  assert.ok(!h.calls.some(c => c[0] === 'startTimer'))
})

test('begin uses debug preset total of 10 seconds', () => {
  const h = makeHarness({ debug: true, now: 100000 })
  const ctrl = createBeginCountdownController(h.options)
  ctrl.begin({ id: 's1', start_time: 99000, total_paused_sec: 0 })
  const startCall = h.calls.find(c => c[0] === 'startTimer')
  assert.ok(startCall)
  assert.equal(startCall[1], 10)
})

test('begin accounts for server paused time', () => {
  const h = makeHarness({ now: 100000, workDuration: 25 })
  const ctrl = createBeginCountdownController(h.options)
  ctrl.begin({ id: 's1', start_time: 90000, total_paused_sec: 5 })
  // elapsedMs = 100000 - 90000 - 5000 = 5000
  // remainingMs = 25*60*1000 - 5000 = 1495000
  assert.equal(h.timerState.totalPausedMs, 5000)
  assert.equal(h.timerState.remainingSec, Math.ceil(1495000 / 1000))
})
