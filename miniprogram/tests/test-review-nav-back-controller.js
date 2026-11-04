const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createNavBackController,
} = require('../subpackages/study/review-today/utils/nav-back-controller')

function createHarness(overrides = {}) {
  const state = {
    phase: 'overview',
    patches: [],
    masterCleared: false,
    timerCleared: false,
    activityCleared: false,
    navigatedBack: false,
    reLaunched: false,
  }
  const controller = createNavBackController({
    getPhase: () => state.phase,
    setData: patch => { state.patches.push(patch) },
    clearMasterUndo: () => { state.masterCleared = true },
    clearReviewTimer: () => { state.timerCleared = true },
    clearReviewActivity: () => { state.activityCleared = true },
    getCurrentPages: () => [1, 2],
    navigateBack: () => { state.navigatedBack = true },
    reLaunch: () => { state.reLaunched = true },
    ...overrides,
  })
  return { controller, state }
}

test('onNavBack shows exit confirm in reviewing phase', () => {
  const { controller, state } = createHarness()
  state.phase = 'reviewing'
  controller.onNavBack()

  assert.deepEqual(state.patches[0], { exitConfirmVisible: true })
  assert.equal(state.navigatedBack, false)
  assert.equal(state.activityCleared, false)
})

test('onNavBack navigates back in non-reviewing phase', () => {
  const { controller, state } = createHarness()
  controller.onNavBack()

  assert.equal(state.navigatedBack, true)
})

test('onNavBack reLaunches when only one page in stack', () => {
  const { controller, state } = createHarness()
  const c = createNavBackController({
    getPhase: () => 'overview',
    setData: () => {},
    clearMasterUndo: () => {},
    clearReviewTimer: () => {},
    getCurrentPages: () => [1],
    navigateBack: () => { state.navigatedBack = true },
    reLaunch: () => { state.reLaunched = true },
  })
  c.onNavBack()

  assert.equal(state.reLaunched, true)
  assert.equal(state.navigatedBack, false)
})

test('closeExitConfirm hides confirm', () => {
  const { controller, state } = createHarness()
  controller.closeExitConfirm()

  assert.deepEqual(state.patches[0], { exitConfirmVisible: false })
  assert.equal(state.activityCleared, false)
})

test('confirmExitReview clears state and navigates back', () => {
  const { controller, state } = createHarness()
  controller.confirmExitReview()

  assert.equal(state.masterCleared, true)
  assert.equal(state.timerCleared, true)
  assert.equal(state.activityCleared, true)
  assert.equal(state.navigatedBack, true)
})
