const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred, flush } = require('./helpers/wrong-book-batch-fixture')
const plain = value => JSON.parse(JSON.stringify(value))
const event = action => ({ currentTarget: { dataset: { action } } })

test('batch options keep component receiver and fallback and forward the original options identity', async () => {
  const f = fixture(), options = { title: 'options' }
  assert.equal(await f.page._showAppOptions(options), -1)
  f.page.selectComponent = () => ({ showOptions: true })
  assert.equal(await f.page._showAppOptions(options), -1)
  const expected = Promise.resolve(2), dialog = {
    showOptions(value) { assert.equal(this, dialog); assert.equal(value, options); return expected },
  }
  f.page.selectComponent = id => { assert.equal(id, '#appDialog'); return dialog }
  assert.equal(f.page._showAppOptions(options), expected)
})

test('more menu keeps empty selection guard, await-late dispatcher and non-awaited action', async () => {
  const f = fixture(), pending = deferred()
  await f.page.openBatchMore()
  assert.equal(f.calls[0][0], 'toast')
  f.page.data.selectedCount = 3
  f.page._showAppOptions = function (options) {
    assert.equal(this, f.page)
    assert.equal(options.message, '将作用于已选择的 3 道错题')
    assert.deepEqual(plain(options.items), ['移出错题本', '永久删除'])
    assert.deepEqual(plain(options.dangerIndexes), [1])
    return pending.promise
  }
  const work = f.page.openBatchMore()
  f.page.onBatchAction = function (e) {
    assert.equal(this, f.page); f.calls.push(['action', e.currentTarget.dataset.action])
    return new Promise(() => {})
  }
  pending.resolve(1); await work
  assert.deepEqual(f.calls.at(-1), ['action', 'delete'])
  f.page._showAppOptions = async () => -1
  f.calls.length = 0; await f.page.openBatchMore(); assert.equal(f.calls.length, 0)
  f.page._showAppOptions = async () => 0
  await f.page.openBatchMore(); assert.deepEqual(f.calls.at(-1), ['action', 'remove_from_book'])
})

test('batch IDs use exact numeric string equivalence while labels and confirmation messages stay stable', () => {
  const f = fixture()
  f.page.data.selectedIds = ['1', '01', '1.0', '1e2', '', '0', '-2', 'NaN', 'Infinity', 5, null]
  assert.deepEqual(plain(f.page._resolveBatchIds()), [1, '01', '1.0', '1e2', '', 0, -2, 'NaN', 'Infinity', 5, null])
  assert.deepEqual(plain(f.page._batchActionLabels()), {
    add_to_review: '加入今日复习', mark_mastered: '标记为已掌握',
    remove_from_book: '移出错题本', delete: '永久删除',
  })
  for (const action of ['delete', 'remove_from_book', 'mark_mastered', 'other']) {
    assert.equal(f.page._isDangerousBatchAction(action), ['delete', 'remove_from_book'].includes(action))
  }
  assert.equal(f.page._batchConfirmMessage('delete', 2), '将永久删除已选择的 2 道错题记录，是否继续？')
  assert.equal(f.page._batchConfirmMessage('other', 2), '将把已选择的 2 道题移出错题本，是否继续？')
})

test('batch action guards precede dataset access and closing menu precedes empty-selection toast', async () => {
  for (const flag of ['batchSubmitting', '_batchMasterUndoInFlight']) {
    const f = fixture()
    if (flag === 'batchSubmitting') f.page.data[flag] = true
    else f.page[flag] = true
    await f.page.onBatchAction(null); assert.equal(f.calls.length, 0)
  }
  const f = fixture()
  f.page.data.batchMoreVisible = true
  await f.page.onBatchAction(event('delete'))
  assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'toast'])
  assert.equal(f.page.data.batchSubmitting, false)
})

test('danger confirmation captures IDs and labels before await, preserves current API receiver and late success handler', async () => {
  const f = fixture(), confirmation = deferred(), request = deferred(), reload = deferred()
  f.page.data.selectedIds = ['01', '2']
  f.page._confirmBatchAction = function (title, message) {
    assert.equal(this, f.page); assert.equal(title, '永久删除'); assert.ok(message.includes('2 道'))
    return confirmation.promise
  }
  const work = f.page.onBatchAction(event('delete'))
  f.page.data.selectedIds = ['later']
  f.api.post = function (...args) { assert.equal(this, f.api); f.calls.push(['post', ...args]); return request.promise }
  confirmation.resolve(true); await flush()
  assert.deepEqual(plain(f.calls.find(c => c[0] === 'post')), ['post', '/wrong-questions/batch', { action: 'delete', ids: ['01', 2] }])
  assert.equal(f.page.data.batchSubmitting, true)
  f.page._handleBatchSuccess = function (result, labels, action) {
    assert.equal(this, f.page); assert.equal(result.updated_count, 2)
    assert.equal(labels.delete, '永久删除'); assert.equal(action, 'delete'); f.calls.push(['success'])
  }
  f.page._reloadAfterBatch = function () { assert.equal(this, f.page); f.calls.push(['reload']); return reload.promise }
  request.resolve({ updated_count: 2 }); await flush()
  assert.deepEqual(f.calls.slice(-3).map(c => c[0]), ['hideLoading', 'success', 'reload'])
  let done = false; work.then(() => { done = true }); await flush(); assert.equal(done, false)
  reload.resolve(); await work
})

test('cancelled confirmation does not submit and confirmation errors propagate outside request catch', async () => {
  const f = fixture(), error = Error('confirmation')
  f.page.data.selectedIds = ['1']
  f.page._confirmBatchAction = async () => false
  await f.page.onBatchAction(event('delete')); assert.equal(f.calls.length, 0)
  f.page._confirmBatchAction = async () => { throw error }
  f.page._handleBatchError = () => assert.fail('unexpected handler')
  await assert.rejects(f.page.onBatchAction(event('delete')), value => value === error)
  assert.equal(f.page.data.batchSubmitting, false)
})

test('request completion hides loading before destroyed check and dispatches mark-mastered without success reload', async () => {
  for (const destroyed of [false, true]) {
    const f = fixture(), request = deferred(), mastered = deferred()
    f.page.data.selectedIds = ['1']; f.api.post = () => request.promise
    f.page._handleBatchSuccess = () => assert.fail('unexpected success')
    f.page._reloadAfterBatch = () => assert.fail('unexpected reload')
    const work = f.page.onBatchAction(event('mark_mastered'))
    f.page._handleBatchMastered = function (result, ids) {
      assert.equal(this, f.page); assert.deepEqual(plain(ids), [1])
      f.calls.push(['mastered']); return mastered.promise
    }
    f.page._destroyed = destroyed; request.resolve({ updated_count: 1 }); await flush()
    assert.ok(f.calls.some(c => c[0] === 'hideLoading'))
    assert.equal(f.calls.some(c => c[0] === 'mastered'), !destroyed)
    mastered.resolve(); await work
  }
})

test('request catch includes API, success handler and reload failures but loading failure stays outside try', async () => {
  for (const stage of ['post', 'success', 'reload', 'loading']) {
    const f = fixture(), error = Error(stage)
    f.page.data.selectedIds = ['1']
    f.api.post = () => stage === 'post' ? Promise.reject(error) : Promise.resolve({ updated_count: 1 })
    f.page._handleBatchSuccess = () => { if (stage === 'success') throw error }
    f.page._reloadAfterBatch = async () => { if (stage === 'reload') throw error }
    f.page._handleBatchError = function (value) { assert.equal(this, f.page); assert.equal(value, error); f.calls.push(['handled']) }
    if (stage === 'loading') {
      f.context.wx.showLoading = () => { throw error }
      await assert.rejects(f.page.onBatchAction(event('add_to_review')), value => value === error)
      assert.equal(f.calls.some(c => c[0] === 'handled'), false)
      assert.equal(f.page.data.batchSubmitting, true)
    } else {
      await f.page.onBatchAction(event('add_to_review'))
      assert.deepEqual(f.calls.at(-1), ['handled'])
    }
  }
})

test('mastered result preserves skipped-ID precedence and unknown partial-count undo restrictions', async () => {
  const cases = [
    [{ skipped_ids: ['2'], updated_count: 0 }, [1, 3], null],
    [{ updated_count: 2 }, [], '已标记掌握 2 项'],
    [{ updated_count: 'bad' }, [], '所选题目状态未变化'],
    [{ updated_count: -1 }, [], '所选题目状态未变化'],
    [{}, [1, 2, 3], null],
  ]
  for (const [result, undo, toast] of cases) {
    const f = fixture(), ids = [1, 2, 3]
    f.page._clearBatchMasterUndo = function () { assert.equal(this, f.page); f.calls.push(['clearUndo']) }
    f.page._reloadAfterBatch = async function () { assert.equal(this, f.page); f.calls.push(['reload']) }
    await f.page._handleBatchMastered(result, ids)
    assert.deepEqual(plain(f.page._batchMasterUndoIds), undo); assert.notEqual(f.page._batchMasterUndoIds, ids)
    assert.equal(f.page.data.batchMasterUndoVisible, undo.length > 0)
    assert.equal(f.page.data._batchMasterUndoCount, undo.length)
    assert.equal(f.calls[0][0], 'clearUndo'); assert.equal(f.calls.at(-1)[0], 'reload')
    if (toast) assert.equal(f.calls.find(c => c[0] === 'toast')[1].title, toast)
    else {
      const timer = f.page._batchMasterUndoTimer
      assert.equal(f.timers.get(timer).delay, 5000)
      f.page._clearBatchMasterUndo = () => f.calls.push(['lateClear'])
      f.fire(timer); assert.deepEqual(f.calls.at(-1), ['lateClear'])
    }
  }
})

test('batch success keeps toast before state cleanup and preserves existing free-ID failure on missing count', () => {
  const f = fixture()
  f.page._handleBatchSuccess({ updated_count: 0 }, { action: '操作' }, 'action')
  assert.equal(f.calls[0][1].title, '操作成功 0 项')
  assert.deepEqual(f.calls.map(c => c[0]), ['toast', 'clearCapsule', 'setData'])
  assert.equal(f.page.data.batchMode, false)
  f.calls.length = 0
  assert.throws(() => f.page._handleBatchSuccess({}, { action: '操作' }, 'action'),
    error => error.name === 'ReferenceError' && error.message === 'ids is not defined')
  assert.equal(f.calls.length, 0)
})

test('batch errors hide loading before destruction guard and only numeric 404/405 select missing-endpoint flow', () => {
  for (const code of [404, 405, '404', 500]) {
    const f = fixture()
    f.page.data.batchSubmitting = true
    f.page._showBatchMissingEndpoint = function () { assert.equal(this, f.page); f.calls.push(['missing']); return new Promise(() => {}) }
    assert.equal(f.page._handleBatchError({ statusCode: code, message: 'failure' }), undefined)
    assert.equal(f.calls[0][0], 'hideLoading'); assert.equal(f.page.data.batchSubmitting, false)
    assert.equal(f.calls.at(-1)[0], typeof code === 'number' && code < 500 ? 'missing' : 'toast')
  }
  const f = fixture()
  f.page._destroyed = true; f.page.data.batchSubmitting = true
  f.page._handleBatchError(null)
  assert.deepEqual(f.calls, [['hideLoading']]); assert.equal(f.page.data.batchSubmitting, true)
})

test('missing-endpoint and danger dialogs preserve receivers, promises, payloads and falsey fallback', async () => {
  const f = fixture()
  assert.equal(await f.page._confirmBatchAction('title', 'message'), false)
  await f.page._showBatchMissingEndpoint()
  assert.equal(f.calls.at(-1)[0], 'toast')
  const pending = deferred(), modal = {
    show(options) { assert.equal(this, modal); f.calls.push(['modal', options]); return pending.promise },
  }
  f.page.selectComponent = id => { assert.equal(id, '#actionConfirm'); return modal }
  assert.equal(f.page._confirmBatchAction('title', 'message'), pending.promise)
  assert.deepEqual(plain(f.calls.at(-1)[1]), {
    scenario: 'danger', eyebrow: 'IRREVERSIBLE', title: 'title', message: 'message',
    confirmText: '继续操作', cancelText: '取消',
  })
  const work = f.page._showBatchMissingEndpoint()
  assert.equal(f.calls.at(-1)[1].scenario, 'info')
  assert.equal(f.calls.at(-1)[1].hideCancel, true)
  pending.resolve(); await work
})

test('reload calls current stats/list in order, returns Promise.all values and skips destroyed pages', async () => {
  const f = fixture()
  assert.deepEqual(plain(await f.page._reloadAfterBatch()), ['stats', 'list'])
  assert.deepEqual(f.calls, [['stats'], ['list', true]])
  f.page._destroyed = true; f.calls.length = 0
  assert.deepEqual(plain(await f.page._reloadAfterBatch()), []); assert.equal(f.calls.length, 0)
  f.page._destroyed = false
  const error = Error('stats')
  f.page.loadStats = () => { throw error }
  assert.throws(() => f.page._reloadAfterBatch(), value => value === error)
  assert.equal(f.calls.length, 0)
})

test('undo clear keeps timer-first order, skip-write and destroyed behavior without changing in-flight', () => {
  for (const skip of [false, true]) for (const destroyed of [false, true]) {
    const f = fixture()
    f.page._batchMasterUndoTimer = 8; f.page._batchMasterUndoIds = [1]
    f.page._batchMasterUndoInFlight = true; f.page._destroyed = destroyed
    f.page._clearBatchMasterUndo(skip)
    assert.equal(f.calls[0][0], 'clear'); assert.equal(f.page._batchMasterUndoTimer, null)
    assert.deepEqual(plain(f.page._batchMasterUndoIds), [])
    assert.equal(f.calls.length, !skip && !destroyed ? 2 : 1)
    assert.equal(f.page._batchMasterUndoInFlight, true)
  }
})

test('undo preserves undefined return, captured ID copy, live API/platform receiver and non-awaited reload', async () => {
  const f = fixture(), request = deferred(), ids = [1, 2]
  f.page._batchMasterUndoIds = ids; f.page._batchMasterUndoTimer = 8
  f.api.post = function (path, payload) {
    assert.equal(this, f.api); assert.equal(path, '/wrong-questions/batch')
    assert.deepEqual(plain(payload), { action: 'unmark_mastered', ids: [1, 2] })
    assert.notEqual(payload.ids, ids); return request.promise
  }
  assert.equal(f.page.undoBatchMaster(), undefined)
  assert.equal(f.page._batchMasterUndoInFlight, true); assert.equal(f.page._batchMasterUndoTimer, null)
  ids.push(3)
  f.page._clearBatchMasterUndo = function () { assert.equal(this, f.page); f.calls.push(['lateClear']) }
  f.page._reloadAfterBatch = function () { assert.equal(this, f.page); f.calls.push(['lateReload']); return new Promise(() => {}) }
  const platform = {
    hideLoading() { assert.equal(this, platform); f.calls.push(['lateHide']) },
    showToast(options) { assert.equal(this, platform); f.calls.push(['lateToast', options]) },
  }
  f.context.wx = platform; request.resolve({}); await flush()
  assert.equal(f.page._batchMasterUndoInFlight, false)
  assert.deepEqual(f.calls.slice(-4).map(c => c[0]), ['lateHide', 'lateClear', 'lateToast', 'lateReload'])
  assert.equal(f.calls.at(-2)[1].title, '已撤销掌握 2 项')
})

test('undo failure resets in-flight, keeps retry IDs and schedules current clear hook for 5000ms', async () => {
  const f = fixture(), request = deferred()
  f.page._batchMasterUndoIds = [1]; f.api.post = () => request.promise
  f.page.undoBatchMaster(); request.reject({ message: 'retry' }); await flush()
  assert.equal(f.page._batchMasterUndoInFlight, false)
  assert.deepEqual(f.page._batchMasterUndoIds, [1])
  assert.equal(f.calls.find(c => c[0] === 'toast')[1].title, 'retry')
  const timer = f.page._batchMasterUndoTimer
  assert.equal(f.timers.get(timer).delay, 5000)
  f.page._clearBatchMasterUndo = () => f.calls.push(['lateClear'])
  f.fire(timer); assert.deepEqual(f.calls.at(-1), ['lateClear'])
})

test('undo skips work when empty/in-flight and destroyed responses still hide loading and reset in-flight', async () => {
  const f = fixture()
  f.page.undoBatchMaster(); assert.equal(f.calls.length, 0)
  f.page._batchMasterUndoIds = [1]; f.page._batchMasterUndoInFlight = true
  f.page.undoBatchMaster(); assert.equal(f.calls.length, 0)
  for (const rejects of [false, true]) {
    const f = fixture(), request = deferred()
    f.page._batchMasterUndoIds = [1]; f.api.post = () => request.promise
    f.page.undoBatchMaster(); f.page._destroyed = true
    if (rejects) request.reject(Error('failure')); else request.resolve({})
    await flush()
    assert.equal(f.page._batchMasterUndoInFlight, false)
    assert.equal(f.calls.at(-1)[0], 'hideLoading')
    assert.equal(f.calls.some(c => c[0] === 'toast'), false); assert.equal(f.timers.size, 0)
  }
})

test('undo pre-request errors retain original partial in-flight state and success-handler errors enter retry catch', async () => {
  const f = fixture(), error = Error('clear')
  f.page._batchMasterUndoIds = [1]; f.page._batchMasterUndoTimer = 8
  f.context.clearTimeout = () => { throw error }
  assert.throws(() => f.page.undoBatchMaster(), value => value === error)
  assert.equal(f.page._batchMasterUndoInFlight, true); assert.equal(f.page._batchMasterUndoTimer, 8)
  const next = fixture()
  next.page._batchMasterUndoIds = [2]
  next.page._clearBatchMasterUndo = () => { throw Error('application') }
  next.page.undoBatchMaster(); await flush()
  assert.equal(next.calls.find(c => c[0] === 'toast')[1].title, 'application')
  assert.equal(next.timers.size, 1)
})
