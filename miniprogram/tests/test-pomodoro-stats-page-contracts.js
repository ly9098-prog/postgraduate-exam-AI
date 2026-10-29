const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture } = require('./helpers/pomodoro-stats-page-fixture')
const plain = value => JSON.parse(JSON.stringify(value))
const GETTERS = [
  "_getPageInitController",
  "_getSettingsController",
  "_getLifecycleController",
  "_getDynamicRefreshController",
  "_getThemeSyncController",
  "_getSubjectMetaController",
  "_getCumulativeRefreshController",
  "_getCumulativeStartController",
  "_getDistributionCommitController",
  "_getDistributionLoadController",
  "_getDistributionEntryController",
  "_getSelectDateController",
  "_getDayStartEntryController",
  "_getSaveDayStartController",
  "_getDateNavigationController",
  "_getTrendAnimationController",
  "_getChartModeController",
  "_getDeferredHistoryController",
  "_getDurationAnimationController",
  "_getPieAnimationController",
  "_getPieLabelRevealController",
  "_getStartAnimationsController",
  "_getCancelWorkController",
  "_getPieTapController",
  "_getCloseDetailController"
]

for (const name of GETTERS) {
  test(name + ' retains page-local cached controller and dynamic state/platform callbacks', () => {
    const f = fixture(), other = fixture()
    const instance = f.page[name]()
    assert.equal(f.page[name](), instance)
    assert.equal(f.instances.length, 1)
    assert.notEqual(other.page[name](), instance)
    f.page.data = { ...f.page.data, selectedDate: '2026-10-28', _todayDate: '2026-10-29',
      subjects: [{ id: 7 }], history: [{ id: 8 }], chartMode: 'bar' }
    f.page._alive = true
    f.page._isVisible = true
    f.page._requestId = 17
    const options = instance.options
    if (options.isAlive) assert.equal(options.isAlive(), true)
    if (options.getSelectedDate) assert.equal(options.getSelectedDate(), '2026-10-28')
    if (options.getTodayDate) assert.equal(options.getTodayDate(), '2026-10-29')
    if (options.getSubjects) assert.equal(options.getSubjects(), f.page.data.subjects)
    if (options.getHistory) assert.equal(options.getHistory(), f.page.data.history)
    if (options.getRequestId) assert.equal(options.getRequestId(), 17)
    if (options.getChartMode) assert.equal(options.getChartMode(), 'bar')
    if (options.showToast) {
      const wx = { showToast(value) { assert.equal(this, wx); assert.equal(value.title, 'late') } }
      f.context.wx = wx
      options.showToast('late')
    }
  })
}

test('page load preserves initialization identity, private writes then patch and current init hook', () => {
  const f = fixture(), internal = { _alive: true }, data = { selectedDate: '2026-10-29' }
  f.page._getPageInitController = () => ({ initialize: () => ({ internal, data }) })
  f.page._init = function () { assert.equal(this, f.page); f.calls.push(['init', this._alive]) }
  assert.equal(f.page.onLoad(), undefined)
  assert.deepEqual(f.calls, [['setData', data], ['init', true]])
})

test('initial settings wait uses current subject metadata hook and catches only that async rejection', async () => {
  const f = fixture()
  let done
  f.page._ensureSettings = () => new Promise(resolve => { done = resolve })
  const result = f.page._init()
  f.page._ensureSubjectMeta = () => { f.calls.push(['meta']); return Promise.reject(Error('meta')) }
  done()
  await result
  await Promise.resolve()
  assert.deepEqual(f.calls.map(row => row[0]), ['meta', 'warn'])
  const error = Error('settings')
  f.page._ensureSettings = () => Promise.reject(error)
  await assert.rejects(f.page._init(), value => value === error)
})

test('timer shorthand ports capture current timer once while wrapped lifecycle timer stays dynamic', () => {
  const f = fixture(), first = f.context.setTimeout
  const options = f.page._getDynamicRefreshController().options
  const lifecycle = f.page._getLifecycleController().options
  const replacement = () => 98
  f.context.setTimeout = replacement
  assert.equal(options.setTimeout, first)
  f.context.wx = {}
  assert.equal(lifecycle.nextTick(() => {}), undefined)
  assert.equal(options.setTimeout, first)
})

test('distribution commit retains live render hooks, raw array identity and setData callback', () => {
  const f = fixture(), options = f.page._getDistributionCommitController().options, rows = []
  options.setRawSubjects(rows)
  assert.equal(f.page._distributionRawSubjects, rows)
  f.page._renderPieChart = function (...args) { assert.equal(this, f.page); return args }
  assert.deepEqual(options.renderPie(1, false), [1, false])
  let called = false
  options.setData({ distributionHasData: true }, () => { called = true })
  assert.equal(called, true)
})

test('cancel wiring preserves frame receiver and cleanup failures before timer reset', () => {
  const f = fixture(), options = f.page._getCancelWorkController().options
  const node = { cancelAnimationFrame(id) { assert.equal(this, node); assert.equal(id, 4) } }
  options.cancelFrame(4, node)
  options.cancelFrame(0, node)
  f.page._animTimer = 9
  const error = Error('timer')
  f.context.clearTimeout = () => { throw error }
  assert.throws(() => options.clearAnimTimer(), value => value === error)
  assert.equal(f.page._animTimer, 9)
})

test('cache reset keeps fresh cache object and current shade cache receiver', () => {
  const f = fixture(), old = {}, cache = { reset() { assert.equal(this, cache); f.calls.push(['reset']) } }
  f.page._pieRenderCache = old
  f.page._shadeColorCache = cache
  f.page._resetPieCache()
  assert.notEqual(f.page._pieRenderCache, old)
  assert.deepEqual(plain(f.page._pieRenderCache), { sectors: null, wallSteps: null, labelLayout: null })
  assert.deepEqual(f.calls, [['reset']])
})

test('cumulative customized branch retains lifetimeStart only and skips summary hook', () => {
  const f = fixture()
  f.page._cumulativeCustomized = true
  f.page._cumulativeSummaryPatch = () => { throw Error('unexpected summary') }
  assert.deepEqual(plain(f.page._buildCumulativePatch({}, '2026-10-01')), { lifetimeStartDate: '2026-10-01' })
  f.page._cumulativeCustomized = false
  f.page._cumulativeSummaryPatch = (summary, start) => { assert.equal(summary.start_date, start); return { total: 7 } }
  assert.deepEqual(plain(f.page._buildCumulativePatch({ start_date: 'old' }, 'new')), { lifetimeStartDate: 'new', total: 7 })
})

test('duration display patch uses current segments hook and preserves original text identity', () => {
  const f = fixture(), value = {}, segments = []
  f.page._buildDurationSegments = input => { assert.equal(input, value); return segments }
  const patch = f.page._getTodayDurationDisplayPatch(value)
  assert.equal(patch._dispTodayDurationText, value)
  assert.equal(patch._dispTodayDurationSegments, segments)
})

test('date event forwards raw value and preserves undefined return', () => {
  const f = fixture(), values = []
  f.page._selectDate = value => { values.push(value); return 7 }
  assert.equal(f.page.onDateChange({ detail: { value: 'raw' } }), undefined)
  f.page.onDateChange(null)
  f.page.onDateChange({ detail: {} })
  assert.deepEqual(values, ['raw', '', undefined])
})

test('load view overrides are followed by authoritative current state and late formatter hooks', () => {
  const f = fixture()
  f.page.data.subjects = [{ current: true }]
  f.page.data.distributionHasData = true
  f.page.data.distributionRangeStart = 'keep-start'
  f.page.data.distributionRangeEnd = 'keep-end'
  f.page._fmtMin = sec => 'min:' + sec
  f.page._formatSession = item => ({ session: item.id })
  f.page._formatSelectedDurationLabel = value => 'label:' + value
  f.page._hasDistributionData = rows => rows.length > 0
  f.page._formatPieDateLabel = value => 'pie:' + value
  f.page._getTodayDurationDisplayPatch = text => ({ _dispTodayDurationText: text })
  f.page._buildCumulativePatch = () => ({ cumulativeSessions: 9 })
  const view = f.page._buildLoadViewState({ stats: {}, summary: { sessions: 2, duration_sec: 60 },
    lifetime: {}, trends: [], effectiveHistory: { items: [{ id: 3 }], total: 1 },
    effectiveDate: '2026-10-28', authoritativeToday: '2026-10-29', willAnimate: false,
    displayDaySubjects: false, currentSubjects: ['ignored'] })
  assert.equal(view.dataPatch.subjects, f.page.data.subjects)
  assert.equal(view.dataPatch.distributionRangeStart, 'keep-start')
  assert.equal(view.dataPatch.todayDurationText, 'min:60')
  assert.deepEqual(plain(view.dataPatch.history), [{ session: 3 }])
  assert.equal(view.dataPatch.cumulativeSessions, 9)
})
