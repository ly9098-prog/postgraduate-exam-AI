const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createOverviewLoadController,
} = require('../subpackages/study/review-today/utils/overview-load-controller')

function harness(overrides = {}) {
  const state = {
    seq: 0,
    alive: true,
    autoStartPending: false,
    overviewLoading: false,
    views: [],
    errors: [],
    started: false,
  }
  const options = {
    nextRequestSeq: () => ++state.seq,
    isRequestCurrent: seq => seq === state.seq,
    isPageAlive: () => state.alive,
    isAutoStartPending: () => state.autoStartPending,
    setAutoStartPending: value => { state.autoStartPending = value },
    setOverviewLoading: value => { state.overviewLoading = value },
    getOverview: async () => ({ date: '2026-10-25' }),
    buildOverviewVM: overview => ({
      todayRemainingCount: overview.remaining || 0,
      sourceDate: overview.date,
    }),
    applyOverviewToSession: () => {},
    adjustVmForActiveSession: vm => vm,
    setData: (patch, callback) => {
      state.views.push(patch)
      if (callback) callback()
    },
    startReview: () => { state.started = true },
    logError: (...args) => { state.errors.push(args) },
    ...overrides,
  }
  return { options, state, get controller() { return createOverviewLoadController(options) } }
}

test('load shows loading then switches to overview', async () => {
  const h = harness()
  await h.controller.load()

  assert.deepEqual(h.state.views, [
    { phase: 'loading', isStarting: false, isContinuing: false },
    { todayRemainingCount: 0, sourceDate: '2026-10-25', phase: 'empty' },
  ])
  assert.equal(h.state.overviewLoading, false)
  assert.equal(h.state.started, false)
})

test('load autostarts only when questions remain and pending flag is set', async () => {
  const h = harness({
    getOverview: async () => ({ date: '2026-10-25', remaining: 3 }),
  })
  h.state.autoStartPending = true
  await h.controller.load()

  assert.equal(h.state.started, true)
  assert.equal(h.state.autoStartPending, false)
})

test('empty overview clears the pending autostart flag', async () => {
  const h = harness()
  h.state.autoStartPending = true
  await h.controller.load()

  assert.equal(h.state.started, false)
  assert.equal(h.state.autoStartPending, false)
})

test('stale load responses do not mutate the page', async () => {
  const h = harness()
  h.options.getOverview = async () => {
    h.state.seq++
    return { date: '2026-10-25', remaining: 3 }
  }
  await h.controller.load()

  assert.deepEqual(h.state.views, [
    { phase: 'loading', isStarting: false, isContinuing: false },
  ])
  assert.equal(h.state.overviewLoading, true)
})

test('load failures show the error phase for current requests', async () => {
  const failure = new Error('network')
  const h = harness({ getOverview: async () => { throw failure } })
  await h.controller.load()

  assert.deepEqual(h.state.views.slice(-1), [{
    phase: 'error',
    errorText: '复习计划加载失败，请稍后重试',
  }])
  assert.equal(h.state.overviewLoading, false)
  assert.deepEqual(h.state.errors[0], ['加载复习概览失败', failure])
})

test('silent refresh applies active-session adjustment without loading phase', async () => {
  const h = harness({
    getOverview: async () => ({ date: '2026-10-25', remaining: 2 }),
    adjustVmForActiveSession: vm => {
      vm.adjusted = true
      return vm
    },
  })
  await h.controller.refreshSilently()

  assert.deepEqual(h.state.views, [{
    todayRemainingCount: 2,
    sourceDate: '2026-10-25',
    adjusted: true,
  }])
  assert.equal(h.state.overviewLoading, false)
})

test('silent refresh failures stay quiet for current requests', async () => {
  const failure = new Error('network')
  const h = harness({ getOverview: async () => { throw failure } })
  await h.controller.refreshSilently()

  assert.deepEqual(h.state.views, [])
  assert.deepEqual(h.state.errors[0], ['刷新复习概览失败', failure])
})
