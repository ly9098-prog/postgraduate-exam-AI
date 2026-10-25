const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPausedConfirmController,
} = require('../subpackages/study/practice/utils/paused-confirm-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    started: true,
    submitted: false,
    submitting: false,
    session: {
      backgroundMs: 10,
      _timingPauseActive: false,
      currentQuestionStartedMonoMs: 100,
      submissionSnapshot: null,
    },
    now: 1000,
    showNow: 1020,
    prompts: [],
    settled: [],
    timerCleared: 0,
    timerStarted: 0,
  }
  const controller = createPausedConfirmController({
    getSession: () => state.getSession ? state.getSession() : state.session,
    monotonicNow: () => state.now,
    settleQuestionTime: pause => state.settled.push(pause),
    clearTimer: () => { state.timerCleared += 1 },
    showConfirm: async options => {
      state.prompts.push(options)
      if (state.beforeResolve) state.beforeResolve()
      state.now = state.showNow
      return state.confirmResult
    },
    isPageAlive: () => state.alive,
    isStarted: () => state.started,
    isSubmitted: () => state.submitted,
    isSubmitting: () => state.submitting,
    startTimer: () => { state.timerStarted += 1 },
    ...overrides,
  })
  return { controller, state }
}

test('pauses timing before the prompt and resumes only after cancellation', async () => {
  const { controller, state } = createHarness()
  state.confirmResult = false
  state.showNow = 1020

  assert.equal(await controller.show({ title: '退出练习？' }), false)

  assert.deepEqual(state.settled, [true])
  assert.equal(state.timerCleared, 1)
  assert.deepEqual(state.prompts, [{ title: '退出练习？' }])
  assert.equal(state.session.backgroundMs, 30)
  assert.equal(state.session._timingPauseActive, false)
  assert.equal(state.session.currentQuestionStartedMonoMs, 1020)
  assert.equal(state.timerStarted, 1)
})

test('confirmed prompts leave the timer stopped', async () => {
  const { controller, state } = createHarness()
  state.confirmResult = true
  state.showNow = 1020

  assert.equal(await controller.show({ title: '确认交卷？' }), true)

  assert.equal(state.session.backgroundMs, 30)
  assert.equal(state.session.currentQuestionStartedMonoMs, 100)
  assert.equal(state.timerStarted, 0)
})

test('restores pause accounting even when the prompt fails', async () => {
  const { controller, state } = createHarness({
    showConfirm: async () => {
      state.now = state.showNow
      throw new Error('prompt failed')
    },
  })
  state.showNow = 1020

  await assert.rejects(() => controller.show({}), /prompt failed/)

  assert.equal(state.session.backgroundMs, 30)
  assert.equal(state.session._timingPauseActive, false)
  assert.equal(state.timerStarted, 0)
})

test('does not restart after cancellation when page or practice state is no longer active', async () => {
  const cases = [
    { key: 'dead', update: state => { state.alive = false } },
    { key: 'new-session', update: state => { state.getSession = () => ({ ...state.session }) } },
    { key: 'not-started', update: state => { state.started = false } },
    { key: 'submitted', update: state => { state.submitted = true } },
    { key: 'submitting', update: state => { state.submitting = true } },
    { key: 'pending-submission', update: state => { state.session.submissionSnapshot = {} } },
  ]

  for (const item of cases) {
    const { controller, state } = createHarness()
    state.confirmResult = false
    item.update(state)
    await controller.show({})
    assert.equal(state.timerStarted, 0, item.key)
  }
})

test('does not restart when page or session state changes while the prompt is pending', async () => {
  const { controller, state } = createHarness()
  state.confirmResult = false
  state.showNow = 1020
  state.beforeResolve = () => {
    state.alive = false
    state.getSession = () => ({ ...state.session, submissionSnapshot: {} })
    state.now = state.showNow
  }

  assert.equal(await controller.show({}), false)

  assert.equal(state.timerStarted, 0)
  assert.equal(state.session.backgroundMs, 30)
  assert.equal(state.session.currentQuestionStartedMonoMs, 100)
})

test('supports a missing session without restarting timing', async () => {
  const { controller, state } = createHarness({ getSession: () => null })
  state.confirmResult = false

  assert.equal(await controller.show({}), false)

  assert.deepEqual(state.settled, [true])
  assert.equal(state.timerCleared, 1)
  assert.equal(state.timerStarted, 0)
})
