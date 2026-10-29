const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

function setup() {
  const f = fixture(), timers = new Map()
  let next = 30
  f.context.Date = { now: () => 1000 }
  f.context.console = { error: (...args) => f.calls.push(['error', ...args]) }
  f.context.setTimeout = (fn, ms) => {
    const id = ++next
    timers.set(id, { fn, ms }); f.calls.push(['timer', id, ms]); return id
  }
  f.context.clearTimeout = id => { f.calls.push(['clear', id]); timers.delete(id) }
  f.context.wx.setStorageSync = function (...args) {
    assert.equal(this, f.context.wx); f.calls.push(['storage', ...args])
  }
  f.api.post = function (...args) {
    assert.equal(this, f.api); f.calls.push(['post', ...args]); return Promise.resolve({})
  }
  const page = f.page
  page.data.questionIds = [11, '12', 12, 13]
  page.data.currentIdx = 2
  page._wqCache = { 12: { data: page.data.wq }, 13: { data: { id: 13 } } }
  page._clearMasterUndo = function () { assert.equal(this, page); f.calls.push(['clearUndo']) }
  page.loadData = function (...args) { assert.equal(this, page); f.calls.push(['load', ...args]) }
  page.goBack = function () { assert.equal(this, page); f.calls.push(['back']) }
  return {
    ...f, timers,
    fire(id) { const timer = timers.get(id); assert.ok(timer); timers.delete(id); timer.fn() },
  }
}

test('more/remove dialogs preserve exact patches and only close-remove has a busy guard', () => {
  const f = setup(), page = f.page
  page.data.removeSubmitting = true
  page.openMoreMenu(); page.closeMoreMenu(); page.openRemoveConfirm(); page.closeRemoveConfirm()
  assert.deepEqual(plain(f.calls), [
    ['setData', { moreMenuVisible: true }], ['setData', { moreMenuVisible: false }],
    ['setData', { moreMenuVisible: false, removeConfirmVisible: true }],
  ])
  page.data.removeSubmitting = false
  assert.equal(page.closeRemoveConfirm(), undefined)
  assert.deepEqual(plain(f.calls.at(-1)), ['setData', { removeConfirmVisible: false }])
})

test('remove ignores missing ids and busy submissions and captures private id before request', async () => {
  const f = setup(), page = f.page
  page.data.wq = null
  await page.removeFromWrongBook(); assert.deepEqual(f.calls, [])
  page.data.wq = { id: 12 }; page.data.removeSubmitting = true
  await page.removeFromWrongBook(); assert.deepEqual(f.calls, [])
  page.data.removeSubmitting = false; page._currentWqId = '44'
  const request = deferred()
  f.api.post = function (...args) {
    assert.equal(this, f.api); f.calls.push(['post', ...args]); return request.promise
  }
  const work = page.removeFromWrongBook()
  assert.deepEqual(plain(f.calls), [
    ['clearUndo'], ['setData', { removeSubmitting: true }],
    ['post', '/wrong-questions/batch', { action: 'remove_from_book', ids: ['44'] }],
  ])
  page._alive = false; request.resolve({}); await work
  assert.equal(page.data.removeSubmitting, true)
  assert.equal(page._wqCache[12].data.id, 12)
  assert.equal(f.calls.length, 3)
})

test('remove reads current navigation after await, removes string-equivalent duplicates and preserves storage shape', async () => {
  const f = setup(), page = f.page, request = deferred(), cache = page._wqCache
  f.api.post = () => request.promise
  const work = page.removeFromWrongBook()
  page.data.questionIds = [99, '12', 13, 12, 14]; page.data.currentIdx = 3
  const options = []
  f.context.wx = {
    setStorageSync(...args) { assert.equal(this, f.context.wx); options.push(args); f.calls.push(['lateStorage']) },
    showToast(...args) { assert.equal(this, f.context.wx); f.calls.push(['lateToast', ...args]) },
  }
  request.resolve({ skipped_ids: [12], updated_count: 0 })
  await work
  assert.equal(page._wqCache, cache); assert.equal(cache[12], undefined)
  assert.equal(cache[13].data.id, 13)
  assert.deepEqual(plain(options), [['wrong_detail_nav', { ids: [99, 13, 14], ts: 1000 }]])
  assert.deepEqual(Object.keys(options[0][1]), ['ids', 'ts'])
  assert.deepEqual(plain(page.data.questionIds), [99, 13, 14])
  assert.equal(page.data.currentIdx, 2)
  assert.equal(page.data.totalQuestions, 3)
  assert.equal(page.data.removeSubmitting, false)
  assert.equal(page.data.removeConfirmVisible, false)
  assert.deepEqual(f.calls.map(c => c[0]), [
    'clearUndo', 'setData', 'lateStorage', 'setData', 'setData', 'load', 'lateToast',
  ])
  assert.deepEqual(f.calls.at(-2), ['load', 14])
})

test('remove storage error is swallowed and current loader is awaited before toast', async () => {
  const f = setup(), wait = deferred(), page = f.page
  f.context.wx.setStorageSync = () => { throw new Error('storage') }
  page.loadData = function (id) {
    assert.equal(this, page); f.calls.push(['load', id]); return wait.promise
  }
  let done = false
  const work = page.removeFromWrongBook().then(() => { done = true })
  await new Promise(setImmediate)
  assert.equal(done, false)
  assert.equal(page.data.currentIdx, 1)
  assert.deepEqual(f.calls.at(-1), ['load', 13])
  assert.equal(f.calls.filter(c => c[0] === 'toast').length, 0)
  page._alive = false
  wait.resolve(); await work
  // There is intentionally no second alive guard after the awaited loader.
  assert.equal(f.calls.at(-1)[1].title, '已移出错题本')
})

test('last removal toasts before replacing 220ms back timer and reads current back hook when fired', async () => {
  const f = setup(), page = f.page
  page.data.questionIds = ['12', 12]
  page._removeBackTimer = 8
  await page.removeFromWrongBook()
  assert.deepEqual(plain(page.data.questionIds), [])
  assert.equal(page.data.currentIdx, 2)
  assert.equal(f.timers.get(page._removeBackTimer).ms, 220)
  assert.deepEqual(f.calls.slice(-3).map(c => c[0]), ['toast', 'clear', 'timer'])
  page.goBack = function () { assert.equal(this, page); f.calls.push(['lateBack']) }
  f.fire(page._removeBackTimer)
  assert.equal(page._removeBackTimer, null)
  assert.deepEqual(f.calls.at(-1), ['lateBack'])
})

test('last removal timer clears its handle but does not navigate after unload', async () => {
  const f = setup()
  f.page.data.questionIds = null
  f.page._wqCache = null
  await f.page.removeFromWrongBook()
  f.page._alive = false; f.fire(f.page._removeBackTimer)
  assert.equal(f.page._removeBackTimer, null)
  assert.equal(f.calls.some(c => c[0] === 'back'), false)
})

test('request and loader failures keep catch boundaries and do not roll back completed navigation writes', async () => {
  for (const atLoader of [false, true]) {
    const f = setup(), error = new Error(atLoader ? 'loader' : 'request')
    if (atLoader) f.page.loadData = () => { throw error }
    else f.api.post = () => { throw error }
    await f.page.removeFromWrongBook()
    assert.equal(f.page.data.removeSubmitting, false)
    const logged = f.calls.find(c => c[0] === 'error')
    assert.equal(logged[2], error)
    assert.equal(f.calls.at(-1)[1].title, '移出失败，请重试')
    assert.deepEqual(plain(f.page.data.questionIds), atLoader ? [11, 13] : [11, '12', 12, 13])
    assert.equal(f.page._wqCache[12] === undefined, atLoader)
  }
})

test('undo-clear and initial patch failures occur outside remove try and propagate without retry toast', async () => {
  for (const atPatch of [false, true]) {
    const f = setup(), error = new Error('before try')
    if (atPatch) f.page.setData = () => { throw error }
    else f.page._clearMasterUndo = () => { throw error }
    await assert.rejects(f.page.removeFromWrongBook(), value => value === error)
    assert.equal(f.calls.some(c => ['post', 'error', 'toast'].includes(c[0])), false)
  }
})

test('dead rejected requests suppress error writes while toast failure after last removal reaches original catch', async () => {
  const f = setup(), request = deferred()
  f.api.post = () => request.promise
  const work = f.page.removeFromWrongBook()
  f.page._alive = false; request.reject(new Error('late')); await work
  assert.deepEqual(f.calls.map(c => c[0]), ['clearUndo', 'setData'])
  const other = setup(), error = new Error('toast')
  other.page.data.questionIds = [12]
  let attempts = 0
  other.context.wx.showToast = () => { if (++attempts === 1) throw error }
  await other.page.removeFromWrongBook()
  assert.equal(attempts, 2)
  assert.equal(other.timers.size, 0)
  assert.equal(other.calls.find(c => c[0] === 'error')[2], error)
})
