const assert = require('node:assert/strict')
const { test } = require('node:test')
const { renderPieChart } = require('../subpackages/productivity/pomodoro-stats/pie-renderer')

function createRecordingCtx() {
  const calls = []
  const gradient = { addColorStop(offset, color) { calls.push({ name: 'addColorStop', offset, color }) } }
  const ctx = {
    save() { calls.push({ name: 'save' }) },
    restore() { calls.push({ name: 'restore' }) },
    clearRect(x, y, w, h) { calls.push({ name: 'clearRect', x, y, w, h }) },
    translate(x, y) { calls.push({ name: 'translate', x, y }) },
    scale(x, y) { calls.push({ name: 'scale', x, y }) },
    createRadialGradient(...args) { calls.push({ name: 'createRadialGradient', args }); return gradient },
    beginPath() { calls.push({ name: 'beginPath' }) },
    arc(x, y, r, startA, endA) { calls.push({ name: 'arc', x, y, r, startA, endA }) },
    moveTo(x, y) { calls.push({ name: 'moveTo', x, y }) },
    lineTo(x, y) { calls.push({ name: 'lineTo', x, y }) },
    fill() { calls.push({ name: 'fill' }) },
    stroke() { calls.push({ name: 'stroke' }) },
    clip() { calls.push({ name: 'clip' }) },
    fillText(text, x, y) { calls.push({ name: 'fillText', text, x, y }) },
    quadraticCurveTo(c1x, c1y, x, y) { calls.push({ name: 'quadraticCurveTo', c1x, c1y, x, y }) },
    closePath() { calls.push({ name: 'closePath' }) },
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

const PALETTE = {
  badgeFill: '#fff',
  badgeText: '#000',
  shadowStart: 'rgba(0,0,0,0.25)',
  shadowMid: 'rgba(0,0,0,0.10)',
  separator: 'rgba(0,0,0,0.18)',
  selectedMask: 'rgba(0,0,0,0.7)',
}

function baseOptions(ctx, overrides = {}) {
  return {
    ctx,
    rect: { width: 300, height: 200 },
    subjects: [
      { subject: 101, duration_sec: 75, _color: '#3B82F6', _durationBadgeText: '1时15分' },
      { subject: 202, duration_sec: 25, _color: '#F59E0B', _durationBadgeText: '0时25分' },
    ],
    themeMode: 'dark',
    dpr: 2,
    selectedSubject: null,
    progress: 1,
    includeLabels: true,
    cache: {},
    palette: PALETTE,
    shade: (hex, amount) => `${hex}:${amount}`,
    ...overrides,
  }
}

test('does nothing without a context or sized rect', () => {
  const { ctx } = createRecordingCtx()
  renderPieChart(baseOptions(null))
  renderPieChart(baseOptions(ctx, { rect: null }))
  renderPieChart(baseOptions(ctx, { rect: { width: 0, height: 100 } }))
})

test('clears the canvas and returns on an empty distribution', () => {
  const { ctx, calls } = createRecordingCtx()
  renderPieChart(baseOptions(ctx, { subjects: [] }))
  assert.equal(calls.filter(c => c.name === 'clearRect').length, 1)
  assert.equal(calls.some(c => c.name === 'createRadialGradient'), false)
})

test('builds and reuses the sector cache', () => {
  const { ctx } = createRecordingCtx()
  const options = baseOptions(ctx)
  renderPieChart(options)
  assert.ok(options.cache.sectors.length === 2)
  assert.ok(options.cache.wallSteps >= 5)
  assert.ok(Array.isArray(options.cache.labelLayout))
  const sectors = options.cache.sectors
  renderPieChart(options)
  assert.equal(options.cache.sectors, sectors)
})

test('renders shadow, separators, lighting and labels at full progress', () => {
  const { ctx, calls } = createRecordingCtx()
  renderPieChart(baseOptions(ctx))
  assert.equal(calls.filter(c => c.name === 'createRadialGradient').length, 2)
  assert.ok(calls.some(c => c.name === 'fillText'))
  assert.ok(calls.some(c => c.name === 'strokeStyle' && c.value === PALETTE.separator))
})

test('skips completion effects before the reveal threshold', () => {
  const { ctx, calls } = createRecordingCtx()
  renderPieChart(baseOptions(ctx, { progress: 0.4, includeLabels: true }))
  assert.equal(calls.some(c => c.name === 'createRadialGradient'), false)
  assert.equal(calls.some(c => c.name === 'fillText'), false)
})

test('sorts selected sector last and masks the unselected sectors', () => {
  const { ctx, calls } = createRecordingCtx()
  const options = baseOptions(ctx, { selectedSubject: 202 })
  renderPieChart(options)
  assert.ok(calls.some(c => c.name === 'fillStyle' && c.value === PALETTE.selectedMask))
  assert.ok(calls.some(c => c.name === 'fillStyle' && c.value === '#F59E0B:12'))
})

test('skips selected mask when reveal is below 0.9', () => {
  const { ctx, calls } = createRecordingCtx()
  renderPieChart(baseOptions(ctx, { selectedSubject: 202, progress: 0.85 }))
  assert.equal(calls.some(c => c.name === 'fillStyle' && c.value === PALETTE.selectedMask), false)
})
