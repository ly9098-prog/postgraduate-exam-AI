const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createFreeTimerBeginController,
} = require('../pages/pomodoro/utils/free-timer-begin-controller')

function createHarness(overrides = {}) {
  const calls = { clearTimer: 0, setData: [], computed: 0, autoFinish: 0, startFree: 0, nextTick: 0, initCanvas: [], drawRing: [] }
  const timer = { sessionId: null, sessionStartTime: 0, totalPausedMs: 0, freeDisplayOffsetMs: 0, pauseStartTime: null, elapsedSec: 0, freeFriendlyText: '', progress: 0 }
  const options = {
    parseServerTime: () => overrides.serverStart !== undefined ? overrides.serverStart : 1000,
    now: () => overrides.now || 61000,
    maxMs: 18000000,
    formatElapsedSec: sec => ({ display: `d${sec}`, friendly: `f${sec}` }),
    clearTimer: () => { calls.clearTimer += 1 },
    timer: () => timer,
    runningPhase: 'running',
    setData: data => calls.setData.push(data),
    updateComputedFields: () => { calls.computed += 1 },
    autoFinishFreeTimer: () => { calls.autoFinish += 1 },
    startFreeTimerInterval: () => { calls.startFree += 1 },
    nextTick: cb => { calls.nextTick += 1; cb() },
    initCanvas: force => { calls.initCanvas.push(force) },
    drawRing: (total, isBreak) => { calls.drawRing.push([total, isBreak]) },
  }
  return { controller: createFreeTimerBeginController(options), calls, timer }
}

test('begin sets up the free timer from server start time and starts the interval', () => {
  const harness = createHarness({ serverStart: 1000, now: 61000 })
  harness.controller.begin({ id: 5, start_time: 'x', total_paused_sec: 0 })
  assert.equal(harness.timer.sessionId, 5)
  assert.equal(harness.timer.sessionStartTime, 1000)
  assert.equal(harness.timer.freeDisplayOffsetMs, 0)
  assert.equal(harness.timer.elapsedSec, 60)
  assert.equal(harness.calls.clearTimer, 1)
  assert.equal(harness.calls.startFree, 1)
  assert.deepEqual(harness.calls.initCanvas, [true])
  assert.deepEqual(harness.calls.drawRing, [[0, false]])
})

test('begin auto-finishes when the session has already exceeded the max', () => {
  const harness = createHarness({ serverStart: 0, now: 19000000 })
  harness.controller.begin({ id: 9, start_time: 'x', total_paused_sec: 0 })
  assert.equal(harness.calls.autoFinish, 1)
  assert.equal(harness.calls.startFree, 0)
})

test('begin caps the display at the max even before auto-finish', () => {
  const harness = createHarness({ serverStart: 0, now: 18000001 })
  harness.controller.begin({ id: 7, start_time: 'x', total_paused_sec: 0 })
  assert.equal(harness.timer.elapsedSec, 18000)
  assert.equal(harness.calls.autoFinish, 1)
})
