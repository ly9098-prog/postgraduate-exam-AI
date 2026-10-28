const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  buildLoadCommitPageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/load-commit-page-adapter')
const {
  buildLoadFailurePageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/load-failure-page-adapter')
const {
  buildDateCommitPageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/date-commit-page-adapter')
const {
  buildDateFailurePageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/date-failure-page-adapter')
const {
  buildDateRequestPageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/date-request-page-adapter')
const {
  buildStatsCanvasInitPageCapabilities,
} = require('../subpackages/productivity/pomodoro-stats/stats-canvas-init-page-adapter')

function recordingPage() {
  const calls = []
  const page = {
    _alive: true,
    _isVisible: true,
    _requestId: 9,
    _dateRequestSeq: 4,
    _cumulativeCustomized: true,
    _displayTodayDurationSec: 11,
    _rawTodayDur: 22,
    _pieCanvasNode: { name: 'pie-node' },
    _pieCtx: { name: 'pie-ctx' },
    _pieRect: { width: 10 },
    _canvasInitPending: false,
    _canvasInitCallbacks: [],
    _barInitPending: false,
    _barInitCallbacks: [],
    data: {
      selectedDate: '2026-10-24',
      _todayDate: '2026-10-24',
      contentReady: true,
      cumulativeStartDate: '2026-10-01',
      distributionPeriod: 'day',
      chartMode: 'pie',
      barCanvasMounted: false,
      subjects: [{ subject_id: 1 }],
      distributionHasData: true,
      distributionRangeStart: '2026-10-20',
      distributionRangeEnd: '2026-10-26',
      _dispTodaySessions: 3,
      lifetimeStartDate: '2026-10-01',
    },
    setData: (...args) => calls.push(['setData', ...args]),
    _queueDeferredHistory: (...args) => calls.push(['deferred', ...args]),
    _refreshCumulativeSummary: (...args) => calls.push(['cumulative', ...args]),
    _loadDistributionForPeriod: (...args) => calls.push(['distribution', ...args]),
    _initCanvases: callback => calls.push(['initPie', callback]),
    _renderPieChart: (...args) => calls.push(['renderPie', ...args]),
    _startAnimations: (...args) => calls.push(['animations', ...args]),
    _initTrendCanvas: callback => calls.push(['initTrend', callback]),
    _renderTrendBars: (...args) => calls.push(['renderTrend', ...args]),
    _resetPieCache: () => calls.push(['resetPie']),
    _animateSelectedDuration: (...args) => calls.push(['duration', ...args]),
    _animatePieOnly: () => calls.push(['pieAnimation']),
    _reconcileFromServer: (...args) => calls.push(['reconcile', ...args]),
    _buildSubjectItems: subjects => ({ subjects }),
    _hasDistributionData: subjects => subjects.length > 0,
    _fmtMin: sec => `${sec}m`,
    _formatSelectedDurationLabel: date => `selected:${date}`,
    _formatSession: item => `session:${item}`,
    _formatPieDateLabel: date => `pie:${date}`,
    _getDateCommitController: () => ({
      commit: (...args) => calls.push(['commitDate', ...args]),
    }),
    _getDateFailureController: () => ({
      handle: (...args) => calls.push(['dateFailure', ...args]),
    }),
  }
  return { page, calls }
}

function fakeApi(calls) {
  return {
    get: (path, params) => {
      calls.push(['api', path, params])
      return Promise.resolve({ path, params })
    },
  }
}

test('load commit adapter delegates state and rendering callbacks', () => {
  const { page, calls } = recordingPage()
  const capabilities = buildLoadCommitPageCapabilities(page)

  capabilities.setDisplayTodayDurationSec(1)
  capabilities.setDaySubjectsRaw([{ subject_id: 2 }])
  capabilities.setRawTodayDuration(3)
  capabilities.setRawWeekDuration(4)
  capabilities.setData({ loading: false }, () => {})
  capabilities.queueDeferredHistory(9, 4, '2026-10-24', [], 2)
  capabilities.refreshCumulativeSummary('2026-10-01', true)
  capabilities.loadDistributionForPeriod('week', false)
  capabilities.initCanvases(() => {})
  capabilities.renderPie(1, true)
  capabilities.startAnimations(9)
  capabilities.initTrendCanvas(() => {})
  capabilities.renderTrendBars(1)

  assert.equal(capabilities.getRequestId(), 9)
  assert.equal(capabilities.isBarMounted(), false)
  assert.equal(capabilities.getPieCanvasNode(), page._pieCanvasNode)
  assert.deepEqual(calls.map(call => call[0]), [
    'setData',
    'deferred',
    'cumulative',
    'distribution',
    'initPie',
    'renderPie',
    'animations',
    'initTrend',
    'renderTrend',
  ])
})

test('load failure adapter exposes current request and snapshot state', () => {
  const { page, calls } = recordingPage()
  const capabilities = buildLoadFailurePageCapabilities(page)
  const error = new Error('offline')

  capabilities.logError('load failed', error)
  capabilities.setData({ loading: false })

  assert.equal(capabilities.isAlive(), true)
  assert.equal(capabilities.getRequestId(), 9)
  assert.equal(capabilities.getDateRequestSeq(), 4)
  assert.equal(capabilities.getSelectedDate(), '2026-10-24')
  assert.equal(capabilities.isContentReady(), true)
  assert.deepEqual(calls.map(call => call[0]), ['setData'])
})

test('date commit adapter delegates animations and pie initialization', () => {
  const { page, calls } = recordingPage()
  const capabilities = buildDateCommitPageCapabilities(page)

  capabilities.setRawTodayDuration(5)
  capabilities.setDaySubjectsRaw([{ subject_id: 3 }])
  capabilities.resetPieCache()
  capabilities.setData({ pieLoading: false }, () => {})
  capabilities.animateSelectedDuration(1, 2, 3, 4)
  capabilities.loadDistributionForPeriod('day', true)
  capabilities.initCanvases(() => {})
  capabilities.animatePieOnly()

  assert.equal(capabilities.isPieReady(), true)
  assert.deepEqual(calls.map(call => call[0]), [
    'resetPie',
    'setData',
    'duration',
    'distribution',
    'initPie',
    'pieAnimation',
  ])
})

test('date failure adapter preserves the existing toast guard', () => {
  const { page, calls } = recordingPage()
  const capabilities = buildDateFailurePageCapabilities(page, {
    wx: { showToast: options => calls.push(['toast', options]) },
  })

  capabilities.showToast('failed')
  assert.deepEqual(calls, [['toast', { title: 'failed', icon: 'none' }]])

  const withoutToast = buildDateFailurePageCapabilities(page, { wx: {} })
  withoutToast.showToast('failed')
  assert.deepEqual(calls, [['toast', { title: 'failed', icon: 'none' }]])
})

test('date request adapter preserves API shapes and view-state inputs', async () => {
  const { page, calls } = recordingPage()
  const capabilities = buildDateRequestPageCapabilities(page, {
    api: fakeApi(calls),
  })

  assert.equal(capabilities.getDateRequestSeq(), 4)
  capabilities.incrementDateRequestSeq()
  assert.equal(page._dateRequestSeq, 5)
  assert.equal(capabilities.getDistributionPeriod(), 'day')

  const today = await capabilities.getInitialResponses('2026-10-24', true)
  const dated = await capabilities.getInitialResponses('2026-10-23', false)
  await capabilities.getHistory('2026-10-25')

  assert.deepEqual(today[0].params, {})
  assert.deepEqual(dated[0].params, { date: '2026-10-23' })
  assert.deepEqual(today[1].params, {
    page: 1,
    page_size: 20,
    date: '2026-10-24',
  })
  assert.deepEqual(calls.at(-1), [
    'api',
    '/pomodoro/history',
    { page: 1, page_size: 20, date: '2026-10-25' },
  ])

  capabilities.reconcileFromServer(null, { summary: true })
  capabilities.setRawTodayDuration(6)
  capabilities.setDaySubjectsRaw([{ subject_id: 4 }])
  capabilities.resetPieCache()
  capabilities.commitDate({ view: 1 }, { seq: 5 })
  capabilities.handleDateFailure(new Error('offline'), { seq: 5 })

  const viewState = capabilities.buildDateViewState({
    summary: { subjects: [] },
    effectiveHistory: { items: [], total: 0 },
    effectiveDate: '2026-10-24',
    todayDate: '2026-10-24',
    showDayDistribution: true,
  })
  assert.equal(viewState.subjects, undefined)
  assert.deepEqual(calls.map(call => call[0]), [
    'api', 'api', 'api', 'api', 'api',
    'reconcile', 'resetPie', 'commitDate', 'dateFailure',
  ])
})

test('canvas init adapter binds page and WeChat query ports', () => {
  const { page, calls } = recordingPage()
  const query = { name: 'query' }
  const capabilities = buildStatsCanvasInitPageCapabilities(page, {
    wx: {
      createSelectorQuery: () => query,
      getWindowInfo: () => ({ pixelRatio: 3 }),
    },
  })

  assert.equal(capabilities.getPage(), page)
  assert.equal(capabilities.createQuery(), query)
  assert.deepEqual(capabilities.getWindowInfo(), { pixelRatio: 3 })
  assert.equal(capabilities.pieSelector(), '#pie-canvas')
  assert.equal(capabilities.trendSelector(), '#trend-bars-canvas')
  assert.equal(capabilities.isPieReady(), true)
  assert.equal(capabilities.isPiePending(), false)
  assert.equal(capabilities.isTrendMounted(), false)
  assert.equal(capabilities.isTrendReady(), false)
  assert.equal(capabilities.isTrendPending(), false)

  page.data.barCanvasMounted = true
  page._trendCanvasNode = {}
  page._trendCtx = {}
  page._trendBarsRect = {}
  assert.equal(capabilities.isTrendMounted(), true)
  assert.equal(capabilities.isTrendReady(), true)

  capabilities.setPiePending(true)
  capabilities.addPieCallback(() => {})
  capabilities.setTrendPending(true)
  capabilities.addTrendCallback(() => {})
  assert.equal(page._canvasInitPending, true)
  assert.equal(page._canvasInitCallbacks.length, 1)
  assert.equal(page._barInitPending, true)
  assert.equal(page._barInitCallbacks.length, 1)

  capabilities.commitPie({ node: 'node', ctx: 'ctx', rect: 'rect', dpr: 3 })
  capabilities.commitTrend({ node: 'trend', ctx: 'ctx2', rect: 'rect2' })
  assert.equal(page._pieCanvasNode, 'node')
  assert.equal(page._pieCtx, 'ctx')
  assert.equal(page._pieRect, 'rect')
  assert.equal(page._pieDpr, 3)
  assert.equal(page._trendCanvasNode, 'trend')
  assert.equal(page._trendCtx, 'ctx2')
  assert.equal(page._trendBarsRect, 'rect2')
  assert.deepEqual(calls, [])
})
