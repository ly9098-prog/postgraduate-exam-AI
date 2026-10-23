const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createStatsCanvasInitController,
} = require('../subpackages/productivity/pomodoro-stats/canvas-init-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    page: { name: 'page' },
    pieReady: false,
    piePending: false,
    pieCallbacks: [],
    trendReady: false,
    trendPending: false,
    trendCallbacks: [],
    trendMounted: true,
    queries: [],
    commits: [],
  }

  const options = {
    isAlive: () => state.alive,
    getPage: () => state.page,
    createQuery: () => ({
      in(page) {
        assert.equal(page, state.page)
        return this
      },
      select(selector) {
        state.queries.push(selector)
        return this
      },
      fields(fields) {
        assert.deepEqual(fields, { node: true, size: true })
        return this
      },
      exec(callback) {
        state.queries.push(callback)
      },
    }),
    getWindowInfo: () => ({ pixelRatio: 3 }),
    pieSelector: () => '#pie-canvas',
    trendSelector: () => '#trend-bars-canvas',
    isPieReady: () => state.pieReady,
    isPiePending: () => state.piePending,
    setPiePending: value => { state.piePending = value },
    getPieCallbacks: () => state.pieCallbacks,
    setPieCallbacks: value => { state.pieCallbacks = value },
    addPieCallback: callback => state.pieCallbacks.push(callback),
    commitPie: value => {
      state.pieReady = true
      state.commits.push(['pie', value])
    },
    isTrendMounted: () => state.trendMounted,
    isTrendReady: () => state.trendReady,
    isTrendPending: () => state.trendPending,
    setTrendPending: value => { state.trendPending = value },
    getTrendCallbacks: () => state.trendCallbacks,
    setTrendCallbacks: value => { state.trendCallbacks = value },
    addTrendCallback: callback => state.trendCallbacks.push(callback),
    commitTrend: value => {
      state.trendReady = true
      state.commits.push(['trend', value])
    },
    ...overrides,
  }
  return { controller: createStatsCanvasInitController(options), options, state }
}

function runQuery(state, result, canvas = {}) {
  const callback = state.queries.at(-1)
  callback(result ? [{ ...result, node: result.node || canvas }] : null)
}

test('initializes the pie canvas with the real device pixel ratio', () => {
  const harness = createHarness()
  const calls = []
  const canvas = {
    width: 0,
    height: 0,
    scaleCalls: [],
    ctx: { scale: (...args) => canvas.scaleCalls.push(args) },
    getContext: () => canvas.ctx,
  }

  harness.controller.initPie(() => calls.push('pie'))
  assert.equal(harness.state.piePending, true)
  runQuery(harness.state, { width: 100, height: 50 }, canvas)

  assert.deepEqual([canvas.width, canvas.height], [300, 150])
  assert.deepEqual(canvas.scaleCalls, [[3, 3]])
  assert.equal(harness.state.commits.length, 1)
  assert.equal(harness.state.commits[0][0], 'pie')
  const commit = harness.state.commits[0][1]
  assert.equal(commit.node, canvas)
  assert.equal(commit.ctx, canvas.ctx)
  assert.deepEqual(commit.rect, { width: 100, height: 50 })
  assert.equal(commit.dpr, 3)
  assert.deepEqual(calls, ['pie'])
  assert.equal(harness.state.piePending, false)
})

test('queues pie callbacks while initialization is pending and keeps zero-size nodes uncached', () => {
  const harness = createHarness()
  const calls = []
  harness.controller.initPie(() => calls.push('first'))
  harness.controller.initPie(() => calls.push('second'))
  assert.equal(harness.state.pieCallbacks.length, 2)

  const hiddenCanvas = { getContext: () => ({ scale() {} }) }
  runQuery(harness.state, { width: 0, height: 50 }, hiddenCanvas)
  assert.equal(harness.state.piePending, false)
  assert.deepEqual(calls, ['first', 'second'])
  assert.deepEqual(harness.state.commits, [])

  harness.controller.initPie(() => calls.push('third'))
  runQuery(harness.state, null)
  assert.deepEqual(calls, ['first', 'second', 'third'])
  assert.equal(harness.state.piePending, false)
})

test('initializes the trend canvas only after the user has mounted it', () => {
  const unmounted = createHarness()
  unmounted.state.trendMounted = false
  const calls = []
  unmounted.controller.initTrend(() => calls.push('unmounted'))
  assert.deepEqual(calls, ['unmounted'])
  assert.equal(unmounted.state.queries.length, 0)

  const harness = createHarness()
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ scale() {} }),
  }
  harness.controller.initTrend(() => calls.push('trend'))
  runQuery(harness.state, { width: 200, height: 40 }, canvas)

  assert.equal(harness.state.queries[0], '#trend-bars-canvas')
  assert.equal(harness.state.trendReady, true)
  assert.deepEqual(harness.state.commits[0][1].rect, { width: 200, height: 40 })
  assert.deepEqual(calls, ['unmounted', 'trend'])
})

test('skips existing canvases without issuing another query', () => {
  const harness = createHarness()
  harness.state.pieReady = true
  harness.state.trendReady = true
  const calls = []
  harness.controller.initPie(() => calls.push('pie'))
  harness.controller.initTrend(() => calls.push('trend'))
  assert.deepEqual(calls, ['pie', 'trend'])
  assert.equal(harness.state.queries.length, 0)
})
