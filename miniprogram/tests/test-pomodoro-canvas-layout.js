const assert = require('node:assert/strict')
const {
  CANVAS_INIT_MAX_RETRIES,
  canvasRetryDelay,
  buildCanvasRect,
  isStageAligned,
  isRectStable,
  evaluateCanvasLayout,
  buildCanvasSetup,
} = require('../pages/pomodoro/utils/canvas-layout')

const stage = { left: 10, top: 20, width: 300, height: 300 }
const canvas = { node: {}, left: 10, top: 20, width: 300, height: 300 }

assert.equal(CANVAS_INIT_MAX_RETRIES, 16)
for (const [count, expected] of [[0, 16], [1, 24], [8, 80], [15, 136], [16, 140], [100, 140]]) {
  assert.equal(canvasRetryDelay(count), expected)
}
assert.equal(canvasRetryDelay(-1), 16)
assert.equal(canvasRetryDelay('invalid'), 16)

assert.deepEqual(buildCanvasRect(stage, canvas), {
  left: 10, top: 20, width: 300, height: 300,
})
assert.equal(buildCanvasRect(stage, { ...canvas, left: undefined, top: undefined }).left, 10)
for (const invalid of [
  null,
  {},
  { ...canvas, node: null },
  { ...canvas, width: 0 },
  { ...canvas, height: 0 },
]) {
  assert.equal(buildCanvasRect(stage, invalid), null)
}

assert.equal(isStageAligned(stage, stage), true)
assert.equal(isStageAligned({ ...stage, left: 12 }, stage), true)
assert.equal(isStageAligned({ ...stage, left: 12.01 }, stage), false)
assert.equal(isStageAligned({ ...stage, top: 17.9 }, stage), false)
assert.equal(isStageAligned({ ...stage, top: 18.01 }, stage), true)

assert.equal(isRectStable(stage, { ...stage, width: 301 }), true)
assert.equal(isRectStable(stage, { ...stage, width: 301.01 }), false)
assert.equal(isRectStable(stage, null), false)

assert.deepEqual(evaluateCanvasLayout(stage, null, null), { status: 'missing', rect: null })
assert.deepEqual(evaluateCanvasLayout(stage, canvas, null), { status: 'unstable', rect: stage })
assert.deepEqual(evaluateCanvasLayout(stage, { ...canvas, left: 13 }, stage), {
  status: 'misaligned',
  rect: { ...stage, left: 13 },
})
assert.deepEqual(evaluateCanvasLayout(stage, canvas, stage), { status: 'ready', rect: stage })

assert.deepEqual(buildCanvasSetup({ width: 300, height: 300 }, 2), {
  dpr: 2,
  width: 300,
  height: 300,
  size: 300,
  pixelWidth: 600,
  pixelHeight: 600,
})
assert.deepEqual(buildCanvasSetup({ width: 300, height: 260 }, 0), {
  dpr: 1,
  width: 300,
  height: 260,
  size: 260,
  pixelWidth: 300,
  pixelHeight: 260,
})
assert.deepEqual(buildCanvasSetup({ width: 301, height: 299 }, 1.5), {
  dpr: 1.5,
  width: 301,
  height: 299,
  size: 299,
  pixelWidth: 452,
  pixelHeight: 449,
})

console.log('Pomodoro canvas layout passed: retry/rect/alignment/stability/setup')
