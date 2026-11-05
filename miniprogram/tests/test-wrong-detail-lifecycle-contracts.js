const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

function setup() {
  const guardCalls = []
  const renderGuard = {
    setRenderGuardPage: value => guardCalls.push(['page', value]),
    resetRenderGuard: () => guardCalls.push(['reset']),
  }
  const f = fixture({ renderGuard }), timers = new Map()
  let now = 10000, nextTimer = 40
  f.context.Date = { now: () => now }
  f.context.setTimeout = (fn, ms) => {
    const id = ++nextTimer
    timers.set(id, { fn, ms })
    f.calls.push(['timer', id, ms])
    return id
  }
  f.context.clearTimeout = id => { f.calls.push(['clear', id]); timers.delete(id) }
  return {
    ...f, guardCalls, renderGuard, timers,
    now: value => { now = value },
    fire(id) { const timer = timers.get(id); assert.ok(timer); timers.delete(id); timer.fn() },
  }
}

function availabilitySetup() {
  const f = setup()
  f.page._initAiAvailabilityState()
  f.page._showBottomActions = () => {}
  f.page._refreshAiAvailability = function (options) {
    return f.definition._refreshAiAvailability.call(this, options)
  }
  return f
}

test('returning within negative cache TTL restores remaining cooldown and observes recovery', async () => {
  const f = availabilitySetup()
  let requests = 0
  f.api.get = async () => {
    requests++
    return { enabled: true, status: 'available' }
  }
  f.page._applyAiAvailability({
    enabled: false, status: 'unavailable', reason: 'transient', retry_after_ms: 30000,
  })
  f.page.onHide()
  assert.equal(f.page._aiAvailabilityRetryTimer, null)
  f.now(15000)
  f.page.onShow()
  assert.equal(requests, 0)
  const timer = f.page._aiAvailabilityRetryTimer
  assert.ok(timer, 'cached failure must resume polling')
  assert.equal(f.timers.get(timer).ms, 25000)
  f.now(40000)
  f.fire(timer)
  for (let tick = 0; tick < 8; tick++) await Promise.resolve()
  assert.equal(requests, 1)
  assert.equal(f.page.data.aiAvailabilityEnabled, true)
  assert.equal(f.page._aiAvailabilityRetryTimer, null)
})

test('hidden in-flight health response cannot update controls or restart polling', async () => {
  const f = availabilitySetup(), pending = deferred()
  f.page.data.aiAvailabilityEnabled = false
  f.api.get = () => pending.promise
  const request = f.page._refreshAiAvailability({ force: true, silent: true })
  f.page.onHide()
  pending.resolve({ enabled: true, status: 'available' })
  await request
  assert.equal(f.page.data.aiAvailabilityEnabled, false)
  assert.equal(f.page._aiAvailabilityRetryTimer, null)
  assert.equal(f.timers.size, 0)
  f.api.get = async () => ({ enabled: true, status: 'available' })
  f.page.onShow()
  for (let tick = 0; tick < 8; tick++) await Promise.resolve()
  assert.equal(f.page.data.aiAvailabilityEnabled, true)
})

test('returning with healthy fresh cache does not refetch or schedule polling', () => {
  const f = availabilitySetup()
  f.api.get = () => { throw new Error('fresh healthy state must be reused') }
  f.page._applyAiAvailability({ enabled: true, status: 'available' })
  f.page.onHide()
  f.page.onShow()
  assert.equal(f.page.data.aiAvailabilityEnabled, true)
  assert.equal(f.page._aiAvailabilityRetryTimer, null)
  assert.equal(f.timers.size, 0)
})

test('onLoad resolves both page hooks dynamically, preserves receiver and does not return', () => {
  const f = setup(), options = { id: '12' }
  f.page._initWrongDetailState = function () {
    assert.equal(this, f.page)
    f.calls.push(['init'])
    this._initWrongDetailFromOptions = function (value) {
      assert.equal(this, f.page)
      assert.equal(value, options)
      f.calls.push(['options'])
      return 'ignored'
    }
  }
  assert.equal(f.page.onLoad(options), undefined)
  assert.deepEqual(f.calls, [['init'], ['options']])
})

test('state initialization preserves exact private assignments, null prototypes and data', () => {
  const f = setup(), data = f.page.data
  f.page._teacherActionCtl = { retained: true }
  f.page._initWrongDetailState()
  assert.deepEqual(f.guardCalls, [['page', 'wrong-detail']])
  const expected = {
    _alive: true, _aiRequestId: 0, _currentWqId: null, _aiGenerationMarker: '',
    _switching: false, _navigationSeq: 0, _aiSwipeStart: null,
    _contentTransitionStartedAt: 0, _contentTransitionDirection: '',
    _teacherRequestSeq: 0, _diagnosisRequestSeq: 0,
    _activeTeacherCacheKey: '', _wqCache: {}, _switchMaskTimer: null,
    _contentTransitionTimer: null, _switchWatchdogTimer: null,
    _masterUndoTimer: null, _masterAdvanceTimer: null, _removeBackTimer: null,
    _bottomActionsTimer: null, _bottomActionsLastActiveAt: 0,
    _masterUndoInFlight: false, _pendingMasterUndo: null,
  }
  for (const [key, value] of Object.entries(expected)) assert.deepEqual(plain(f.page[key]), value, key)
  const cacheNames = ['_teacherCache', '_teacherInflight', '_teacherFeedbackCache']
  for (const key of cacheNames) {
    assert.equal(Object.getPrototypeOf(f.page[key]), null)
    assert.deepEqual(Object.keys(f.page[key]), [])
  }
  assert.notEqual(f.page._teacherCache, f.page._teacherInflight)
  assert.equal(f.page.data, data)
  assert.deepEqual(f.page._teacherActionCtl, { retained: true })
  assert.deepEqual(f.calls, [])
  const previousCache = f.page._teacherCache
  f.page._initWrongDetailState()
  assert.notEqual(f.page._teacherCache, previousCache)
})

test('render guard failure occurs before all state initialization writes', () => {
  const f = setup(), error = new Error('guard')
  f.renderGuard.setRenderGuardPage = () => { throw error }
  // The page captures the imported guard at module evaluation.
  const broken = fixture({ renderGuard: f.renderGuard })
  broken.page._alive = false
  assert.throws(() => broken.page._initWrongDetailState(), value => value === error)
  assert.equal(broken.page._alive, false)
  assert.equal(broken.page._aiRequestId, 7)
})

test('invalid option ids patch only the original three fields and stop', () => {
  for (const id of [undefined, '', 'bad', 'Infinity', '-1', '0', null]) {
    const f = setup()
    f.page._resolveQuestionIds = () => assert.fail('unexpected navigation resolution')
    f.page.loadData = () => assert.fail('unexpected load')
    f.page._showBottomActions = () => assert.fail('unexpected show')
    assert.equal(f.page._initWrongDetailFromOptions({ id }), undefined)
    assert.deepEqual(plain(f.calls), [['setData', {
      loading: false, errorText: '错题ID无效', wq: null,
    }]])
  }
  const f = setup()
  assert.throws(() => f.page._initWrongDetailFromOptions(), { name: 'TypeError' })
  assert.deepEqual(f.calls, [])
})

test('valid options preserve ids identity, index fallback and nonawaited load-before-show', () => {
  for (const ids of [[2, 12, 12], [2, 3], []]) {
    const f = setup(), options = { id: '12', source: 'wrong-book' }
    f.page._resolveQuestionIds = function (value, id) {
      assert.equal(this, f.page); assert.equal(value, options); assert.equal(id, 12)
      return ids
    }
    f.page.loadData = function (id) {
      assert.equal(this, f.page)
      f.calls.push(['load', id])
      return new Promise(() => {})
    }
    f.page._showBottomActions = function () { assert.equal(this, f.page); f.calls.push(['show']) }
    assert.equal(f.page._initWrongDetailFromOptions(options), undefined)
    assert.equal(f.page.data.questionIds, ids)
    assert.deepEqual(plain(f.calls), [
      ['setData', { questionIds: ids, currentIdx: Math.max(0, ids.indexOf(12)), totalQuestions: ids.length }],
      ['load', 12], ['show'],
    ])
  }
})

test('option loading synchronous error prevents the subsequent bottom-action hook', () => {
  const f = setup(), error = new Error('load')
  f.page._resolveQuestionIds = () => [12]
  f.page.loadData = () => { throw error }
  f.page._showBottomActions = () => assert.fail('unexpected show')
  assert.throws(() => f.page._initWrongDetailFromOptions({ id: '12' }), value => value === error)
  assert.equal(f.page.data.currentIdx, 0)
})

test('navigation storage preserves source and TTL boundaries, duplicates, numeric finite values', () => {
  for (const source of ['wrong-book', 'practice-result', 'exam-result']) {
    const f = setup()
    f.context.wx = {
      getStorageSync(key) {
        assert.equal(this, f.context.wx); assert.equal(key, 'wrong_detail_nav')
        return { ids: ['12', 12, 'bad', null, -3, Infinity, '2'], ts: 9999, source }
      },
    }
    assert.deepEqual(plain(f.page._resolveQuestionIds({ source }, 12)), [12, 12, 0, -3, 2])
  }
  for (const [age, storedSource, expected] of [
    [1799999, 'wrong-book', [12, 13]], [1800000, 'wrong-book', [12]],
    [-1, '', [12, 13]], [0, 'exam-result', [12]], [0, undefined, [12, 13]],
  ]) {
    const f = setup()
    f.context.wx.getStorageSync = () => ({ ids: [12, 13], ts: 10000 - age, source: storedSource })
    assert.deepEqual(plain(f.page._resolveQuestionIds({ source: 'wrong-book' }, 12)), expected)
  }
})

test('navigation storage errors and malformed/missing/current-id-free records fall back', () => {
  const f = setup()
  for (const value of [null, {}, { ids: {} }, { ids: [] }, { ids: [13], ts: 10000 }]) {
    f.context.wx.getStorageSync = () => value
    assert.deepEqual(plain(f.page._resolveQuestionIds({ source: 'wrong-book' }, 12)), [12])
  }
  f.context.wx.getStorageSync = () => { throw new Error('storage') }
  assert.deepEqual(plain(f.page._resolveQuestionIds({ source: 'exam-result' }, 12)), [12])
  f.context.wx.getStorageSync = () => assert.fail('unsupported source must skip storage')
  assert.deepEqual(plain(f.page._resolveQuestionIds({ source: 'other' }, 12)), [12])
  assert.deepEqual(plain(f.page._resolveQuestionIds(undefined, 12)), [12])
})

test('visibility/interaction hooks preserve their original alive and question guards', () => {
  const f = setup()
  f.page._showBottomActions = function () { assert.equal(this, f.page); f.calls.push(['show']) }
  f.page._clearBottomActionsTimer = function () { assert.equal(this, f.page); f.calls.push(['clear']) }
  f.page._alive = false; f.page.onShow()
  f.page._alive = true; f.page.data.wq = null; f.page.onShow()
  f.page.data.wq = {}; f.page.onShow()
  f.page._alive = false
  f.page.onHide(); f.page.onPageScroll(); f.page.onPageInteraction()
  assert.deepEqual(f.calls, [['show'], ['clear'], ['show'], ['show']])
})

test('bottom-action timer clear uses original truthy handle guard and nulls after clear', () => {
  const f = setup()
  f.page._bottomActionsTimer = 0
  assert.equal(f.page._clearBottomActionsTimer(), undefined)
  assert.equal(f.page._bottomActionsTimer, 0)
  f.page._bottomActionsTimer = 99
  f.context.clearTimeout = id => { assert.equal(f.page._bottomActionsTimer, 99); f.calls.push(['clear', id]) }
  f.page._clearBottomActionsTimer()
  assert.equal(f.page._bottomActionsTimer, null)
  assert.deepEqual(f.calls, [['clear', 99]])
})

test('bottom-action scheduling waits three idle seconds and reuses one timer', () => {
  const f = setup(), page = f.page
  page.data.bottomActionsVisible = false
  page._showBottomActions()
  const first = page._bottomActionsTimer
  assert.equal(page._bottomActionsLastActiveAt, 10000)
  assert.equal(f.timers.get(first).ms, 3000)
  f.now(12000); page._showBottomActions()
  assert.equal(page._bottomActionsTimer, first)
  f.now(13000); f.fire(first)
  const second = page._bottomActionsTimer
  assert.equal(f.timers.get(second).ms, 2000)
  assert.equal(page.data.bottomActionsVisible, true)
  f.now(15000); f.fire(second)
  assert.equal(page._bottomActionsTimer, null)
  assert.equal(page.data.bottomActionsVisible, false)
  assert.deepEqual(plain(f.calls.filter(call => call[0] === 'setData')), [
    ['setData', { bottomActionsVisible: true }], ['setData', { bottomActionsVisible: false }],
  ])
})

test('bottom-action alive guards and already-hidden expiry avoid extra writes', () => {
  const f = setup(), page = f.page
  page._alive = false; page._showBottomActions(); page._scheduleBottomActionsAutoHide()
  assert.equal(f.timers.size, 0)
  page._alive = true; page._bottomActionsLastActiveAt = 10000
  page._scheduleBottomActionsAutoHide()
  const first = page._bottomActionsTimer
  page._alive = false; f.fire(first)
  assert.equal(page._bottomActionsTimer, null)
  assert.equal(f.timers.size, 0)
  page._alive = true; page.data.bottomActionsVisible = false
  page._scheduleBottomActionsAutoHide()
  f.now(13000); f.fire(page._bottomActionsTimer)
  assert.deepEqual(f.calls.filter(call => call[0] === 'setData'), [])
})

test('unload invalidates sequences before ordered timer hooks and cache/guard cleanup', () => {
  const f = setup(), page = f.page
  page._teacherRequestSeq = 4; page._diagnosisRequestSeq = 6
  const fields = ['_switchMaskTimer', '_contentTransitionTimer', '_switchWatchdogTimer', '_removeBackTimer']
  fields.forEach((name, i) => { page[name] = 20 + i })
  const cache = { retained: true }
  page._wqCache = cache
  page._clearBottomActionsTimer = function () {
    assert.equal(this, page)
    assert.equal(page._alive, false); assert.equal(page._aiRequestId, 8)
    assert.equal(page._teacherRequestSeq, 5); assert.equal(page._diagnosisRequestSeq, 7)
    assert.equal(page._wqCache, cache)
    f.calls.push(['bottom'])
  }
  page._clearMasterUndo = function () {
    assert.equal(this, page); assert.equal(page._wqCache, cache); f.calls.push(['undo'])
  }
  assert.equal(page.onUnload(), undefined)
  assert.deepEqual(f.calls, [['clear', 20], ['clear', 21], ['clear', 22], ['clear', 23], ['bottom'], ['undo']])
  fields.forEach(name => assert.equal(page[name], null))
  for (const name of ['_wqCache', '_teacherCache', '_teacherInflight', '_teacherFeedbackCache']) {
    assert.equal(page[name], null)
  }
  assert.equal(page._activeTeacherCacheKey, '')
  assert.equal(page._aiGenerationMarker, '')
  assert.deepEqual(f.guardCalls, [['reset']])
  assert.equal(page.data.wq.id, 12)
})

test('unload hook error preserves partial cleanup and original error propagation', () => {
  const f = setup(), error = new Error('clear'), cache = f.page._wqCache
  f.page._clearBottomActionsTimer = () => { throw error }
  f.page._clearMasterUndo = () => assert.fail('must stop after hook failure')
  assert.throws(() => f.page.onUnload(), value => value === error)
  assert.equal(f.page._alive, false)
  assert.equal(f.page._wqCache, cache)
  assert.deepEqual(f.guardCalls, [])
})
