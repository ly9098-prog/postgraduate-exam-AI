const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  getPieGeometry,
  drawEllipticSector,
  roundRectPath,
} = require('../subpackages/productivity/pomodoro-stats/pie-geometry')

function createRecordingCtx() {
  const calls = []
  const ctx = {
    save() { calls.push({ name: 'save' }) },
    restore() { calls.push({ name: 'restore' }) },
    translate(x, y) { calls.push({ name: 'translate', x, y }) },
    scale(x, y) { calls.push({ name: 'scale', x, y }) },
    beginPath() { calls.push({ name: 'beginPath' }) },
    moveTo(x, y) { calls.push({ name: 'moveTo', x, y }) },
    arc(x, y, r, startA, endA) { calls.push({ name: 'arc', x, y, r, startA, endA }) },
    closePath() { calls.push({ name: 'closePath' }) },
    fill() { calls.push({ name: 'fill' }) },
    stroke() { calls.push({ name: 'stroke' }) },
    quadraticCurveTo(c1x, c1y, x, y) { calls.push({ name: 'quadraticCurveTo', c1x, c1y, x, y }) },
    lineTo(x, y) { calls.push({ name: 'lineTo', x, y }) },
    set fillStyle(value) { calls.push({ name: 'fillStyle', value }) },
    set strokeStyle(value) { calls.push({ name: 'strokeStyle', value }) },
    set lineWidth(value) { calls.push({ name: 'lineWidth', value }) },
  }
  return { ctx, calls }
}

test('getPieGeometry returns centered geometry with side gutters and fixed tilt', () => {
  const geometry = getPieGeometry({ width: 400, height: 600 })
  assert.equal(geometry.w, 400)
  assert.equal(geometry.h, 600)
  assert.equal(geometry.centerX, 200)
  assert.equal(geometry.centerY, 294)
  assert.equal(geometry.radius, Math.min(400 * 0.215, 600 * 0.275))
  assert.equal(geometry.tilt, 0.74)
  assert.equal(geometry.depth, geometry.radius * 0.08)
})

test('getPieGeometry clamps radius to the shorter dimension', () => {
  const tall = getPieGeometry({ width: 200, height: 1000 })
  assert.equal(tall.radius, 200 * 0.215)
  const wide = getPieGeometry({ width: 1000, height: 100 })
  assert.equal(wide.radius, 100 * 0.275)
})

test('drawEllipticSector saves, scales by scaleY and restores', () => {
  const { ctx, calls } = createRecordingCtx()
  drawEllipticSector(ctx, 10, 20, 30, 0.74, 0, 1.5, '#fff', null, null)

  const saveIndex = calls.findIndex(c => c.name === 'save')
  const scaleIndex = calls.findIndex(c => c.name === 'scale')
  const restoreIndex = calls.findIndex(c => c.name === 'restore')
  assert.ok(saveIndex < scaleIndex && scaleIndex < restoreIndex)
  assert.deepEqual(calls[scaleIndex], { name: 'scale', x: 1, y: 0.74 })
})

test('drawEllipticSector fills only when a fill style is supplied', () => {
  const fillOnly = createRecordingCtx()
  drawEllipticSector(fillOnly.ctx, 0, 0, 10, 1, 0, 1, '#fff', null, null)
  assert.ok(fillOnly.calls.some(c => c.name === 'fillStyle' && c.value === '#fff'))
  assert.equal(fillOnly.calls.some(c => c.name === 'stroke'), false)

  const strokeOnly = createRecordingCtx()
  drawEllipticSector(strokeOnly.ctx, 0, 0, 10, 1, 0, 1, null, '#000', 2)
  assert.ok(strokeOnly.calls.some(c => c.name === 'strokeStyle' && c.value === '#000'))
  assert.ok(strokeOnly.calls.some(c => c.name === 'lineWidth' && c.value === 2))
  assert.equal(strokeOnly.calls.some(c => c.name === 'fill'), false)
})

test('drawEllipticSector defaults lineWidth to 1 when strokeStyle is set without lineW', () => {
  const { ctx, calls } = createRecordingCtx()
  drawEllipticSector(ctx, 0, 0, 10, 1, 0, 1, null, '#000')
  assert.ok(calls.some(c => c.name === 'lineWidth' && c.value === 1))
})

test('roundRectPath clamps radius to half the smallest dimension', () => {
  const { ctx, calls } = createRecordingCtx()
  roundRectPath(ctx, 0, 0, 100, 50, 30)

  // radius 30 would exceed 50/2 = 25, so clamp to 25.
  const moveTo = calls.find(c => c.name === 'moveTo')
  assert.deepEqual(moveTo, { name: 'moveTo', x: 25, y: 0 })
})

test('roundRectPath traces four corners with quadratic curves', () => {
  const { ctx, calls } = createRecordingCtx()
  roundRectPath(ctx, 0, 0, 10, 10, 2)
  const curves = calls.filter(c => c.name === 'quadraticCurveTo')
  assert.equal(curves.length, 4)
})

test('roundRectPath uses the supplied radius when it fits', () => {
  const { ctx, calls } = createRecordingCtx()
  roundRectPath(ctx, 0, 0, 100, 100, 10)
  const moveTo = calls.find(c => c.name === 'moveTo')
  assert.deepEqual(moveTo, { name: 'moveTo', x: 10, y: 0 })
})
