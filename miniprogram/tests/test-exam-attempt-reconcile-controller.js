const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamAttemptReconcileController,
} = require('../subpackages/exam/utils/exam-attempt-reconcile-controller')

function harness(overrides = {}) {
  const state = {
    pageAlive: true,
    cleared: 0,
    attemptTerminal: false,
    attemptAbandoned: false,
    abandonedNavigations: 0,
    terminalNavigations: 0,
  }
  const options = {
    isPageAlive: () => state.pageAlive,
    getAttempt: async () => ({ status: 'in_progress' }),
    clearPending: () => { state.cleared += 1 },
    setAttemptTerminal: value => { state.attemptTerminal = value },
    setAttemptAbandoned: value => { state.attemptAbandoned = value },
    onAbandoned: () => { state.abandonedNavigations += 1 },
    onTerminal: () => { state.terminalNavigations += 1 },
    ...overrides,
  }
  return { options, state, get controller() { return createExamAttemptReconcileController(options) } }
}

test('keeps in-progress attempts active', async () => {
  const h = harness()
  assert.equal(await h.controller.reconcile(), false)
  assert.equal(h.state.cleared, 0)
  assert.equal(h.state.attemptTerminal, false)
})

test('clears and marks abandoned attempts', async () => {
  const h = harness({ getAttempt: async () => ({ status: 'abandoned' }) })
  assert.equal(await h.controller.reconcile(), true)
  assert.equal(h.state.cleared, 1)
  assert.equal(h.state.attemptTerminal, true)
  assert.equal(h.state.attemptAbandoned, true)
  assert.equal(h.state.abandonedNavigations, 1)
  assert.equal(h.state.terminalNavigations, 0)
})

test('clears and marks submitted attempts terminal', async () => {
  const h = harness({ getAttempt: async () => ({ status: 'submitted' }) })
  assert.equal(await h.controller.reconcile(), true)
  assert.equal(h.state.cleared, 1)
  assert.equal(h.state.attemptTerminal, true)
  assert.equal(h.state.attemptAbandoned, false)
  assert.equal(h.state.terminalNavigations, 1)
  assert.equal(h.state.abandonedNavigations, 0)
})

test('clears and marks expired attempts terminal', async () => {
  const h = harness({ getAttempt: async () => ({ status: 'expired' }) })
  assert.equal(await h.controller.reconcile(), true)
  assert.equal(h.state.attemptTerminal, true)
  assert.equal(h.state.attemptAbandoned, false)
  assert.equal(h.state.terminalNavigations, 1)
})

test('ignores unknown statuses without side effects', async () => {
  const h = harness({ getAttempt: async () => ({ status: 'unknown' }) })
  assert.equal(await h.controller.reconcile(), false)
  assert.equal(h.state.cleared, 0)
  assert.equal(h.state.attemptTerminal, false)
  assert.equal(h.state.terminalNavigations, 0)
})

test('does not fetch when the page is closed', async () => {
  let fetched = false
  const h = harness({
    getAttempt: async () => { fetched = true; return { status: 'submitted' } },
  })
  h.state.pageAlive = false
  assert.equal(await h.controller.reconcile(), false)
  assert.equal(fetched, false)
})

test('fetch failures resolve false without state mutation', async () => {
  const h = harness({ getAttempt: async () => { throw new Error('network') } })
  assert.equal(await h.controller.reconcile(), false)
  assert.equal(h.state.cleared, 0)
  assert.equal(h.state.attemptTerminal, false)
  assert.equal(h.state.terminalNavigations, 0)
})
