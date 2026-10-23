const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createShadeColorCache } = require('../subpackages/productivity/pomodoro-stats/shade-color-cache')
const viewHelpers = require('../subpackages/productivity/pomodoro-stats/view-helpers')

function createCountingShadeFn() {
  const state = { calls: 0 }
  const fn = (hex, amount) => {
    state.calls += 1
    return viewHelpers.shadeColor(hex, amount)
  }
  return { fn, state }
}

test('caches the first computed value and returns it for repeated keys', () => {
  const { fn, state } = createCountingShadeFn()
  const cache = createShadeColorCache(fn)
  const first = cache.shade('#3B82F6', 12)
  const second = cache.shade('#3B82F6', 12)
  assert.equal(first, second)
  assert.equal(first, viewHelpers.shadeColor('#3B82F6', 12))
  assert.equal(state.calls, 1)
})

test('keeps separate entries for different colors and amounts', () => {
  const cache = createShadeColorCache()
  const a = cache.shade('#3B82F6', 12)
  const b = cache.shade('#3B82F6', -52)
  const c = cache.shade('#F59E0B', 12)
  assert.notEqual(a, b)
  assert.notEqual(a, c)
})

test('reset clears previously cached values', () => {
  const { fn, state } = createCountingShadeFn()
  const cache = createShadeColorCache(fn)
  const first = cache.shade('#3B82F6', 12)
  cache.reset()
  const second = cache.shade('#3B82F6', 12)
  assert.equal(first, second)
  assert.equal(state.calls, 2)
})

test('handles invalid colors the same as viewHelpers.shadeColor', () => {
  const cache = createShadeColorCache()
  assert.equal(cache.shade(null, 12), viewHelpers.shadeColor(null, 12))
  assert.equal(cache.shade('not-a-color', -10), viewHelpers.shadeColor('not-a-color', -10))
})

test('memoises falsy cached values without recomputation loops', () => {
  const cache = createShadeColorCache()
  const key = '#000000|0'
  const first = cache.shade('#000000', 0)
  const second = cache.shade('#000000', 0)
  assert.equal(first, second)
  assert.match(key, /^#[0-9a-fA-F]{6}\|-?\d+$/)
})
