const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createStartBreakController } = require('../pages/pomodoro/utils/start-break-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let now = overrides.now ?? 100000
  let countdownEndAt = 0
  let timerController = null
  const timerState = {}
  const options = {
    now: () => now,
    safeSetStorage: (key, value) => { calls.push(['safeSetStorage', key, value]) },
    safeRemoveStorage: key => { calls.push(['safeRemoveStorage', key]) },
    setTimerFields: patch => { Object.assign(timerState, patch); calls.push(['setTimerFields', patch]) },
    formatCountdownDisplay: sec => ({ min: Math.floor(sec / 60), sec: sec % 60 }),
    breakPhase: () => 'break',
    setData: data => { calls.push(['setData', data]) },
    clearTimer: () => { calls.push(['clearTimer']) },
    initCanvas: force => { calls.push(['initCanvas', force]) },
    setCountdownTotalSec: value => { calls.push(['setCountdownTotalSec', value]) },
    setCountdownEndAt: value => { countdownEndAt = value },
    getCountdownEndAt: () => countdownEndAt,
    getRemainingSec: () => timerState.remainingSec,
    getProgress: () => timerState.progress,
    drawRing: (total, isBreak) => { calls.push(['drawRing', total, isBreak]) },
    resetToIdle: () => { calls.push(['resetToIdle']) },
    getTimerController: () => timerController,
    setTimerController: value => { timerController = value },
    setTimeout: (fn, delay) => { calls.push(['setTimeout', delay, fn]); return { fn, delay } },
    clearTimeout: () => {},
    clearInterval: () => {},
  }
  return {
    options,
    calls,
    get timerState() { return timerState },
    advance: value => { now += value },
    setEndAt: value => { countdownEndAt = value },
  }
}

test('start clears expired break and resets idle', () => {
  const h = makeHarness({ now: 100000 })
  h.setEndAt(0)
  createStartBreakController(h.options).start(300, { startTime: 0, remainingMs: 0 })
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_break'))
  assert.ok(h.calls.some(c => c[0] === 'resetToIdle'))
})

test('start preserves original break total and start time', () => {
  const h = makeHarness({ now: 100000 })
  createStartBreakController(h.options).start(300, { startTime: 90000, remainingMs: 120000 })
  const setStorage = h.calls.find(c => c[0] === 'safeSetStorage')
  assert.equal(setStorage[2].totalSec, 300)
  assert.equal(setStorage[2].startTime, 90000)
  assert.equal(h.timerState.remainingSec, 290)
  assert.ok(h.calls.some(c => c[0] === 'drawRing' && c[1] === 300 && c[2] === true))
})

test('tick creates countdown controller and schedules next delay', () => {
  const h = makeHarness({ now: 100000 })
  createStartBreakController(h.options).start(300, { startTime: 90000, remainingMs: 100000 })
  assert.ok(h.calls.some(c => c[0] === 'setTimeout'))
})

test('completed break clears timer, removes snapshot, and resets idle', () => {
  const h = makeHarness({ now: 100000 })
  const controller = createStartBreakController(h.options)
  controller.start(300, { startTime: 0, remainingMs: 1000 })
  h.setEndAt(h.options.now())
  // Force the next tick through the scheduled callback.
  const timer = h.calls.filter(c => c[0] === 'setTimeout').at(-1)
  timer && timer[2]()
  assert.ok(h.calls.some(c => c[0] === 'safeRemoveStorage' && c[1] === 'pomodoro_break'))
  assert.ok(h.calls.some(c => c[0] === 'resetToIdle'))
})
