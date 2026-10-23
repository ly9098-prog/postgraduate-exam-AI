const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createChartModeController,
} = require('../subpackages/productivity/pomodoro-stats/chart-mode-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    chartMode: 'pie',
    barCanvasMounted: false,
    barRenderedOnce: false,
    barAnimationToken: 0,
    patches: [],
    callbacks: [],
    timers: [],
    pieInitialized: false,
    trendInitialized: false,
    trendAnimated: false,
    trendRenders: [],
    pieRenders: [],
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getChartMode: () => state.chartMode,
    isBarMounted: () => state.barCanvasMounted,
    isBarRenderedOnce: () => state.barRenderedOnce,
    incrementBarAnimationToken: () => { state.barAnimationToken += 1 },
    setData: (patch, callback) => {
      state.patches.push(patch)
      Object.assign(state, patch)
      if (!callback) return
      if (options.hasNextTick()) options.nextTick(callback)
      else options.setTimeout(callback, 0)
    },
    hasNextTick: () => true,
    nextTick: callback => state.callbacks.push(callback),
    setTimeout: (callback, delay) => {
      const timer = { callback, delay }
      state.timers.push(timer)
      return timer
    },
    initCanvases: callback => { state.pieInitialized = true; callback() },
    renderPie: progress => state.pieRenders.push(progress),
    initTrendCanvas: callback => { state.trendInitialized = true; callback() },
    animateTrendOnly: () => { state.trendAnimated = true },
    renderTrendBars: progress => state.trendRenders.push(progress),
    isFirstMount: () => !state.barRenderedOnce,
    ...overrides,
  }
  return { controller: createChartModeController(options), options, state }
}

function flush(state) {
  while (state.callbacks.length) state.callbacks.shift()()
}

test('switches from bar to pie and draws the final pie', () => {
  const harness = createHarness()
  harness.state.chartMode = 'bar'
  harness.state.barCanvasMounted = true
  harness.state.barRenderedOnce = true
  harness.controller.toggle()

  assert.equal(harness.state.barAnimationToken, 1)
  assert.deepEqual(harness.state.patches, [{ chartMode: 'pie', barRendering: false }])
  flush(harness.state)
  assert.equal(harness.state.pieInitialized, true)
  assert.deepEqual(harness.state.pieRenders, [1])
  assert.equal(harness.state.trendInitialized, false)
})

test('lazily mounts the bar canvas and starts its first animation', () => {
  const harness = createHarness()
  harness.controller.toggle()

  assert.deepEqual(harness.state.patches, [{
    chartMode: 'bar',
    barCanvasMounted: true,
    barRendering: true,
    selectedSubjectDetail: null,
    _selectedSubject: null,
  }])
  assert.equal(harness.state.chartMode, 'bar')
  flush(harness.state)
  assert.equal(harness.state.trendInitialized, true)
  assert.equal(harness.state.trendAnimated, true)
  assert.deepEqual(harness.state.trendRenders, [])
  assert.equal(harness.state.pieInitialized, false)
})

test('renders an already rendered bar immediately when returning to bar mode', () => {
  const harness = createHarness()
  harness.state.barCanvasMounted = true
  harness.state.barRenderedOnce = true
  harness.controller.toggle()
  flush(harness.state)

  assert.equal(harness.state.barRendering, false)
  assert.equal(harness.state.trendAnimated, false)
  assert.deepEqual(harness.state.trendRenders, [1])
})

test('falls back to setTimeout when nextTick is unavailable', () => {
  const harness = createHarness()
  harness.state.chartMode = 'bar'
  harness.state.barCanvasMounted = true
  harness.options.hasNextTick = () => false
  harness.controller.toggle()

  assert.equal(harness.state.callbacks.length, 0)
  assert.equal(harness.state.timers.length, 1)
  assert.equal(harness.state.timers[0].delay, 0)
  harness.state.timers[0].callback()
  assert.equal(harness.state.timers.length, 2)
  harness.state.timers[1].callback()
  assert.deepEqual(harness.state.pieRenders, [1])
})

test('stops drawing after the page dies, hides, or changes mode', () => {
  const dead = createHarness()
  dead.state.chartMode = 'bar'
  dead.controller.toggle()
  dead.state.alive = false
  flush(dead.state)
  assert.equal(dead.state.pieInitialized, false)

  const hidden = createHarness()
  hidden.controller.toggle()
  hidden.state.visible = false
  flush(hidden.state)
  assert.equal(hidden.state.trendInitialized, false)

  const modeChanged = createHarness()
  modeChanged.state.barCanvasMounted = true
  modeChanged.state.barRenderedOnce = true
  modeChanged.controller.toggle()
  modeChanged.state.chartMode = 'pie'
  flush(modeChanged.state)
  assert.equal(modeChanged.state.trendInitialized, false)
  assert.deepEqual(modeChanged.state.trendRenders, [])
})
