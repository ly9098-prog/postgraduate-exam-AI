const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createStartAnimationsController,
} = require('../subpackages/productivity/pomodoro-stats/start-animations-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    requestId: 1,
    chartMode: 'pie',
    todaySessions: 7,
    rawTodayDur: 1200,
    animActive: false,
    finalDrawn: true,
    pieLabelToken: 0,
    displayDurationSec: null,
    now: 1000,
    data: [],
    timers: [],
    rafCallbacks: [],
    renders: [],
    revealed: 0,
    animTimer: null,
    rafId: null,
    pieCanvasNode: null,
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getRequestId: () => state.requestId,
    getChartMode: () => state.chartMode,
    getTodaySessions: () => state.todaySessions,
    getRawTodayDurationSec: () => state.rawTodayDur,
    getAnimActive: () => state.animActive,
    getFinalDrawn: () => state.finalDrawn,
    getPieCanvasNode: () => state.pieCanvasNode,
    setAnimActive: value => { state.animActive = value },
    setFinalDrawn: value => { state.finalDrawn = value },
    setDisplayDurationSec: value => { state.displayDurationSec = value },
    setAnimTimer: timer => { state.animTimer = timer },
    setRafId: id => { state.rafId = id },
    incrementPieLabelToken: () => { state.pieLabelToken += 1 },
    now: () => state.now,
    setTimeout: (callback, delay) => {
      const timer = { callback, delay }
      state.timers.push(timer)
      if (delay === 16) state.rafId = timer
      else state.animTimer = timer
      return timer
    },
    setData: patch => state.data.push(patch),
    getDurationDisplayPatch: text => ({ display: text }),
    formatMin: sec => `${Math.floor(sec / 60)}分钟`,
    renderPie: (progress, includeLabels) => state.renders.push({ progress, includeLabels }),
    revealPieLabelsIncrementally: () => { state.revealed += 1 },
    ...overrides,
  }
  return { controller: createStartAnimationsController(options), options, state }
}

function drainNumberAnimation(state) {
  while (state.animTimer) {
    const timer = state.animTimer
    state.animTimer = null
    timer.callback()
  }
}

function runRafOnce(state, advanceTime) {
  const raf = state.rafId
  state.rafId = null
  advanceTime()
  raf.callback()
}

function drainRaf(state, advanceTime) {
  while (state.rafId) {
    const raf = state.rafId
    state.rafId = null
    advanceTime()
    raf.callback()
  }
}

test('does not start outside the live, visible, current pie request', () => {
  const dead = createHarness()
  dead.state.alive = false
  dead.controller.start(1)

  const hidden = createHarness()
  hidden.state.visible = false
  hidden.controller.start(1)

  const stale = createHarness()
  stale.controller.start(0)

  const bar = createHarness()
  bar.state.chartMode = 'bar'
  bar.controller.start(1)

  for (const h of [dead, hidden, stale, bar]) {
    assert.deepEqual(h.state.data, [])
    assert.deepEqual(h.state.renders, [])
    assert.equal(h.state.pieLabelToken, 0)
  }
})

test('runs the seven-step number animation and pie frames to completion', () => {
  const h = createHarness()
  h.controller.start(1)

  assert.equal(h.state.animActive, true)
  assert.equal(h.state.finalDrawn, false)
  assert.equal(h.state.pieLabelToken, 1)
  assert.equal(h.state.data.length, 1)
  assert.ok(h.state.rafId)
  assert.equal(h.state.data[0]._dispTodaySessions, 3)
  assert.equal(h.state.data[0].durationValueAnimating, true)

  drainNumberAnimation(h.state)
  assert.equal(h.state.data.length, 7)
  assert.equal(h.state.data.at(-1)._dispTodaySessions, 7)
  assert.equal(h.state.data.at(-1).display, '20分钟')
  assert.equal(h.state.data.at(-1).durationValueAnimating, false)
  assert.equal(h.state.animTimer, null)
  assert.equal(h.state.timers.filter(timer => timer.delay === 60).length, 6)

  drainRaf(h.state, () => { h.state.now += 500 })
  assert.equal(h.state.finalDrawn, true)
  assert.equal(h.state.animActive, false)
  assert.equal(h.state.revealed, 1)
  assert.equal(h.state.renders.at(-1).progress, 1)
  assert.equal(h.state.renders.at(-1).includeLabels, false)
  assert.equal(h.state.rafId, null)
})

test('throttles pie redraws to at least 28ms', () => {
  const h = createHarness()
  h.controller.start(1)
  h.state.now += 30
  runRafOnce(h.state, () => {})
  const renderCount = h.state.renders.length

  h.state.now += 10
  runRafOnce(h.state, () => {})
  assert.equal(h.state.renders.length, renderCount)

  h.state.now += 20
  runRafOnce(h.state, () => {})
  assert.equal(h.state.renders.length, renderCount + 1)
})

test('uses canvas requestAnimationFrame when available', () => {
  const h = createHarness()
  h.state.pieCanvasNode = {
    requestAnimationFrame(callback) {
      const handle = { callback }
      h.state.rafId = handle
      return handle
    },
  }
  h.controller.start(1)

  assert.equal(h.state.timers.length, 1)
  assert.equal(h.state.timers.filter(timer => timer.delay === 16).length, 0)
  assert.ok(h.state.rafId)
})

test('later ticks stop after the request becomes stale or the page is hidden', () => {
  const stale = createHarness()
  stale.controller.start(1)
  const staleRaf = stale.state.rafId
  stale.state.requestId = 2
  staleRaf.callback()
  assert.equal(stale.state.renders.length, 0)

  const hidden = createHarness()
  hidden.controller.start(1)
  hidden.state.visible = false
  hidden.state.rafId.callback()
  assert.equal(hidden.state.renders.length, 0)
})
