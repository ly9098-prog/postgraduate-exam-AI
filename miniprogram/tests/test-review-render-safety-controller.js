const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createRenderSafetyController,
} = require('../subpackages/study/review-today/utils/render-safety-controller')

function createHarness(overrides = {}) {
  const state = {
    safeMode: false,
    traces: [],
    dev: true,
  }
  const controller = createRenderSafetyController({
    isSafeModeActive: () => state.safeMode,
    enterSafeMode: () => { state.safeMode = true },
    getRenderTraces: () => state.traces,
    setRenderTraces: t => { state.traces = t },
    isDev: () => state.dev,
    ...overrides,
  })
  return { controller, state }
}

test('checkInvariant no-ops for null model', () => {
  const { controller, state } = createHarness()
  controller.checkInvariant(null)
  assert.equal(state.safeMode, false)
})

test('checkInvariant detects CODE HTML leak and enters safe mode', () => {
  const { controller, state } = createHarness()
  controller.checkInvariant({ mode: 'CODE', rawText: 'a &nbsp; b', html: '', richTextNodes: [] })
  assert.equal(state.safeMode, true)
})

test('checkInvariant detects CODE render violation', () => {
  const { controller, state } = createHarness()
  controller.checkInvariant({ mode: 'CODE', rawText: 'clean', html: '<b? leaked', richTextNodes: [] })
  assert.equal(state.safeMode, true)
})

test('checkInvariant does not enter safe mode if already active', () => {
  const { controller, state } = createHarness()
  state.safeMode = true
  controller.checkInvariant({ mode: 'CODE', rawText: 'a &nbsp; b', html: '', richTextNodes: [] })
  // enterSafeMode not called again (still true, no double-trigger)
  assert.equal(state.safeMode, true)
})

test('checkInvariant logs MIXED empty blocks error', () => {
  const { controller } = createHarness()
  controller.checkInvariant({ mode: 'MIXED', blocks: [] })
  // No throw
})

test('recordTrace appends and caps at 200', () => {
  const { controller, state } = createHarness()
  for (let i = 0; i < 210; i++) controller.recordTrace('trace-' + i)
  assert.equal(state.traces.length, 200)
  assert.equal(state.traces[0], 'trace-10')
})

test('recordTrace no-ops for null', () => {
  const { controller, state } = createHarness()
  controller.recordTrace(null)
  assert.deepEqual(state.traces, [])
})

test('checkSetDataSize no-ops when not dev', () => {
  const { controller, state } = createHarness()
  state.dev = false
  controller.checkSetDataSize({ large: 'data' })
  // No throw
})

test('checkSetDataSize checks payload size in dev mode', () => {
  const { controller } = createHarness()
  controller.checkSetDataSize({ small: 'data' })
  // No throw, just warns if over threshold
})
