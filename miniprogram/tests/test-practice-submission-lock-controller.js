const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubmissionLockController,
} = require('../subpackages/study/practice/utils/submission-lock-controller')

function createHarness(overrides = {}) {
  const state = {
    submission: null,
    toasts: [],
  }
  const controller = createSubmissionLockController({
    getSubmissionSnapshot: () => state.submission,
    showToast: options => state.toasts.push(options),
    ...overrides,
  })
  return { controller, state }
}

test('returns false without a submission snapshot and does not toast', () => {
  const { controller, state } = createHarness()

  assert.equal(controller.isLocked(), false)
  assert.deepEqual(state.toasts, [])
})

test('reports an accepted submission', () => {
  const { controller, state } = createHarness()
  state.submission = { serverAccepted: true }

  assert.equal(controller.isLocked(), true)
  assert.deepEqual(state.toasts, [{
    title: '本次已交卷，请查看结果',
    icon: 'none',
  }])
})

test('reports a rejected submission before the generic locked state', () => {
  const { controller, state } = createHarness()
  state.submission = { retryBlocked: true }

  assert.equal(controller.isLocked(), true)
  assert.deepEqual(state.toasts, [{
    title: '提交已被拒绝，请退出后重试',
    icon: 'none',
  }])
})

test('reports a pending submission as locked', () => {
  const { controller, state } = createHarness()
  state.submission = {}

  assert.equal(controller.isLocked(), true)
  assert.deepEqual(state.toasts, [{
    title: '交卷内容已锁定，请确认提交',
    icon: 'none',
  }])
})
