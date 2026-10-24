const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamSubmitOutcomeController,
} = require('../subpackages/exam/utils/exam-submit-outcome-controller')

function harness(overrides = {}) {
  const state = {
    pageAlive: true,
    cleared: 0,
    attemptTerminal: false,
    reconciled: false,
    resultNavigations: 0,
    submitting: true,
    autoPendingShown: 0,
    manualErrors: [],
  }
  const options = {
    isPageAlive: () => state.pageAlive,
    clearPending: () => { state.cleared += 1 },
    setAttemptTerminal: value => { state.attemptTerminal = value },
    navigateReconciled: () => { state.reconciled = true },
    navigateToResult: () => { state.resultNavigations += 1 },
    reconcileAttemptState: async () => false,
    setSubmitting: value => { state.submitting = value },
    showAutoSubmitPending: () => { state.autoPendingShown += 1 },
    showManualSubmitError: error => { state.manualErrors.push(error) },
    ...overrides,
  }
  return { options, state, get controller() { return createExamSubmitOutcomeController(options) } }
}

test('successful direct submission clears pending and navigates to result', () => {
  const h = harness()
  h.controller.applySuccess({ status: 'submitted' })

  assert.equal(h.state.cleared, 1)
  assert.equal(h.state.attemptTerminal, true)
  assert.equal(h.state.resultNavigations, 1)
  assert.equal(h.state.reconciled, false)
})

test('reconciled submission keeps pending cleanup to reconciliation owner', () => {
  const h = harness()
  h.controller.applySuccess({ _reconciled: true })

  assert.equal(h.state.cleared, 0)
  assert.equal(h.state.attemptTerminal, true)
  assert.equal(h.state.reconciled, true)
  assert.equal(h.state.resultNavigations, 0)
})

test('failure reconciliation marks terminal and delegates navigation', async () => {
  const h = harness({ reconcileAttemptState: async () => true })
  const result = await h.controller.applyFailure(new Error('network'), true)

  assert.equal(result, undefined)
  assert.equal(h.state.attemptTerminal, true)
  assert.equal(h.state.reconciled, true)
  assert.equal(h.state.submitting, true)
  assert.equal(h.state.autoPendingShown, 0)
})

test('closed page failure returns false without UI side effects', async () => {
  const h = harness()
  h.state.pageAlive = false
  const result = await h.controller.applyFailure(new Error('network'), true)

  assert.equal(result, false)
  assert.equal(h.state.attemptTerminal, false)
  assert.equal(h.state.submitting, true)
  assert.equal(h.state.autoPendingShown, 0)
})

test('auto failure restores input and shows pending auto-submit state', async () => {
  const h = harness()
  const result = await h.controller.applyFailure(new Error('network'), true)

  assert.equal(result, false)
  assert.equal(h.state.submitting, false)
  assert.equal(h.state.autoPendingShown, 1)
  assert.deepEqual(h.state.manualErrors, [])
})

test('manual failure restores input and delegates error presentation', async () => {
  const failure = new Error('server')
  const h = harness()
  const result = await h.controller.applyFailure(failure, false)

  assert.equal(result, false)
  assert.equal(h.state.submitting, false)
  assert.equal(h.state.autoPendingShown, 0)
  assert.deepEqual(h.state.manualErrors, [failure])
})
