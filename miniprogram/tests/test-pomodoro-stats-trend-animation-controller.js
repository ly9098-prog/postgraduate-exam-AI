const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createTrendAnimationController,
} = require('../subpackages/productivity/pomodoro-stats/trend-animation-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    chartMode: 'bar',
    trendCtx: {},
    trendBarsRect: { width: 300, height: 100 },
    trendCanvasNode: null,
    barAnimationToken: 0,
    barRafId: null,
    barRenderedOnce: false,
    now: 1000,
    timers: [],
    dataPatches: [],
    renders: [],
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getChartMode: () => state.chartMode,
    getTrendCtx: () => state.trendCtx,
    getTrendBarsRect: () => state.trendBarsRect,
    getTrendCanvasNode: () => state.trendCanvasNode,
    getBarAnimationToken: () => state.barAnimationToken,
    incrementBarAnimationToken: () => { state.barAnimationToken += 1; return state.barAnimationToken },
    setBarRafId: id => { state.barRafId = id },
    markBarRenderedOnce: () => { state.barRenderedOnce = true },
    now: () => state.now,
    setTimeout: (callback, delay) => {
      const timer = { callback, delay }
      state.timers.push(timer)
      state.barRafId = timer
      return timer
    },
    setData: patch => state.dataPatches.push(patch),
    renderTrendBars: progress => state.renders.push(progress),
    ...overrides,
  }
  return { controller: createTrendAnimationController(options), state, options }
}

function drainRaf(state, advanceTime) {
  while (state.barRafId) {
    const raf = state.barRafId
    state.barRafId = null
    advanceTime()
    raf.callback()
  }
}

test('clears barRendering and returns when there is no trend context', () => {
  const h = createHarness()
  h.state.trendCtx = null
  h.controller.animate()
  assert.deepEqual(h.state.dataPatches, [{ barRendering: false }])
  assert.equal(h.state.renders.length, 0)
})

test('animates trend bars from 0 to 1 and marks rendered once', () => {
  const h = createHarness()
  h.controller.animate()

  assert.equal(h.state.barAnimationToken, 1)
  assert.equal(h.state.renders[0], 0)
  assert.ok(h.state.barRafId)

  drainRaf(h.state, () => { h.state.now += 700 })
  assert.equal(h.state.renders.at(-1), 1)
  assert.equal(h.state.barRenderedOnce, true)
  assert.equal(h.state.barRafId, null)
  assert.ok(h.state.dataPatches.some(p => p.barRendering === false))
})

test('throttles intermediate redraws to at least 40ms', () => {
  const h = createHarness()
  h.controller.animate()
  h.state.now += 30
  const raf = h.state.barRafId
  h.state.barRafId = null
  raf.callback()
  const renderCount = h.state.renders.length

  h.state.now += 10
  const raf2 = h.state.barRafId
  h.state.barRafId = null
  raf2.callback()
  assert.equal(h.state.renders.length, renderCount)

  h.state.now += 35
  drainRaf(h.state, () => { h.state.now += 50 })
  assert.ok(h.state.renders.length > renderCount)
})

test('stops when the page is dead, hidden, or not in bar mode', () => {
  const dead = createHarness()
  dead.controller.animate()
  const raf = dead.state.barRafId
  dead.state.barRafId = null
  dead.state.alive = false
  raf.callback()
  assert.equal(dead.state.renders.length, 1)

  const hidden = createHarness()
  hidden.controller.animate()
  const raf2 = hidden.state.barRafId
  hidden.state.barRafId = null
  hidden.state.visible = false
  raf2.callback()
  assert.equal(hidden.state.renders.length, 1)

  const pie = createHarness()
  pie.controller.animate()
  const raf3 = pie.state.barRafId
  pie.state.barRafId = null
  pie.state.chartMode = 'pie'
  raf3.callback()
  assert.equal(pie.state.renders.length, 1)
})

test('stops when a newer animation token supersedes the current one', () => {
  const h = createHarness()
  h.controller.animate()
  const raf = h.state.barRafId
  h.state.barRafId = null
  h.state.barAnimationToken = 99
  raf.callback()
  assert.equal(h.state.renders.length, 1)
})
