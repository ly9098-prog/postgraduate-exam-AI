const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPieAnimationController,
} = require('../subpackages/productivity/pomodoro-stats/pie-animation-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    pieCtx: {},
    pieRect: { width: 300, height: 200 },
    pieCanvasNode: null,
    pieAnimationToken: 0,
    pieLabelToken: 0,
    pieDateRafId: null,
    now: 1000,
    renders: [],
    revealed: 0,
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getPieCtx: () => state.pieCtx,
    getPieRect: () => state.pieRect,
    getPieCanvasNode: () => state.pieCanvasNode,
    getPieAnimationToken: () => state.pieAnimationToken,
    incrementPieAnimationToken: () => { state.pieAnimationToken += 1; return state.pieAnimationToken },
    incrementPieLabelToken: () => { state.pieLabelToken += 1 },
    setPieDateRafId: id => { state.pieDateRafId = id },
    now: () => state.now,
    setTimeout: (callback, delay) => {
      const handle = { callback, delay }
      state.pieDateRafId = handle
      return handle
    },
    renderPie: (progress, includeLabels) => state.renders.push({ progress, includeLabels }),
    revealPieLabelsIncrementally: () => { state.revealed += 1 },
    ...overrides,
  }
  return { controller: createPieAnimationController(options), options, state }
}

function drainRaf(state, advanceTime) {
  while (state.pieDateRafId) {
    const raf = state.pieDateRafId
    state.pieDateRafId = null
    advanceTime()
    raf.callback()
  }
}

test('does nothing when the pie canvas is not ready', () => {
  const noCtx = createHarness()
  noCtx.state.pieCtx = null
  noCtx.controller.animate()

  const noRect = createHarness()
  noRect.state.pieRect = null
  noRect.controller.animate()

  for (const harness of [noCtx, noRect]) {
    assert.equal(harness.state.pieAnimationToken, 0)
    assert.equal(harness.state.pieLabelToken, 0)
    assert.deepEqual(harness.state.renders, [])
    assert.equal(harness.state.revealed, 0)
  }
})

test('animates the date pie to completion without labels in motion frames', () => {
  const harness = createHarness()
  harness.controller.animate()

  assert.equal(harness.state.pieAnimationToken, 1)
  assert.equal(harness.state.pieLabelToken, 1)
  assert.deepEqual(harness.state.renders[0], { progress: 0, includeLabels: false })
  assert.ok(harness.state.pieDateRafId)

  drainRaf(harness.state, () => { harness.state.now += 500 })

  assert.deepEqual(harness.state.renders.at(-1), { progress: 1, includeLabels: false })
  assert.equal(harness.state.pieDateRafId, null)
  assert.equal(harness.state.revealed, 1)
  assert.ok(harness.state.renders.slice(1, -1).every(render => !render.includeLabels))
})

test('throttles intermediate date-pie frames to at least 28ms', () => {
  const harness = createHarness()
  harness.controller.animate()
  harness.state.now += 30
  const firstRaf = harness.state.pieDateRafId
  harness.state.pieDateRafId = null
  firstRaf.callback()
  const renderCount = harness.state.renders.length

  harness.state.now += 10
  const throttledRaf = harness.state.pieDateRafId
  harness.state.pieDateRafId = null
  throttledRaf.callback()
  assert.equal(harness.state.renders.length, renderCount)

  harness.state.now += 20
  drainRaf(harness.state, () => { harness.state.now += 50 })
  assert.ok(harness.state.renders.length > renderCount)
})

test('uses canvas requestAnimationFrame when available', () => {
  const harness = createHarness()
  let rafCalls = 0
  harness.state.pieCanvasNode = {
    requestAnimationFrame(callback) {
      rafCalls += 1
      const handle = { callback }
      harness.state.pieDateRafId = handle
      return handle
    },
  }
  harness.controller.animate()

  assert.equal(rafCalls, 1)
  assert.ok(harness.state.pieDateRafId)
})

test('stops when the page is dead, hidden, or a newer animation starts', () => {
  const dead = createHarness()
  dead.controller.animate()
  const deadRaf = dead.state.pieDateRafId
  dead.state.pieDateRafId = null
  dead.state.alive = false
  deadRaf.callback()
  assert.equal(dead.state.renders.length, 1)
  assert.equal(dead.state.revealed, 0)

  const hidden = createHarness()
  hidden.controller.animate()
  const hiddenRaf = hidden.state.pieDateRafId
  hidden.state.pieDateRafId = null
  hidden.state.visible = false
  hiddenRaf.callback()
  assert.equal(hidden.state.renders.length, 1)
  assert.equal(hidden.state.revealed, 0)

  const stale = createHarness()
  stale.controller.animate()
  const staleRaf = stale.state.pieDateRafId
  stale.state.pieDateRafId = null
  stale.state.pieAnimationToken += 1
  staleRaf.callback()
  assert.equal(stale.state.renders.length, 1)
  assert.equal(stale.state.revealed, 0)
})
