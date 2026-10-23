const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCelebrationDismissController,
} = require('../pages/pomodoro/utils/celebration-dismiss-controller')

function createHarness(overrides = {}) {
  const calls = { removes: [], setData: [], breakSec: [], persistence: 0, startBreak: [], resetIdle: 0 }
  const storage = new Map(overrides.storage || [])
  const options = {
    getStorage: (key, context) => {
      if (overrides.readFailure) return { ok: false, value: null }
      return { ok: true, value: storage.get(key) }
    },
    removeStorage: (key, context) => { calls.removes.push([key, context]); storage.delete(key) },
    resolveBreakSec: (flag, breakSec, view) => overrides.breakSec === undefined ? 0 : overrides.breakSec,
    getCompletionBreakSec: () => overrides.completionBreakSec || null,
    setCompletionBreakSec: value => { calls.breakSec.push(value) },
    view: () => ({}),
    setData: data => calls.setData.push(data),
    persistenceError: () => { calls.persistence += 1 },
    startBreak: sec => { calls.startBreak.push(sec) },
    resetIdle: () => { calls.resetIdle += 1 },
  }
  return { controller: createCelebrationDismissController(options), calls, storage }
}

test('dismiss reads the completion marker and clears it before starting a break', () => {
  const harness = createHarness({
    storage: [['pomodoro_completion', { sessionId: 5 }]],
    breakSec: 300,
  })
  harness.controller.dismiss()
  assert.deepEqual(harness.calls.removes, [['pomodoro_completion', 'best-effort cleanup']])
  assert.deepEqual(harness.calls.breakSec, [null])
  assert.deepEqual(harness.calls.setData, [{ showCelebration: false }])
  assert.deepEqual(harness.calls.startBreak, [300])
  assert.equal(harness.calls.resetIdle, 0)
})

test('dismiss resets to idle when there is no break', () => {
  const harness = createHarness({
    storage: [['pomodoro_completion', { sessionId: 5 }]],
    breakSec: 0,
  })
  harness.controller.dismiss()
  assert.equal(harness.calls.resetIdle, 1)
  assert.deepEqual(harness.calls.startBreak, [])
})

test('dismiss fails closed when the completion marker cannot be read', () => {
  const harness = createHarness({ readFailure: true })
  harness.controller.dismiss()
  assert.equal(harness.calls.persistence, 1)
  assert.deepEqual(harness.calls.removes, [])
  assert.deepEqual(harness.calls.setData, [])
})
