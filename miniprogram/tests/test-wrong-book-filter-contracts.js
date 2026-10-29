const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture: lifecycleFixture } = require('./helpers/wrong-book-lifecycle-fixture')
const plain = value => JSON.parse(JSON.stringify(value))
const event = value => ({ detail: { value } })

function fixture() {
  const f = lifecycleFixture()
  f.page._syncDateFilter = f.methods._syncDateFilter
  f.page._updateFilterCount = f.methods._updateFilterCount
  f.api = f.stubs['../../../utils/api']
  f.dateFilter = f.stubs['../../../components/question-filter-panel/date-range']
  f.api.now = function () { assert.equal(this, f.api); f.calls.push(['now']); return 123 }
  f.dateFilter.presetRange = function (preset, time) {
    assert.equal(this, f.dateFilter); f.calls.push(['range', preset, time])
    return { dateFrom: 'from', dateTo: 'to' }
  }
  return f
}

test('filter count and presence retain truthy flags and combine either date into one criterion', () => {
  const f = fixture()
  assert.equal(f.page._hasFilters(), false)
  Object.assign(f.page.data, { selectedSubjectId: 0, selectedErrorType: '', selectedTopic: '', dateFrom: '', dateTo: '' })
  f.page._updateFilterCount(); assert.equal(f.page.data.filterCount, 0)
  Object.assign(f.page.data, { selectedSubjectId: '0', selectedErrorType: 'calculation', selectedTopic: 'topic', dateFrom: 'from', dateTo: 'to' })
  assert.equal(f.page._hasFilters(), true)
  assert.equal(f.page._updateFilterCount(), undefined); assert.equal(f.page.data.filterCount, 4)
  Object.assign(f.page.data, { selectedSubjectId: null, selectedErrorType: '', selectedTopic: '', dateFrom: '' })
  f.page._updateFilterCount(); assert.equal(f.page.data.filterCount, 1)
})

test('filter params keep product scope, field order, original values and truthy omission rules', () => {
  const f = fixture()
  assert.deepEqual(plain(f.page._filterParams()), { product_scope: 'exam408' })
  Object.assign(f.page.data, { selectedSubjectId: '02', selectedErrorType: 'other',
    selectedTopic: 'topic', dateFrom: 'from', dateTo: 'to' })
  const params = f.page._filterParams()
  assert.deepEqual(Object.keys(params), ['product_scope', 'subject_id', 'error_type', 'topic', 'date_from', 'date_to'])
  assert.equal(params.subject_id, '02')
  f.page.data.selectedSubjectId = NaN; f.page.data.selectedErrorType = false
  assert.deepEqual(Object.keys(f.page._filterParams()), ['product_scope', 'topic', 'date_from', 'date_to'])
})

test('date sync always reads current API time, skips range helper for custom and writes an empty patch', () => {
  const f = fixture()
  f.page.data.selectedDatePreset = 'custom'
  assert.equal(f.page._syncDateFilter(), undefined)
  assert.deepEqual(plain(f.calls), [['now'], ['setData', {}]])
  f.calls.length = 0; f.page.data.selectedDatePreset = 'week'
  f.page._syncDateFilter()
  assert.deepEqual(plain(f.calls), [['now'], ['range', 'week', 123], ['setData', { dateFrom: 'from', dateTo: 'to' }]])
  assert.equal(f.page.data.dateFrom, 'from')
})

test('date sync time/range failures propagate before write and do not get swallowed', () => {
  const f = fixture(), error = Error('time')
  f.api.now = () => { throw error }
  assert.throws(() => f.page._syncDateFilter(), value => value === error)
  assert.equal(f.calls.length, 0)
  f.api.now = () => 1
  f.dateFilter.presetRange = () => { throw error }
  assert.throws(() => f.page._syncDateFilter(), value => value === error)
  assert.equal(f.calls.length, 0)
})

test('filter toggle synchronizes before readiness checks and does not await subjects before current visibility write', () => {
  const f = fixture()
  f.page._syncDateFilter = function () { assert.equal(this, f.page); f.calls.push(['sync']); this.data.subjectsLoaded = false }
  f.page.loadSubjects = function () {
    assert.equal(this, f.page); f.calls.push(['subjects']); this.data.showFilter = true
    return new Promise(() => {})
  }
  assert.equal(f.page.toggleFilter(), undefined)
  assert.deepEqual(f.calls.map(c => c[0]), ['sync', 'subjects', 'setData'])
  assert.equal(f.page.data.showFilter, false)
  for (const [loaded, loading] of [[true, false], [false, true]]) {
    f.calls.length = 0
    f.page._syncDateFilter = () => {}
    f.page.data.subjectsLoaded = loaded; f.page.data.subjectsLoading = loading
    f.page.toggleFilter()
    assert.equal(f.calls.some(c => c[0] === 'subjects'), false)
  }
})

test('subject selection keeps nullish/empty handling and unvalidated Number conversion with current reload receiver', () => {
  const f = fixture(), selected = []
  f.page._beginFilterReload = function (patch) { assert.equal(this, f.page); selected.push(patch.selectedSubjectId); return 99 }
  for (const value of ['', null, undefined, '02', 'bad', false, 'Infinity']) {
    assert.equal(f.page.selectSubject(event(value)), undefined)
  }
  assert.deepEqual(selected.slice(0, 4), [null, null, null, 2])
  assert.equal(Number.isNaN(selected[4]), true); assert.equal(selected[5], 0); assert.equal(selected[6], Infinity)
})

test('error/date selection preserves raw error value, date field order and falsey defaults', () => {
  const f = fixture(), patches = []
  f.page._beginFilterReload = function (patch) { assert.equal(this, f.page); patches.push(patch) }
  const raw = { custom: true }
  f.page.selectErrorType(event(raw)); assert.equal(patches[0].selectedErrorType, raw)
  f.page.onDateFilterChange({ detail: { preset: 'custom', dateFrom: 'from', dateTo: 'to' } })
  assert.deepEqual(Object.keys(patches[1]), ['selectedDatePreset', 'dateFrom', 'dateTo'])
  f.page.onDateFilterChange({ detail: null })
  assert.deepEqual(plain(patches[2]), { selectedDatePreset: '', dateFrom: '', dateTo: '' })
})

test('retry returns the exact loader result and preserves list access failure before invocation', () => {
  const f = fixture(), result = new Promise(() => {})
  f.page.loadList = function (reset) { assert.equal(this, f.page); f.calls.push(['list', reset]); return result }
  assert.equal(f.page.retryList(), result); assert.deepEqual(f.calls, [['list', true]])
  f.page.data.list = [{ id: 1 }]; assert.equal(f.page.retryList(), result)
  assert.deepEqual(f.calls.at(-1), ['list', false])
  f.page.data.list = null
  assert.throws(() => f.page.retryList(), error => error.name === 'TypeError')
  assert.equal(f.calls.length, 2)
})

test('load more preserves busy/more guards and invokes current loader without arguments or return', () => {
  const f = fixture()
  f.page.loadList = function (...args) { assert.equal(this, f.page); assert.equal(args.length, 0); f.calls.push(['list']); return 99 }
  for (const [loading, hasMore] of [[true, true], [false, false]]) {
    f.page.data.loading = loading; f.page.data.hasMore = hasMore
    assert.equal(f.page.loadMore(), undefined); assert.equal(f.calls.length, 0)
  }
  f.page.data.loading = false; f.page.data.hasMore = true
  assert.equal(f.page.loadMore(), undefined); assert.deepEqual(f.calls, [['list']])
})

test('topic clear and reset preserve exact patches and reload error propagation', () => {
  const f = fixture(), patches = []
  f.page._beginFilterReload = function (patch) { assert.equal(this, f.page); patches.push(patch); return 99 }
  assert.equal(f.page.clearTopic(), undefined)
  assert.deepEqual(plain(patches[0]), { selectedTopic: '' })
  assert.equal(f.page.resetFilters(), undefined)
  assert.deepEqual(plain(patches[1]), {
    selectedSubjectId: null, selectedErrorType: '', selectedTopic: '', selectedDatePreset: '',
    dateFrom: '', dateTo: '', filterCount: 0,
  })
  const error = Error('reload')
  f.page._beginFilterReload = () => { throw error }
  assert.throws(() => f.page.clearTopic(), value => value === error)
  assert.throws(() => f.page.resetFilters(), value => value === error)
})
