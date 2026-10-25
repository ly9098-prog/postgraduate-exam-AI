const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPomodoroPauseSyncController,
} = require('../pages/pomodoro/utils/pause-sync-controller')

function createHarness(overrides = {}) {
  const state = {
    pending: new Map(),
    synced: true,
    syncCalls: 0,
    syncResult: true,
  }
  const controller = createPomodoroPauseSyncController({
    setPendingPomodoroSync: (action, sessionId, clientActionAt) => {
      state.pending.set(action, { sessionId, clientActionAt })
      return state.pendingEnabled !== false
    },
    retryPendingPomodoroSync: () => {
      state.syncCalls += 1
      return Promise.resolve(state.syncResult)
    },
    ...overrides,
  })
  return { controller, state }
}

test('postPause sets the pending pause action and retries the sync', async () => {
  const { controller, state } = createHarness()

  assert.equal(await controller.postPause(42, 12345), true)

  assert.deepEqual(state.pending.get('pause'), { sessionId: 42, clientActionAt: 12345 })
  assert.equal(state.syncCalls, 1)
})

test('postPause throws when local persistence is unavailable', async () => {
  const { controller, state } = createHarness({ setPendingPomodoroSync: () => false })

  await assert.rejects(controller.postPause(42, 12345), /pomodoro local persistence unavailable/)

  assert.equal(state.syncCalls, 0)
})

test('postPause throws when the pending sync is still pending', async () => {
  const { controller, state } = createHarness()
  state.syncResult = false

  await assert.rejects(controller.postPause(42, 12345), /pomodoro pause sync pending/)

  assert.equal(state.syncCalls, 1)
})

test('postPause propagates a sync error without masking it', async () => {
  const failure = new Error('network unavailable')
  const calls = []
  const { controller, state } = createHarness({
    setPendingPomodoroSync: () => true,
    retryPendingPomodoroSync: () => {
      calls.push(1)
      return Promise.reject(failure)
    },
  })

  await assert.rejects(controller.postPause(42, 12345), failure)
  assert.equal(calls.length, 1, 'retry must be attempted before the error propagates')
})
