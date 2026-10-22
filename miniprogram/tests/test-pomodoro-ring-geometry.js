const assert = require('node:assert/strict')
const {
  RING_PADDING,
  buildRingColors,
  buildRingGeometry,
  buildRingCache,
  shouldDrawRing,
} = require('../pages/pomodoro/utils/ring-geometry')

assert.deepEqual(buildRingColors(true, true), {
  start: '#F43F5E', end: '#F97316', dot: '#F97316',
})
assert.deepEqual(buildRingColors(false, true), {
  start: '#34D399', end: '#059669', dot: '#10B981',
})
assert.deepEqual(buildRingColors(false, false), {
  start: '#06B6D4', end: '#3B82F6', dot: '#3B82F6',
})

assert.deepEqual(buildRingGeometry(360), {
  size: 360,
  center: 180,
  radius: 162,
  lineWidth: 12,
})
assert.equal(buildRingGeometry(360).radius, 180 - RING_PADDING)
assert.deepEqual(buildRingGeometry(null), {
  size: 0,
  center: 0,
  radius: 0,
  lineWidth: 12,
})

const stops = []
const ctx = {
  createLinearGradient(x0, y0, x1, y1) {
    const gradient = { x0, y0, x1, y1, stops }
    return {
      addColorStop(offset, color) { stops.push([offset, color]) },
      gradient,
    }
  },
}
const cache = buildRingCache(ctx, 100, false, true)
assert.equal(cache.size, 100)
assert.equal(cache.center, 50)
assert.equal(cache.radius, 32)
assert.equal(cache.colors.start, '#34D399')
assert.equal(cache.glowGrad.gradient.x1, 100)
assert.deepEqual(stops, [
  [0, '#34D399'], [1, '#059669'],
  [0, '#34D399'], [1, '#059669'],
])
assert.equal(buildRingCache(null, 100, false, false), null)

const previous = { progress: 0.5, isBreak: false, totalSec: 1500, at: 1000 }
assert.equal(shouldDrawRing(0.5, true, previous, 1100), true)
assert.equal(shouldDrawRing(0.5001, false, previous, 1100), false)
assert.equal(shouldDrawRing(0.5001, false, previous, 2000), true)
assert.equal(shouldDrawRing(0.503, false, { ...previous, totalSec: 360 }, 1100), true)
assert.equal(shouldDrawRing(0.5, false, null, 1000), true)
assert.equal(shouldDrawRing(0.5, false, { progress: undefined, isBreak: false }, 1000), true)

console.log('Pomodoro ring geometry passed: colors/geometry/cache/throttle')
