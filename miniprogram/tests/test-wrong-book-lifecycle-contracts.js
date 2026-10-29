const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred, flush } = require('./helpers/wrong-book-lifecycle-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

test('load resets only existing sequence/state fields and preserves helper order and query conversion', () => {
  const f = fixture(), p = f.page
  f.config.enableMathImage = 'enabled'
  Object.assign(p, { _destroyed: true, _statsRequestSeq: 9, _subjectsRequestSeq: 9,
    _taskFlowRequestSeq: 9, _listRequestSeq: 12, _batchMasterUndoInFlight: true, _ready: true, _alive: true })
  assert.equal(p.onLoad({ subject_id: '02', topic: 'topic' }), undefined)
  assert.equal(p._destroyed, false); assert.equal(p._statsRequestSeq, 0)
  assert.equal(p._subjectsRequestSeq, 0); assert.equal(p._taskFlowRequestSeq, 0)
  assert.equal(p._listRequestSeq, 12); assert.equal(p._ready, true); assert.equal(p._alive, true)
  assert.equal(p._batchMasterUndoInFlight, false); assert.equal(p.data.enableMathImage, 'enabled')
  assert.equal(p.data.selectedSubjectId, 2); assert.equal(p.data.selectedTopic, 'topic')
  assert.deepEqual(f.calls.map(c => c[0]), [
    'setData', '_syncDateFilter', 'decode', 'setData', 'setData', '_updateFilterCount',
    '_checkExportCapability', '_restoreAiAutoSetting', '_restoreAiDiagnosisFromCache',
  ])
})

test('load query rejects zero/nonfinite subjects, accepts negative numbers and resolves helper changes live', () => {
  for (const value of [undefined, '', '0', 'bad', 'Infinity', '-2']) {
    const f = fixture()
    f.page._syncDateFilter = function () {
      assert.equal(this, f.page)
      this._updateFilterCount = () => f.calls.push(['lateFilter'])
    }
    f.page.onLoad({ subject_id: value })
    assert.equal(f.page.data.selectedSubjectId, value === '-2' ? -2 : null)
    assert.ok(f.calls.some(c => c[0] === 'lateFilter'))
  }
  const f = fixture(), error = Error('sync')
  f.page._syncDateFilter = () => { throw error }
  assert.throws(() => f.page.onLoad(null), value => value === error)
  assert.deepEqual(f.calls.map(c => c[0]), ['setData'])
})

test('ready sets its flag and does not await subjects before reading the current page loader', () => {
  const f = fixture()
  f.page.loadSubjects = function () {
    assert.equal(this, f.page); assert.equal(this._ready, true)
    f.calls.push(['subjects'])
    this._loadPage = function () { assert.equal(this, f.page); f.calls.push(['lateLoad']); return new Promise(() => {}) }
    return new Promise(() => {})
  }
  assert.equal(f.page.onReady(), undefined)
  assert.deepEqual(f.calls, [['subjects'], ['lateLoad']])
})

test('show marks alive, synchronizes and reveals capsule before its ready guard', () => {
  const f = fixture()
  f.page.data.batchMode = true
  f.page._syncDateFilter = function () { assert.equal(this._alive, true); f.calls.push(['sync']) }
  assert.equal(f.page.onShow(), undefined)
  assert.deepEqual(f.calls.map(c => c[0]), ['sync', '_showBatchCapsuleAndRefreshTimer'])
})

test('ready show starts stats/list in order and calls the current diagnosis even after destruction', async () => {
  const f = fixture(), stats = deferred(), list = deferred()
  f.page._ready = true
  f.page.loadStats = function () { assert.equal(this, f.page); f.calls.push(['stats']); return stats.promise }
  f.page.loadList = function (reset) { assert.equal(this, f.page); assert.equal(reset, true); f.calls.push(['list']); return list.promise }
  assert.equal(f.page.onShow(), undefined)
  assert.deepEqual(f.calls.map(c => c[0]), ['_syncDateFilter', 'stats', 'list'])
  f.page._checkAiDiagnosis = function () { assert.equal(this, f.page); f.calls.push(['lateDiagnosis']) }
  stats.resolve(); await flush(); assert.equal(f.calls.length, 3)
  f.page._destroyed = true; list.resolve(); await flush()
  assert.deepEqual(f.calls.at(-1), ['lateDiagnosis'])
})

test('hide changes alive before cleanup and preserves thrown cleanup errors', () => {
  const f = fixture(), error = Error('clear')
  f.page._alive = true
  f.page._clearBatchCapsuleIdleTimer = function () { assert.equal(this._alive, false); throw error }
  assert.throws(() => f.page.onHide(), value => value === error)
})

test('unload invalidates six sequences before ordered timer cleanup and suppresses undo view write', () => {
  const f = fixture(), p = f.page
  const fields = ['_exportCapabilityRequestId', '_statsRequestSeq', '_subjectsRequestSeq',
    '_taskFlowRequestSeq', '_listRequestSeq', '_aiDiagnosisRequestId']
  for (const field of fields) p[field] = 5
  Object.assign(p, { _alive: true, _selectionPulseTimer: 20, _aiAutoSwitchTimer: 21, _batchMasterUndoInFlight: true })
  p._clearBatchCapsuleIdleTimer = function () {
    assert.equal(this, p); assert.equal(p._destroyed, true); assert.equal(p._alive, false)
    for (const field of fields) assert.equal(p[field], 6)
    f.calls.push(['capsule'])
  }
  p._clearBatchMasterUndo = function (skip) {
    assert.equal(this, p); assert.equal(skip, true); assert.equal(p._batchMasterUndoInFlight, false)
    f.calls.push(['undo'])
  }
  p.onUnload()
  assert.deepEqual(f.calls, [['capsule'], ['clearTimer', 20], ['clearTimer', 21], ['undo']])
  assert.equal(p._selectionPulseTimer, null); assert.equal(p._aiAutoSwitchTimer, null)
})

test('unload failure preserves original partial cleanup and in-flight state', () => {
  const f = fixture(), error = Error('timer')
  Object.assign(f.page, { _selectionPulseTimer: 20, _aiAutoSwitchTimer: 21, _batchMasterUndoInFlight: true })
  f.context.clearTimeout = () => { throw error }
  assert.throws(() => f.page.onUnload(), value => value === error)
  assert.equal(f.page._selectionPulseTimer, 20); assert.equal(f.page._aiAutoSwitchTimer, 21)
  assert.equal(f.page._batchMasterUndoInFlight, true); assert.equal(f.page._destroyed, true)
})

test('export capability flag must be literal true and always resets the initial fields', async () => {
  for (const enabled of [undefined, false, 1, 'true']) {
    const f = fixture()
    f.config.WRONG_BOOK_EXPORT_ENABLED = enabled
    f.exportApi.getCapabilities = () => assert.fail('unexpected capability fetch')
    await f.methods._checkExportCapability.call(f.page)
    assert.equal(f.page._exportCapabilityRequestId, 1)
    assert.equal(f.page.data.exportAvailable, false); assert.equal(f.page.data.exportCapabilityChecked, true)
    assert.equal(f.calls.length, 2)
    assert.deepEqual(Object.keys(f.calls[0][1]), ['exportAvailable', 'exportCapabilityChecked', 'exportUnavailableText'])
  }
})

test('capability requires both strict feature flags, keeps receiver and allows destroyed success with current formatter', async () => {
  for (const capability of [{ export_enabled: true, pdf_enabled: true }, { export_enabled: true, pdf_enabled: 1 }, null]) {
    const f = fixture(), request = deferred()
    f.config.WRONG_BOOK_EXPORT_ENABLED = true
    f.exportApi.getCapabilities = function () { assert.equal(this, f.exportApi); return request.promise }
    const work = f.methods._checkExportCapability.call(f.page)
    f.page._destroyed = true
    f.exportApi.getExportCapabilityErrorMessage = function (error, data) {
      assert.equal(this, f.exportApi); assert.equal(error, null); assert.equal(data, capability); return 'late message'
    }
    request.resolve(capability); await work
    const available = capability && capability.pdf_enabled === true
    assert.equal(f.page.data.exportAvailable, !!available)
    assert.equal(f.page.data.exportUnavailableText, available ? '' : 'late message')
  }
})

test('stale capability success and rejection skip formatting/writeback and current failure uses live formatter', async () => {
  for (const stale of [false, true]) for (const rejects of [false, true]) {
    const f = fixture(), request = deferred(), error = Error('capability')
    f.config.WRONG_BOOK_EXPORT_ENABLED = true; f.exportApi.getCapabilities = () => request.promise
    const work = f.methods._checkExportCapability.call(f.page)
    f.exportApi.getExportCapabilityErrorMessage = function (value) {
      assert.equal(this, f.exportApi); assert.equal(stale, false); assert.equal(value, error); return 'failure'
    }
    if (stale) f.page._exportCapabilityRequestId++
    if (rejects) request.reject(error); else request.resolve({ export_enabled: true, pdf_enabled: true })
    await work
    assert.equal(f.calls.length, stale ? 1 : 2)
    assert.equal(f.page.data.exportCapabilityChecked, !stale)
    if (!stale && rejects) assert.equal(f.page.data.exportUnavailableText, 'failure')
  }
})

test('capability initial write stays outside try and a success formatter failure enters the original catch', async () => {
  const f = fixture(), error = Error('initial')
  f.page.setData = () => { throw error }
  await assert.rejects(f.methods._checkExportCapability.call(f.page), value => value === error)
  const next = fixture()
  next.config.WRONG_BOOK_EXPORT_ENABLED = true
  next.exportApi.getCapabilities = async () => ({})
  let calls = 0
  next.exportApi.getExportCapabilityErrorMessage = function (value) {
    if (calls++ === 0) throw error
    assert.equal(value, error); return 'recovered'
  }
  await next.methods._checkExportCapability.call(next.page)
  assert.equal(next.page.data.exportUnavailableText, 'recovered'); assert.equal(calls, 2)
})

test('detail navigation stores the live task ID array, prepends missing ID and keeps raw list IDs', () => {
  const f = fixture(), ids = ['2', '1']
  f.page._getVisibleIds = function () { assert.equal(this, f.page); return ids }
  f.page._navigateToDetail('3&x')
  assert.deepEqual(ids, ['3&x', '2', '1'])
  assert.equal(f.calls[0][1], 'wrong_detail_nav'); assert.equal(f.calls[0][2].ids, ids)
  assert.equal(f.calls[0][2].ts, 12345)
  assert.ok(f.calls[1][1].url.includes('id=3%26x&idx=0&source=wrong-book'))
  f.page.data.activeView = 'all'; f.page.data.list = [{ id: 2 }, { id: '2' }, { id: 4 }]
  f.page._navigateToDetail('2')
  assert.deepEqual(plain(f.calls[2][2].ids), [2, '2', 4])
  assert.ok(f.calls[3][1].url.includes('&idx=0&'))
})

test('detail storage failure logs then uses current platform navigation while navigation errors propagate', () => {
  const f = fixture(), error = Error('navigate')
  f.page._getVisibleIds = () => []
  f.context.wx.setStorageSync = () => {
    f.context.wx = { navigateTo() { f.calls.push(['lateNavigate']); throw error } }
    throw Error('storage')
  }
  assert.throws(() => f.page._navigateToDetail(1), value => value === error)
  assert.deepEqual(f.calls.map(c => c[0]), ['warn', 'lateNavigate'])
})

test('export selected validates availability and positive-or-negative finite nonzero IDs before app access', () => {
  const f = fixture()
  f.page.data.exportUnavailableText = 'disabled'; f.page.onExportSelected()
  assert.equal(f.calls.at(-1)[1].title, 'disabled')
  f.page.data.exportAvailable = true
  f.page.data.selectedIds = ['0', 'bad', Infinity, null]
  f.page.onExportSelected(); assert.equal(f.calls.at(-1)[1].title, '请先选择错题')
  f.page.data.selectedIds = Array.from({ length: 101 }, (_, i) => i + 1)
  f.page.onExportSelected(); assert.ok(f.calls.at(-1)[1].title.includes('100 道'))
  assert.equal(f.calls.some(c => c[0] === 'app'), false)
  f.page.data.selectedIds = ['01', '-2', '2.5', '0', 'bad']
  assert.equal(f.page.onExportSelected(), undefined)
  assert.deepEqual(plain(f.globalData.exportSelectedIds), [1, -2, 2.5])
  assert.deepEqual(f.calls.slice(-3).map(c => c[0]), ['app', 'globalData', 'navigate'])
  assert.equal(f.calls.at(-1)[1].url, '/subpackages/export/export-config/export-config')
})

test('export writes global IDs before navigation and app failures propagate', () => {
  const f = fixture(), error = Error('app')
  f.page.data.exportAvailable = true; f.page.data.selectedIds = [1]
  f.context.getApp = () => { throw error }
  assert.throws(() => f.page.onExportSelected(), value => value === error)
  f.context.getApp = () => f.app
  f.context.wx.navigateTo = () => { throw error }
  assert.throws(() => f.page.onExportSelected(), value => value === error)
  assert.deepEqual(plain(f.globalData.exportSelectedIds), [1])
})

test('back fallback reads the current platform and records/detail routes preserve their invocation behavior', () => {
  const f = fixture()
  assert.equal(f.page.goBack(), undefined)
  const fail = f.calls[0][1].fail, platform = {
    reLaunch(options) { assert.equal(this, platform); f.calls.push(['lateRelaunch', options]) },
    navigateTo(options) { assert.equal(this, platform); f.calls.push(['lateNavigate', options]) },
  }
  f.context.wx = platform; fail()
  assert.equal(f.calls.at(-1)[1].url, '/pages/home/home')
  f.page.onViewExportRecords(); assert.equal(f.calls.at(-1)[1].url, '/subpackages/export/export-records/export-records')
  f.page._navigateToDetail = function (id) { assert.equal(this, f.page); f.calls.push(['detail', id]); return 99 }
  assert.equal(f.page.goDetail({ currentTarget: { dataset: { id: 'raw' } } }), undefined)
  assert.deepEqual(f.calls.at(-1), ['detail', 'raw'])
})
