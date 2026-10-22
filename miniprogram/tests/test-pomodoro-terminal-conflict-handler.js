const assert = require('node:assert/strict')
const {
  buildConflictToast,
  handleTerminalConflict,
} = require('../pages/pomodoro/utils/terminal-conflict-handler')

// ── buildConflictToast ──

const completedToast = buildConflictToast({ serverStatus: 'completed' })
assert.equal(completedToast.title, '已同步其他设备的完成状态')
assert.equal(completedToast.icon, 'none')
assert.equal(completedToast.duration, 2000)

const interruptedToast = buildConflictToast({ serverStatus: 'interrupted' })
assert.equal(interruptedToast.title, '已同步其他设备的结束状态')

// ── handleTerminalConflict: null/empty conflict ──

assert.equal(handleTerminalConflict({}, 1, null), false)
assert.equal(handleTerminalConflict({}, 1, undefined), false)

// ── storage error conflict ──

function makeOptions(overrides) {
  const calls = []
  const base = {
    isStorageError: (c) => !!(c && c.storageUnreadable),
    persistenceError: () => calls.push('persistenceError'),
    dropSessionActions: () => true,
    getStorage: () => ({ ok: true, value: null }),
    removeStorage: () => true,
    ackConflict: () => true,
    clearTimer: () => calls.push('clearTimer'),
    setData: (data) => calls.push(['setData', data]),
    resetIdle: () => calls.push('resetIdle'),
    showToast: () => calls.push('showToast'),
    loadStats: () => calls.push('loadStats'),
    completionBreakSec: 300,
  }
  const opts = Object.assign({}, base, overrides || {})
  opts._calls = calls
  return opts
}

const storageError = handleTerminalConflict(
  makeOptions(), 1, { storageUnreadable: true }
)
assert.equal(storageError, false)

// ── successful conflict resolution ──

const opts = makeOptions()
const result = handleTerminalConflict(opts, 42, {
  sessionId: 42,
  requestedAction: 'complete',
  serverStatus: 'completed',
})
assert.equal(result, true)
assert.equal(opts.completionBreakSec, null)
assert.ok(opts._calls.includes('clearTimer'))
assert.ok(opts._calls.includes('resetIdle'))
assert.ok(opts._calls.includes('showToast'))
assert.ok(opts._calls.includes('loadStats'))

// ── dropSessionActions failure ──

const dropFailed = makeOptions({ dropSessionActions: () => false })
assert.equal(handleTerminalConflict(dropFailed, 1, { sessionId: 1, requestedAction: 'complete' }), false)
assert.ok(dropFailed._calls.includes('persistenceError'))

// ── getStorage failure ──

const getFailed = makeOptions({ getStorage: () => ({ ok: false, value: null }) })
assert.equal(handleTerminalConflict(getFailed, 1, { sessionId: 1, requestedAction: 'complete' }), false)
assert.ok(getFailed._calls.includes('persistenceError'))

// ── completion removal failure ──

const completionFailed = makeOptions({
  getStorage: () => ({ ok: true, value: { sessionId: 5 } }),
  removeStorage: (key) => key === 'pomodoro_completion' ? false : true,
})
assert.equal(handleTerminalConflict(completionFailed, 5, { sessionId: 5, requestedAction: 'complete' }), false)
assert.ok(completionFailed._calls.includes('persistenceError'))

// ── ackConflict failure ──

const ackFailed = makeOptions({ ackConflict: () => false })
assert.equal(handleTerminalConflict(ackFailed, 1, { sessionId: 1, requestedAction: 'complete' }), false)
assert.ok(ackFailed._calls.includes('persistenceError'))

console.log('Pomodoro terminal conflict handler passed: toast/null/storage/drop/get/completion/ack')
