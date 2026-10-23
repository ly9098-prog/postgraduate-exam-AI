const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildPieLabelLayout,
} = require('../subpackages/productivity/pomodoro-stats/pie-label-layout')

const GEOMETRY = {
  w: 320,
  h: 190,
  centerX: 160,
  centerY: 93,
  radius: 68,
  tilt: 0.74,
}

function sectors(count) {
  return Array.from({ length: count }, (_, index) => {
    const startA = (index / count) * Math.PI * 2
    const endA = ((index + 1) / count) * Math.PI * 2
    return { id: index, startA, endA }
  })
}

test('returns one badge per sector with geometry and sector identity', () => {
  const layout = buildPieLabelLayout(sectors(3), GEOMETRY)

  assert.equal(layout.length, 3)
  assert.deepEqual(layout.map(item => item.sec.id), [0, 1, 2])
  layout.forEach(item => {
    assert.equal(item.badgeW, 54)
    assert.equal(item.badgeH, 23)
    assert.equal(item.badgeX, item.badgeCenterX - 27)
    assert.equal(item.badgeY, item.badgeCenterY - 11.5)
  })
})

test('builds deterministic layouts with identical inputs', () => {
  const first = buildPieLabelLayout(sectors(7), GEOMETRY)
  const second = buildPieLabelLayout(sectors(7), GEOMETRY)

  assert.deepEqual(first, second)
})

test('resolves dense sector collisions while retaining order and bounds', () => {
  const layout = buildPieLabelLayout(sectors(24), GEOMETRY)

  assert.equal(layout.length, 24)
  assert.deepEqual(layout.map(item => item.index), Array.from({ length: 24 }, (_, i) => i))
  layout.forEach(item => {
    assert.ok(item.badgeX >= 6)
    assert.ok(item.badgeX <= GEOMETRY.w - 6 - 54)
    assert.ok(item.badgeY >= 8)
    assert.ok(item.badgeY <= GEOMETRY.h - 8 - 23)
    assert.ok(Number.isFinite(item.elbowX))
    assert.ok(Number.isFinite(item.elbowY))
    assert.ok(Number.isFinite(item.lineEndX))
    assert.ok(Number.isFinite(item.lineEndY))
  })

  let separated = 0
  for (let i = 0; i < layout.length; i++) {
    for (let j = i + 1; j < layout.length; j++) {
      const a = layout[i]
      const b = layout[j]
      const separatedX = Math.abs(a.badgeCenterX - b.badgeCenterX) >= 59
      const separatedY = Math.abs(a.badgeCenterY - b.badgeCenterY) >= 27
      if (separatedX || separatedY) separated += 1
    }
  }
  assert.ok(separated > 0)
})

test('places left and right sector badges on opposite sides of the pie', () => {
  const layout = buildPieLabelLayout([
    { id: 'left', startA: Math.PI - 0.2, endA: Math.PI + 0.2 },
    { id: 'right', startA: -0.2, endA: 0.2 },
  ], GEOMETRY)
  const byId = Object.fromEntries(layout.map(item => [item.sec.id, item]))

  assert.ok(byId.left.badgeCenterX < byId.right.badgeCenterX)
  assert.ok(byId.left.startX < GEOMETRY.centerX)
  assert.ok(byId.right.startX > GEOMETRY.centerX)
})

test('returns an empty layout without sectors', () => {
  assert.deepEqual(buildPieLabelLayout([], GEOMETRY), [])
})
