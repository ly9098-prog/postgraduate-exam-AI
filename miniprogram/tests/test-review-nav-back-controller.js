const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createNavBackController,
} = require('../subpackages/study/review-today/utils/nav-back-controller')

function createHarness(overrides = {}) {
  const state = {
    phase: 'overview',
    masterCleared: false,
    timerCleared: false,
    activityCleared: false,
    navigatedBack: false,
    reLaunched: false,
    pending: false,
    prompts: [],
    confirmResult: true,
    submitting: false,
    warnings: [],
  }
  const controller = createNavBackController({
    getPhase: () => state.phase,
    clearMasterUndo: () => { state.masterCleared = true },
    clearReviewTimer: () => { state.timerCleared = true },
    clearReviewActivity: () => { state.activityCleared = true },
    getCurrentPages: () => [1, 2],
    navigateBack: () => { state.navigatedBack = true },
    reLaunch: () => { state.reLaunched = true },
    isExitConfirmPending: () => state.pending,
    setExitConfirmPending: value => { state.pending = value },
    isSubmittingGroup: () => state.submitting,
    logWarn: (...args) => { state.warnings.push(args) },
    showConfirm: options => {
      state.prompts.push(options)
      return Promise.resolve(state.confirmResult)
    },
    ...overrides,
  })
  return { controller, state }
}

test('onNavBack shows the shared exit prompt in reviewing phase', async () => {
  const { controller, state } = createHarness()
  state.phase = 'reviewing'
  state.confirmResult = false
  await controller.onNavBack()

  assert.equal(state.prompts.length, 1)
  assert.equal(state.prompts[0].title, '退出本组复习？')
  assert.equal(state.prompts[0].layout, 'minimal')
  assert.equal(state.prompts[0].confirmText, '退出')
  assert.equal(state.prompts[0].cancelText, '继续复习')
  assert.equal(state.navigatedBack, false)
  assert.equal(state.activityCleared, false)
  assert.equal(state.pending, false)
})

test('onNavBack navigates back in non-reviewing phase', async () => {
  const { controller, state } = createHarness()
  await controller.onNavBack()

  assert.equal(state.prompts.length, 0)
  assert.equal(state.navigatedBack, true)
})

test('onNavBack reLaunches when only one page in stack', async () => {
  const { controller, state } = createHarness({ getCurrentPages: () => [1] })
  await controller.onNavBack()

  assert.equal(state.reLaunched, true)
  assert.equal(state.navigatedBack, false)
})

test('cancelled exit keeps review state untouched', async () => {
  const { controller, state } = createHarness()
  state.phase = 'reviewing'
  state.confirmResult = false
  await controller.onNavBack()

  assert.equal(state.prompts.length, 1)
  assert.equal(state.masterCleared, false)
  assert.equal(state.timerCleared, false)
  assert.equal(state.activityCleared, false)
  assert.equal(state.navigatedBack, false)
})

test('confirmed exit clears review state and navigates back', async () => {
  const { controller, state } = createHarness()
  state.phase = 'reviewing'
  await controller.onNavBack()

  assert.equal(state.masterCleared, true)
  assert.equal(state.timerCleared, true)
  assert.equal(state.activityCleared, true)
  assert.equal(state.navigatedBack, true)
})

test('repeated back while the exit prompt is open opens only one prompt', async () => {
  let resolvePrompt
  const { controller, state } = createHarness({
    showConfirm: options => {
      state.prompts.push(options)
      return new Promise(resolve => { resolvePrompt = resolve })
    },
  })
  state.phase = 'reviewing'

  const first = controller.onNavBack()
  await Promise.resolve()
  assert.equal(state.prompts.length, 1)
  assert.equal(state.pending, true)

  await controller.onNavBack()
  assert.equal(state.prompts.length, 1)

  resolvePrompt(false)
  await first
  assert.equal(state.pending, false)
  assert.equal(state.navigatedBack, false)
})

test('warns about a discarded result while a group submission is in flight', async () => {
  const { controller, state } = createHarness()
  state.phase = 'reviewing'
  state.submitting = true
  state.confirmResult = false
  await controller.onNavBack()

  assert.equal(state.prompts.length, 1)
  assert.equal(state.prompts[0].message, '本组提交仍在进行中，退出后本次提交结果将不再展示，确定退出吗？')
  assert.equal(state.prompts[0].cancelText, '继续等待')
})

test('a failing confirm dialog is logged and never navigates', async () => {
  const { controller, state } = createHarness({
    showConfirm: () => Promise.reject(new Error('dialog failed')),
  })
  state.phase = 'reviewing'
  await controller.onNavBack()

  assert.equal(state.warnings.length, 1)
  assert.equal(state.warnings[0][0], '退出确认弹窗异常')
  assert.equal(state.pending, false)
  assert.equal(state.navigatedBack, false)
  assert.equal(state.activityCleared, false)
})
