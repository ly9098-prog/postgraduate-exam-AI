const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createThemeSyncController,
} = require('../subpackages/productivity/pomodoro-stats/theme-sync-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    viewReady: true,
    hasData: true,
    currentTheme: 'light',
    storedTheme: 'dark',
    subjects: [
      { subject_id: 1, subject_code: 'code-1', _label: '408', _color: 'old-pie' },
      { subject_code: 'code-2', _label: 'Math', _color: 'old-pie' },
    ],
    history: [
      { subject_id: 2, subject_code: 'code-2', _subjectLabel: 'Math', _color: 'old-history' },
      { subject_code: 'code-3', _subjectLabel: 'English', _color: 'old-history' },
    ],
    patches: [],
    resetPieCache: false,
    chartMode: 'pie',
    barMounted: false,
    trendCtx: null,
    nextTicks: [],
  }

  const options = {
    getStoredTheme: () => state.storedTheme,
    applyNativeTheme: theme => { state.nativeTheme = theme },
    getCurrentTheme: () => state.currentTheme,
    getSubjects: () => state.subjects,
    getHistory: () => state.history,
    getPieSubjectColor: (key, theme) => `pie:${key}:${theme}`,
    getSubjectColor: (key, theme) => `history:${key}:${theme}`,
    setData: (patch, callback) => {
      state.patches.push(patch)
      Object.assign(state, patch)
      callback()
    },
    resetPieCache: () => { state.resetPieCache = true },
    isAlive: () => state.alive,
    isViewReady: () => state.viewReady,
    hasData: () => state.hasData,
    isVisible: () => state.visible,
    getChartMode: () => state.chartMode,
    renderPie: (progress, includeLabels) => {
      state.renders.push(['pie', progress, includeLabels])
    },
    isBarMounted: () => state.barMounted,
    hasTrendContext: () => !!state.trendCtx,
    renderTrendBars: progress => {
      state.renders.push(['bar', progress])
    },
    nextTick: callback => { state.nextTicks.push(callback) },
    ...overrides,
  }

  state.renders = []
  return { controller: createThemeSyncController(options), options, state }
}

function drainNextTicks(state) {
  while (state.nextTicks.length) state.nextTicks.shift()()
}

test('returns false without a view patch when the stored theme is unchanged', () => {
  const harness = createHarness()
  harness.state.storedTheme = 'light'

  const changed = harness.controller.sync()

  assert.equal(changed, false)
  assert.equal(harness.state.nativeTheme, 'light')
  assert.deepEqual(harness.state.patches, [])
  assert.equal(harness.state.resetPieCache, false)
  assert.deepEqual(harness.state.renders, [])
})

test('applies the theme and decorates subject and history colors', () => {
  const harness = createHarness()

  const changed = harness.controller.sync()

  assert.equal(changed, true)
  assert.equal(harness.state.nativeTheme, 'dark')
  assert.deepEqual(harness.state.subjects.map(item => item._color), [
    'pie:1:dark',
    'pie:code-2:dark',
  ])
  assert.deepEqual(harness.state.history.map(item => item._color), [
    'history:2:dark',
    'history:code-3:dark',
  ])
  assert.deepEqual(harness.state.patches, [{
    themeMode: 'dark',
    subjects: harness.state.subjects,
    history: harness.state.history,
  }])
  assert.equal(harness.state.resetPieCache, true)
})

test('skips redraw before the page is usable or before data exists', () => {
  for (const key of ['alive', 'viewReady', 'hasData']) {
    const harness = createHarness()
    harness.state[key] = false
    harness.controller.sync()
    drainNextTicks(harness.state)
    assert.deepEqual(harness.state.renders, [])
  }
})

test('skips redraw after the next tick when the page is dead or hidden', () => {
  const dead = createHarness()
  dead.controller.sync()
  dead.state.alive = false
  drainNextTicks(dead.state)
  assert.deepEqual(dead.state.renders, [])

  const hidden = createHarness()
  hidden.controller.sync()
  hidden.state.visible = false
  drainNextTicks(hidden.state)
  assert.deepEqual(hidden.state.renders, [])
})

test('renders the final pie chart through the injected next tick capability', () => {
  const harness = createHarness()
  harness.controller.sync()

  assert.deepEqual(harness.state.renders, [])
  assert.equal(harness.state.nextTicks.length, 1)
  drainNextTicks(harness.state)
  assert.deepEqual(harness.state.renders, [['pie', 1, true]])
})

test('renders only a user-mounted bar chart with trend context', () => {
  const unmounted = createHarness()
  unmounted.state.chartMode = 'bar'
  unmounted.state.barMounted = false
  unmounted.state.trendCtx = null
  unmounted.controller.sync()
  drainNextTicks(unmounted.state)
  assert.deepEqual(unmounted.state.renders, [])

  const mountedWithoutContext = createHarness()
  mountedWithoutContext.state.chartMode = 'bar'
  mountedWithoutContext.state.barMounted = true
  mountedWithoutContext.state.trendCtx = null
  mountedWithoutContext.controller.sync()
  drainNextTicks(mountedWithoutContext.state)
  assert.deepEqual(mountedWithoutContext.state.renders, [])

  const mounted = createHarness()
  mounted.state.chartMode = 'bar'
  mounted.state.barMounted = true
  mounted.state.trendCtx = {}
  mounted.controller.sync()
  drainNextTicks(mounted.state)
  assert.deepEqual(mounted.state.renders, [['bar', 1]])
})
