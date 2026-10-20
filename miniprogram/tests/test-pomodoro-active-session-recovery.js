const assert = require('node:assert/strict')
const { test } = require('node:test')
const { recoverActiveSession } = require('../pages/pomodoro/utils/active-session-recovery')

function fixture(overrides = {}) {
  const calls = []
  const state = { running: false, sessionId: null }
  const options = {
    readCached: () => null,
    isStorageError: value => !!(value && value.storageUnreadable),
    persistenceError: () => calls.push('storage-error'),
    canLightSync: () => false,
    syncLight: session => { calls.push('light'); return restore(session) },
    restoreSession: restore,
    isRunning: () => state.running,
    sessionId: () => state.sessionId,
    restoreBreak: () => { calls.push('break'); return false },
    retryPending: async () => { calls.push('retry'); return true },
    consumeConflict: () => null,
    handleConflict: (id, conflict) => calls.push(['conflict', id, conflict]),
    deferStats: () => calls.push('stats'),
    fetchActive: async () => { calls.push('fetch'); return null },
    hasPendingTerminal: () => false,
    removeStorage: key => calls.push(['remove', key]),
    clearTimer: () => calls.push('clear-timer'),
    resetIdle: () => { calls.push('idle'); state.running = false },
    isCurrent: () => true,
    ...overrides,
  }
  function restore(session) {
    calls.push(['restore', session.id])
    state.running = true
    state.sessionId = session.id
  }
  return { options, calls, state }
}

test('cached dial restores synchronously before pending drain and server fetch', async () => {
  const f = fixture({ readCached: () => ({ id: 1 }) })
  const recovery = recoverActiveSession(f.options, true)
  assert.deepEqual(f.calls, [['restore', 1], 'retry'])
  await recovery
  assert.deepEqual(f.calls, [['restore', 1], 'retry', 'fetch', 'idle', 'break', 'stats'])
})

test('local break restores before network; active server session replaces it', async () => {
  const f = fixture({ fetchActive: async () => ({ id: 2 }) })
  f.options.restoreBreak = () => { f.calls.push('break'); return true }
  await recoverActiveSession(f.options, false)
  assert.deepEqual(f.calls, [
    'break', 'clear-timer', ['remove', 'pomodoro_break'], ['restore', 2], 'stats',
  ])
})

test('offline pending drain preserves local state and never fetches active', async () => {
  const f = fixture({
    readCached: () => ({ id: 3 }),
    retryPending: async () => false,
  })
  await recoverActiveSession(f.options, true)
  assert.deepEqual(f.calls, [['restore', 3], 'stats'])
  assert.equal(f.state.running, true)
})

test('terminal conflict ends recovery before stats or server fetch', async () => {
  const conflict = { sessionId: 4 }
  const f = fixture({ consumeConflict: () => conflict })
  await recoverActiveSession(f.options, true)
  assert.deepEqual(f.calls, ['break', 'retry', ['conflict', 4, conflict]])
})

test('storage errors at cache or fetch stop without later writes', async () => {
  for (const source of ['readCached', 'fetchActive']) {
    const f = fixture()
    f.options[source] = () => ({ storageUnreadable: true })
    await recoverActiveSession(f.options, false)
    assert.equal(f.calls.at(-1), 'storage-error')
    assert.ok(!f.calls.includes('stats'))
    assert.ok(!f.calls.some(call => Array.isArray(call)))
  }
})

test('failed local or server restore prevents further recovery and stats', async () => {
  for (const source of ['readCached', 'fetchActive']) {
    const f = fixture({ restoreSession: () => false })
    f.options[source] = () => ({ id: 5 })
    await recoverActiveSession(f.options, false)
    assert.ok(!f.calls.includes('stats'))
    if (source === 'readCached') assert.deepEqual(f.calls, [])
  }
})

test('stale generation after drain or fetch suppresses reconciliation', async () => {
  for (const pending of [true, false]) {
    const f = fixture({ isCurrent: () => false })
    await recoverActiveSession(f.options, pending)
    assert.deepEqual(f.calls, pending ? ['break', 'retry'] : ['break', 'fetch'])
  }
})

test('pending terminal action removes stale running snapshot without resurrection', async () => {
  const f = fixture({ fetchActive: async () => ({ id: 6 }) })
  f.options.hasPendingTerminal = (id, actions) => {
    assert.equal(id, 6)
    assert.deepEqual(actions, ['complete', 'interrupt'])
    return true
  }
  await recoverActiveSession(f.options, false)
  assert.deepEqual(f.calls, ['break', ['remove', 'pomodoro_running_state'], 'stats'])
})

test('light sync receives persistence flag for local and server sessions', async () => {
  const f = fixture({
    readCached: () => ({ id: 7 }),
    fetchActive: async () => ({ id: 7 }),
    canLightSync: () => true,
  })
  f.options.syncLight = (session, persist) => {
    assert.equal(persist, true)
    f.state.running = true
    f.state.sessionId = session.id
    f.calls.push('light')
  }
  await recoverActiveSession(f.options, false)
  assert.deepEqual(f.calls, ['light', 'light', 'stats'])
})

test('no active row does not repeat a successfully restored local break', async () => {
  const f = fixture()
  f.options.restoreBreak = () => { f.calls.push('break'); return true }
  await recoverActiveSession(f.options, false)
  assert.deepEqual(f.calls, ['break', 'fetch', 'stats'])
})
