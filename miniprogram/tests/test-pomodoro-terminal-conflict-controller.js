const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createTerminalConflictController,
} = require('../pages/pomodoro/utils/terminal-conflict-controller')
const {
  createTerminalConflict,
  isValidTerminalConflict,
  matchesTerminalConflict,
  isStorageConflict,
} = require('../pages/pomodoro/utils/terminal-conflict-state')
const {
  handleTerminalConflict,
} = require('../pages/pomodoro/utils/terminal-conflict-handler')

const CONFLICT_KEY = 'pomodoro_terminal_conflict'

function createHarness(overrides = {}) {
  const calls = []
  const toasts = []
  const state = {
    storage: new Map(Object.entries(overrides.storage || {})),
    breakSec: overrides.breakSec === undefined ? 1500 : overrides.breakSec,
    persistenceErrors: 0,
  }
  const options = {
    storageKey: CONFLICT_KEY,
    now: () => overrides.now || 5000,
    createConflict: createTerminalConflict,
    isValidConflict: isValidTerminalConflict,
    matchesConflict: matchesTerminalConflict,
    isStorageConflict,
    handleTerminalConflict,
    getStorage(key, context) {
      calls.push(['getStorage', key, context])
      if (overrides.readFailure && overrides.readFailure(key, context)) {
        return { ok: false, value: null }
      }
      return { ok: true, value: state.storage.get(key) }
    },
    setStorage(key, value, context) {
      calls.push(['setStorage', key, context])
      if (overrides.setFailure && overrides.setFailure(key, context)) return false
      state.storage.set(key, value)
      return true
    },
    removeStorage(key, context) {
      calls.push(['removeStorage', key, context])
      if (overrides.removeFailure && overrides.removeFailure(key, context)) return false
      state.storage.delete(key)
      return true
    },
    dropSessionActions(sessionId) {
      calls.push(['dropSessionActions', sessionId])
      if (overrides.dropResult === false) return false
      return true
    },
    persistenceError() {
      state.persistenceErrors += 1
      calls.push(['persistenceError'])
    },
    getCompletionBreakSec() {
      return state.breakSec
    },
    setCompletionBreakSec(value) {
      calls.push(['setCompletionBreakSec', value])
      state.breakSec = value
    },
    clearTimer() {
      calls.push(['clearTimer'])
    },
    setData(data) {
      calls.push(['setData', data])
    },
    resetIdle() {
      calls.push(['resetIdle'])
    },
    showToast(toast) {
      calls.push(['showToast', toast.title])
      toasts.push(toast)
    },
    loadStats() {
      calls.push(['loadStats'])
    },
  }
  return {
    controller: createTerminalConflictController(options),
    calls,
    state,
    toasts,
  }
}

test('record persists the conflict marker and caches it in memory', () => {
  const harness = createHarness()

  assert.equal(harness.controller.record(7, 'complete', 'completed'), true)
  assert.deepEqual(harness.state.storage.get(CONFLICT_KEY), {
    sessionId: 7,
    requestedAction: 'complete',
    serverStatus: 'completed',
    savedAt: 5000,
  })
  assert.deepEqual(harness.controller.read(), harness.state.storage.get(CONFLICT_KEY))
})

test('record returns false and keeps memory empty when storage write fails', () => {
  const harness = createHarness({ setFailure: () => true })

  assert.equal(harness.controller.record(7, 'complete', 'completed'), false)
  assert.equal(harness.state.storage.has(CONFLICT_KEY), false)
  assert.equal(harness.controller.read(), null)
})

test('read prefers the in-memory conflict without touching storage', () => {
  const harness = createHarness()
  assert.equal(harness.controller.record(8, 'interrupt', 'interrupted'), true)
  harness.calls.length = 0

  const conflict = harness.controller.read()
  assert.equal(conflict.sessionId, 8)
  assert.deepEqual(harness.calls, [])
})

test('read loads a valid stored conflict and invalidates unusable values', () => {
  const stored = createTerminalConflict(9, 'complete', 'completed', 1000)
  const valid = createHarness({ storage: { [CONFLICT_KEY]: stored } })
  assert.deepEqual(valid.controller.read(), stored)

  const invalid = createHarness({ storage: { [CONFLICT_KEY]: { savedAt: 1 } } })
  assert.equal(invalid.controller.read(), null)
})

test('read fails closed with a storage marker when storage cannot be read', () => {
  const harness = createHarness({ readFailure: () => true })

  assert.deepEqual(harness.controller.read(), { storageUnreadable: true })
})

test('consume passes storage errors through and only returns matching conflicts', () => {
  const unreadable = createHarness({ readFailure: () => true })
  assert.deepEqual(unreadable.controller.consume(7, 'complete'), { storageUnreadable: true })

  const harness = createHarness({
    storage: { [CONFLICT_KEY]: createTerminalConflict(7, 'complete', 'completed', 1) },
  })
  assert.equal(harness.controller.consume(7, 'complete').sessionId, 7)
  assert.equal(harness.controller.consume(7, 'interrupt'), null)
  assert.equal(harness.controller.consume(8, 'complete'), null)
})

test('consumeAny returns the stored conflict regardless of session or action', () => {
  const stored = createTerminalConflict(7, 'complete', 'completed', 1)
  const harness = createHarness({ storage: { [CONFLICT_KEY]: stored } })

  assert.deepEqual(harness.controller.consumeAny(), stored)
})

test('ack rejects empty and storage-conflict values without removing storage', () => {
  const harness = createHarness({
    storage: { [CONFLICT_KEY]: createTerminalConflict(7, 'complete', 'completed', 1) },
  })

  assert.equal(harness.controller.ack(null), false)
  assert.equal(harness.controller.ack({ storageUnreadable: true }), false)
  assert.equal(harness.state.storage.has(CONFLICT_KEY), true)
})

test('ack removes the marker and clears matching in-memory state', () => {
  const harness = createHarness()
  harness.controller.record(7, 'complete', 'completed')

  assert.equal(harness.controller.read().sessionId, 7)
  assert.equal(harness.controller.ack(harness.controller.read()), true)
  assert.equal(harness.state.storage.has(CONFLICT_KEY), false)
  assert.equal(harness.controller.read(), null)
})

test('ack keeps evidence when storage removal fails', () => {
  const harness = createHarness({
    storage: { [CONFLICT_KEY]: createTerminalConflict(7, 'complete', 'completed', 1) },
    removeFailure: (key, context) => key === CONFLICT_KEY && context === 'terminal conflict ack',
  })

  assert.equal(harness.controller.ack(harness.controller.read()), false)
  assert.equal(harness.state.storage.has(CONFLICT_KEY), true)
  assert.equal(harness.controller.read().sessionId, 7)
})

test('ack keeps a newer in-memory conflict that no longer matches', () => {
  const harness = createHarness({
    storage: { [CONFLICT_KEY]: createTerminalConflict(7, 'complete', 'completed', 1) },
  })
  const stale = harness.controller.read()
  // A second device terminal result arrives before the stale marker is acked.
  harness.controller.record(8, 'interrupt', 'interrupted')

  assert.equal(harness.controller.ack(stale), true)
  assert.equal(harness.state.storage.has(CONFLICT_KEY), false)
  assert.equal(harness.controller.read().sessionId, 8)
})

test('handle ignores missing and unreadable conflicts with a persistence error', () => {
  const empty = createHarness()
  assert.equal(empty.controller.handle(7, null), false)
  assert.equal(empty.state.persistenceErrors, 0)

  const unreadable = createHarness()
  assert.equal(unreadable.controller.handle(7, { storageUnreadable: true }), false)
  assert.equal(unreadable.state.persistenceErrors, 1)
})

test('handle fails closed when pending actions or completion cannot be cleaned', () => {
  const conflict = createTerminalConflict(7, 'complete', 'completed', 1)

  const dropFailure = createHarness({ dropResult: false })
  assert.equal(dropFailure.controller.handle(7, conflict), false)
  assert.equal(dropFailure.state.persistenceErrors, 1)
  assert.deepEqual(dropFailure.calls.map(call => call[0]), ['dropSessionActions', 'persistenceError'])

  const readFailure = createHarness({
    storage: { pomodoro_completion: { sessionId: 7 } },
    readFailure: (key, context) => key === 'pomodoro_completion' &&
      context === 'terminal conflict completion',
  })
  assert.equal(readFailure.controller.handle(7, conflict), false)
  assert.equal(readFailure.state.persistenceErrors, 1)

  const removeFailure = createHarness({
    storage: { pomodoro_completion: { sessionId: 7 } },
    removeFailure: (key, context) => key === 'pomodoro_completion' &&
      context === 'terminal conflict completion',
  })
  assert.equal(removeFailure.controller.handle(7, conflict), false)
  assert.equal(removeFailure.state.persistenceErrors, 1)
  assert.equal(removeFailure.state.storage.has('pomodoro_completion'), true)
})

test('handle keeps the marker and memory when the acknowledgement fails', () => {
  const conflict = createTerminalConflict(7, 'complete', 'completed', 1)
  const harness = createHarness({
    storage: { [CONFLICT_KEY]: conflict },
    removeFailure: (key, context) => key === CONFLICT_KEY && context === 'terminal conflict ack',
  })
  // Reading first caches the marker in memory so a failed ack can be replayed.
  harness.controller.read()

  assert.equal(harness.controller.handle(7, conflict), false)
  assert.equal(harness.state.persistenceErrors, 1)
  assert.equal(harness.state.storage.has(CONFLICT_KEY), true)
  assert.equal(harness.controller.read().sessionId, 7)
  assert.equal(harness.state.breakSec, 1500)
  assert.ok(!harness.calls.some(call => call[0] === 'clearTimer'))
  assert.ok(!harness.calls.some(call => call[0] === 'loadStats'))
})

test('handle cleans local state in order and acknowledges only after cleanup', () => {
  const conflict = createTerminalConflict(7, 'complete', 'completed', 1)
  const harness = createHarness({
    storage: {
      [CONFLICT_KEY]: conflict,
      pomodoro_completion: { sessionId: 7 },
      pomodoro_break: { sessionId: 7 },
      pomodoro_pause_adjustment: { sessionId: 7 },
    },
  })
  harness.controller.read()

  assert.equal(harness.controller.handle(7, conflict), true)
  assert.deepEqual(harness.calls.map(call => call[0]), [
    'getStorage',
    'dropSessionActions',
    'getStorage',
    'removeStorage',
    'removeStorage',
    'removeStorage',
    'removeStorage',
    'setCompletionBreakSec',
    'clearTimer',
    'setData',
    'resetIdle',
    'showToast',
    'loadStats',
  ])
  assert.deepEqual(harness.calls[1], ['dropSessionActions', 7])
  assert.deepEqual(harness.calls[2], ['getStorage', 'pomodoro_completion', 'terminal conflict completion'])
  assert.deepEqual(harness.calls[3], ['removeStorage', 'pomodoro_completion', 'terminal conflict completion'])
  assert.deepEqual(harness.calls[4], ['removeStorage', 'pomodoro_break', 'best-effort cleanup'])
  assert.deepEqual(harness.calls[5], ['removeStorage', 'pomodoro_pause_adjustment', 'best-effort cleanup'])
  assert.deepEqual(harness.calls[6], ['removeStorage', CONFLICT_KEY, 'terminal conflict ack'])
  assert.deepEqual(harness.calls[7], ['setCompletionBreakSec', null])
  assert.deepEqual(harness.calls[8], ['clearTimer'])
  assert.deepEqual(harness.calls[9], ['setData', { showCelebration: false, showEndConfirm: false }])
  assert.deepEqual(harness.calls[10], ['resetIdle'])
  assert.deepEqual(harness.calls[11], ['showToast', '已同步其他设备的完成状态'])
  assert.deepEqual(harness.calls[12], ['loadStats'])
  assert.equal(harness.state.storage.size, 0)
  assert.equal(harness.controller.read(), null)
})

test('handle leaves an unrelated completion record untouched', () => {
  const conflict = createTerminalConflict(7, 'interrupt', 'interrupted', 1)
  const harness = createHarness({
    storage: {
      [CONFLICT_KEY]: conflict,
      pomodoro_completion: { sessionId: 99 },
    },
  })

  assert.equal(harness.controller.handle(7, conflict), true)
  assert.equal(harness.state.storage.get('pomodoro_completion').sessionId, 99)
  assert.ok(harness.calls.some(call => call[0] === 'showToast' &&
    call[1] === '已同步其他设备的结束状态'))
})
