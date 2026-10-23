const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildPieSectors } = require('../subpackages/productivity/pomodoro-stats/pie-sector-builder')

const GEOMETRY = {
  w: 300,
  h: 200,
  centerX: 150,
  centerY: 98,
  radius: 64.5,
  tilt: 0.74,
  depth: 5.16,
}

test('builds sectors from positive-duration subjects only', () => {
  const subjects = [
    { subject: '101', duration_sec: 75, _color: '#3B82F6' },
    { subject: '202', duration_sec: 25, _color: '#F59E0B' },
    { subject: '303', duration_sec: 0, _color: '#10B981' },
  ]
  const { sectors } = buildPieSectors(subjects, GEOMETRY, () => '#000')
  assert.equal(sectors.length, 2)
  assert.equal(sectors[0].subject.subject, '101')
  assert.equal(sectors[0].pct, 0.75)
  assert.equal(sectors[1].pct, 0.25)
})

test('starts at twelve o’clock and produces continuous angles', () => {
  const { sectors } = buildPieSectors([
    { subject: '101', duration_sec: 75 },
    { subject: '202', duration_sec: 25 },
  ], GEOMETRY, () => '#000')
  assert.equal(sectors[0].startA, -Math.PI / 2)
  assert.equal(sectors[0].endA, sectors[1].startA)
  assert.equal(sectors[1].endA, -Math.PI / 2 + Math.PI * 2)
})

test('uses a denominator of at least one second', () => {
  const subjects = [{ subject: '101', duration_sec: 0 }]
  const { sectors } = buildPieSectors(subjects, GEOMETRY, () => '#000')
  assert.deepEqual(sectors, [])
})

test('keeps wall steps between five and seven', () => {
  const shallow = buildPieSectors([{ subject: '101', duration_sec: 1 }], { ...GEOMETRY, depth: 1 }, () => '#000')
  const deep = buildPieSectors([{ subject: '101', duration_sec: 1 }], { ...GEOMETRY, depth: 50 }, () => '#000')
  const normal = buildPieSectors([{ subject: '101', duration_sec: 1 }], GEOMETRY, () => '#000')
  assert.equal(shallow.wallSteps, 5)
  assert.equal(deep.wallSteps, 7)
  assert.equal(normal.wallSteps, 5)
})

test('computes one wall shade per layer using the shade helper', () => {
  const calls = []
  const shade = (hex, amount) => {
    calls.push({ hex, amount })
    return `${hex}-${amount}`
  }
  const subjects = [{ subject: '101', duration_sec: 1, _color: '#3B82F6' }]
  const { sectors, wallSteps } = buildPieSectors(subjects, GEOMETRY, shade)
  assert.equal(sectors[0]._wallShades.length, wallSteps)
  assert.equal(calls.length, wallSteps)
  assert.equal(sectors[0]._wallShades[0], '#3B82F6--44')
  assert.ok(calls.every(call => call.hex === '#3B82F6'))
})

test('returns a label layout for the built sectors', () => {
  const subjects = [{ subject: '101', duration_sec: 1, _color: '#3B82F6' }]
  const { labelLayout } = buildPieSectors(subjects, GEOMETRY, () => '#000')
  assert.equal(Array.isArray(labelLayout), true)
  assert.equal(labelLayout.length, 1)
  assert.equal(labelLayout[0].sec.subject.subject, '101')
})
