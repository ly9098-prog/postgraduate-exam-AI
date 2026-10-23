const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDistributionCommitController,
} = require('../subpackages/productivity/pomodoro-stats/distribution-commit-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    chartMode: 'pie',
    rawSubjects: null,
    pieCacheReset: false,
    subjectItems: [{ subject: 1, duration_sec: 1 }],
    hasData: true,
    dataPatch: null,
    dataCallback: null,
    initCanvasesCallback: null,
    animated: false,
    rendered: null,
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getChartMode: () => state.chartMode,
    setRawSubjects: subjects => { state.rawSubjects = subjects },
    resetPieCache: () => { state.pieCacheReset = true },
    buildSubjectItems: subjects => state.subjectItems,
    hasDistributionData: subjects => state.hasData,
    setData: (patch, callback) => {
      state.dataPatch = patch
      state.dataCallback = callback
    },
    initCanvases: callback => { state.initCanvasesCallback = callback },
    animatePieOnly: () => { state.animated = true },
    renderPie: (progress, includeLabels) => { state.rendered = { progress, includeLabels } },
    ...overrides,
  }
  return { controller: createDistributionCommitController(options), state, options }
}

test('commits subjects, clears loading and selection, and animates the pie', () => {
  const h = createHarness()
  const raw = [{ subject: 1, duration_sec: 1 }]
  h.controller.commit(raw, true)

  assert.deepEqual(h.state.rawSubjects, raw)
  assert.notEqual(h.state.rawSubjects, raw)
  assert.equal(h.state.pieCacheReset, true)
  assert.deepEqual(h.state.dataPatch, {
    subjects: h.state.subjectItems,
    distributionHasData: true,
    pieLoading: false,
    selectedSubjectDetail: null,
    _selectedSubject: null,
  })

  h.state.dataCallback()
  assert.ok(h.state.initCanvasesCallback)
  h.state.initCanvasesCallback()
  assert.equal(h.state.animated, true)
  assert.equal(h.state.rendered, null)
})

test('renders the final pie immediately when animation is disabled', () => {
  const h = createHarness()
  h.controller.commit([], false)
  h.state.dataCallback()
  h.state.initCanvasesCallback()

  assert.equal(h.state.animated, false)
  assert.deepEqual(h.state.rendered, { progress: 1, includeLabels: true })
})

test('copies non-array input as an empty subject list', () => {
  const h = createHarness()
  h.controller.commit(null, false)
  assert.deepEqual(h.state.rawSubjects, [])
})

test('stops before canvas initialization when the page is dead, hidden, or not in pie mode', () => {
  const dead = createHarness()
  dead.state.alive = false
  dead.controller.commit([], true)
  dead.state.dataCallback()
  assert.equal(dead.state.initCanvasesCallback, null)

  const hidden = createHarness()
  hidden.state.visible = false
  hidden.controller.commit([], true)
  hidden.state.dataCallback()
  assert.equal(hidden.state.initCanvasesCallback, null)

  const bar = createHarness()
  bar.state.chartMode = 'bar'
  bar.controller.commit([], true)
  bar.state.dataCallback()
  assert.equal(bar.state.initCanvasesCallback, null)
})

test('stops after canvas initialization when guards become stale', () => {
  const dead = createHarness()
  dead.controller.commit([], true)
  dead.state.dataCallback()
  dead.state.alive = false
  dead.state.initCanvasesCallback()
  assert.equal(dead.state.animated, false)
  assert.equal(dead.state.rendered, null)

  const hidden = createHarness()
  hidden.controller.commit([], true)
  hidden.state.dataCallback()
  hidden.state.visible = false
  hidden.state.initCanvasesCallback()
  assert.equal(hidden.state.animated, false)

  const bar = createHarness()
  bar.controller.commit([], true)
  bar.state.dataCallback()
  bar.state.chartMode = 'bar'
  bar.state.initCanvasesCallback()
  assert.equal(bar.state.animated, false)
})
