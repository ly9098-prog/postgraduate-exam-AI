const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createGroupSubmitFlowController,
} = require('../subpackages/study/review-today/utils/group-submit-flow-controller')

function harness(overrides = {}) {
  const state = {
    alive: true,
    groupQuestions: [{ id: 1 }],
    events: [],
    confirmations: [],
    begins: [],
    requests: [],
    results: [],
    errors: [],
    toasts: [],
    submitting: true,
  }
  const options = {
    getGroupQuestions: () => state.groupQuestions,
    confirm: async questions => {
      state.events.push('confirm')
      state.confirmations.push(questions)
      return true
    },
    begin: async questions => {
      state.events.push('begin')
      state.begins.push(questions)
      return { 1: 'A' }
    },
    request: async input => {
      state.events.push('request')
      state.requests.push(input)
      return { status: 'submitted', groupResults: [{ question_id: 1 }] }
    },
    isQuestionAnswered: (question, answers) => Boolean(answers[question.id]),
    getRequestId: question => `review-${question.id}`,
    buildTimingSession: () => ({ started_at: 1, ended_at: 2 }),
    enrichForResult: question => ({ ...question, enriched: true }),
    failureNeedsRefresh: result => result.refresh_required === true,
    applyResult: input => {
      state.events.push('result')
      state.results.push(input)
    },
    isPageAlive: () => state.alive,
    logError: (...args) => { state.errors.push(args) },
    showResultFailureToast: () => { state.toasts.push('failure') },
    setSubmitting: value => { state.submitting = value },
    ...overrides,
  }
  return { options, state, get controller() { return createGroupSubmitFlowController(options) } }
}

test('runs confirm, begin, request, and result in order', async () => {
  const h = harness()
  assert.equal(await h.controller.submit(), true)

  assert.deepEqual(h.state.events, ['confirm', 'begin', 'request', 'result'])
  assert.deepEqual(h.state.confirmations, [[{ id: 1 }]])
  assert.deepEqual(h.state.begins, [[{ id: 1 }]])
  assert.deepEqual(h.state.requests, [{
    groupQuestions: [{ id: 1 }],
    answers: { 1: 'A' },
    isQuestionAnswered: h.options.isQuestionAnswered,
    getRequestId: h.options.getRequestId,
    buildTimingSession: h.options.buildTimingSession,
    enrichForResult: h.options.enrichForResult,
    failureNeedsRefresh: h.options.failureNeedsRefresh,
  }])
  assert.deepEqual(h.state.results, [{
    groupQuestions: [{ id: 1 }],
    groupResults: [{ question_id: 1 }],
  }])
  assert.deepEqual(h.state.toasts, [])
})

test('cancelled confirmation stops before begin', async () => {
  const h = harness({ confirm: async () => false })
  assert.equal(await h.controller.submit(), false)
  assert.deepEqual(h.state.begins, [])
  assert.deepEqual(h.state.requests, [])
})

test('failed begin stops before request', async () => {
  const h = harness({ begin: async () => null })
  assert.equal(await h.controller.submit(), false)
  assert.deepEqual(h.state.requests, [])
})

test('non-submitted request stops before result', async () => {
  const h = harness({ request: async () => ({ status: 'incomplete' }) })
  assert.equal(await h.controller.submit(), false)
  assert.deepEqual(h.state.results, [])
})

test('result failure logs, toasts, and restores submitting', async () => {
  const failure = new Error('render failed')
  const h = harness({ applyResult: () => { throw failure } })
  assert.equal(await h.controller.submit(), false)

  assert.deepEqual(h.state.errors[0], ['提交失败', failure])
  assert.deepEqual(h.state.toasts, ['failure'])
  assert.equal(h.state.submitting, false)
})

test('closed page result failure stays silent', async () => {
  const failure = new Error('render failed')
  const h = harness({
    applyResult: () => { throw failure },
    isPageAlive: () => false,
  })
  assert.equal(await h.controller.submit(), false)
  assert.deepEqual(h.state.errors, [])
  assert.deepEqual(h.state.toasts, [])
  assert.equal(h.state.submitting, true)
})
