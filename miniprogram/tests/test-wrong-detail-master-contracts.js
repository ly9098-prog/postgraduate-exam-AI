const assert = require('node:assert/strict')
const { test } = require('node:test')
const { fixture, deferred } = require('./helpers/wrong-detail-ai-recovery-fixture')
const plain = value => JSON.parse(JSON.stringify(value))

function setup() {
  const f = fixture(), timers = new Map()
  let next = 30
  f.context.setTimeout = (fn, ms) => {
    const id = ++next
    timers.set(id, { fn, ms })
    f.calls.push(['timer', id, ms])
    return id
  }
  f.context.clearTimeout = id => { f.calls.push(['clear', id]); timers.delete(id) }
  f.context.console = { error: (...args) => f.calls.push(['error', ...args]) }
  f.api.post = function (...args) {
    assert.equal(this, f.api)
    f.calls.push(['post', ...args])
    return Promise.resolve({ updated_count: 1 })
  }
  f.page.data.questionIds = [12, 13, 14]
  f.page._wqCache = { 12: { data: f.page.data.wq, ts: 1000, status: 'ready' } }
  f.page._navigateTo = function (...args) { assert.equal(this, f.page); f.calls.push(['navigate', ...args]) }
  f.page.loadData = function (...args) { assert.equal(this, f.page); f.calls.push(['load', ...args]) }
  return {
    ...f, timers,
    fire(id) { const value = timers.get(id); assert.ok(value); timers.delete(id); value.fn() },
  }
}

test('master confirmation dialogs retain busy/mastered guards and dynamic action dispatch', () => {
  const f = setup(), page = f.page
  page.data.masterSubmitting = true
  for (const name of ['openMasterConfirm', 'closeMasterConfirm', 'openUnmasterConfirm', 'closeUnmasterConfirm']) {
    assert.equal(page[name](), undefined)
  }
  assert.deepEqual(f.calls, [])
  page.data.masterSubmitting = false; page.data.isCurrentMastered = true
  page.openMasterConfirm(); page.openUnmasterConfirm(); page.closeUnmasterConfirm()
  page.data.isCurrentMastered = false
  page.openUnmasterConfirm(); page.openMasterConfirm(); page.closeMasterConfirm()
  assert.deepEqual(plain(f.calls), [
    ['setData', { unmasterConfirmVisible: true }], ['setData', { unmasterConfirmVisible: false }],
    ['setData', { masterConfirmVisible: true }], ['setData', { masterConfirmVisible: false }],
  ])
  page.openMasterConfirm = function () { assert.equal(this, page); f.calls.push(['master']) }
  page.openUnmasterConfirm = function () { assert.equal(this, page); f.calls.push(['unmaster']) }
  page.onMasterAction(); page.data.isCurrentMastered = true; page.onMasterAction()
  assert.deepEqual(f.calls.slice(-2), [['master'], ['unmaster']])
})

test('mark captures private id and updates busy state before request, then awaits the current handler', async () => {
  const f = setup(), page = f.page, request = deferred(), handler = deferred()
  page._currentWqId = '44'
  f.api.post = function (...args) {
    assert.equal(this, f.api)
    f.calls.push(['post', ...args])
    return request.promise
  }
  let done = false
  const work = page.confirmMastered().then(() => { done = true })
  assert.deepEqual(plain(f.calls), [
    ['setData', { masterSubmitting: true, masterConfirmVisible: false }],
    ['post', '/wrong-questions/batch', { action: 'mark_mastered', ids: ['44'] }],
  ])
  const result = { updated_count: 1 }
  page._currentWqId = 45
  page._handleMasterResult = function (value, id) {
    assert.equal(this, page); assert.equal(value, result); assert.equal(id, '44')
    f.calls.push(['lateHandler']); return handler.promise
  }
  request.resolve(result)
  await Promise.resolve(); await Promise.resolve()
  assert.equal(done, false)
  handler.resolve(); await work
  assert.equal(done, true)
})

test('mark/unmark ignore missing ids and busy submissions; late dead responses leave busy state', async () => {
  for (const method of ['confirmMastered', 'confirmUnmastered']) {
    const f = setup(), page = f.page
    page.data.wq = null
    await page[method](); assert.deepEqual(f.calls, [])
    page.data.wq = { id: 12 }; page.data.masterSubmitting = true
    await page[method](); assert.deepEqual(f.calls, [])
    page.data.masterSubmitting = false
    const request = deferred()
    f.api.post = () => request.promise
    const work = page[method]()
    page._alive = false; request.resolve({ updated_count: 1 }); await work
    assert.equal(page.data.masterSubmitting, true)
    assert.equal(f.calls.length, 1)
  }
})

test('mark skipped and nonpositive updates sync from server; other count shapes remain changes', async () => {
  for (const [result, changed] of [
    [{ skipped_ids: ['12'], updated_count: 1 }, false],
    [{ skipped_ids: [13], updated_count: 0 }, false],
    [{ updated_count: -1 }, false], [{ updated_count: '' }, false],
    [{ updated_count: null }, true], [{ updated_count: 'bad' }, true],
    [{}, true], [null, true],
  ]) {
    const f = setup(), page = f.page, wait = deferred()
    page._clearMasterUndo = () => f.calls.push(['clearUndo'])
    page._applyMasterChanged = id => f.calls.push(['changed', id])
    page.loadData = id => { f.calls.push(['load', id]); return wait.promise }
    const work = page._handleMasterResult(result, 12)
    if (!changed) {
      assert.deepEqual(plain(f.calls), [['clearUndo'], ['setData', { masterSubmitting: false }], ['load', 12]])
      page._alive = false
    }
    wait.resolve(); await work
    assert.deepEqual(plain(f.calls), changed ? [['changed', 12]] :
      [['clearUndo'], ['setData', { masterSubmitting: false }], ['load', 12]])
  }
  const f = setup()
  await f.page._handleMasterResult({ updated_count: 0 }, 12)
  assert.equal(f.calls.at(-1)[1].title, '题目状态已同步')
})

test('changed mark preserves cache metadata, distinct view copy, undo snapshot and live advance index', () => {
  const f = setup(), page = f.page, entry = page._wqCache[12], old = entry.data
  page._applyMasterChanged(12)
  assert.equal(page._wqCache[12], entry)
  assert.equal(entry.ts, 1000); assert.equal(entry.status, 'ready')
  assert.notEqual(entry.data, old); assert.equal(old.is_mastered, undefined)
  assert.notEqual(page.data.wq, entry.data)
  assert.deepEqual(plain(page._pendingMasterUndo), { wqId: 12, originalIdx: 0 })
  assert.equal(page.data.isCurrentMastered, true)
  assert.equal(page.data.masterUndoVisible, true)
  assert.equal(f.timers.get(page._masterUndoTimer).ms, 5000)
  assert.equal(f.timers.get(page._masterAdvanceTimer).ms, 120)
  page.data.currentIdx = 1
  page._alive = false
  f.fire(page._masterAdvanceTimer)
  assert.equal(page._masterAdvanceTimer, null)
  assert.deepEqual(f.calls.at(-1), ['navigate', 2, 150])
})

test('changed mark with a different displayed question preserves it and skips advance at the end', () => {
  const f = setup(), page = f.page, question = { id: 99 }
  page.data.currentIdx = 2; page.data.wq = question
  page._applyMasterChanged(12)
  assert.equal(page.data.wq, question)
  assert.equal(page.data.isCurrentMastered, false)
  assert.equal(page.data.masterUndoVisible, true)
  assert.equal(page._masterAdvanceTimer, undefined)
  assert.deepEqual(plain(page._pendingMasterUndo), { wqId: 12, originalIdx: 2 })
})

test('mark errors reset only busy with no toast; unmark errors also show retry toast', async () => {
  for (const method of ['confirmMastered', 'confirmUnmastered']) {
    const f = setup(), error = new Error('request')
    f.api.post = () => { throw error }
    await f.page[method]()
    assert.equal(f.page.data.masterSubmitting, false)
    assert.equal(f.calls[1][0], 'error')
    assert.equal(f.calls[1][2], error)
    const toasts = f.calls.filter(c => c[0] === 'toast')
    assert.equal(toasts.length, method === 'confirmMastered' ? 0 : 1)
  }
})

test('unmark preserves skipped synchronization and success cache/view/clear/toast order', async () => {
  for (const result of [{ skipped_ids: ['12'] }, { updated_count: 0 }]) {
    const f = setup()
    f.api.post = async () => result
    f.page._clearMasterUndo = () => f.calls.push(['clearUndo'])
    await f.page.confirmUnmastered()
    assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'clearUndo', 'setData', 'load', 'toast'])
    assert.equal(f.calls.at(-1)[1].title, '题目状态已同步')
  }
  const f = setup(), entry = f.page._wqCache[12], old = entry.data
  f.page._clearMasterUndo = () => f.calls.push(['clearUndo'])
  await f.page.confirmUnmastered()
  assert.deepEqual(plain(f.calls[1]), ['post', '/wrong-questions/batch', {
    action: 'unmark_mastered', ids: [12],
  }])
  assert.equal(f.page._wqCache[12], entry); assert.notEqual(entry.data, old)
  assert.equal(entry.data.is_mastered, false)
  assert.equal(f.page.data.wq.is_mastered, false)
  assert.notEqual(f.page.data.wq, entry.data)
  assert.deepEqual(f.calls.map(c => c[0]), ['setData', 'post', 'clearUndo', 'setData', 'toast'])
})

test('undo ignores missing/inflight snapshots, clears timers before request, and finally unlocks', async () => {
  const f = setup(), page = f.page, request = deferred(), pending = { wqId: 12, originalIdx: 0 }
  await page.undoMastered(); assert.deepEqual(f.calls, [])
  page._pendingMasterUndo = pending; page._masterUndoInFlight = true
  await page.undoMastered(); assert.deepEqual(f.calls, [])
  page._masterUndoInFlight = false; page._masterUndoTimer = 2; page._masterAdvanceTimer = 3
  page._performUndoMastered = function (value) {
    assert.equal(this, page); assert.equal(value, pending); assert.equal(page._masterUndoInFlight, true)
    f.calls.push(['perform']); return request.promise
  }
  const work = page.undoMastered()
  assert.deepEqual(f.calls, [['clear', 2], ['clear', 3], ['perform']])
  request.resolve(); await work
  assert.equal(page._masterUndoInFlight, false)
  assert.equal(page._masterUndoTimer, null); assert.equal(page._masterAdvanceTimer, null)
  assert.equal(f.calls.at(-1)[1].title, '已撤销掌握')
})

test('undo timer-clear failure precedes try/finally and retains the original inflight flag', async () => {
  const f = setup(), error = new Error('clear')
  f.page._pendingMasterUndo = { wqId: 12 }
  f.page._clearMasterUndoTimers = () => { throw error }
  await assert.rejects(f.page.undoMastered(), value => value === error)
  assert.equal(f.page._masterUndoInFlight, true)
})

test('undo request keeps API receiver and rereads the commit hook after await', async () => {
  const f = setup(), pending = { wqId: 12 }, request = deferred()
  f.api.post = function (...args) { assert.equal(this, f.api); f.calls.push(['post', ...args]); return request.promise }
  const work = f.page._performUndoMastered(pending)
  f.page._commitUndoMastered = function (value) {
    assert.equal(this, f.page); assert.equal(value, pending); f.calls.push(['lateCommit'])
  }
  request.resolve({ updated_count: 0, skipped_ids: [12] })
  await work
  assert.deepEqual(plain(f.calls), [
    ['post', '/wrong-questions/batch', { action: 'unmark_mastered', ids: [12] }], ['lateCommit'],
  ])
})

test('undo 404/410 baseline still commits after handled missing response and emits success toast', async () => {
  for (const status of [404, 410]) {
    const f = setup(), pending = { wqId: 12 }, error = { statusCode: status }
    f.page._pendingMasterUndo = pending
    f.api.post = async () => { throw error }
    f.page._clearMasterUndo = () => { f.calls.push(['clearUndo']); f.page._pendingMasterUndo = null }
    f.page._dropQuestionFromNavigation = function (id) {
      assert.equal(this, f.page); f.calls.push(['drop', id])
    }
    f.page._commitUndoMastered = value => { assert.equal(value, pending); f.calls.push(['commit']) }
    await f.page.undoMastered()
    assert.deepEqual(f.calls.map(c => c[0]), ['clearUndo', 'drop', 'toast', 'commit', 'toast'])
    assert.equal(f.calls[2][1].title, '该错题已被移除，无法撤销')
    assert.equal(f.calls[4][1].title, '已撤销掌握')
    assert.equal(f.page._masterUndoInFlight, false)
  }
})

test('other undo errors preserve identity, rearm only matching pending and release inflight even if handler throws', async () => {
  for (const same of [true, false]) {
    const f = setup(), error = { status: 500 }, pending = { wqId: 12 }
    f.page._pendingMasterUndo = pending
    f.page._performUndoMastered = async () => {
      if (!same) f.page._pendingMasterUndo = { wqId: 12 }
      throw error
    }
    await f.page.undoMastered()
    assert.equal(f.page._masterUndoInFlight, false)
    assert.equal(f.timers.size, same ? 1 : 0)
    assert.equal(f.page.data.masterUndoVisible, same)
    assert.equal(f.calls.at(-1)[1].title, '撤销失败，请重试')
    await assert.rejects(f.page._handleUndoRequestError(error, pending), value => value === error)
  }
  const f = setup(), error = new Error('handler')
  f.page._pendingMasterUndo = { wqId: 12 }
  f.page._performUndoMastered = async () => { throw new Error('request') }
  f.page._handleUndoMasterError = () => { throw error }
  await assert.rejects(f.page.undoMastered(), value => value === error)
  assert.equal(f.page._masterUndoInFlight, false)
})

test('undo commit chooses navigate, current view, reload or no-op from current state and preserves cache metadata', () => {
  for (const [ids, idx, displayed, expected] of [
    [[1, '12'], 0, 12, 'navigate'], [[12], 0, '12', 'setData'],
    [[12], 0, 99, 'load'], [[1], 0, 99, null],
  ]) {
    const f = setup(), page = f.page, entry = page._wqCache[12]
    page.data.questionIds = ids; page.data.currentIdx = idx; page.data.wq = { id: displayed }
    page._clearMasterUndo = () => f.calls.push(['clearUndo'])
    page._commitUndoMastered({ wqId: 12, originalIdx: 999 })
    assert.equal(page._wqCache[12], entry); assert.equal(entry.ts, 1000)
    assert.equal(entry.data.is_mastered, false)
    assert.deepEqual(f.calls.map(c => c[0]), expected ? ['clearUndo', expected] : ['clearUndo'])
    if (expected === 'navigate') assert.deepEqual(f.calls[1], ['navigate', 1, 150])
    if (expected === 'load') assert.deepEqual(f.calls[1], ['load', 12])
  }
})

test('undo expiry and clear preserve truthy timer guards, fallback duration and dead-page rules', () => {
  for (const [duration, expected] of [[undefined, 5000], [0, 5000], [-1, 5000], ['23', 23]]) {
    const f = setup(), page = f.page
    page._masterUndoTimer = 9; page._pendingMasterUndo = { wqId: 12 }
    page.data.masterUndoVisible = true
    page._armMasterUndoExpiry(duration)
    assert.deepEqual(f.calls[0], ['clear', 9])
    assert.equal(f.timers.get(page._masterUndoTimer).ms, expected)
    page._alive = false; f.fire(page._masterUndoTimer)
    assert.equal(page._pendingMasterUndo, null); assert.equal(page._masterUndoTimer, null)
    assert.equal(page.data.masterUndoVisible, true)
  }
  const f = setup(), page = f.page
  page._masterUndoTimer = 3; page._masterAdvanceTimer = 4
  page._pendingMasterUndo = {}; page.data.masterUndoVisible = true
  page._clearMasterUndo()
  assert.deepEqual(plain(f.calls), [['clear', 3], ['clear', 4], ['setData', { masterUndoVisible: false }]])
  assert.equal(page._pendingMasterUndo, null)
})
