const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPomodoroActiveSessionReconciler,
} = require('../pages/pomodoro/utils/active-session-reconciler')

function createHarness(overrides = {}) {
  const state = {
    storage: new Map(),
    removed: [],
    server: { id: 7, subject_id: 2 },
    cached: null,
    throws: false,
    pendingActions: new Set(),
    clearFails: false,
    removeFails: false,
  }
  state.storage.set('pomodoro_running_state', { ok: true, value: state.cached })

  const controller = createPomodoroActiveSessionReconciler({
    safeGetPomodoroStorage: (key, context) => {
      state.getContexts = state.getContexts || []
      state.getContexts.push({ key, context })
      return state.storage.get(key) || { ok: true, value: null }
    },
    buildCachedActiveSession: local => {
      state.builtFrom = local
      return state.cached
    },
    getActive: async path => {
      state.getActivePath = path
      if (state.throws) throw new Error('network unavailable')
      return state.server
    },
    safeRemovePomodoroStorage: (key, context) => {
      state.removed.push({ key, context })
      return !state.removeFails
    },
    hasPendingPomodoroAction: (sessionId, actions) => {
      state.pendingChecks = state.pendingChecks || []
      state.pendingChecks.push({ sessionId, actions })
      return state.pendingActions.has(sessionId)
    },
    clearLocalPauseAdjustment: sessionId => {
      state.clearedSessionId = sessionId
      return !state.clearFails
    },
    ...overrides,
  })
  return { controller, state }
}

test('server active session clears running state, pending pause adjustment, and returns server', async () => {
  const { controller, state } = createHarness()
  state.cached = { id: 5 }
  state.storage.set('pomodoro_running_state', { ok: true, value: { id: 5 } })

  const result = await controller.fetchActive()

  assert.equal(result, state.server)
  assert.equal(state.getActivePath, '/pomodoro/active')
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'server active reconcile' },
  ])
  assert.deepEqual(state.pendingChecks, [{ sessionId: 7, actions: ['pause', 'resume'] }])
  assert.equal(state.clearedSessionId, 7)
})

test('server active with pending pause keeps local pause adjustment', async () => {
  const { controller, state } = createHarness()
  state.pendingActions.add(7)

  const result = await controller.fetchActive()

  assert.equal(result, state.server)
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'server active reconcile' },
  ])
  assert.equal(state.clearedSessionId, undefined)
})

test('server no-active removes running state and returns null', async () => {
  const { controller, state } = createHarness()
  state.server = null

  const result = await controller.fetchActive()

  assert.equal(result, null)
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'server no-active reconcile' },
  ])
})

test('network failure returns cached snapshot when available', async () => {
  const { controller, state } = createHarness()
  state.cached = { id: 5, subject_id: 2 }
  state.storage.set('pomodoro_running_state', { ok: true, value: { id: 5 } })
  state.throws = true

  const result = await controller.fetchActive()

  assert.equal(result, state.cached)
  assert.deepEqual(state.removed, [])
})

test('network failure with no cached snapshot removes invalid running state', async () => {
  const { controller, state } = createHarness()
  state.throws = true
  state.cached = null

  const result = await controller.fetchActive()

  assert.equal(result, null)
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'invalid cached active session' },
  ])
})

test('storage read failure returns storageUnreadable without network call', async () => {
  let called = false
  const { controller, state } = createHarness({
    safeGetPomodoroStorage: () => ({ ok: false, value: null }),
    getActive: async () => { called = true },
  })

  const result = await controller.fetchActive()

  assert.deepEqual(result, { storageUnreadable: true })
  assert.equal(called, false)
  assert.deepEqual(state.removed, [])
})

test('remove failure during server-active reconcile returns storageUnreadable', async () => {
  const { controller, state } = createHarness()
  state.removeFails = true

  const result = await controller.fetchActive()

  assert.deepEqual(result, { storageUnreadable: true })
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'server active reconcile' },
  ])
})

test('clearLocalPauseAdjustment failure returns storageUnreadable', async () => {
  const { controller, state } = createHarness()
  state.clearFails = true

  const result = await controller.fetchActive()

  assert.deepEqual(result, { storageUnreadable: true })
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'server active reconcile' },
  ])
})

test('remove failure during no-active reconcile returns storageUnreadable', async () => {
  const { controller, state } = createHarness()
  state.server = null
  state.removeFails = true

  const result = await controller.fetchActive()

  assert.deepEqual(result, { storageUnreadable: true })
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'server no-active reconcile' },
  ])
})

test('remove failure during invalid-cached cleanup returns storageUnreadable', async () => {
  const { controller, state } = createHarness()
  state.throws = true
  state.cached = null
  state.removeFails = true

  const result = await controller.fetchActive()

  assert.deepEqual(result, { storageUnreadable: true })
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'invalid cached active session' },
  ])
})
