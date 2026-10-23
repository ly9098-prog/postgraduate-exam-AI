const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createBreakRestoreController,
} = require('../pages/pomodoro/utils/break-restore-controller')

function createHarness(overrides = {}) {
  const calls = { removes: [], resetIdle: 0, startBreak: [] }
  const storage = new Map(overrides.storage || [])
  const options = {
    getStorageSync: key => storage.get(key),
    now: () => overrides.now || 100000,
    removeStorage: (key, context) => { calls.removes.push([key, context]); storage.delete(key) },
    resetIdle: () => { calls.resetIdle += 1 },
    startBreak: (totalSec, breakOptions) => { calls.startBreak.push([totalSec, breakOptions]) },
  }
  return { controller: createBreakRestoreController(options), calls, storage }
}

test('restore returns false when there is no saved break', () => {
  const harness = createHarness()
  assert.equal(harness.controller.restore(), false)
  assert.deepEqual(harness.calls.startBreak, [])
})

test('restore returns false for a malformed saved break', () => {
  const harness = createHarness({ storage: [['pomodoro_break', { startTime: 1 }]] })
  assert.equal(harness.controller.restore(), false)
})

test('restore cleans up and resets idle when the break has expired', () => {
  const harness = createHarness({
    storage: [['pomodoro_break', { startTime: 1000, totalSec: 60 }]],
    now: 200000,
  })
  assert.equal(harness.controller.restore(), false)
  assert.deepEqual(harness.calls.removes, [['pomodoro_break', 'best-effort cleanup']])
  assert.equal(harness.calls.resetIdle, 1)
  assert.deepEqual(harness.calls.startBreak, [])
})

test('restore restarts the break with the original start time and remaining', () => {
  const harness = createHarness({
    storage: [['pomodoro_break', { startTime: 50000, totalSec: 300 }]],
    now: 100000,
  })
  assert.equal(harness.controller.restore(), true)
  assert.deepEqual(harness.calls.startBreak, [[300, { startTime: 50000, remainingMs: 300000 - 50000 }]])
})

test('restore swallows storage read errors and returns false', () => {
  const controller = createBreakRestoreController({
    getStorageSync: () => { throw new Error('storage error') },
    now: () => 0,
    removeStorage: () => {},
    resetIdle: () => {},
    startBreak: () => {},
  })
  assert.equal(controller.restore(), false)
})
