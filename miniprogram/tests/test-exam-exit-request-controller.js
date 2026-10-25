const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamExitRequestController,
} = require('../subpackages/exam/utils/exam-exit-request-controller')

function createHarness(overrides = {}) {
  const state = {
    submitting: false,
    navigationLocked: false,
    settles: [],
    navigations: [],
    dialogShown: false,
    confirmed: true,
  }
  const controller = createExamExitRequestController({
    isSubmitting: () => state.submitting,
    isNavigationLocked: () => state.navigationLocked,
    settleCurrentTime: () => {
      state.settles.push(undefined)
      return Promise.resolve()
    },
    showExitDialog: () => {
      state.dialogShown = true
      return Promise.resolve(state.confirmed)
    },
    navigateBack: options => {
      state.navigations.push(options)
    },
    ...overrides,
  })
  return { controller, state }
}

test('confirmed exit settles the draft and navigates back one page', async () => {
  const { controller, state } = createHarness()

  assert.equal(await controller.request(), undefined)

  assert.deepEqual(state.settles, [undefined])
  assert.equal(state.dialogShown, true)
  assert.deepEqual(state.navigations, [{ delta: 1 }])
})

test('cancelled exit keeps the user on the exam page', async () => {
  const { controller, state } = createHarness()
  state.confirmed = false

  assert.equal(await controller.request(), undefined)

  assert.deepEqual(state.settles, [undefined])
  assert.equal(state.dialogShown, true)
  assert.deepEqual(state.navigations, [])
})

test('submitting and navigation-locked attempts do not show the dialog', async () => {
  for (const patch of [{ submitting: true }, { navigationLocked: true }]) {
    const { controller, state } = createHarness()
    Object.assign(state, patch)
    assert.equal(await controller.request(), undefined)
    assert.deepEqual(state.settles, [])
    assert.equal(state.dialogShown, false)
    assert.deepEqual(state.navigations, [])
  }
})

test('draft save failure does not block confirmation', async () => {
  const settleCurrentTime = () => Promise.reject(new Error('draft save failed'))
  const { controller, state } = createHarness({ settleCurrentTime })

  assert.equal(await controller.request(), undefined)

  assert.equal(state.dialogShown, true)
  assert.deepEqual(state.navigations, [{ delta: 1 }])
})
