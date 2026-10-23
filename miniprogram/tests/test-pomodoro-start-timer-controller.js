const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createStartTimerController } = require('../pages/pomodoro/utils/start-timer-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let now = overrides.now ?? 100000
  let countdownEndAt = 0
  let timerController = null
  const timerState = {}
  const data = { isPaused: false, showEndConfirm: false, phase: 'running' }
  const options = {
    clearTimer: () => { calls.push(['clearTimer']) },
    initCanvas: force => { calls.push(['initCanvas', force]) },
    setTimeout: (fn, delay) => { calls.push(['setTimeout', delay, fn]); return { fn, delay } },
    clearTimeout: () => {},
    clearInterval: () => {},
    setTimerController: c => { timerController = c },
    getRemainingSec: () => timerState.remainingSec,
    formatCountdownDisplay: sec => ({ min: Math.floor(sec / 60), sec: sec % 60 }),
    now: () => now,
    setCountdownTotalSec: v => { calls.push(['setCountdownTotalSec', v]) },
    setCountdownEndAt: v => { countdownEndAt = v },
    getCountdownEndAt: () => countdownEndAt,
    setTimerFields: patch => { Object.assign(timerState, patch) },
    setData: data => { calls.push(['setData', data]) },
    isPaused: () => data.isPaused,
    showEndConfirm: () => data.showEndConfirm,
    getProgress: () => timerState.progress,
    drawRing: (total, isBreak) => { calls.push(['drawRing', total, isBreak]) },
    isBreakPhase: () => data.phase === 'break',
    onWorkComplete: () => { calls.push(['onWorkComplete']) },
  }
  return {
    options, calls, get timerState() { return timerState }, get timerController() { return timerController },
    setPaused: v => { data.isPaused = v },
    setEndAt: v => { countdownEndAt = v },
    advance: v => { now += v },
  }
}

test('start initializes canvas, timer, and view state', () => {
  const h = makeHarness({ now: 100000 })
  createStartTimerController(h.options).start(300, { remainingMs: 120000, forceRunning: true })
  assert.ok(h.calls.some(c => c[0] === 'clearTimer'))
  assert.ok(h.calls.some(c => c[0] === 'initCanvas'))
  assert.ok(h.calls.some(c => c[0] === 'setData' && c[1].isPaused === false))
  assert.equal(h.timerState.remainingSec, 120)
})

test('start resolves remainingMs from remainingSec when missing', () => {
  const h = makeHarness()
  createStartTimerController(h.options).start(300, { remainingSec: 180 })
  assert.equal(h.timerState.remainingSec, 180)
})

test('tick stops when paused', () => {
  const h = makeHarness({ now: 100000 })
  createStartTimerController(h.options).start(300, { remainingMs: 120000 })
  h.setPaused(true)
  const timer = h.calls.filter(c => c[0] === 'setTimeout').at(-1)
  timer && timer[2]()
  // No further scheduling after stop
  assert.equal(h.calls.filter(c => c[0] === 'setTimeout').length, 1)
})

test('tick calls onWorkComplete when remaining reaches zero', () => {
  const h = makeHarness({ now: 100000 })
  createStartTimerController(h.options).start(300, { remainingMs: 100 })
  h.setEndAt(h.options.now())
  const timer = h.calls.filter(c => c[0] === 'setTimeout').at(-1)
  timer && timer[2]()
  assert.ok(h.calls.some(c => c[0] === 'onWorkComplete'))
  assert.ok(h.calls.some(c => c[0] === 'clearTimer'))
})
