const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createFreeElapsedController,
} = require('../pages/pomodoro/utils/free-elapsed-controller')

function makeHarness(overrides = {}) {
  const state = {
    sessionId: 'session-1',
    sessionStartTime: 1000,
    totalPausedMs: 100,
  }
  const options = {
    now: () => overrides.now ?? 11000,
    getSessionId: () => state.sessionId,
    getSessionStartTime: () => overrides.sessionStartTime ?? state.sessionStartTime,
    getTotalPausedMs: () => overrides.totalPausedMs ?? state.totalPausedMs,
    mergeLocalPauseAdjustment: (sessionId, totalPausedMs) => {
      if (overrides.mergePausedMs !== undefined) return overrides.mergePausedMs
      assert.equal(sessionId, 'session-1')
      return totalPausedMs
    },
  }
  return { options, state }
}

test('getElapsedMs uses injected clock and timer state', () => {
  const h = makeHarness({ now: 12000 })
  assert.equal(createFreeElapsedController(h.options).getElapsedMs(), 10900)
  assert.equal(createFreeElapsedController(h.options).getElapsedMs(12500), 11400)
})

test('getEffectiveElapsedMs merges local pause adjustment only after valid start', () => {
  const valid = makeHarness({ now: 12000, totalPausedMs: 100 })
  valid.options.mergeLocalPauseAdjustment = (sessionId, totalPausedMs) => {
    assert.deepEqual([sessionId, totalPausedMs], ['session-1', 100])
    return 1000
  }
  assert.equal(
    createFreeElapsedController(valid.options).getEffectiveElapsedMs(),
    10000,
  )

  const invalid = makeHarness({ sessionStartTime: 'invalid', now: 12000 })
  let read = false
  invalid.options.mergeLocalPauseAdjustment = () => {
    read = true
    return 1000
  }
  assert.equal(
    createFreeElapsedController(invalid.options).getEffectiveElapsedMs(),
    0,
  )
  assert.equal(read, false)
})

test('getEffectiveElapsedMs preserves invalid pause NaN propagation', () => {
  const h = makeHarness({ now: 12000, totalPausedMs: 'invalid' })
  h.options.mergeLocalPauseAdjustment = (sessionId, totalPausedMs) => totalPausedMs
  assert.ok(Number.isNaN(
    createFreeElapsedController(h.options).getEffectiveElapsedMs(),
  ))
})
