const assert = require('node:assert/strict')
const { test } = require('node:test')
const { drawPieLabels } = require('../subpackages/productivity/pomodoro-stats/pie-label-renderer')

function createRecordingCtx() {
  const calls = []
  const ctx = {
    save() { calls.push({ name: 'save' }) },
    restore() { calls.push({ name: 'restore' }) },
    beginPath() { calls.push({ name: 'beginPath' }) },
    moveTo(x, y) { calls.push({ name: 'moveTo', x, y }) },
    lineTo(x, y) { calls.push({ name: 'lineTo', x, y }) },
    arc(x, y, r, startA, endA) { calls.push({ name: 'arc', x, y, r, startA, endA }) },
    quadraticCurveTo(c1x, c1y, x, y) { calls.push({ name: 'quadraticCurveTo', c1x, c1y, x, y }) },
    closePath() { calls.push({ name: 'closePath' }) },
    fill() { calls.push({ name: 'fill' }) },
    stroke() { calls.push({ name: 'stroke' }) },
    fillText(text, x, y) { calls.push({ name: 'fillText', text, x, y }) },
    set fillStyle(value) { calls.push({ name: 'fillStyle', value }) },
    set strokeStyle(value) { calls.push({ name: 'strokeStyle', value }) },
    set lineWidth(value) { calls.push({ name: 'lineWidth', value }) },
    set globalAlpha(value) { calls.push({ name: 'globalAlpha', value }) },
    set font(value) { calls.push({ name: 'font', value }) },
    set textAlign(value) { calls.push({ name: 'textAlign', value }) },
    set textBaseline(value) { calls.push({ name: 'textBaseline', value }) },
    set lineCap(value) { calls.push({ name: 'lineCap', value }) },
    set lineJoin(value) { calls.push({ name: 'lineJoin', value }) },
  }
  return { ctx, calls }
}

const LAYOUT = [{
  sec: {
    color: '#3B82F6',
    subject: { _durationBadgeText: '1时20分' },
  },
  startX: 10,
  startY: 20,
  elbowX: 30,
  elbowY: 40,
  lineEndX: 50,
  lineEndY: 60,
  badgeX: 50.25,
  badgeY: 60.5,
  badgeW: 40,
  badgeH: 18,
}]

test('draws each label with an elbow line, dot, badge and text', () => {
  const { ctx, calls } = createRecordingCtx()
  drawPieLabels(ctx, LAYOUT, 1, { badgeFill: '#fff', badgeText: '#000' }, 1)

  assert.equal(calls.filter(c => c.name === 'moveTo').length, 2)
  assert.equal(calls.filter(c => c.name === 'fillText').length, 1)
  assert.equal(calls[0].name, 'save')
  assert.equal(calls.at(-1).name, 'restore')
})

test('snaps badge positions and horizontal glyph origin to device pixels', () => {
  const { ctx, calls } = createRecordingCtx()
  drawPieLabels(ctx, LAYOUT, 1, { badgeFill: '#fff', badgeText: '#000' }, 2)

  const moveTos = calls.filter(c => c.name === 'moveTo')
  assert.equal(moveTos[0].x, 10)
  assert.equal(moveTos[0].y, 20)
  const text = calls.find(c => c.name === 'fillText')
  assert.equal(text.x, 70.5)
})

test('defaults DPR to 1 when omitted or invalid', () => {
  const { ctx: ctxA, calls: callsA } = createRecordingCtx()
  drawPieLabels(ctxA, LAYOUT, 1, { badgeFill: '#fff', badgeText: '#000' })
  const textA = callsA.find(c => c.name === 'fillText')
  assert.equal(textA.x, 70)

  const { ctx: ctxB, calls: callsB } = createRecordingCtx()
  drawPieLabels(ctxB, LAYOUT, 1, { badgeFill: '#fff', badgeText: '#000' }, null)
  const textB = callsB.find(c => c.name === 'fillText')
  assert.equal(textB.x, 70)
})

test('skips empty layouts and non-positive reveal without touching the context', () => {
  for (const [layout, reveal] of [[[], 1], [LAYOUT, 0], [LAYOUT, -1]]) {
    const { ctx, calls } = createRecordingCtx()
    drawPieLabels(ctx, layout, reveal, { badgeFill: '#fff', badgeText: '#000' }, 1)
    assert.deepEqual(calls, [])
  }
})

test('supports a bounded slice for incremental reveal', () => {
  const layout = [
    LAYOUT[0],
    { ...LAYOUT[0], sec: { ...LAYOUT[0].sec, color: '#F59E0B' } },
  ]
  const { ctx, calls } = createRecordingCtx()
  drawPieLabels(ctx, layout, 1, { badgeFill: '#fff', badgeText: '#000' }, 1, 1, 2)
  assert.equal(calls.filter(c => c.name === 'fillText').length, 1)
  assert.ok(calls.some(c => c.name === 'strokeStyle' && c.value === '#F59E0B'))
})
