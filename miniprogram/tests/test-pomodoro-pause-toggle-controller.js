const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPauseToggleController,
} = require('../pages/pomodoro/utils/pause-toggle-controller')

function createHarness(overrides = {}) {
  const calls = { pauseFree: 0, resumeFree: 0, pauseCountdown: 0, resumeCountdown: 0 }
  const timers = { scheduled: [], cleared: [] }
  let nextId = 1
  const options = {
    cooldownMs: 500,
    setTimeout(callback, delay) {
      const id = nextId++
      timers.scheduled.push({ id, delay, callback })
      return id
    },
    clearTimeout(id) { timers.cleared.push(id) },
    phase: () => overrides.phase || 'running',
    runningPhase: 'running',
    sessionId: () => overrides.sessionId === undefined ? 1 : overrides.sessionId,
    actionLoading: () => overrides.actionLoading || false,
    showEndConfirm: () => overrides.showEndConfirm || false,
    isFreeTimer: () => overrides.isFreeTimer || false,
    isPaused: () => overrides.isPaused || false,
    pauseFree() { calls.pauseFree += 1 },
    resumeFree() { calls.resumeFree += 1 },
    pauseCountdown() { calls.pauseCountdown += 1 },
    resumeCountdown() { calls.resumeCountdown += 1 },
  }
  return { controller: createPauseToggleController(options), calls, timers }
}

test('acquire returns true once and auto-unlocks after the cooldown', () => {
  const harness = createHarness()

  assert.equal(harness.controller.acquire(), true)
  assert.equal(harness.controller.acquire(), false)
  assert.equal(harness.timers.scheduled.length, 1)
  assert.equal(harness.timers.scheduled[0].delay, 500)

  harness.timers.scheduled[0].callback()
  assert.equal(harness.controller.acquire(), true)
})

test('release cancels a pending unlock timer and clears the lock', () => {
  const harness = createHarness()

  harness.controller.acquire()
  const id = harness.timers.scheduled[0].id
  harness.controller.release()
  assert.deepEqual(harness.timers.cleared, [id])
  assert.equal(harness.controller.acquire(), true)
})

test('release is a no-op when no timer is pending', () => {
  const harness = createHarness()
  harness.controller.release()
  assert.deepEqual(harness.timers.cleared, [])
})

test('toggle rejects invalid phase, missing session, actionLoading and end-confirm', () => {
  for (const overrides of [
    { phase: 'idle' },
    { sessionId: null },
    { actionLoading: true },
    { showEndConfirm: true },
  ]) {
    const harness = createHarness(overrides)
    harness.controller.toggle()
    assert.deepEqual(harness.calls, { pauseFree: 0, resumeFree: 0, pauseCountdown: 0, resumeCountdown: 0 })
  }
})

test('toggle acquires the lock and dispatches to the right handler', () => {
  const pauseCountdown = createHarness({ isFreeTimer: false, isPaused: false })
  pauseCountdown.controller.toggle()
  assert.equal(pauseCountdown.calls.pauseCountdown, 1)

  const resumeCountdown = createHarness({ isFreeTimer: false, isPaused: true })
  resumeCountdown.controller.toggle()
  assert.equal(resumeCountdown.calls.resumeCountdown, 1)

  const pauseFree = createHarness({ isFreeTimer: true, isPaused: false })
  pauseFree.controller.toggle()
  assert.equal(pauseFree.calls.pauseFree, 1)

  const resumeFree = createHarness({ isFreeTimer: true, isPaused: true })
  resumeFree.controller.toggle()
  assert.equal(resumeFree.calls.resumeFree, 1)
})

test('a rapid second toggle is rejected by the cooldown', () => {
  const harness = createHarness()
  harness.controller.toggle()
  harness.controller.toggle()
  assert.equal(harness.calls.pauseCountdown, 1)
})
