const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExitRequestController,
} = require('../subpackages/study/practice/utils/exit-request-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    exitInFlight: false,
    submitting: false,
    submitted: false,
    pendingResultUrl: '',
    submission: null,
    prompts: [],
    pausedPrompts: [],
    openedResults: [],
    guards: [],
    clearedPending: [],
    requestSeq: 0,
    timerCleared: false,
    feedbackTimer: { id: 1 },
    resetCount: 0,
    scrollCount: 0,
  }
  const controller = createExitRequestController({
    isExitConfirmInFlight: () => state.exitInFlight,
    setExitConfirmInFlight: value => { state.exitInFlight = value },
    isSubmitting: () => state.submitting,
    isSubmitted: () => state.submitted,
    getPendingResultUrl: () => state.pendingResultUrl,
    getSubmissionSnapshot: () => state.submission,
    showConfirm: async options => { state.prompts.push(options); return state.confirmResult },
    showPausedConfirm: async options => { state.pausedPrompts.push(options); return state.pausedResult },
    openSubmittedResult: (resultUrl, submission) => state.openedResults.push({ resultUrl, submission }),
    isPageAlive: () => state.alive,
    clearPendingSubmission: requestId => state.clearedPending.push(requestId),
    setUnloadGuard: enabled => state.guards.push(enabled),
    incrementQuestionRequestSeq: () => { state.requestSeq += 1 },
    clearTimer: () => { state.timerCleared = true },
    clearFeedbackTimer: () => { state.feedbackTimer = null },
    resetPracticeState: () => { state.resetCount += 1 },
    scrollToSetupTop: () => { state.scrollCount += 1 },
    setLastExitSource: value => { state.lastExitSource = value },
    ...overrides,
  })
  return { controller, state }
}

test('returns immediately while another exit confirmation is in flight', async () => {
  const { controller, state } = createHarness()
  state.exitInFlight = true

  await controller.request()

  assert.deepEqual(state.prompts, [])
  assert.deepEqual(state.pausedPrompts, [])
})

test('shows a locked submitting prompt and restores the in-flight flag', async () => {
  const { controller, state } = createHarness()
  state.submitting = true

  await controller.request()

  assert.deepEqual(state.prompts, [{
    scenario: 'info',
    title: '正在交卷',
    message: '提交完成前请保持当前页面。',
    confirmText: '知道了',
    hideCancel: true,
    hideEyebrow: true,
  }])
  assert.equal(state.exitInFlight, false)
  assert.equal(state.resetCount, 0)
})

test('restores the in-flight flag when the submitting prompt fails', async () => {
  const { controller, state } = createHarness({
    showConfirm: async () => { throw new Error('prompt failed') },
  })
  state.submitting = true

  await assert.rejects(() => controller.request(), /prompt failed/)

  assert.equal(state.exitInFlight, false)
})

test('restores the in-flight flag when the main confirmation prompt fails', async () => {
  const { controller, state } = createHarness({
    showPausedConfirm: async () => { throw new Error('paused prompt failed') },
  })

  await assert.rejects(() => controller.request(), /paused prompt failed/)

  assert.equal(state.exitInFlight, false)
  assert.equal(state.resetCount, 0)
})

test('reopens an already submitted result without prompting', async () => {
  const { controller, state } = createHarness()
  state.submitted = true
  state.pendingResultUrl = '/result?x=1'
  state.submission = { requestId: 'req-1' }

  await controller.request()

  assert.deepEqual(state.openedResults, [{
    resultUrl: '/result?x=1',
    submission: { requestId: 'req-1' },
  }])
  assert.deepEqual(state.prompts, [])
  assert.deepEqual(state.pausedPrompts, [])
})

test('prompts through the paused dialog for an unsubmitted practice', async () => {
  const { controller, state } = createHarness()
  state.pausedResult = false

  await controller.request()

  assert.deepEqual(state.pausedPrompts, [{
    scenario: 'info',
    layout: 'minimal',
    title: '退出练习？',
    message: '本组练习尚未提交，确定退出吗？',
    confirmText: '退出',
    cancelText: '继续作答',
    hideEyebrow: true,
  }])
  assert.equal(state.exitInFlight, false)
  assert.equal(state.resetCount, 0)
})

test('prompts through the standard dialog for a pending submission', async () => {
  const { controller, state } = createHarness()
  state.submission = { requestId: 'pending' }
  state.confirmResult = false

  await controller.request()

  assert.deepEqual(state.prompts, [{
    scenario: 'info',
    layout: 'minimal',
    title: '退出练习？',
    message: '交卷仍在确认中，退出后可下次继续确认。',
    confirmText: '退出',
    cancelText: '继续确认',
    hideEyebrow: true,
  }])
  assert.equal(state.resetCount, 0)
})

test('uses retry-blocked copy and clears pending storage after confirmation', async () => {
  const { controller, state } = createHarness()
  state.submission = { requestId: 'blocked', retryBlocked: true }
  state.confirmResult = true

  await controller.request()

  assert.equal(state.prompts[0].message, '本次提交未通过，退出后可重新开始。')
  assert.equal(state.prompts[0].cancelText, '继续作答')
  assert.deepEqual(state.clearedPending, ['blocked'])
  assert.deepEqual(state.guards, [false])
  assert.equal(state.requestSeq, 1)
  assert.equal(state.timerCleared, true)
  assert.equal(state.feedbackTimer, null)
  assert.equal(state.resetCount, 1)
  assert.equal(state.scrollCount, 1)
})

test('confirms a normal pending submission without clearing persistent cache', async () => {
  const { controller, state } = createHarness()
  state.submission = { requestId: 'pending' }
  state.confirmResult = true

  await controller.request()

  assert.deepEqual(state.clearedPending, [])
  assert.deepEqual(state.guards, [false])
  assert.equal(state.requestSeq, 1)
  assert.equal(state.timerCleared, true)
  assert.equal(state.feedbackTimer, null)
  assert.equal(state.resetCount, 1)
  assert.equal(state.scrollCount, 1)
})

test('does not reset after cancellation or page death', async () => {
  const cancelled = createHarness()
  cancelled.state.pausedResult = false
  await cancelled.controller.request()
  assert.equal(cancelled.state.resetCount, 0)
  assert.equal(cancelled.state.guards.length, 0)
  assert.equal(cancelled.state.requestSeq, 0)
  assert.equal(cancelled.state.timerCleared, false)
  assert.equal(cancelled.state.scrollCount, 0)

  const dead = createHarness()
  dead.state.pausedResult = true
  dead.state.alive = false
  await dead.controller.request()
  assert.equal(dead.state.resetCount, 0)
  assert.equal(dead.state.guards.length, 0)
  assert.equal(dead.state.requestSeq, 0)
  assert.equal(dead.state.timerCleared, false)
  assert.equal(dead.state.scrollCount, 0)
  assert.deepEqual(dead.state.clearedPending, [])
})

test('keeps the exit source available for future diagnostics', async () => {
  const { controller, state } = createHarness()
  state.pausedResult = false

  await controller.request({ source: 'system-back' })

  assert.equal(state.lastExitSource, 'system-back')
  assert.deepEqual(state.pausedPrompts, [{
    scenario: 'info',
    layout: 'minimal',
    title: '退出练习？',
    message: '本组练习尚未提交，确定退出吗？',
    confirmText: '退出',
    cancelText: '继续作答',
    hideEyebrow: true,
  }])
})
