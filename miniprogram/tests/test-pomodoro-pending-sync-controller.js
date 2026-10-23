const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPendingSyncController,
} = require('../pages/pomodoro/utils/pending-sync-controller')
const {
  canReconcilePendingSync,
  decidePendingSyncReconciliation,
} = require('../pages/pomodoro/utils/sync-reconciliation')

function pendingAction(action, sessionId, overrides = {}) {
  return {
    action,
    sessionId,
    savedAt: 1000,
    clientActionAt: 2000,
    nonce: `${action}-${sessionId}`,
    ...overrides,
  }
}

function createHarness(overrides = {}) {
  const calls = {
    posts: [],
    clearPending: [],
    updatePending: [],
    enqueued: [],
    clearRetryTimer: [],
    scheduledRetry: [],
    persistenceErrors: 0,
    loggedErrors: [],
    maybeCleared: [],
    dropped: [],
    restored: [],
    storageReads: [],
    storageRemoves: [],
    breakSec: [],
    setData: [],
  }
  const state = {
    queue: overrides.queue === undefined ? [] : overrides.queue,
    queueReadable: overrides.queueReadable !== false,
    conflict: Object.hasOwn(overrides, 'conflict') ? overrides.conflict : null,
    storage: new Map(Object.entries(overrides.storage || {})),
  }
  const options = {
    getQueue() {
      return state.queueReadable ? state.queue : null
    },
    clearPending(expected) {
      calls.clearPending.push(expected)
      if (overrides.clearPendingResult === false) return false
      state.queue = state.queue.filter(item => item.nonce !== expected.nonce)
      return true
    },
    updatePending(expected, patch) {
      calls.updatePending.push([expected, patch])
      if (overrides.updatePendingResult === false) return null
      state.queue = state.queue.map(item => (
        item.nonce === expected.nonce ? { ...item, ...patch } : item
      ))
      return state.queue.find(item => item.nonce === expected.nonce) || null
    },
    enqueue(action, sessionId, clientActionAt) {
      calls.enqueued.push([action, sessionId, clientActionAt])
      if (overrides.enqueueResult === false) return null
      const pending = pendingAction(action, sessionId, { clientActionAt })
      state.queue.push(pending)
      return pending
    },
    hasPending(sessionId, action) {
      return state.queue.some(item => (
        item.sessionId === sessionId && item.action === action
      ))
    },
    canReconcile: canReconcilePendingSync,
    decideReconciliation: decidePendingSyncReconciliation,
    formatClientActionAt(timestamp) {
      try {
        return new Date(timestamp).toISOString()
      } catch (_) {
        return null
      }
    },
    post(path, body) {
      calls.posts.push([path, body])
      if (overrides.post) return overrides.post(path, body, calls)
      return Promise.resolve({ status: 'ok' })
    },
    getActive() {
      if (overrides.getActiveError) return Promise.reject(overrides.getActiveError)
      return Promise.resolve(overrides.active === undefined ? null : overrides.active)
    },
    now: () => overrides.now || 3000,
    isVisible: () => overrides.pageVisible !== false,
    restoreSession(active) {
      calls.restored.push(active)
      return overrides.restoreResult === undefined ? true : overrides.restoreResult
    },
    maybeClearAdjustment(sessionId) {
      calls.maybeCleared.push(sessionId)
    },
    dropSessionActions(sessionId) {
      calls.dropped.push(sessionId)
      if (overrides.dropResult === false) return false
      state.queue = state.queue.filter(item => item.sessionId !== sessionId)
      return true
    },
    getStorage(key, context) {
      calls.storageReads.push([key, context])
      if (overrides.storageReadFailure) return { ok: false, value: null }
      return { ok: true, value: state.storage.get(key) }
    },
    removeStorage(key, context) {
      calls.storageRemoves.push([key, context])
      if (overrides.removeFailure && overrides.removeFailure(key, context)) return false
      state.storage.delete(key)
      return true
    },
    setCompletionBreakSec(value) {
      calls.breakSec.push(value)
    },
    setData(data) {
      calls.setData.push(data)
    },
    recordTerminalConflict(sessionId, action, status) {
      if (overrides.recordConflictResult === false) return false
      state.conflict = { sessionId, requestedAction: action, serverStatus: status }
      return true
    },
    readConflict() {
      return state.conflict
    },
    isStorageConflict(value) {
      return !!(value && value.storageUnreadable)
    },
    clearRetryTimer(reset) {
      calls.clearRetryTimer.push(reset)
    },
    scheduleRetry(error) {
      calls.scheduledRetry.push(error)
    },
    persistenceError() {
      calls.persistenceErrors += 1
    },
    logError(...args) {
      calls.loggedErrors.push(args)
    },
  }
  return {
    controller: createPendingSyncController(options),
    calls,
    state,
  }
}

test('drain acknowledges an already-empty queue and resets retry backoff', async () => {
  const harness = createHarness()

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.clearRetryTimer, [true])
  assert.equal(harness.calls.posts.length, 0)
})

test('drain fails closed when the durable queue cannot be read', async () => {
  const harness = createHarness({ queueReadable: false })

  assert.equal(await harness.controller.drain(), false)
  assert.equal(harness.calls.persistenceErrors, 1)
  assert.deepEqual(harness.calls.clearRetryTimer, [])
  assert.equal(harness.calls.posts.length, 0)
})

test('drain posts queued actions strictly from the head with client timestamps', async () => {
  const harness = createHarness({
    queue: [
      pendingAction('pause', 7, { clientActionAt: 2000 }),
      pendingAction('resume', 7, { clientActionAt: 3000 }),
    ],
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.posts, [
    ['/pomodoro/7/pause', { client_action_at: '1970-01-01T00:00:02.000Z' }],
    ['/pomodoro/7/resume', { client_action_at: '1970-01-01T00:00:03.000Z' }],
  ])
  assert.deepEqual(harness.calls.clearPending.map(item => item.action), ['pause', 'resume'])
  assert.deepEqual(harness.calls.maybeCleared, [7, 7])
  assert.deepEqual(harness.calls.clearRetryTimer, [true, true, true])
  assert.equal(harness.state.queue.length, 0)
})

test('drain omits malformed client timestamps without blocking replay', async () => {
  const harness = createHarness({
    queue: [pendingAction('pause', 8, { clientActionAt: 'not-a-time' })],
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.posts[0], ['/pomodoro/8/pause', {}])
})

test('a committed action is not acknowledged when local queue removal fails', async () => {
  const harness = createHarness({
    queue: [pendingAction('pause', 9)],
    clearPendingResult: false,
  })

  assert.equal(await harness.controller.drain(), false)
  assert.equal(harness.calls.loggedErrors.length, 1)
  assert.equal(harness.calls.persistenceErrors, 1)
  assert.equal(harness.calls.posts.length, 1)
  assert.equal(harness.state.queue.length, 1)
})

test('terminal status mismatch records a conflict before dropping session actions', async () => {
  const harness = createHarness({
    queue: [pendingAction('complete', 10)],
    post: async () => ({ status: 'interrupted' }),
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.state.conflict, {
    sessionId: 10,
    requestedAction: 'complete',
    serverStatus: 'interrupted',
  })
  assert.deepEqual(harness.calls.dropped, [10])
  assert.equal(harness.calls.clearPending.length, 0)
  assert.deepEqual(harness.calls.clearRetryTimer, [true, true])
})

test('terminal mismatch stops when the conflict or cleanup cannot persist', async () => {
  const recordFailure = createHarness({
    queue: [pendingAction('interrupt', 11)],
    post: async () => ({ status: 'completed' }),
    recordConflictResult: false,
  })
  assert.equal(await recordFailure.controller.drain(), false)
  assert.equal(recordFailure.calls.persistenceErrors, 1)
  assert.equal(recordFailure.calls.dropped.length, 0)

  const dropFailure = createHarness({
    queue: [pendingAction('interrupt', 12)],
    post: async () => ({ status: 'completed' }),
    dropResult: false,
  })
  assert.equal(await dropFailure.controller.drain(), false)
  assert.equal(dropFailure.calls.persistenceErrors, 1)
  assert.equal(dropFailure.state.queue.length, 1)
})

test('unreconciled transient failures schedule bounded retry and stop', async () => {
  const error = { statusCode: 503 }
  const harness = createHarness({
    queue: [pendingAction('pause', 13)],
    post: async () => { throw error },
  })

  assert.equal(await harness.controller.drain(), false)
  assert.deepEqual(harness.calls.scheduledRetry, [error])
  assert.equal(harness.calls.posts.length, 1)
  assert.equal(harness.state.queue.length, 1)
})

test('404/409 reconciliation acknowledges canonical pause or resume state', async () => {
  const harness = createHarness({
    queue: [pendingAction('pause', 14)],
    post: async () => { throw { statusCode: 404 } },
    active: { id: 14, status: 'paused' },
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.maybeCleared, [14])
  assert.deepEqual(harness.calls.clearRetryTimer, [true, true])
  assert.equal(harness.state.queue.length, 0)
})

test('clock-skew rejection updates the queued timestamp before replay', async () => {
  let attempts = 0
  const harness = createHarness({
    queue: [pendingAction('pause', 15)],
    active: { id: 15, status: 'running' },
    post: async () => {
      attempts += 1
      if (attempts === 1) {
        throw { statusCode: 409, code: 'POMODORO_CLOCK_SKEW' }
      }
      return { status: 'paused' }
    },
  })

  assert.equal(await harness.controller.drain(), true)
  assert.equal(harness.calls.updatePending.length, 1)
  assert.deepEqual(harness.calls.updatePending[0][1], {
    clientActionAt: 3000,
    clockSkewRetries: 1,
  })
  assert.equal(harness.calls.posts.length, 2)
})

test('stale terminal reconciliation clears completion before restoring active state', async () => {
  const harness = createHarness({
    queue: [pendingAction('complete', 16)],
    post: async () => { throw { statusCode: 409, code: 'POMODORO_STALE_ACTION' } },
    active: { id: 16, status: 'running' },
    storage: {
      pomodoro_completion: { sessionId: 16 },
      pomodoro_break: { sessionId: 16 },
      unrelated: { sessionId: 99 },
    },
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.storageReads[0], [
    'pomodoro_completion',
    'stale terminal reconcile',
  ])
  assert.equal(harness.state.storage.get('pomodoro_break'), undefined)
  assert.deepEqual(harness.calls.storageRemoves, [
    ['pomodoro_completion', 'stale terminal reconcile'],
    ['pomodoro_break', 'best-effort cleanup'],
  ])
  assert.deepEqual(harness.calls.restored, [{ id: 16, status: 'running' }])
  assert.deepEqual(harness.calls.breakSec, [null])
  assert.deepEqual(harness.calls.setData, [{
    showCelebration: false,
    showEndConfirm: false,
  }])
  assert.deepEqual(harness.calls.maybeCleared, [16])
})

test('stale terminal cleanup failures preserve the pending action', async () => {
  const readFailure = createHarness({
    queue: [pendingAction('interrupt', 17)],
    post: async () => { throw { statusCode: 409, code: 'POMODORO_NOT_READY' } },
    active: { id: 17, status: 'paused' },
    storageReadFailure: true,
  })
  assert.equal(await readFailure.controller.drain(), false)
  assert.equal(readFailure.state.queue.length, 1)
  assert.deepEqual(readFailure.calls.restored, [])

  const removeFailure = createHarness({
    queue: [pendingAction('complete', 18)],
    post: async () => { throw { statusCode: 409, code: 'POMODORO_STALE_ACTION' } },
    active: { id: 18, status: 'running' },
    storage: { pomodoro_completion: { sessionId: 18 } },
    removeFailure: key => key === 'pomodoro_completion',
  })
  assert.equal(await removeFailure.controller.drain(), false)
  assert.equal(removeFailure.state.queue.length, 1)
  assert.deepEqual(removeFailure.calls.restored, [])
})

test('stale active restore is skipped while hidden but still acknowledges the action', async () => {
  const harness = createHarness({
    queue: [pendingAction('interrupt', 19)],
    post: async () => { throw { statusCode: 409, code: 'POMODORO_NOT_READY' } },
    active: { id: 19, status: 'running' },
    pageVisible: false,
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.restored, [])
  assert.deepEqual(harness.calls.maybeCleared, [19])
  assert.equal(harness.state.queue.length, 0)
})

test('a vanished server session drops all stale local actions', async () => {
  const harness = createHarness({
    queue: [pendingAction('pause', 20)],
    post: async () => { throw { statusCode: 404 } },
    active: null,
  })

  assert.equal(await harness.controller.drain(), true)
  assert.deepEqual(harness.calls.dropped, [20])
  assert.equal(harness.state.queue.length, 0)
})

test('complete and interrupt enqueue terminal actions and use the shared drain', async () => {
  const complete = createHarness({
    post: async () => ({ status: 'completed' }),
  })
  assert.equal(await complete.controller.complete(21, 4000), true)
  assert.deepEqual(complete.calls.enqueued, [['complete', 21, 4000]])
  assert.deepEqual(complete.calls.posts[0], [
    '/pomodoro/21/complete',
    { client_action_at: '1970-01-01T00:00:04.000Z' },
  ])

  const interrupt = createHarness({
    post: async () => ({ status: 'interrupted' }),
  })
  assert.equal(await interrupt.controller.interrupt(22, 5000), true)
  assert.deepEqual(interrupt.calls.enqueued, [['interrupt', 22, 5000]])
})

test('terminal wrappers reject missing IDs, enqueue failures and storage conflicts', async () => {
  const missing = createHarness()
  assert.equal(await missing.controller.complete(null, 1000), false)
  assert.equal(missing.calls.enqueued.length, 0)

  const enqueueFailure = createHarness({ enqueueResult: false })
  assert.equal(await enqueueFailure.controller.interrupt(23, 1000), false)
  assert.equal(enqueueFailure.calls.persistenceErrors, 1)

  const storageConflict = createHarness({
    post: async () => ({ status: 'completed' }),
    conflict: { storageUnreadable: true },
  })
  assert.equal(await storageConflict.controller.complete(24, 1000), false)

  const mismatchedConflict = createHarness({
    post: async () => ({ status: 'completed' }),
    conflict: { sessionId: 24, requestedAction: 'interrupt' },
  })
  assert.equal(await mismatchedConflict.controller.complete(24, 1000), true)
})

test('concurrent drain callers share one in-flight request', async () => {
  let resolvePost
  const harness = createHarness({
    queue: [pendingAction('pause', 25)],
    post: () => new Promise(resolve => { resolvePost = resolve }),
  })

  const first = harness.controller.drain()
  const second = harness.controller.drain()
  assert.equal(first, second)
  assert.equal(harness.calls.posts.length, 1)
  resolvePost({ status: 'paused' })
  assert.equal(await first, true)
  assert.equal(harness.state.queue.length, 0)
})
