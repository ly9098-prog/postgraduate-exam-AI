const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createDrawRingController } = require('../pages/pomodoro/utils/draw-ring-controller')

function makeCtx() {
  const ops = []
  return {
    clearRect: (...a) => ops.push(['clearRect', ...a]),
    beginPath: () => ops.push(['beginPath']),
    stroke: () => ops.push(['stroke']),
    fill: () => ops.push(['fill']),
    arc: (...a) => ops.push(['arc', ...a]),
    set strokeStyle(v) { ops.push(['strokeStyle', v]) },
    set fillStyle(v) { ops.push(['fillStyle', v]) },
    set lineWidth(v) { ops.push(['lineWidth', v]) },
    set lineCap(v) { ops.push(['lineCap', v]) },
    set globalAlpha(v) { ops.push(['globalAlpha', v]) },
    ops,
  }
}

function makeHarness(overrides = {}) {
  const ctx = makeCtx()
  let ringCache = null
  let pendingDraw = null
  let lastDrawnProgress, lastDrawnIsBreak, lastDrawnAt = 0
  let data = { ringCanvasPaintReady: false }
  const options = {
    getCtx: () => overrides.ctx !== undefined ? overrides.ctx : ctx,
    setPendingDraw: v => { pendingDraw = v },
    isPageVisible: () => overrides.pageVisible ?? true,
    showEndConfirm: () => overrides.showEndConfirm ?? false,
    ringCanvasVisible: () => overrides.ringCanvasVisible ?? true,
    canvasInitPending: () => overrides.canvasInitPending ?? false,
    initCanvas: () => {},
    getProgress: () => overrides.progress ?? 0.5,
    now: () => 100000,
    getLastDrawnProgress: () => lastDrawnProgress,
    getLastDrawnIsBreak: () => lastDrawnIsBreak,
    getLastDrawnAt: () => lastDrawnAt,
    setLastDrawnProgress: v => { lastDrawnProgress = v },
    setLastDrawnIsBreak: v => { lastDrawnIsBreak = v },
    setLastDrawnAt: v => { lastDrawnAt = v },
    isFreeTimer: () => overrides.isFreeTimer ?? false,
    themeMode: () => overrides.themeMode ?? 'dark',
    getRingCache: () => ringCache,
    setRingCache: v => { ringCache = v },
    buildRingCache: () => ({ center: 100, radius: 50, lineWidth: 10, colors: { dot: '#fff' }, glowGrad: 'glow', grad: 'grad', size: 200 }),
    ringCanvasPaintReady: () => data.ringCanvasPaintReady,
    setData: d => { Object.assign(data, d) },
  }
  return { options, ctx, get pendingDraw() { return pendingDraw }, get data() { return data } }
}

test('draw sets pendingDraw when ctx is null', () => {
  const h = makeHarness({ ctx: null })
  createDrawRingController(h.options).draw(300, false)
  assert.ok(h.pendingDraw && h.pendingDraw.totalSec === 300 && h.pendingDraw.isBreak === false)
})

test('draw paints ring and reveals canvas when progress > 0', () => {
  const h = makeHarness({ progress: 0.5 })
  createDrawRingController(h.options).draw(300, false)
  assert.ok(h.ctx.ops.some(o => o[0] === 'arc'))
  assert.equal(h.data.ringCanvasPaintReady, true)
})

test('draw skips when progress unchanged', () => {
  const h = makeHarness({ progress: 0.5 })
  const ctrl = createDrawRingController(h.options)
  ctrl.draw(300, false)
  const ops1 = h.ctx.ops.length
  h.ctx.ops.length = 0
  ctrl.draw(300, false)
  assert.equal(h.ctx.ops.length, 0)
})

test('draw paints end dot when 0 < progress < 1', () => {
  const h = makeHarness({ progress: 0.5 })
  createDrawRingController(h.options).draw(300, false)
  assert.ok(h.ctx.ops.some(o => o[0] === 'fill'))
})
