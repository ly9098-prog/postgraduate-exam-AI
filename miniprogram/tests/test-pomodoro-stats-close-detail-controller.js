const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCloseDetailController,
} = require('../subpackages/productivity/pomodoro-stats/close-detail-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    patches: [],
    callbacks: [],
    renders: [],
  }
  const options = {
    isAlive: () => state.alive,
    setData: (patch, callback) => {
      state.patches.push(patch)
      state.callbacks.push(callback)
    },
    renderPie: progress => state.renders.push(progress),
    ...overrides,
  }
  return { controller: createCloseDetailController(options), state }
}

test('clears the selected subject and redraws the final pie', () => {
  const h = createHarness()
  h.controller.close()

  assert.deepEqual(h.state.patches, [{ selectedSubjectDetail: null, _selectedSubject: null }])
  h.state.callbacks[0]()
  assert.deepEqual(h.state.renders, [1])
})

test('clears selection but skips redraw when the page is dead', () => {
  const h = createHarness({ isAlive: () => false })
  h.controller.close()
  h.state.callbacks[0]()

  assert.deepEqual(h.state.patches, [{ selectedSubjectDetail: null, _selectedSubject: null }])
  assert.deepEqual(h.state.renders, [])
})
