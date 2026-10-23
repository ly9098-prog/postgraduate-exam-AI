const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPieLabelRevealController,
} = require('../subpackages/productivity/pomodoro-stats/pie-label-reveal-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    pieCtx: {},
    pieRect: { width: 300, height: 200 },
    pieCanvasNode: null,
    labelLayout: [{ id: 1 }, { id: 2 }, { id: 3 }],
    geometry: { cx: 150 },
    pieLabelToken: 0,
    pieLabelRafId: null,
    draws: [],
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getPieCtx: () => state.pieCtx,
    getPieRect: () => state.pieRect,
    getPieCanvasNode: () => state.pieCanvasNode,
    getLabelLayout: () => state.labelLayout,
    getPieLabelToken: () => state.pieLabelToken,
    incrementPieLabelToken: () => { state.pieLabelToken += 1; return state.pieLabelToken },
    setPieLabelRafId: id => { state.pieLabelRafId = id },
    getGeometry: rect => ({ ...state.geometry, rect }),
    setTimeout: (callback, delay) => {
      const handle = { callback, delay }
      state.pieLabelRafId = handle
      return handle
    },
    drawPieLabels: (ctx, geometry, layout, reveal, start, end) => {
      state.draws.push({ ctx, geometry, layout, reveal, start, end })
    },
    ...overrides,
  }
  return { controller: createPieLabelRevealController(options), options, state }
}

function drainRaf(state) {
  while (state.pieLabelRafId) {
    const raf = state.pieLabelRafId
    state.pieLabelRafId = null
    raf.callback()
  }
}

test('does nothing without canvas state or labels', () => {
  for (const key of ['pieCtx', 'pieRect', 'labelLayout']) {
    const harness = createHarness()
    harness.state[key] = null
    harness.controller.reveal()
    assert.equal(harness.state.pieLabelToken, 0)
    assert.equal(harness.state.pieLabelRafId, null)
    assert.deepEqual(harness.state.draws, [])
  }

  const empty = createHarness()
  empty.state.labelLayout = []
  empty.controller.reveal()
  assert.equal(empty.state.pieLabelToken, 0)
  assert.deepEqual(empty.state.draws, [])
})

test('reveals labels in pairs until the layout is complete', () => {
  const harness = createHarness()
  harness.controller.reveal()

  assert.equal(harness.state.pieLabelToken, 1)
  assert.ok(harness.state.pieLabelRafId)
  drainRaf(harness.state)

  assert.deepEqual(harness.state.draws.map(draw => [draw.start, draw.end]), [[0, 2], [2, 3]])
  assert.ok(harness.state.draws.every(draw => draw.reveal === 1))
  assert.equal(harness.state.pieLabelRafId, null)
})

test('uses canvas requestAnimationFrame when available', () => {
  const harness = createHarness()
  let rafCalls = 0
  harness.state.pieCanvasNode = {
    requestAnimationFrame(callback) {
      rafCalls += 1
      const handle = { callback }
      harness.state.pieLabelRafId = handle
      return handle
    },
  }
  harness.controller.reveal()

  assert.equal(rafCalls, 1)
  assert.ok(harness.state.pieLabelRafId)
})

test('stops when the page is dead, hidden, or a newer label animation starts', () => {
  const dead = createHarness()
  dead.controller.reveal()
  const deadRaf = dead.state.pieLabelRafId
  dead.state.pieLabelRafId = null
  dead.state.alive = false
  deadRaf.callback()
  assert.deepEqual(dead.state.draws, [])

  const hidden = createHarness()
  hidden.controller.reveal()
  const hiddenRaf = hidden.state.pieLabelRafId
  hidden.state.pieLabelRafId = null
  hidden.state.visible = false
  hiddenRaf.callback()
  assert.deepEqual(hidden.state.draws, [])

  const stale = createHarness()
  stale.controller.reveal()
  const staleRaf = stale.state.pieLabelRafId
  stale.state.pieLabelRafId = null
  stale.state.pieLabelToken += 1
  staleRaf.callback()
  assert.deepEqual(stale.state.draws, [])
})
