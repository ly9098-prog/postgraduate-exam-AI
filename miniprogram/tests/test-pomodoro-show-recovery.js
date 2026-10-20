const assert = require('node:assert/strict')
const { test } = require('node:test')
const { recoverOnShow } = require('../pages/pomodoro/utils/show-recovery')

function fixture(overrides = {}) {
  const calls = []
  const stored = new Map()
  const options = {
    readStorage: (key, context) => {
      calls.push(['read', key, context])
      return { ok: true, value: stored.get(key) }
    },
    removeStorage: (key, context) => { calls.push(['remove', key, context]); stored.delete(key) },
    persistenceError: () => calls.push('storage-error'),
    reconcileStart: async () => { calls.push('start'); return 'none' },
    isCurrent: () => true,
    consumeConflict: () => null,
    handleConflict: (id, conflict) => calls.push(['conflict', id, conflict]),
    showCompletion: value => calls.push(['completion', value]),
    retryPending: async () => { calls.push('retry'); return true },
    loadStats: () => calls.push('stats'),
    deferStats: () => calls.push('defer'),
    isNavigatingToStats: () => false,
    resetNavigation: () => calls.push('navigation-reset'),
    clearConfirmation: () => calls.push('clear-confirm'),
    confirmSnapshot: () => null,
    isValidConfirmation: () => true,
    restoreConfirmation: value => calls.push(['confirm', value]),
    recoverActive: async pending => calls.push(['active', pending]),
    ...overrides,
  }
  return { calls, stored, options }
}

test('pending storage error stops before uncertain-start request', async () => {
  const f = fixture()
  await recoverOnShow(f.options, { storageUnreadable: true })
  assert.deepEqual(f.calls, ['storage-error'])
})

test('unknown start resolutions short-circuit later recovery', async () => {
  for (const resolution of ['storage_error', 'cancelled', 'restored']) {
    const f = fixture({ reconcileStart: async () => resolution })
    await recoverOnShow(f.options, null)
    assert.deepEqual(f.calls, [resolution === 'storage_error' ? 'storage-error' : 'defer'])
  }
})

test('stale show generation stops immediately after uncertain-start reconciliation', async () => {
  const f = fixture({ isCurrent: () => false })
  await recoverOnShow(f.options, null)
  assert.deepEqual(f.calls, ['start'])
})

test('persisted terminal conflict takes precedence over completion marker', async () => {
  const conflict = { sessionId: 3 }
  const f = fixture({ consumeConflict: () => conflict })
  f.stored.set('pomodoro_completion', { sessionId: 3 })
  await recoverOnShow(f.options, null)
  assert.deepEqual(f.calls, ['start', ['conflict', 3, conflict]])
})

test('completion storage failure stops; missing session ID is cleaned then falls through', async () => {
  const error = fixture({ readStorage: () => ({ ok: false }) })
  await recoverOnShow(error.options, null)
  assert.deepEqual(error.calls, ['start', 'storage-error'])
  const f = fixture()
  f.stored.set('pomodoro_completion', { motto: 'legacy-invalid' })
  await recoverOnShow(f.options, null)
  assert.ok(!f.stored.has('pomodoro_completion'))
  assert.deepEqual(f.calls.at(-1), ['active', null])
})

test('valid completion retains marker, shows view, retries pending and defers stats', async () => {
  const f = fixture()
  const completion = Object.freeze({ sessionId: 4 })
  f.stored.set('pomodoro_completion', completion)
  const pending = { action: 'complete' }
  await recoverOnShow(f.options, pending)
  assert.equal(f.stored.get('pomodoro_completion'), completion)
  assert.deepEqual(f.calls.slice(2), [['completion', completion], 'retry', 'defer', 'stats'])
  assert.ok(!f.calls.some(call => Array.isArray(call) && call[0] === 'active'))
})

test('completion retry conflict supersedes immediate statistics refresh', async () => {
  const f = fixture()
  let consumed = 0
  const conflict = { sessionId: 5 }
  f.options.consumeConflict = () => consumed++ ? conflict : null
  f.stored.set('pomodoro_completion', { sessionId: 5 })
  await recoverOnShow(f.options, true)
  assert.deepEqual(f.calls.at(-1), ['conflict', 5, conflict])
  assert.ok(!f.calls.includes('stats'))
})

test('navigation reset discards confirmation without reading it, then recovers active', async () => {
  const f = fixture({ isNavigatingToStats: () => true })
  await recoverOnShow(f.options, null)
  assert.deepEqual(f.calls.slice(2), ['navigation-reset', 'clear-confirm', ['active', null]])
})

test('in-memory confirmation precedes storage; stored valid confirmation restores and stops', async () => {
  for (const memory of [false, true]) {
    const snapshot = { sessionId: 6 }
    const f = fixture({ confirmSnapshot: () => memory ? snapshot : null })
    f.stored.set('pomodoro_confirm_pause', snapshot)
    await recoverOnShow(f.options, null)
    assert.deepEqual(f.calls.at(-1), ['confirm', snapshot])
    assert.equal(f.calls.filter(call => Array.isArray(call) && call[0] === 'read').length, memory ? 1 : 2)
  }
})

test('confirmation read failure stops; invalid confirmation clears before active recovery', async () => {
  const f = fixture({ isValidConfirmation: () => false })
  f.stored.set('pomodoro_confirm_pause', { sessionId: 7 })
  await recoverOnShow(f.options, null)
  assert.deepEqual(f.calls.slice(-2), ['clear-confirm', ['active', null]])
  const failing = fixture()
  failing.options.readStorage = key => ({ ok: key !== 'pomodoro_confirm_pause' })
  await recoverOnShow(failing.options, null)
  assert.deepEqual(failing.calls, ['start', 'storage-error'])
})

test('missing confirmation session ID keeps legacy fallthrough without clearing', async () => {
  const f = fixture()
  f.stored.set('pomodoro_confirm_pause', { mode: 'free-complete' })
  const pending = { action: 'pause' }
  await recoverOnShow(f.options, pending)
  assert.deepEqual(f.calls.at(-1), ['active', pending])
  assert.ok(!f.calls.includes('clear-confirm'))
})
