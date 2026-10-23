const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createGroupSubmitRequestController,
} = require('../subpackages/study/review-today/utils/submit-request-controller')

const questions = [
  { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1 },
  { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 2 },
]
const answers = { 1: 'A', 2: 'B' }

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    submitting: true,
    toasts: [],
    requests: [],
    response: { results: [] },
  }
  const controller = createGroupSubmitRequestController({
    postGrade: async payload => {
      state.requests.push(payload)
      if (overrides.throwOnPost) throw new Error('network failed')
      return state.response
    },
    showToast: options => { state.toasts.push(options) },
    setSubmitting: value => { state.submitting = value },
    isPageAlive: () => state.alive,
  })
  return { controller, state }
}

function input(overrides = {}) {
  return {
    groupQuestions: questions,
    answers,
    isQuestionAnswered: () => true,
    getRequestId: question => `request-${question.schedule_id}`,
    buildTimingSession: () => null,
    enrichForResult: question => ({ ...question, enriched: true }),
    failureNeedsRefresh: () => false,
    ...overrides,
  }
}

test('sends immutable reviews with the pre-request timing session', async () => {
  const { controller, state } = createHarness()
  state.response = {
    results: [
      { schedule_id: 1, question_version_id: 21, occurrence_seq: 1, success: true, is_correct: true, correct_answer: 'A' },
      { schedule_id: 2, question_version_id: 22, occurrence_seq: 2, success: true, is_correct: false, correct_answer: 'B' },
    ],
  }
  const result = await controller.submit(input({ buildTimingSession: () => ({ duration: 9 }) }))

  assert.equal(result.status, 'submitted')
  assert.deepEqual(state.requests, [{
    reviews: [
      { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1, request_id: 'request-1', user_answer: 'A' },
      { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 2, request_id: 'request-2', user_answer: 'B' },
    ],
    session: { duration: 9 },
  }])
  assert.equal(result.groupResults[0].isCorrect, true)
  assert.equal(result.groupResults[1].isCorrect, false)
  assert.deepEqual(state.toasts, [])
})

test('reports empty results and stops submission', async () => {
  const { controller, state } = createHarness()
  const result = await controller.submit(input())

  assert.equal(result.status, 'empty')
  assert.deepEqual(state.toasts, [{ title: '批改结果为空，请重试', icon: 'none' }])
  assert.equal(state.submitting, false)
})

test('warns on partial results but projects returned questions', async () => {
  const { controller, state } = createHarness()
  state.response = {
    results: [
      { schedule_id: 1, question_version_id: 21, occurrence_seq: 1, success: true, is_correct: true },
    ],
  }
  const result = await controller.submit(input())

  assert.equal(result.status, 'submitted')
  assert.deepEqual(state.toasts, [{ title: '部分题目批改失败', icon: 'none' }])
  assert.equal(result.groupResults[1].submitFailed, true)
  assert.equal(result.groupResults[1].retryable, true)
})

test('stops on build errors and page death', async () => {
  const version = createHarness()
  const versionResult = await version.controller.submit(input({
    groupQuestions: [{ ...questions[0], question_version_id: null }],
  }))
  assert.equal(versionResult.status, 'version')
  assert.deepEqual(version.state.toasts, [{ title: '复习任务版本信息缺失，请刷新后重试', icon: 'none' }])
  assert.equal(version.state.submitting, false)

  const incomplete = createHarness()
  const incompleteResult = await incomplete.controller.submit(input({
    isQuestionAnswered: () => false,
  }))
  assert.equal(incompleteResult.status, 'incomplete')
  assert.deepEqual(incomplete.state.toasts, [{ title: '请完成全部题目后再提交', icon: 'none' }])
  assert.equal(incomplete.state.submitting, false)

  const dead = createHarness()
  dead.state.alive = false
  const deadResult = await dead.controller.submit(input())
  assert.equal(deadResult.status, 'dead')
  assert.equal(dead.state.submitting, true)
  assert.deepEqual(dead.state.toasts, [])
})

test('lets request errors propagate to the page handler', async () => {
  const { controller, state } = createHarness({ throwOnPost: true })
  await assert.rejects(() => controller.submit(input()), /network failed/)
  assert.deepEqual(state.toasts, [])
  assert.equal(state.submitting, true)
})
