const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamSubmitEntryController,
} = require('../subpackages/exam/utils/exam-submit-entry-controller')

function createHarness(overrides = {}) {
  const state = {
    attemptTerminal: false,
    navigationLocked: false,
    submitPromise: null,
    submitting: false,
    timeExpired: false,
    confirmingSubmit: false,
    dialogs: [],
    performed: [],
  }
  const controller = createExamSubmitEntryController({
    isAttemptTerminal: () => state.attemptTerminal,
    isNavigationLocked: () => state.navigationLocked,
    getSubmitPromise: () => state.submitPromise,
    isSubmitting: () => state.submitting,
    isTimeExpired: () => state.timeExpired,
    isConfirmingSubmit: () => state.confirmingSubmit,
    setConfirmingSubmit: value => { state.confirmingSubmit = value },
    showConfirmDialog: dialog => {
      state.dialogs.push(dialog)
      return Promise.resolve(true)
    },
    buildConfirmDialog: () => ({
      scenario: 'unanswered',
      title: '确认交卷',
      message: '还有 1 题未作答。\n交卷后不可修改。',
      confirmText: '确认交卷',
      cancelText: '继续检查',
      hideEyebrow: true,
    }),
    performSubmit: auto => {
      state.performed.push(auto)
      return Promise.resolve('submitted')
    },
    setSubmitPromise: task => { state.submitPromise = task },
    clearSubmitPromise: task => {
      if (state.submitPromise === task) state.submitPromise = null
    },
    ...overrides,
  })
  return { controller, state }
}

test('manual submission confirms, performs once, and clears the single-flight task', async () => {
  const { controller, state } = createHarness()

  assert.equal(await controller.request(), 'submitted')

  assert.equal(state.confirmingSubmit, false)
  assert.deepEqual(state.dialogs, [{
    scenario: 'unanswered',
    title: '确认交卷',
    message: '还有 1 题未作答。\n交卷后不可修改。',
    confirmText: '确认交卷',
    cancelText: '继续检查',
    hideEyebrow: true,
  }])
  assert.deepEqual(state.performed, [false])
  assert.equal(state.submitPromise, null)
})

test('auto submission skips the confirmation dialog', async () => {
  const { controller, state } = createHarness()

  assert.equal(await controller.request({ auto: true }), 'submitted')

  assert.deepEqual(state.dialogs, [])
  assert.deepEqual(state.performed, [true])
})

test('expired attempts submit automatically without confirmation', async () => {
  const { controller, state } = createHarness()
  state.timeExpired = true

  assert.equal(await controller.request(), 'submitted')

  assert.deepEqual(state.dialogs, [])
  assert.deepEqual(state.performed, [true])
})

test('terminal and locked attempts never perform submission', async () => {
  for (const patch of [{ attemptTerminal: true }, { navigationLocked: true }]) {
    const { controller, state } = createHarness()
    Object.assign(state, patch)
    assert.equal(await controller.request(), false)
    assert.deepEqual(state.dialogs, [])
    assert.deepEqual(state.performed, [])
  }
})

test('an existing single-flight task is returned without another dialog or task', async () => {
  const existing = Promise.resolve('existing')
  const { controller, state } = createHarness({ getSubmitPromise: () => existing })

  assert.equal(await controller.request(), 'existing')

  assert.deepEqual(state.dialogs, [])
  assert.deepEqual(state.performed, [])
})

test('a running submission or confirmation blocks a second manual request', async () => {
  const submitting = createHarness()
  submitting.state.submitting = true
  assert.equal(await submitting.controller.request(), undefined)
  assert.deepEqual(submitting.state.performed, [])

  const confirming = createHarness()
  confirming.state.confirmingSubmit = true
  assert.equal(await confirming.controller.request(), undefined)
  assert.deepEqual(confirming.state.dialogs, [])
  assert.deepEqual(confirming.state.performed, [])
})

test('cancel keeps the attempt active and clears the confirming flag', async () => {
  const { controller, state } = createHarness({
    showConfirmDialog: () => Promise.resolve(false),
  })

  assert.equal(await controller.request(), undefined)

  assert.equal(state.confirmingSubmit, false)
  assert.deepEqual(state.performed, [])
  assert.equal(state.submitPromise, null)
})

test('state that becomes terminal during confirmation rejects a second task', async () => {
  const { controller, state } = createHarness({
    showConfirmDialog: () => {
      state.attemptTerminal = true
      return Promise.resolve(true)
    },
  })

  assert.equal(await controller.request(), false)

  assert.equal(state.confirmingSubmit, false)
  assert.deepEqual(state.performed, [])
  assert.equal(state.submitPromise, null)
})

test('an auto task started during confirmation becomes the returned single-flight task', async () => {
  const autoTask = Promise.resolve('auto-started')
  const showConfirmDialog = () => {
    autoHarness.state.submitPromise = autoTask
    return Promise.resolve(true)
  }
  const autoHarness = createHarness({ showConfirmDialog })

  assert.equal(await autoHarness.controller.request(), 'auto-started')

  assert.equal(autoHarness.state.dialogs.length, 0)
  assert.deepEqual(autoHarness.state.performed, [])
  assert.equal(autoHarness.state.submitPromise, autoTask)
})

test('submission failures clear only the matching single-flight task', async () => {
  const { controller, state } = createHarness({
    performSubmit: () => Promise.reject(new Error('submit failed')),
  })

  await assert.rejects(controller.request(), /submit failed/)

  assert.equal(state.submitPromise, null)
})
