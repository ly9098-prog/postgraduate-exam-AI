/** Regression checks for the extracted Pomodoro durable pending-sync queue. */
/* eslint-disable no-console */
const assert = require('assert')
const { createPendingSyncQueue } = require('../pages/pomodoro/utils/pending-sync-queue')

function createStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  const calls = []
  let readFailure = false
  let writeFailure = false
  let removeFailure = false
  return {
    calls,
    read(key, context) {
      calls.push(['read', key, context])
      if (readFailure) return { ok: false, value: null }
      return { ok: true, value: values.get(key) }
    },
    write(key, value, context) {
      calls.push(['write', key, context, value])
      if (writeFailure) return false
      values.set(key, value)
      return true
    },
    remove(key, context) {
      calls.push(['remove', key, context])
      if (removeFailure) return false
      values.delete(key)
      return true
    },
    get(key) { return values.get(key) },
    failRead(value) { readFailure = value },
    failWrite(value) { writeFailure = value },
    failRemove(value) { removeFailure = value },
  }
}

let now = 1000
const storage = createStorage()
const warnings = []
const queue = createPendingSyncQueue({
  storage,
  now: () => now++,
  random: () => 0.123456,
  logger: { warn: (...args) => warnings.push(args) },
})

assert.deepStrictEqual(queue.read(), [])
const pause = queue.enqueue('pause', 'session-a', 77)
assert.deepStrictEqual(pause, {
  action: 'pause', sessionId: 'session-a', savedAt: 1000, clientActionAt: 77, nonce: '1001-4fzyo8',
})
assert.strictEqual(queue.enqueue('pause', 'session-a', 88), pause)
const resume = queue.enqueue('resume', 'session-a', 88)
assert.strictEqual(resume.savedAt, 1002)
assert.strictEqual(resume.clientActionAt, 88)
assert.strictEqual(queue.head(), pause)
assert.strictEqual(queue.has('session-a', ['resume']), true)
assert.strictEqual(queue.clear(pause), true)
assert.strictEqual(queue.head(), resume)
assert.strictEqual(queue.update(resume, { clientActionAt: 99 }).clientActionAt, 99)

const legacyStorage = createStorage({ pomodoro_pending_sync: {
  action: 'pause', sessionId: 'legacy', savedAt: 5, nonce: 'old', completeAfter: true,
} })
const legacy = createPendingSyncQueue({ storage: legacyStorage, now: () => 42 })
assert.deepStrictEqual(legacy.read().map(item => item.action), ['pause', 'complete'])
assert.strictEqual(legacyStorage.get('pomodoro_pending_sync').length, 2)

const invalidStorage = createStorage({ pomodoro_pending_sync: [
  { action: 'pause', sessionId: 'ok', savedAt: 2 },
  { action: 'unknown', sessionId: 'bad', savedAt: 2 },
  { action: 'resume', sessionId: 'bad-time', savedAt: 0 },
] })
const invalid = createPendingSyncQueue({ storage: invalidStorage, now: () => 7 })
assert.deepStrictEqual(invalid.read().map(item => item.sessionId), ['ok'])
invalidStorage.failWrite(true)
invalidStorage.get('pomodoro_pending_sync').push({ action: 'bad', sessionId: 'x', savedAt: 3 })
assert.strictEqual(invalid.read(), null)
assert.deepStrictEqual(invalid.head(), { storageUnreadable: true })
assert.strictEqual(invalid.has('ok', 'pause'), true)

const capStorage = createStorage({ pomodoro_pending_sync: Array.from({ length: 196 }, (_, i) => ({
  action: 'pause', sessionId: `s-${i}`, savedAt: i + 1, nonce: `${i}`,
})) })
const capped = createPendingSyncQueue({
  storage: capStorage, now: () => 500, random: () => 0,
  logger: { warn: (...args) => warnings.push(args) },
})
assert.strictEqual(capped.enqueue('resume', 'new-session'), null)
assert.strictEqual(capped.enqueue('complete', 'new-session').action, 'complete')
assert.strictEqual(capped.enqueue('complete', 'new-session').sessionId, 'new-session')
assert.strictEqual(capStorage.get('pomodoro_pending_sync').length, 197)
assert.strictEqual(warnings.length, 1)

const isolatedA = createStorage()
const isolatedB = createStorage()
const a = createPendingSyncQueue({ storage: isolatedA, now: () => 1, random: () => 0 })
const b = createPendingSyncQueue({ storage: isolatedB, now: () => 2, random: () => 0 })
a.enqueue('pause', 'a')
assert.strictEqual(b.read().length, 0)
assert.strictEqual(isolatedA.get('pomodoro_pending_sync').length, 1)
assert.strictEqual(isolatedB.get('pomodoro_pending_sync'), undefined)

const failureStorage = createStorage()
const failure = createPendingSyncQueue({ storage: failureStorage, now: () => 9, random: () => 0 })
failureStorage.failWrite(true)
assert.strictEqual(failure.enqueue('pause', 'failed'), null)
failureStorage.failWrite(false)
assert.strictEqual(failure.read().length, 0)
failureStorage.failRemove(true)
assert.strictEqual(failure.clear(), false)


failureStorage.failRemove(false)
failureStorage.failRead(true)
assert.strictEqual(failure.read(), null)
assert.deepStrictEqual(failure.head(), { storageUnreadable: true })
assert.strictEqual(failure.has('missing', 'pause'), true)
assert.strictEqual(failure.enqueue('resume', 'failed'), null)
assert.strictEqual(failure.clear({ nonce: 'x' }), false)
assert.strictEqual(failure.update({ nonce: 'x' }, {}), null)
failureStorage.failRead(false)
assert.strictEqual(failure.write({}), false)
assert.strictEqual(failure.write([]), true)

for (let i = 0; i < 3; i++) assert.ok(capped.enqueue('interrupt', `terminal-${i}`))
assert.strictEqual(capStorage.get('pomodoro_pending_sync').length, 200)
assert.strictEqual(capped.enqueue('complete', 'over-cap'), null)
assert.strictEqual(capStorage.get('pomodoro_pending_sync').length, 200)
assert.strictEqual(capped.enqueue('complete', 'new-session').sessionId, 'new-session')

const prior = a.head()
a.enqueue('resume', 'a')
const terminal = a.enqueue('complete', 'a')
a.enqueue('pause', 'other')
assert.deepStrictEqual(a.enqueue('complete', 'a'), terminal)
assert.strictEqual(a.update({ nonce: 'absent' }, { clientActionAt: 4 }), null)
isolatedA.failWrite(true)
assert.strictEqual(a.update(prior, { clientActionAt: 5 }), null)
isolatedA.failRemove(true)
assert.strictEqual(a.clear(prior), false)
isolatedA.failRemove(false)
isolatedA.failWrite(false)
assert.strictEqual(a.head().clientActionAt, 1)
assert.strictEqual(a.clear(), true)
assert.deepStrictEqual(a.read(), [])

const { readStorage, writeStorage, removeStorage } = require('../pages/pomodoro/utils/session-storage')
const diagnostics = []
const originalError = console.error
const originalWarn = console.warn
console.error = (...args) => diagnostics.push(['error', ...args])
console.warn = (...args) => diagnostics.push(['warn', ...args])
try {
  const values = new Map()
  const wx = {
    getStorageSync: key => values.get(key),
    setStorageSync: (key, value) => values.set(key, value),
    removeStorageSync: key => values.delete(key),
  }
  assert.strictEqual(writeStorage(wx, 'key', 'value'), true)
  assert.deepStrictEqual(readStorage(wx, 'key'), { ok: true, value: 'value' })
  assert.strictEqual(removeStorage(wx, 'key'), true)
  assert.strictEqual(readStorage(wx, 'key').value, undefined)
  const broken = new Proxy({}, { get: () => () => { throw new Error('storage failure') } })
  assert.deepStrictEqual(readStorage(broken, 'key', 'read-context'), { ok: false, value: null })
  assert.strictEqual(writeStorage(broken, 'key', 'value', 'write-context'), false)
  assert.strictEqual(removeStorage(broken, 'key', 'remove-context'), false)
  assert.deepStrictEqual(diagnostics.map(item => item.slice(0, 2)), [
    ['error', 'pomodoro storage read failed (read-context): key'],
    ['error', 'pomodoro storage write failed (write-context): key'],
    ['warn', 'pomodoro storage remove failed (remove-context): key'],
  ])
} finally {
  console.error = originalError
  console.warn = originalWarn
}
console.log('Pomodoro pending-sync queue and session-storage checks passed')
