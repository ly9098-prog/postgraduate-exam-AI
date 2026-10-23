const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createEndSessionController } = require('../pages/pomodoro/utils/end-session-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const options = {
    getSessionId: () => overrides.sessionId ?? 's1',
    clearTimer: () => { calls.push(['clearTimer']) },
    completeWithRetry: () => { calls.push(['completeWithRetry']); return Promise.resolve(overrides.synced ?? true) },
    now: () => 100000,
    consumeTerminalConflict: () => { calls.push(['consumeTerminalConflict']); return overrides.conflict ?? null },
    handleTerminalConflict: () => { calls.push(['handleTerminalConflict']) },
    loadTodayStats: () => { calls.push(['loadTodayStats']) },
    resetToIdle: () => { calls.push(['resetToIdle']) },
  }
  return { options, calls }
}

test('end returns early when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createEndSessionController(h.options).end()
  assert.equal(h.calls.length, 0)
})

test('end clears timer, completes with retry, and resets to idle', () => {
  const h = makeHarness()
  createEndSessionController(h.options).end()
  assert.ok(h.calls.some(c => c[0] === 'clearTimer'))
  assert.ok(h.calls.some(c => c[0] === 'completeWithRetry'))
  assert.ok(h.calls.some(c => c[0] === 'resetToIdle'))
})

test('end loads stats when sync succeeds', async () => {
  const h = makeHarness({ synced: true })
  createEndSessionController(h.options).end()
  await new Promise(r => setTimeout(r, 50))
  assert.ok(h.calls.some(c => c[0] === 'loadTodayStats'))
})

test('end handles terminal conflict', async () => {
  const h = makeHarness({ conflict: { type: 'conflict' } })
  createEndSessionController(h.options).end()
  await new Promise(r => setTimeout(r, 50))
  assert.ok(h.calls.some(c => c[0] === 'handleTerminalConflict'))
  assert.ok(!h.calls.some(c => c[0] === 'loadTodayStats'))
})
