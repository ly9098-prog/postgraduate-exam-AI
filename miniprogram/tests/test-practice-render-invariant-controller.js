const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createRenderInvariantController,
} = require('../subpackages/study/practice/utils/render-invariant-controller')

function createHarness(overrides = {}) {
  const state = { safeModeEntered: false }
  const controller = createRenderInvariantController({
    isSafeModeActive: () => state.safeModeEntered,
    enterSafeMode: () => { state.safeModeEntered = true },
    ...overrides,
  })
  return { controller, state }
}

test('no-op for null render model', () => {
  const { controller } = createHarness()
  controller.check(null)
  // No error thrown, no safe mode
})

test('valid single-mode model passes silently', () => {
  const { controller, state } = createHarness()
  controller.check({ mode: 'RICH_TEXT', html: '', richTextNodes: [] })
  assert.equal(state.safeModeEntered, false)
})

test('CODE mode with HTML entities triggers safe mode', () => {
  const { controller, state } = createHarness()
  controller.check({
    mode: 'CODE',
    rawText: 'some &nbsp; text',
    html: '',
    richTextNodes: [],
  })
  assert.equal(state.safeModeEntered, true)
})

test('CODE mode with render violation triggers safe mode', () => {
  const { controller, state } = createHarness()
  controller.check({
    mode: 'CODE',
    rawText: 'clean text',
    html: '<span>leaked</span>',
    richTextNodes: [],
  })
  assert.equal(state.safeModeEntered, true)
})

test('CODE mode violation does not trigger safe mode if already in safe mode', () => {
  const { controller, state } = createHarness()
  state.safeModeEntered = true
  controller.check({
    mode: 'CODE',
    rawText: 'some &nbsp; text',
    html: '',
    richTextNodes: [],
  })
  // enterSafeMode should not be called again
  assert.equal(state.safeModeEntered, true)
})

test('MIXED mode with empty blocks logs error', () => {
  const { controller } = createHarness()
  // Should not throw
  controller.check({ mode: 'MIXED', blocks: [] })
})

test('MIXED mode with CODE block containing HTML entities logs error', () => {
  const { controller } = createHarness()
  controller.check({
    mode: 'MIXED',
    blocks: [
      { type: 'TEXT', rawText: 'hello' },
      { type: 'CODE', rawText: 'code &amp; text' },
    ],
  })
  // No throw, just console.error
})
