const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createActiveSyncController,
} = require('../pages/pomodoro/utils/active-sync-controller')

function baseView(overrides = {}) {
  return {
    phase: 'running',
    isPaused: false,
    isFreeTimer: false,
    allocationMode: 'single',
    selectedSubjectId: 1,
    selectedSubject: { id: 1, name: '数学' },
    subjects: [{ id: 1, name: '数学' }, { id: 2, name: '英语' }],
    selectedPreset: 'standard',
    workDuration: 25,
    ...overrides,
  }
}

function createHarness(overrides = {}) {
  const calls = {
    setData: [], computed: 0, persistence: 0, nextTick: 0,
    initCanvas: [], drawRing: [], autoFinish: 0, startFree: 0,
    clearTimer: 0, onWorkComplete: 0, startTimer: [], parsed: [],
  }
  const view = overrides.view || baseView()
  const timer = overrides.timer || {
    sessionId: 5, sessionStartTime: 1000, totalPausedMs: 0, elapsedSec: 0, progress: 0,
  }
  const options = {
    now: () => overrides.now || 61000,
    view: () => view,
    timer: () => timer,
    runningPhase: 'running',
    parseServerTime(value) {
      calls.parsed.push(value)
      return overrides.serverStart === undefined ? 0 : overrides.serverStart
    },
    setData(data) { calls.setData.push(data) },
    updateComputedFields() { calls.computed += 1 },
    mergeLocalPauseAdjustment(sessionId, value, failClosed) {
      if (overrides.mergeResult === null) return null
      return overrides.mergeResult === undefined ? value : overrides.mergeResult
    },
    persistenceError() { calls.persistence += 1 },
    canvasReady: () => overrides.canvasReady === undefined ? true : overrides.canvasReady,
    ctx: () => (overrides.ctx === undefined ? {} : overrides.ctx),
    nextTick(callback) { calls.nextTick += 1; callback() },
    isPageVisible: () => overrides.pageVisible !== false,
    initCanvas(force) { calls.initCanvas.push(force) },
    drawRing(total, isBreak) { calls.drawRing.push([total, isBreak]) },
    maxMs: 18000000,
    formatElapsedSec: sec => ({ display: `d${sec}`, friendly: `f${sec}` }),
    autoFinishFreeTimer() { calls.autoFinish += 1 },
    startFreeTimerInterval() { calls.startFree += 1 },
    clearTimer() { calls.clearTimer += 1 },
    onWorkComplete() { calls.onWorkComplete += 1 },
    startTimer(totalSec, timerOptions) { calls.startTimer.push([totalSec, timerOptions]) },
  }
  return { controller: createActiveSyncController(options), calls, view, timer }
}

test('canLightSync requires a matching live session in the running phase', () => {
  const ok = createHarness()
  assert.equal(ok.controller.canLightSync({ id: 5, status: 'running', preset: 'countdown' }), true)

  assert.equal(createHarness({
    timer: { sessionId: 0, sessionStartTime: 1000 },
  }).controller.canLightSync({ id: 0, status: 'running', preset: 'countdown' }), false)

  assert.equal(ok.controller.canLightSync({ id: 99, status: 'running', preset: 'countdown' }), false)
  assert.equal(ok.controller.canLightSync({ id: 5, status: 'paused', preset: 'countdown' }), false)
  assert.equal(ok.controller.canLightSync({ id: 5, status: 'running', preset: 'free' }), false)
  assert.equal(createHarness({ view: baseView({ phase: 'idle' }) })
    .controller.canLightSync({ id: 5, status: 'running', preset: 'countdown' }), false)
  assert.equal(createHarness({ timer: { sessionId: 5, sessionStartTime: 0 } })
    .controller.canLightSync({ id: 5, status: 'running', preset: 'countdown' }), false)
})

test('syncLight applies server start time and restarts the countdown from wall clock', () => {
  const harness = createHarness({ serverStart: 61000, now: 91000 })

  const result = harness.controller.syncLight(
    { id: 5, status: 'running', preset: 'countdown', start_time: 'x', total_paused_sec: 0 },
    false
  )

  assert.equal(result, true)
  assert.equal(harness.timer.sessionStartTime, 61000)
  assert.equal(harness.timer.totalPausedMs, 0)
  // 25 min - 30 s remaining => 1470 s.
  assert.deepEqual(harness.calls.startTimer, [
    [1500, { remainingMs: 1470000, forceRunning: true, reuseCanvas: true }],
  ])
})

test('syncLight completes an already-elapsed countdown instead of restarting', () => {
  const harness = createHarness({ serverStart: 0, now: 2000000 })
  harness.timer.sessionStartTime = 0
  harness.timer.remainingSec = 0

  const result = harness.controller.syncLight(
    { id: 5, status: 'running', preset: 'countdown', total_paused_sec: 0 },
    false
  )

  assert.equal(result, true)
  assert.equal(harness.calls.clearTimer, 1)
  assert.equal(harness.calls.onWorkComplete, 1)
  assert.deepEqual(harness.calls.startTimer, [])
})

test('syncLight keeps a paused countdown and rebuilds a missing canvas', () => {
  const harness = createHarness({
    view: baseView({ isPaused: true }),
    canvasReady: false,
    ctx: null,
  })

  assert.equal(harness.controller.syncLight(
    { id: 5, status: 'paused', preset: 'countdown', total_paused_sec: 0 },
    false
  ), true)
  assert.deepEqual(harness.calls.startTimer, [])
  assert.deepEqual(harness.calls.initCanvas, [true])
  assert.deepEqual(harness.calls.drawRing, [[1500, false]])
})

test('syncLight caps a long free timer and restarts its interval', () => {
  const harness = createHarness({
    view: baseView({ isFreeTimer: true }),
    now: 5000000,
  })
  harness.timer.sessionStartTime = 0
  harness.timer.elapsedSec = 0

  assert.equal(harness.controller.syncLight(
    { id: 5, status: 'running', preset: 'free', total_paused_sec: 0 },
    false
  ), true)
  assert.equal(harness.calls.startFree, 1)
  assert.equal(harness.calls.autoFinish, 0)
  assert.deepEqual(harness.calls.setData, [{ freeDisplayTime: 'd5000' }])
  assert.equal(harness.timer.elapsedSec, 5000)
})

test('syncLight auto-finishes a free timer past the maximum', () => {
  const harness = createHarness({
    view: baseView({ isFreeTimer: true }),
    now: 19000000,
  })
  harness.timer.sessionStartTime = 0

  assert.equal(harness.controller.syncLight(
    { id: 5, status: 'running', preset: 'free', total_paused_sec: 0 },
    false
  ), true)
  assert.equal(harness.calls.autoFinish, 1)
  assert.equal(harness.calls.startFree, 0)
})

test('syncLight does not restart a paused free timer', () => {
  const harness = createHarness({
    view: baseView({ isFreeTimer: true, isPaused: true }),
    now: 9000,
  })

  assert.equal(harness.controller.syncLight(
    { id: 5, status: 'paused', preset: 'free', total_paused_sec: 0 },
    false
  ), true)
  assert.equal(harness.calls.startFree, 0)
})

test('syncLight fails closed when the local pause adjustment cannot be read', () => {
  const strict = createHarness({ mergeResult: null })
  assert.equal(strict.controller.syncLight(
    { id: 5, status: 'running', preset: 'countdown', total_paused_sec: 3 },
    true
  ), false)
  assert.equal(strict.calls.persistence, 1)
  assert.equal(strict.calls.startTimer.length, 0)
  assert.equal(strict.timer.totalPausedMs, 0)

  const soft = createHarness({ mergeResult: null })
  assert.equal(soft.controller.syncLight(
    { id: 5, status: 'running', preset: 'countdown', total_paused_sec: 3 },
    false
  ), false)
  assert.equal(soft.calls.persistence, 0)
})

test('syncLight applies the 408 allocation only when the mode changes', () => {
  const changed = createHarness({ view: baseView({ allocationMode: 'single', subjects: [{ id: 2, name: '英语' }] }) })
  changed.controller.syncLight(
    { id: 5, status: 'running', preset: 'countdown', allocation_mode: 'equal_408_core_v1', subject_id: 2 },
    false
  )
  assert.equal(changed.calls.setData.length, 1)
  assert.equal(changed.calls.setData[0].allocationMode, 'equal_408_core_v1')
  assert.equal(changed.calls.setData[0].selectedSubject._isAggregate, true)
  assert.equal(changed.calls.computed, 1)

  const same = createHarness({ view: baseView({ allocationMode: 'equal_408_core_v1' }) })
  same.controller.syncLight(
    { id: 5, status: 'running', preset: 'countdown', allocation_mode: 'equal_408_core_v1' },
    false
  )
  assert.deepEqual(same.calls.setData, [])
  assert.equal(same.calls.computed, 0)
})
