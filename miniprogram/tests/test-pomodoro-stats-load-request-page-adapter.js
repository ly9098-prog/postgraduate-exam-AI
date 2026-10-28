const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildLoadRequestPageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/load-request-page-adapter')
const {
  CAPABILITY_NAMES,
} = require('../subpackages/productivity/pomodoro-stats/load-request-controller-capabilities')

function createPage() {
  const calls = []
  const page = {
    _alive: true,
    _requestId: 7,
    _dateRequestSeq: 3,
    _hasData: true,
    _statsLoadInFlight: 0,
    data: {
      selectedDate: '2026-01-02',
      _todayDate: '2026-01-03',
      distributionPeriod: 'week',
    },
    _ensureSettings: () => calls.push(['settings']),
    _ensureSubjectMeta: () => calls.push(['subjects']),
    _cancelDeferredHistory: value => calls.push(['cancel-history', value]),
    setData: patch => calls.push(['setData', patch]),
    _reconcileFromServer: (stats, summary) => calls.push(['reconcile', stats, summary]),
    _resetPieCache: () => calls.push(['reset-pie']),
    _cancelDurationAnimation: value => calls.push(['cancel-duration', value]),
    _buildLoadViewState: overrides => calls.push(['build-view', overrides]),
    _getLoadCommitController: () => ({
      commit: (viewState, context) => calls.push(['commit', viewState, context]),
    }),
    _getLoadFailureController: () => ({
      handle: (error, context) => calls.push(['failure', error, context]),
    }),
  }
  return { page, calls }
}

function createApi(calls) {
  return {
    get: (path, params) => {
      calls.push(['api', path, params])
      return Promise.resolve({ path, params })
    },
  }
}

test('maps page state and API requests to the load-request contract', async () => {
  const { page, calls } = createPage()
  const capabilities = buildLoadRequestPageCapabilities(page, {
    api: createApi(calls),
    normalizeOverview: value => ({ normalized: value }),
  })
  assert.deepEqual(Object.keys(capabilities), CAPABILITY_NAMES)

  assert.equal(capabilities.isAlive(), true)
  assert.equal(capabilities.getRequestId(), 7)
  assert.equal(capabilities.getSelectedDate(), '2026-01-02')
  assert.equal(capabilities.getTodayDate(), '2026-01-03')
  assert.equal(capabilities.getDateRequestSeq(), 3)
  assert.equal(capabilities.hasData(), true)
  assert.equal(capabilities.getDistributionPeriod(), 'week')

  capabilities.ensureSettings()
  capabilities.ensureSubjectMeta()
  capabilities.setHasData(false)
  capabilities.incrementDateRequestSeq()
  capabilities.incrementStatsLoadInFlight()
  capabilities.decrementStatsLoadInFlight()
  capabilities.cancelDeferredHistory(true)
  capabilities.setData({ loading: false })

  assert.equal(page._hasData, false)
  assert.equal(page._dateRequestSeq, 4)
  assert.equal(page._statsLoadInFlight, 0)
  assert.deepEqual(calls, [
    ['settings'],
    ['subjects'],
    ['cancel-history', true],
    ['setData', { loading: false }],
  ])

  const today = await capabilities.getInitialResponses('2026-01-02', true)
  const dated = await capabilities.getInitialResponses('2026-01-02', false)
  assert.deepEqual(today[0].params, {})
  assert.deepEqual(dated[0].params, { date: '2026-01-02' })
  assert.deepEqual(today[1].params, {
    page: 1,
    page_size: 20,
    date: '2026-01-02',
  })
  await capabilities.getHistory('2026-01-01')
  assert.deepEqual(calls.at(-1), [
    'api',
    '/pomodoro/history',
    { page: 1, page_size: 20, date: '2026-01-01' },
  ])
  assert.deepEqual(capabilities.normalizeOverview({ ok: true }), {
    normalized: { ok: true },
  })
})

test('delegates page callbacks without changing their arguments', () => {
  const { page, calls } = createPage()
  const capabilities = buildLoadRequestPageCapabilities(page, {
    api: { get: () => Promise.resolve() },
    normalizeOverview: value => value,
  })

  capabilities.reconcileFromServer({ stats: 1 }, { summary: 2 })
  capabilities.resetPieCache()
  capabilities.cancelDurationAnimation(true)
  capabilities.buildLoadViewState({ view: 1 })
  capabilities.commitLoad({ view: 2 }, { context: 3 })
  const failure = new Error('failure')
  capabilities.handleLoadFailure(failure, { context: 4 })

  assert.deepEqual(calls, [
    ['reconcile', { stats: 1 }, { summary: 2 }],
    ['reset-pie'],
    ['cancel-duration', true],
    ['build-view', { view: 1 }],
    ['commit', { view: 2 }, { context: 3 }],
    ['failure', failure, { context: 4 }],
  ])
})
