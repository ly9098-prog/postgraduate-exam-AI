const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamSubmitRetryController,
} = require('../subpackages/exam/utils/exam-submit-retry-controller')

function harness(overrides = {}) {
  const state = {
    pageAlive: true,
    terminalNavigation: false,
    posts: [],
    reconciliations: [],
    sleeps: [],
  }
  const options = {
    isPageAlive: () => state.pageAlive,
    isTerminalNavigation: () => state.terminalNavigation,
    getRetryDelays: () => [0, 450, 1200],
    sleep: async delay => { state.sleeps.push(delay) },
    postSubmit: async finalAnswers => {
      state.posts.push(finalAnswers)
      return { id: 12, status: 'submitted' }
    },
    reconcileAttemptState: async error => {
      state.reconciliations.push(error)
      return false
    },
    isRetryableSubmitError: error => {
      const status = Number(error && error.statusCode)
      return status === 0 || status >= 500
    },
    getPageClosedMessage: () => '页面已关闭',
    getSubmitFailedMessage: () => '交卷失败',
    ...overrides,
  }
  return { options, state, get controller() { return createExamSubmitRetryController(options) } }
}

test('returns the first successful submit response without retry', async () => {
  const h = harness()
  const result = await h.controller.postWithRetry([{ item_id: 101 }])

  assert.deepEqual(result, { id: 12, status: 'submitted' })
  assert.deepEqual(h.state.posts, [[{ item_id: 101 }]])
  assert.deepEqual(h.state.sleeps, [])
})

test('retries retryable failures with the configured delays', async () => {
  const h = harness()
  const failures = [new Error('server'), new Error('network')]
  failures[0].statusCode = 500
  failures[1].statusCode = 0
  h.options.postSubmit = async () => {
    h.state.posts.push([])
    const error = failures.shift()
    if (error) throw error
    return { status: 'submitted' }
  }
  h.options.reconcileAttemptState = async error => {
    h.state.reconciliations.push(error)
    return false
  }

  const result = await h.controller.postWithRetry([])

  assert.deepEqual(result, { status: 'submitted' })
  assert.deepEqual(h.state.sleeps, [450, 1200])
  assert.deepEqual(
    h.state.reconciliations.map(error => error && error.statusCode),
    [500, 0]
  )
})

test('reconciliation short-circuits to the reconciled marker', async () => {
  const h = harness()
  const failure = new Error('network')
  failure.statusCode = 0
  failure.statusCode = 0
  h.options.postSubmit = async () => { h.state.posts.push([]); throw failure }
  h.options.reconcileAttemptState = async error => {
    h.state.reconciliations.push({ statusCode: error && error.statusCode })
    return false
  }
  h.options.reconcileAttemptState = async error => {
    h.state.reconciliations.push(error)
    return true
  }

  const result = await h.controller.postWithRetry([])

  assert.deepEqual(result, { _reconciled: true })
  assert.equal(h.state.posts.length, 1)
  assert.deepEqual(h.state.sleeps, [])
})

test('does not retry non-retryable submit errors', async () => {
  const failure = new Error('bad request')
  failure.statusCode = 400
  const h = harness({ postSubmit: async () => { throw failure } })

  await assert.rejects(() => h.controller.postWithRetry([]), failure)
  assert.deepEqual(h.state.sleeps, [])
})

test('throws the last error after the final retry', async () => {
  const failure = new Error('network')
  failure.statusCode = 0
  const h = harness()
  h.options.postSubmit = async () => { h.state.posts.push([]); throw failure }
  h.options.reconcileAttemptState = async error => {
    h.state.reconciliations.push(error)
    return false
  }

  await assert.rejects(() => h.controller.postWithRetry([]), failure)
  assert.equal(h.state.posts.length, 3)
  assert.deepEqual(h.state.sleeps, [450, 1200])
})

test('stops before posting when the page is closed or already navigating', async () => {
  const closed = harness()
  closed.state.pageAlive = false
  await assert.rejects(
    () => closed.controller.postWithRetry([]),
    /页面已关闭/
  )
  assert.deepEqual(closed.state.posts, [])

  const navigating = harness()
  navigating.state.terminalNavigation = true
  await assert.rejects(
    () => navigating.controller.postWithRetry([]),
    /页面已关闭/
  )
  assert.deepEqual(navigating.state.posts, [])
})

test('throws the captured error when the page closes during a retry', async () => {
  const failure = new Error('network')
  failure.statusCode = 0
  const h = harness()
  h.options.postSubmit = async () => { h.state.posts.push([]); throw failure }
  h.options.reconcileAttemptState = async error => {
    h.state.reconciliations.push(error)
    return false
  }
  h.options.sleep = async delay => { h.state.sleeps.push(delay); h.state.pageAlive = false }

  await assert.rejects(() => h.controller.postWithRetry([]), failure)
  assert.deepEqual(h.state.sleeps, [450])
})
