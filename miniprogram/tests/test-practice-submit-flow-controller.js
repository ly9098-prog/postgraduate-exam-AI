const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubmitFlowController,
} = require('../subpackages/study/practice/utils/submit-flow-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    submitting: false,
    submitted: false,
    pendingResultUrl: '',
    submission: null,
    questions: [{ id: 1 }],
    traceId: 'trace-page',
    views: [],
    confirms: [],
    prepared: [],
    persisted: [],
    requests: [],
    errors: [],
    completed: [],
    opened: [],
    timerCleared: 0,
  }
  const controller = createSubmitFlowController({
    isSubmitting: () => state.submitting,
    getSubmissionSnapshot: () => state.submission,
    isSubmitted: () => state.submitted,
    getPendingResultUrl: () => state.pendingResultUrl,
    openSubmittedResult: (resultUrl, submission) => state.opened.push({ resultUrl, submission }),
    showConfirm: async options => state.confirms.push(options),
    getQuestions: () => state.questions,
    prepareSubmission: async skipConfirm => {
      state.prepared.push(skipConfirm)
      return state.preparedSubmission
    },
    clearTimer: () => { state.timerCleared += 1 },
    persistPendingSubmission: (submission, status, resultUrl) => {
      state.persisted.push({ submission, status, resultUrl })
      return state.persistResult
    },
    setData: patch => state.views.push(patch),
    buildSubmitPayload: (submission, traceId) => ({ submission, traceId }),
    getTraceId: () => state.traceId,
    requestSubmit: async payload => {
      state.requests.push(payload)
      if (state.requestError) throw state.requestError
      return state.submitResult
    },
    isPageAlive: () => state.alive,
    handleSubmitError: async (submission, error) => state.errors.push({ submission, error }),
    completeSubmit: (submission, submitResult, questions) => state.completed.push({
      submission,
      submitResult,
      questions,
    }),
    ...overrides,
  })
  return { controller, state }
}

test('returns while a submission is already in progress', async () => {
  const { controller, state } = createHarness()
  state.submitting = true

  await controller.submit(false)

  assert.deepEqual(state.views, [])
  assert.deepEqual(state.requests, [])
})

test('reopens an already submitted result', async () => {
  const { controller, state } = createHarness()
  state.submitted = true
  state.pendingResultUrl = '/result'
  state.submission = { requestId: 'req' }

  await controller.submit(false)

  assert.deepEqual(state.opened, [{ resultUrl: '/result', submission: state.submission }])
  assert.deepEqual(state.requests, [])
})

test('blocks a retry-blocked submission with the exact prompt', async () => {
  const { controller, state } = createHarness()
  state.submission = { retryBlocked: true }

  await controller.submit(false)

  assert.deepEqual(state.confirms, [{
    scenario: 'danger',
    title: '本次提交无法继续重试',
    message: '请退出本组练习后重新开始。',
    showCancel: false,
    confirmText: '知道了',
    hideEyebrow: true,
  }])
  assert.deepEqual(state.requests, [])
})

test('prepares a new submission and completes a successful request', async () => {
  const { controller, state } = createHarness()
  state.preparedSubmission = { requestId: 'new' }
  state.submitResult = { id: 'server' }

  await controller.submit(true)

  assert.deepEqual(state.prepared, [true])
  assert.deepEqual(state.views, [{ submitting: true }])
  assert.deepEqual(state.requests, [{
    submission: { requestId: 'new' },
    traceId: 'trace-page',
  }])
  assert.deepEqual(state.completed, [{
    submission: { requestId: 'new' },
    submitResult: state.submitResult,
    questions: state.questions,
  }])
})

test('repersists an existing pending submission before retrying', async () => {
  const { controller, state } = createHarness()
  state.submission = { requestId: 'pending', pendingPersisted: false }
  state.persistResult = true
  state.submitResult = { id: 'server' }

  await controller.submit(false)

  assert.equal(state.timerCleared, 1)
  assert.deepEqual(state.persisted, [{
    submission: state.submission,
    status: 'pending',
    resultUrl: '',
  }])
  assert.equal(state.submission.pendingPersisted, true)
  assert.deepEqual(state.prepared, [])
  assert.deepEqual(state.completed[0].submission, state.submission)
})

test('stops when preparation returns no submission', async () => {
  const { controller, state } = createHarness()
  state.preparedSubmission = null

  await controller.submit(false)

  assert.deepEqual(state.views, [])
  assert.deepEqual(state.requests, [])
})

test('stops after a successful response when the page has died', async () => {
  const { controller, state } = createHarness()
  state.preparedSubmission = { requestId: 'new' }
  state.submitResult = { id: 'server' }
  state.alive = false

  await controller.submit(false)

  assert.equal(state.requests.length, 1)
  assert.deepEqual(state.completed, [])
})

test('routes request failures to the error controller', async () => {
  const { controller, state } = createHarness()
  state.preparedSubmission = { requestId: 'new' }
  state.requestError = new Error('network failed')

  await controller.submit(false)

  assert.deepEqual(state.errors, [{
    submission: { requestId: 'new' },
    error: state.requestError,
  }])
  assert.deepEqual(state.completed, [])
})
