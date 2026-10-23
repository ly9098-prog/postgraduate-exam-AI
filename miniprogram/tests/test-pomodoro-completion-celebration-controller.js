const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCompletionCelebrationController,
} = require('../pages/pomodoro/utils/completion-celebration-controller')

function createHarness(overrides = {}) {
  const calls = {
    removes: [], sets: [], setData: [], recordSession: [], canvasInvalidates: 0,
  }
  const options = {
    buildCompletionCelebration: (id, opts, ctx) => overrides.celebration || {
      completionFlag: { sessionId: id },
      viewData: { showCelebration: true },
      breakSec: 300,
      sessionId: id,
      selectedTaskType: opts && opts.selectedTaskType,
    },
    data: () => overrides.view || {},
    mottoes: [],
    nextCelebrationType: () => 'excellent',
    recordSession: (session, taskType) => { calls.recordSession.push([session, taskType]) },
    removeStorage: (key, context) => { calls.removes.push([key, context]) },
    setStorage: (key, value, context) => { calls.sets.push([key, value, context]) },
    clearConfirmSnapshot: () => { calls.clearConfirmSnapshot = true },
    timer: () => ({ endConfirmMode: 'x' }),
    setCompletionBreakSec: value => { calls.breakSec = value },
    invalidateCanvas: () => { calls.canvasInvalidates += 1 },
    setData: data => calls.setData.push(data),
  }
  return { controller: createCompletionCelebrationController(options), calls }
}

test('show builds the celebration, persists the marker and invalidates canvas', () => {
  const harness = createHarness()
  harness.controller.show(42, {})

  assert.deepEqual(harness.calls.removes, [
    ['pomodoro_running_state', 'best-effort cleanup'],
    ['pomodoro_pause', 'best-effort cleanup'],
    ['pomodoro_free_pause', 'best-effort cleanup'],
    ['pomodoro_confirm_pause', 'best-effort cleanup'],
    ['pomodoro_pause_adjustment', 'best-effort cleanup'],
  ])
  assert.deepEqual(harness.calls.sets, [['pomodoro_completion', { sessionId: 42 }, 'completion marker']])
  assert.equal(harness.calls.breakSec, 300)
  assert.equal(harness.calls.canvasInvalidates, 1)
  assert.deepEqual(harness.calls.setData, [{ showCelebration: true }])
  assert.equal(harness.calls.clearConfirmSnapshot, true)
})

test('show records the task type when the celebration has one', () => {
  const harness = createHarness({
    celebration: {
      completionFlag: { sessionId: 7 },
      viewData: {},
      breakSec: 0,
      sessionId: 7,
      selectedTaskType: 'exam',
    },
  })
  harness.controller.show(7, {})
  assert.deepEqual(harness.calls.recordSession, [[{ id: 7 }, 'exam']])
})

test('show does not record when there is no selectedTaskType', () => {
  const harness = createHarness({
    celebration: {
      completionFlag: { sessionId: 8 },
      viewData: {},
      breakSec: 0,
      sessionId: 8,
    },
  })
  harness.controller.show(8, {})
  assert.deepEqual(harness.calls.recordSession, [])
})
