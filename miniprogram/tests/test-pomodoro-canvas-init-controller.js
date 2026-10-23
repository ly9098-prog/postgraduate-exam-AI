const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCanvasInitController,
} = require('../pages/pomodoro/utils/canvas-init-controller')

function makeHarness(overrides = {}) {
  const state = {
    canvasReady: false,
    ctx: null,
    canvasInitPending: false,
    canvasInitSeq: 0,
    ringCache: { stale: true },
    data: { ringCanvasPaintReady: true },
    lastDrawnProgress: 0.2,
    lastDrawnIsBreak: false,
    lastDrawnAt: 123,
    dpr: 0,
    canvasSize: null,
    pendingDraw: { totalSec: 300, isBreak: false },
    retries: 0,
    scheduled: [],
    queries: [],
    selectorCalls: [],
  }

  const options = {
    canvasReady: () => state.canvasReady,
    getCtx: () => state.ctx,
    canvasInitPending: () => state.canvasInitPending,
    getCanvasInitSeq: () => state.canvasInitSeq,
    setCanvasInitSeq: value => { state.canvasInitSeq = value },
    setCanvasInitPending: value => { state.canvasInitPending = value },
    setCanvasReady: value => { state.canvasReady = value },
    setCtx: value => { state.ctx = value },
    setRingCache: value => { state.ringCache = value },
    ringCanvasPaintReady: () => state.data.ringCanvasPaintReady,
    setData: data => { Object.assign(state.data, data) },
    setLastDrawnProgress: value => { state.lastDrawnProgress = value },
    setLastDrawnIsBreak: value => { state.lastDrawnIsBreak = value },
    setLastDrawnAt: value => { state.lastDrawnAt = value },
    maxRetries: () => overrides.maxRetries ?? 16,
    nextTick: fn => state.scheduled.push(['nextTick', fn]),
    isPageVisible: () => overrides.pageVisible ?? true,
    createSelectorQuery: () => ({
      in: () => { throw new Error('in() is supplied by the page adapter') },
      select(selector) {
        state.selectorCalls.push(selector)
        return {
          boundingClientRect: () => this,
          fields: () => this,
        }
      },
      exec: callback => state.queries.push(callback),
    }),
    setTimeout: (fn, delay) => state.scheduled.push(['timeout', fn, delay]),
    getWindowInfo: () => ({ pixelRatio: overrides.pixelRatio ?? 3 }),
    setDpr: value => { state.dpr = value },
    setCanvasSize: value => { state.canvasSize = value },
    getPendingDraw: () => state.pendingDraw,
    setPendingDraw: value => { state.pendingDraw = value },
    drawRing: (totalSec, isBreak) => state.scheduled.push(['draw', totalSec, isBreak]),
  }
  return { options, state, get controller() { return createCanvasInitController(options) } }
}

test('init skips an existing canvas and an in-flight initialization', () => {
  const existing = makeHarness()
  existing.state.canvasReady = true
  existing.state.ctx = { ctx: true }
  existing.controller.init(false)
  assert.equal(existing.state.canvasInitSeq, 0)

  const inFlight = makeHarness()
  inFlight.state.canvasInitPending = true
  inFlight.controller.init(false)
  assert.equal(inFlight.state.canvasInitSeq, 0)
})

test('forced init invalidates canvas, cache and draw throttle state', () => {
  const h = makeHarness()
  h.controller.init(true)
  assert.equal(h.state.canvasInitSeq, 1)
  assert.equal(h.state.canvasInitPending, true)
  assert.equal(h.state.canvasReady, false)
  assert.equal(h.state.ctx, null)
  assert.equal(h.state.ringCache, null)
  assert.equal(h.state.data.ringCanvasPaintReady, false)
  assert.deepEqual(
    [h.state.lastDrawnProgress, h.state.lastDrawnIsBreak, h.state.lastDrawnAt],
    [undefined, undefined, 0],
  )
  assert.equal(h.state.scheduled.length, 1)
})

test('schedule ignores stale sequences, retry limits and hidden pages', () => {
  const stale = makeHarness()
  stale.controller.schedule(0, 1, null)
  assert.equal(stale.state.scheduled.length, 0)

  const limited = makeHarness()
  limited.controller.schedule(17, 0, null)
  assert.equal(limited.state.canvasInitPending, false)
  assert.equal(limited.state.scheduled.length, 0)

  const hidden = makeHarness({ pageVisible: false })
  hidden.controller.schedule(0, 0, null)
  assert.equal(hidden.state.scheduled.length, 1)
  hidden.state.canvasInitPending = true
  hidden.state.scheduled[0][1]()
  assert.equal(hidden.state.canvasInitPending, false)
  assert.equal(hidden.state.queries.length, 0)
})

test('successful initialization binds canvas state and flushes pending draw', () => {
  const h = makeHarness()
  const initialRect = { width: 100, height: 100, left: 0, top: 0 }
  h.controller.schedule(0, 0, initialRect)
  h.state.scheduled[0][1]()
  assert.deepEqual(h.state.selectorCalls, ['.ring-stage', '#progress-ring'])

  const canvas = {
    width: 0,
    height: 0,
    getContext: () => {
      const ctx = {}
      ctx.setTransform = (...args) => { ctx.transform = args }
      return ctx
    },
  }
  h.state.queries[0]([initialRect, { node: canvas, ...initialRect }])

  assert.deepEqual([canvas.width, canvas.height], [300, 300])
  assert.equal(h.state.dpr, 3)
  assert.equal(h.state.canvasSize, 100)
  assert.equal(h.state.canvasReady, true)
  assert.equal(h.state.canvasInitPending, false)
  assert.equal(h.state.ringCache, null)
  assert.deepEqual(h.state.scheduled.at(-1), ['draw', 300, false])
  assert.equal(h.state.pendingDraw, null)
})

test('unstable layout retries and accepts a stable repeated rect', () => {
  const h = makeHarness()
  h.controller.schedule(0, 0, null)
  const initialRect = { width: 100, height: 100, left: 0, top: 0 }
  h.state.scheduled[0][1]()
  h.state.queries[0]([initialRect, { node: { width: 0, height: 0 }, ...initialRect }])

  const timeout = h.state.scheduled.at(-1)
  assert.equal(timeout[0], 'timeout')
  assert.equal(timeout[2], 16)
  timeout[1]()
  const retry = h.state.scheduled.at(-1)
  assert.equal(retry[0], 'nextTick')
  retry[1]()
  const canvas = { width: 0, height: 0, getContext: () => ({ setTransform() {} }) }
  h.state.queries.at(-1)([initialRect, { node: canvas, ...initialRect }])
  assert.deepEqual([canvas.width, canvas.height], [300, 300])
  assert.equal(h.state.canvasReady, true)
  assert.equal(h.state.canvasInitPending, false)
})
