const assert = require('node:assert/strict')
const {
  getLocalPauseAdjustment,
  mergeLocalPauseAdjustment,
  clearLocalPauseAdjustment,
} = require('../pages/pomodoro/utils/pause-adjustment')

function makeStorage(raw) {
  let stored = raw !== undefined ? raw : null
  return {
    read: (key, context) => ({
      ok: stored !== null,
      value: stored,
    }),
    remove: () => { stored = null; return true },
  }
}

function storageWithValue(raw) {
  return {
    read: () => ({ ok: true, value: raw }),
    remove: () => true,
  }
}

// ── getLocalPauseAdjustment ──

assert.equal(getLocalPauseAdjustment(storageWithValue(null), 5, false), 0)
assert.equal(getLocalPauseAdjustment(storageWithValue({ sessionId: 5, totalPausedMs: 3000 }), 5, false), 3000)
assert.equal(getLocalPauseAdjustment(storageWithValue({ sessionId: 5, totalPausedMs: 3000 }), 6, false), 0)
assert.equal(getLocalPauseAdjustment(storageWithValue({}), 5, false), 0)
assert.equal(getLocalPauseAdjustment({ read: () => ({ ok: false, value: null }) }, 5, false), 0)
assert.equal(getLocalPauseAdjustment({ read: () => ({ ok: false, value: null }) }, 5, true), null)

// ── mergeLocalPauseAdjustment ──

assert.equal(mergeLocalPauseAdjustment(storageWithValue({ sessionId: 5, totalPausedMs: 5000 }), 5, 3000, false), 5000)
assert.equal(mergeLocalPauseAdjustment(storageWithValue({ sessionId: 5, totalPausedMs: 2000 }), 5, 3000, false), 3000)
assert.equal(mergeLocalPauseAdjustment(storageWithValue(null), 5, 3000, false), 3000)
assert.equal(mergeLocalPauseAdjustment({ read: () => ({ ok: false, value: null }) }, 5, 3000, true), null)

// ── clearLocalPauseAdjustment ──

const cleared = { removed: false }
const matchingStorage = {
  read: () => ({ ok: true, value: { sessionId: 5, totalPausedMs: 1000 } }),
  remove: () => { cleared.removed = true; return true },
}
assert.equal(clearLocalPauseAdjustment(matchingStorage, 5), true)
assert.equal(cleared.removed, true)

const nonMatchingStorage = {
  read: () => ({ ok: true, value: { sessionId: 6, totalPausedMs: 1000 } }),
  remove: () => false,
}
assert.equal(clearLocalPauseAdjustment(nonMatchingStorage, 5), true)

const nullStorage = {
  read: () => ({ ok: true, value: null }),
  remove: () => true,
}
assert.equal(clearLocalPauseAdjustment(nullStorage, 5), true)

const readFailStorage = {
  read: () => ({ ok: false, value: null }),
  remove: () => true,
}
assert.equal(clearLocalPauseAdjustment(readFailStorage, 5), false)

console.log('Pomodoro pause adjustment passed: get/merge/clear')
