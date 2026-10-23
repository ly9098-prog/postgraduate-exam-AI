const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  getCanvasPalette,
  LIGHT_PALETTE,
  DARK_PALETTE,
} = require('../subpackages/productivity/pomodoro-stats/canvas-palette')

test('returns the light palette only for light mode', () => {
  assert.equal(getCanvasPalette('light'), LIGHT_PALETTE)
})

test('falls back to the dark palette for non-light modes', () => {
  assert.equal(getCanvasPalette('dark'), DARK_PALETTE)
  assert.equal(getCanvasPalette(''), DARK_PALETTE)
  assert.equal(getCanvasPalette(undefined), DARK_PALETTE)
  assert.equal(getCanvasPalette(null), DARK_PALETTE)
})

test('light and dark palettes contain the same keys', () => {
  const lightKeys = Object.keys(LIGHT_PALETTE).sort()
  const darkKeys = Object.keys(DARK_PALETTE).sort()
  assert.deepEqual(lightKeys, darkKeys)
})

test('both palettes contain non-empty rgba color strings', () => {
  for (const palette of [LIGHT_PALETTE, DARK_PALETTE]) {
    for (const [key, value] of Object.entries(palette)) {
      assert.equal(typeof value, 'string', `${key} should be a string`)
      assert.match(value, /^rgba\(\d+,\d+,\d+,0?\.\d+\)$/, `${key} should be an rgba color`)
    }
  }
})
