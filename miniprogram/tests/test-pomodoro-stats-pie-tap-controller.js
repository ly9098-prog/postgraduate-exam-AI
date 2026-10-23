const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPieTapController,
} = require('../subpackages/productivity/pomodoro-stats/pie-tap-controller')

const GEOMETRY = { centerX: 100, centerY: 100, radius: 80, tilt: 0.5 }
const RECT = { left: 10, top: 20, width: 200, height: 200 }

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    distributionHasData: true,
    selectedSubjectDetail: null,
    subjects: [
      { subject: 'math', duration_sec: 60 },
      { subject: 'english', duration_sec: 60 },
    ],
    patches: [],
    renders: [],
    timers: [],
  }
  const options = {
    isAlive: () => state.alive,
    hasDistributionData: () => state.distributionHasData,
    getSubjects: () => state.subjects,
    getSelectedSubjectDetail: () => state.selectedSubjectDetail,
    getGeometry: () => GEOMETRY,
    createSelectorQuery: () => ({
      in() { return this },
      select(selector) { state.selector = selector; return this },
      boundingClientRect(callback) { callback(RECT); return this },
      exec() {},
    }),
    setData: (patch, callback) => {
      state.patches.push(patch)
      Object.assign(state, patch)
      if (callback) callback()
    },
    renderPie: progress => state.renders.push(progress),
    setTimeout: (callback, delay) => state.timers.push({ callback, delay }),
    ...overrides,
  }
  return { controller: createPieTapController(options), options, state }
}

function tap(h, clientX, clientY) {
  h.controller.handleTap({ changedTouches: [{ clientX, clientY }] })
}

test('selects the tapped subject and clears feedback after 350ms', () => {
  const h = createHarness()
  tap(h, 150, 120)

  assert.equal(h.state.selectedSubjectDetail.subject, 'math')
  assert.equal(h.state._selectedSubject, 'math')
  assert.equal(h.state.pieTapped, true)
  assert.deepEqual(h.state.renders, [1])
  assert.equal(h.state.selector, '#pie-canvas')
  assert.deepEqual(h.state.timers.map(timer => timer.delay), [350])

  h.state.timers[0].callback()
  assert.equal(h.state.pieTapped, false)
  assert.equal(h.state.selectedSubjectDetail.subject, 'math')
})

test('dismisses a selected detail on an outside-pie tap and redraws once', () => {
  const h = createHarness()
  tap(h, 150, 120)
  h.state.renders.length = 0
  tap(h, 310, 120)

  assert.equal(h.state.selectedSubjectDetail, null)
  assert.equal(h.state._selectedSubject, null)
  assert.deepEqual(h.state.renders, [1])
})

test('ignores outside taps when no detail is selected', () => {
  const h = createHarness()
  tap(h, 310, 120)

  assert.equal(h.state.patches.length, 0)
  assert.deepEqual(h.state.renders, [])
})

test('supports touch and detail-style coordinates and skips invalid taps', () => {
  const touch = createHarness()
  touch.controller.handleTap({ touches: [{ clientX: 70, clientY: 120 }] })
  assert.equal(touch.state.selectedSubjectDetail.subject, 'english')

  const detail = createHarness()
  detail.controller.handleTap({ detail: { x: 150, y: 120 } })
  assert.equal(detail.state.selectedSubjectDetail.subject, 'math')

  const invalid = createHarness()
  invalid.controller.handleTap({ detail: { x: '150', y: 120 } })
  assert.equal(invalid.state.patches.length, 0)
})

test('guards selection and feedback against a dead page', () => {
  const h = createHarness()
  h.state.alive = false
  tap(h, 150, 120)

  assert.equal(h.state.selectedSubjectDetail.subject, 'math')
  assert.deepEqual(h.state.renders, [])
  assert.equal(h.state.timers.length, 0)
})
