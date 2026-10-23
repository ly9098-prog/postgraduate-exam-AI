/**
 * Independent regression for the reset-to-idle controller.
 * Run: node --test miniprogram/tests/test-pomodoro-reset-to-idle-controller.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createResetToIdleController } = require('../pages/pomodoro/utils/reset-to-idle-controller')

function makeHarness() {
  const calls = []
  const options = {
    clearFreeTimerInterval: () => { calls.push(['clearFreeTimerInterval']) },
    setConfirmTimerSnapshot: v => { calls.push(['setConfirmTimerSnapshot', v]) },
    invalidateCanvas: () => { calls.push(['invalidateCanvas']) },
    resetTimerState: () => { calls.push(['resetTimerState']) },
    safeRemoveStorage: key => { calls.push(['safeRemoveStorage', key]) },
    getSelectedTaskType: () => 'study',
    taskTypeLabel: type => `label-${type}`,
    idlePhase: () => 'idle',
    setData: data => { calls.push(['setData', data]) },
    setCompletionBreakSec: v => { calls.push(['setCompletionBreakSec', v]) },
    updateComputedFields: () => { calls.push(['updateComputedFields']) },
  }
  return { options, calls }
}

test('reset clears free timer interval and confirm snapshot', () => {
  const h = makeHarness()
  createResetToIdleController(h.options).reset()
  assert.ok(h.calls.some(c => c[0] === 'clearFreeTimerInterval'))
  assert.ok(h.calls.some(c => c[0] === 'setConfirmTimerSnapshot' && c[1] === null))
})

test('reset invalidates canvas and resets timer state', () => {
  const h = makeHarness()
  createResetToIdleController(h.options).reset()
  assert.ok(h.calls.some(c => c[0] === 'invalidateCanvas'))
  assert.ok(h.calls.some(c => c[0] === 'resetTimerState'))
})

test('reset removes all seven persisted storage keys', () => {
  const h = makeHarness()
  createResetToIdleController(h.options).reset()
  const removed = h.calls.filter(c => c[0] === 'safeRemoveStorage').map(c => c[1])
  const expected = ['pomodoro_break', 'pomodoro_completion', 'pomodoro_pause',
    'pomodoro_free_pause', 'pomodoro_running_state', 'pomodoro_confirm_pause',
    'pomodoro_pause_adjustment']
  for (const key of expected) assert.ok(removed.includes(key), `missing ${key}`)
  assert.equal(removed.length, 7)
})

test('reset sets idle view with task type and clears completion break sec', () => {
  const h = makeHarness()
  createResetToIdleController(h.options).reset()
  const setDataCall = h.calls.find(c => c[0] === 'setData')
  assert.equal(setDataCall[1].phase, 'idle')
  assert.equal(setDataCall[1].selectedTaskType, 'study')
  assert.equal(setDataCall[1].selectedTaskTypeLabel, 'label-study')
  assert.equal(setDataCall[1].isPaused, false)
  assert.equal(setDataCall[1].isFreeTimer, false)
  assert.equal(setDataCall[1].showEndConfirm, false)
  assert.ok(h.calls.some(c => c[0] === 'setCompletionBreakSec' && c[1] === null))
  assert.ok(h.calls.some(c => c[0] === 'updateComputedFields'))
})
