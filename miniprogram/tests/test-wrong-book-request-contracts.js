const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-book-request-fixture')
const plain = value => JSON.parse(JSON.stringify(value))
const flush = () => new Promise(setImmediate)

test('filter reload invalidates both sequences before patch, honors overrides and calls current hooks without await', () => {
  const f = fixture(), page = f.page, overrideList = [{ id: 9 }]
  page._listRequestSeq = 5; page._taskFlowRequestSeq = 7
  page._updateFilterCount = function () {
    assert.equal(this, page); assert.equal(page._listRequestSeq, 6)
    assert.equal(page._taskFlowRequestSeq, 8); f.calls.push(['filter'])
    page.loadList = function (reset) {
      assert.equal(this, page); assert.equal(reset, true)
      f.calls.push(['list']); return new Promise(() => {})
    }
  }
  assert.equal(page._beginFilterReload({ list: overrideList, page: 8, loading: false }), undefined)
  assert.equal(page.data.list, overrideList); assert.equal(page.data.page, 8)
  assert.equal(page.data.loading, false)
  assert.deepEqual(Object.keys(f.calls[0][1]), [
    'list', 'listTotal', 'page', 'hasMore', 'loading', 'listError', 'taskGroups',
    'ungroupedCount', 'selectedIds', 'selectedIdMap', 'selectedCount', 'allVisibleSelected', 'batchMoreVisible',
  ])
  assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'filter', 'list'])
})

test('page load starts stats/list in order, waits for both and invokes current diagnosis unless destroyed', async () => {
  for (const destroyed of [false, true]) {
    const f = fixture(), stats = deferred(), list = deferred(), diagnosis = deferred()
    f.page.loadStats = function () { assert.equal(this, f.page); f.calls.push(['stats']); return stats.promise }
    f.page.loadList = function (reset) { assert.equal(this, f.page); assert.equal(reset, true); f.calls.push(['list']); return list.promise }
    let done = false
    const work = f.page._loadPage().then(() => { done = true })
    assert.deepEqual(plain(f.calls), [['setData', { list: [], page: 1 }], ['stats'], ['list']])
    f.page._checkAiDiagnosis = function () { assert.equal(this, f.page); f.calls.push(['diagnosis']); return diagnosis.promise }
    stats.resolve(); await flush(); assert.equal(done, false)
    f.page._destroyed = destroyed; list.resolve(); await flush()
    assert.equal(f.calls.some(c => c[0] === 'diagnosis'), !destroyed)
    assert.equal(done, destroyed)
    diagnosis.resolve(); await work
  }
})

test('page load preserves synchronous invocation failures and Promise.all rejection propagation', async () => {
  for (const synchronous of [true, false]) {
    const f = fixture(), error = new Error('stats')
    f.page.loadStats = () => { if (synchronous) throw error; return Promise.reject(error) }
    f.page.loadList = () => { f.calls.push(['list']); return Promise.resolve() }
    f.page._checkAiDiagnosis = () => assert.fail('unexpected diagnosis')
    await assert.rejects(f.page._loadPage(), value => value === error)
    assert.equal(f.calls.some(c => c[0] === 'list'), !synchronous)
  }
})

test('stats retains global scope, numeric-unmastered rules, live helpers and current list references', async () => {
  for (const stats of [
    { total: 10, unmastered: 4, high_frequency_count: 3 },
    { total: 10, unmastered: '4' }, { total: 1, unmastered: 4 },
  ]) {
    const f = fixture(), request = deferred(), list = [{ _isMastered: true }, { _isMastered: false }]
    f.api.get = function (...args) { assert.equal(this, f.api); f.calls.push(['get', ...args]); return request.promise }
    const work = f.page.loadStats()
    assert.deepEqual(plain(f.calls), [['get', '/wrong-questions/stats', { product_scope: 'exam408' }]])
    f.page.data.list = list; f.page.data.aiDiagnosis = { summary: 'summary' }
    f.page._oneLineInsight = function (value) { assert.equal(this, f.page); assert.equal(value, 'summary'); return 'insight' }
    request.resolve(stats); await work
    assert.equal(f.page.data.stats, stats); assert.equal(f.page._aiStatsLoaded, true)
    assert.equal(f.page.data.primaryStatCount, typeof stats.unmastered === 'number' ? stats.unmastered : stats.total)
    assert.equal(f.page.data.masteredCount, typeof stats.unmastered === 'number' ? Math.max(0, stats.total - stats.unmastered) : 1)
    assert.equal(f.page.data.analysis.list, list); assert.equal(f.page.data.analysis.stats, stats)
    assert.equal(f.page.data.aiInsightText, 'insight')
  }
})

test('stats filtering skips analysis; stale/destroyed responses and errors stop, while alive=false alone does not', async () => {
  const f = fixture()
  f.page.data.list = [{ _isMastered: true }]; f.page.data.selectedTopic = 'topic'
  f.page._alive = false; f.api.get = async () => ({ total: 4 })
  await f.page.loadStats()
  assert.equal(f.page.data.masteredCount, 1)
  assert.equal(f.calls.some(c => c[0] === 'analysis'), false)
  for (const destroyed of [false, true]) {
    const other = fixture(), request = deferred()
    other.api.get = () => request.promise
    const work = other.page.loadStats()
    if (destroyed) other.page._destroyed = true
    else other.page._statsRequestSeq++
    request.resolve({ total: 9 }); await work
    assert.equal(other.page._aiStatsLoaded, false)
    assert.deepEqual(other.calls, [])
    const failed = deferred(); other.api.get = () => failed.promise
    const retry = other.page.loadStats()
    if (!destroyed) other.page._statsRequestSeq++
    failed.reject(new Error('late')); await retry
    assert.deepEqual(other.calls, [])
  }
})

test('list date rollover forces reset, invalidates task flow and retains params/patch order and nonawaited flow', async () => {
  const f = fixture(), request = deferred(), item = { id: 12 }
  f.page.data.dateFrom = 'old'; f.page.data.dateTo = 'end'
  f.page.data.selectedSubjectId = 4
  f.page._syncDateFilter = function () { assert.equal(this, f.page); this.data.dateFrom = 'new'; f.calls.push(['syncDate']) }
  f.api.get = function (...args) { assert.equal(this, f.api); f.calls.push(['get', ...args]); return request.promise }
  const work = f.page.loadList(false)
  assert.equal(f.page._taskFlowRequestSeq, 1)
  assert.deepEqual(plain(f.calls.slice(0, 3)), [
    ['syncDate'], ['setData', { loading: true, listError: '' }],
    ['get', '/wrong-questions', { page: 1, page_size: 20, product_scope: 'exam408', subject_id: 4, date_from: 'new', date_to: 'end' }],
  ])
  const stats = { high_frequency_count: '2.6' }; f.page.data.stats = stats
  request.resolve({ items: [item], total: '-2', total_pages: 4 }); await work
  assert.equal(f.page.data.list.length, 1); assert.equal(f.page.data.list[0].id, 12)
  assert.equal(f.page.data.listTotal, 0); assert.equal(f.page.data.page, 2); assert.equal(f.page.data.hasMore, true)
  assert.equal(f.page.data.highFrequencyCount, 3)
  assert.deepEqual(plain(f.page.data.analysis.stats), {})
  assert.equal(f.calls.at(-2)[0], 'selection'); assert.equal(f.calls.at(-1)[0], 'taskFlow')
  assert.deepEqual(Object.keys(f.calls.find(c => c[0] === 'setData' && 'list' in c[1])[1]), [
    'list', 'listTotal', 'analysis', 'taskGroups', 'ungroupedCount', 'highFrequencyCount',
    'aiInsightText', 'hasMore', 'page', 'loading',
  ])
})

test('list append reads current list/stats after await and uses original high-frequency fallback', async () => {
  const f = fixture(), request = deferred(), existing = { id: 1 }, appended = { id: 12, _wrongCount: 3 }
  f.api.get = () => request.promise
  const work = f.page.loadList()
  f.page.data.list = [existing]
  const stats = { high_frequency_count: 'bad' }; f.page.data.stats = stats
  request.resolve({ items: [appended, { id: 13, _wrongCount: 4, _isMastered: true }], total: '7', total_pages: 3 })
  await work
  assert.equal(f.page.data.list[0], existing)
  assert.equal(f.page.data.list.length, 3); assert.equal(f.page.data.page, 4)
  assert.equal(f.page.data.hasMore, false); assert.equal(f.page.data.listTotal, 7)
  assert.equal(f.page.data.highFrequencyCount, 1)
  assert.equal(f.page.data.analysis.stats, stats)
  assert.equal(f.calls.some(c => c[0] === 'taskFlow'), false)
})

test('list guards before mapping and after dynamic decoration, preserving later analysis side effects', async () => {
  for (const when of ['response', 'decoration', 'analysis']) {
    const f = fixture(), request = deferred()
    f.api.get = () => request.promise
    const work = f.page.loadList(true)
    if (when === 'response') f.page._alive = false
    f.page._decorateItem = function (item) {
      assert.equal(this, f.page); f.calls.push(['decorate'])
      if (when === 'decoration') this._listRequestSeq++
      return item
    }
    f.page._buildAnalysis = function () {
      f.calls.push(['analysis']); this._listRequestSeq++; return 'analysis'
    }
    request.resolve({ items: [{ id: 12 }], total_pages: 1 }); await work
    assert.equal(f.calls.some(c => c[0] === 'decorate'), when !== 'response')
    assert.equal(f.calls.some(c => c[0] === 'analysis'), when === 'analysis')
    assert.equal(f.page.data.loading, when !== 'analysis')
  }
})

test('list errors always log but only current alive requests format/write; pre-request errors propagate', async () => {
  for (const current of [true, false]) {
    const f = fixture(), request = deferred(), error = new Error('list')
    f.api.get = () => request.promise
    const work = f.page.loadList()
    if (!current) f.page._listRequestSeq++
    request.reject(error); await work
    assert.equal(f.calls.find(c => c[0] === 'error')[2], error)
    assert.equal(f.calls.some(c => c[0] === 'format'), current)
    assert.equal(f.page.data.listError, current ? 'formatted' : '')
  }
  const f = fixture(), error = new Error('date')
  f.page._syncDateFilter = () => { throw error }
  await assert.rejects(f.page.loadList(), value => value === error)
  assert.equal(f.page._listRequestSeq, 0); assert.deepEqual(f.calls, [])
})

test('task flow projects original meta, retains duplicate previews and current helper calls', async () => {
  const f = fixture(), request = deferred(), item = { id: 12 }
  f.api.get = function (...args) { assert.equal(this, f.api); f.calls.push(['get', ...args]); return request.promise }
  const work = f.methods.loadTaskFlow.call(f.page)
  assert.deepEqual(plain(f.calls), [['get', '/wrong-questions/task-flow', { preview_size: 3, product_scope: 'exam408' }]])
  request.resolve({ groups: [
    { key: 'today_due', title: 'due', total: 2, items: [item, item] },
    { key: 'unknown', total: -1, items: [{ id: 13 }] }, { key: 'empty', total: 0 },
  ], summary: { total_count: 8, high_frequency_count: 6 } })
  await work
  assert.equal(f.page.data.taskGroups.length, 2)
  const first = f.page.data.taskGroups[0], other = f.page.data.taskGroups[1]
  assert.deepEqual(plain(first), { key: 'today_due', title: 'due', total: 2, items: [
    { id: 12, decorated: true }, { id: 12, decorated: true },
  ], desc: '基于复习计划，今天最值得先做的题', icon: '今', tone: 'lime' })
  assert.equal(other.title, ''); assert.equal(other.total, 0); assert.equal(other.icon, '·')
  assert.equal(f.page.data.ungroupedCount, 5)
  // The empty global stats object coerces undefined to NaN and uses summary fallback.
  assert.equal(f.page.data.highFrequencyCount, 6)
  assert.equal(f.calls.at(-1)[0], 'selection')
})

test('task flow high-frequency keeps global rounded priority and filtered fallback distinctions', async () => {
  for (const [global, filtered, expected] of [[-2, true, 0], ['2.6', true, 3], ['bad', false, 7], ['bad', true, 5]]) {
    const f = fixture()
    f.page.data.stats = { high_frequency_count: global }; f.page.data.highFrequencyCount = 5
    f.page.data.selectedTopic = filtered ? 'topic' : ''
    f.api.get = async () => ({ summary: { high_frequency_count: 7 } })
    await f.methods.loadTaskFlow.call(f.page)
    assert.equal(f.page.data.highFrequencyCount, expected)
  }
})

test('task-flow error guard omits alive unlike success; params construction remains outside catch', async () => {
  const f = fixture(), request = deferred(), error = new Error('flow')
  f.api.get = () => request.promise
  const work = f.methods.loadTaskFlow.call(f.page)
  f.page._alive = false; request.reject(error); await work
  assert.equal(f.calls.at(-1)[0], 'warn'); assert.equal(f.calls.at(-1)[2], error)
  const other = fixture()
  other.page._filterParams = () => { throw error }
  await assert.rejects(other.methods.loadTaskFlow.call(other.page), value => value === error)
  assert.equal(other.page._taskFlowRequestSeq, 1); assert.deepEqual(other.calls, [])
})

test('subjects honor loading guard, reread current projection after await and do not require alive', async () => {
  const f = fixture(), request = deferred(), raw = [{ id: 12 }], projected = [{ value: 12, label: 'subject' }]
  f.page.data.subjectsLoading = true; await f.page.loadSubjects(); assert.deepEqual(f.calls, [])
  f.page.data.subjectsLoading = false
  f.api.get = function (...args) { assert.equal(this, f.api); f.calls.push(['get', ...args]); return request.promise }
  const work = f.page.loadSubjects()
  assert.deepEqual(plain(f.calls), [
    ['setData', { subjectsLoading: true, subjectsError: false }], ['get', '/practice/subjects'],
  ])
  f.page._alive = false
  f.page._flattenSubjectOptions = function (value) { assert.equal(this, f.page); assert.equal(value, raw); return projected }
  request.resolve(raw); await work
  assert.equal(f.page.data.subjects[1], projected[0])
  assert.equal(f.page.data.subjectsLoaded, true); assert.equal(f.page.data.subjectsLoading, false)
  assert.deepEqual(plain(f.page.data.subjects[0]), { value: '', label: '全部' })
})

test('subjects failure resets fallback, but stale/destroyed requests keep their original loading patch', async () => {
  for (const mode of ['current', 'stale', 'destroyed']) {
    const f = fixture(), request = deferred(), error = new Error('subjects')
    f.api.get = () => request.promise
    const work = f.page.loadSubjects()
    if (mode === 'stale') f.page._subjectsRequestSeq++
    if (mode === 'destroyed') f.page._destroyed = true
    request.reject(error); await work
    assert.equal(f.page.data.subjectsLoading, mode !== 'current')
    assert.equal(f.page.data.subjectsError, mode === 'current')
    assert.equal(f.calls.some(c => c[0] === 'error'), mode === 'current')
    if (mode === 'current') {
      assert.equal(f.page.data.subjectsLoaded, false)
      assert.deepEqual(plain(f.page.data.subjects), [{ value: '', label: '全部' }])
    }
  }
})
