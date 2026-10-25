const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPomodoroSessionActionDropper,
} = require('../pages/pomodoro/utils/session-action-dropper')

function createHarness(overrides = {}) {
  const state = {
    queue: [
      { sessionId: 1, action: 'pause' },
      { sessionId: 2, action: 'resume' },
      { sessionId: 1, action: 'complete' },
    ],
    written: [],
    storage: new Map(),
    removeKeys: [],
    getContexts: [],
  }
  state.storage.set('pomodoro_pause', { ok: true, value: { sessionId: 1 } })
  state.storage.set('pomodoro_free_pause', { ok: true, value: { sessionId: 2 } })
  state.storage.set('pomodoro_pause_adjustment', { ok: true, value: null })
  state.storage.set('pomodoro_running_state', { ok: true, value: { sessionId: 1 } })

  const controller = createPomodoroSessionActionDropper({
    getPendingPomodoroSyncQueue: () => state.queue,
    writePendingPomodoroSyncQueue: queue => {
      state.written.push(queue)
      return true
    },
    safeGetPomodoroStorage: (key, context) => {
      state.getContexts.push(context)
      return state.storage.get(key) || { ok: true, value: null }
    },
    safeRemovePomodoroStorage: (key, context) => {
      state.removeKeys.push({ key, context })
      return true
    },
    ...overrides,
  })
  return { controller, state }
}

test('drop filters the queue and removes matching session snapshots', () => {
  const { controller, state } = createHarness()

  assert.equal(controller.drop(1), true)

  assert.deepEqual(state.written, [
    [
      { sessionId: 2, action: 'resume' },
    ],
  ])
  assert.deepEqual(state.removeKeys.sort((a, b) => a.key.localeCompare(b.key)), [
    { key: 'pomodoro_pause', context: 'drop reconciled session snapshot' },
    { key: 'pomodoro_running_state', context: 'drop reconciled running snapshot' },
  ])
  assert.deepEqual(state.getContexts, [
    'drop reconciled session snapshot',
    'drop reconciled session snapshot',
    'drop reconciled session snapshot',
    'drop reconciled running snapshot',
  ])
})

test('drop returns false when the queue read reports storage failure', () => {
  const { controller, state } = createHarness({
    getPendingPomodoroSyncQueue: () => null,
  })

  assert.equal(controller.drop(1), false)
  assert.deepEqual(state.written, [])
  assert.deepEqual(state.removeKeys, [])
  assert.deepEqual(state.getContexts, [])
})

test('drop returns false when persisting the filtered queue fails', () => {
  const { controller, state } = createHarness({
    writePendingPomodoroSyncQueue: () => false,
  })

  assert.equal(controller.drop(1), false)
  assert.deepEqual(state.removeKeys, [])
  assert.deepEqual(state.getContexts, [])
})

test('drop returns false when reading a stale snapshot fails', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_pause', { ok: false, value: null })

  assert.equal(controller.drop(1), false)
  assert.deepEqual(state.removeKeys, [])
  assert.deepEqual(state.getContexts, ['drop reconciled session snapshot'])
})

test('drop returns false when removing a matching snapshot fails', () => {
  const failing = (key, context) => {
    state.removeKeys.push({ key, context })
    return key === 'pomodoro_pause' ? false : true
  }
  const { controller, state } = createHarness({ safeRemovePomodoroStorage: failing })

  assert.equal(controller.drop(1), false)
  assert.deepEqual(state.removeKeys, [
    { key: 'pomodoro_pause', context: 'drop reconciled session snapshot' },
  ])
  assert.deepEqual(state.getContexts, ['drop reconciled session snapshot'])
})

test('drop leaves newer session snapshots untouched', () => {
  const { controller, state } = createHarness()

  assert.equal(controller.drop(2), true)

  assert.deepEqual(state.removeKeys.sort((a, b) => a.key.localeCompare(b.key)), [
    { key: 'pomodoro_free_pause', context: 'drop reconciled session snapshot' },
  ])
})

test('drop returns false when the running snapshot read fails', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', { ok: false, value: null })

  assert.equal(controller.drop(1), false)
  assert.deepEqual(state.removeKeys.sort((a, b) => a.key.localeCompare(b.key)), [
    { key: 'pomodoro_pause', context: 'drop reconciled session snapshot' },
  ])
  assert.deepEqual(state.getContexts, [
    'drop reconciled session snapshot',
    'drop reconciled session snapshot',
    'drop reconciled session snapshot',
    'drop reconciled running snapshot',
  ])
})

test('drop removes a matching pomodoro_pause_adjustment entry', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_pause_adjustment', { ok: true, value: { sessionId: 1 } })

  assert.equal(controller.drop(1), true)

  assert.deepEqual(state.removeKeys.sort((a, b) => a.key.localeCompare(b.key)), [
    { key: 'pomodoro_pause', context: 'drop reconciled session snapshot' },
    { key: 'pomodoro_pause_adjustment', context: 'drop reconciled session snapshot' },
    { key: 'pomodoro_running_state', context: 'drop reconciled running snapshot' },
  ])
})

test('drop returns false when removing the running snapshot fails', () => {
  const harness = createHarness({
    safeRemovePomodoroStorage: (key, context) => {
      harness.state.removeKeys.push({ key, context })
      return key !== 'pomodoro_running_state'
    },
  })

  assert.equal(harness.controller.drop(1), false)
  assert.deepEqual(harness.state.removeKeys.sort((a, b) => a.key.localeCompare(b.key)), [
    { key: 'pomodoro_pause', context: 'drop reconciled session snapshot' },
    { key: 'pomodoro_running_state', context: 'drop reconciled running snapshot' },
  ])
})
