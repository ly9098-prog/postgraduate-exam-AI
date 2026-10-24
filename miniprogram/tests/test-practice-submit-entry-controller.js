const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubmitEntryController,
} = require('../subpackages/study/practice/utils/submit-entry-controller')

function harness(overrides = {}) {
  const state = {
    questions: [{ id: 1 }, { id: 2 }],
    answerMap: { 1: 'A', 2: '' },
    answeredFlags: { 1: true, 2: false },
    pausedPrompts: [],
    prompts: [],
    toasts: [],
    calls: [],
    requestId: '',
    batchToken: 'batch',
    pausedResult: true,
  }
  const options = {
    getQuestions: () => state.questions,
    getSelectedSubjectId: () => 12,
    getSelectedSubjectName: () => '数据结构',
    getAnswerMap: () => state.answerMap,
    getActiveStartedMonoMs: () => 1000,
    getComboCount: () => 2,
    buildAnsweredFlags: (questions, answerMap) => state.answeredFlags,
    classifyAnswers: options => ({
      answeredCount: 1,
      completedQuestions: [options.questions[0]],
      partialQuestionIds: [2],
      skippedQuestionIds: [2],
      unanswered: 1,
    }),
    isMultiBlank: () => true,
    showToast: options => state.toasts.push(options),
    showPausedConfirm: async options => { state.pausedPrompts.push(options); return state.pausedResult },
    showConfirm: async options => { state.prompts.push(options) },
    clearTimer: () => state.calls.push('clearTimer'),
    settleQuestionTime: pause => state.calls.push(['settle', pause]),
    monotonicNow: () => 4000,
    now: () => 5000,
    getBackgroundMs: () => 500,
    getRequestId: () => state.requestId,
    buildRequestId: () => 'generated-request',
    setRequestId: id => { state.requestId = id },
    buildSubmitAnswers: options => options,
    getQuestionTimeMap: () => ({ 1: 2 }),
    getRecommendationRequestId: () => 'recommendation',
    buildSubmitSession: options => options,
    getBatchMode: () => 'sequential',
    getSelectedMode: () => 'random',
    getStartedAtMs: () => 900,
    buildRecoveryQuestions: questions => questions,
    getBatchToken: () => state.batchToken,
    buildSubmissionSnapshot: options => ({ ...options, snapshot: true }),
    getTraceId: () => 'trace-1',
    getKnowledgeScope: () => ({ root_id: 34 }),
    setSubmissionSnapshot: submission => { state.submission = submission },
    persistPendingSubmission: (submission, status, resultUrl) => {
      state.persisted = { submission, status, resultUrl }
      return true
    },
    setUnloadGuard: (enabled, message) => state.calls.push(['guard', enabled, message]),
    ...overrides,
  }
  return { options, state, get controller() { return createSubmitEntryController(options) } }
}

test('prepares a submission after unanswered confirmation', async () => {
  const h = harness()
  const submission = await h.controller.prepare(false)
  assert.equal(submission.snapshot, true)
  assert.equal(h.state.requestId, 'generated-request')
  assert.equal(h.state.submission, submission)
  assert.equal(submission.duration, 2)
  assert.equal(submission.session.mode, 'sequential')
  assert.deepEqual(h.state.pausedPrompts[0], {
    scenario: 'unanswered',
    title: '还有 1 题未完成',
    message: '现在交卷会将未完成题记为跳过。',
    confirmText: '仍然交卷',
    cancelText: '继续答题',
  })
  assert.deepEqual(h.state.calls, ['clearTimer', ['settle', true], ['guard', true, '交卷仍在确认中。']])
  assert.deepEqual(h.state.persisted, { submission, status: 'pending', resultUrl: '' })
})

test('uses all-done confirmation and preserves an existing request id', async () => {
  const h = harness()
  h.state.requestId = 'existing'
  h.options.classifyAnswers = () => ({
    answeredCount: 2,
    completedQuestions: h.state.questions,
    partialQuestionIds: [],
    skippedQuestionIds: [],
    unanswered: 0,
  })
  const submission = await h.controller.prepare(false)
  assert.equal(submission.requestId, 'existing')
  assert.deepEqual(h.state.pausedPrompts[0], {
    scenario: 'all-done',
    title: '确认交卷？',
    message: '已完成 2 / 2 题',
    confirmText: '确认交卷',
    cancelText: '继续检查',
  })
})

test('stops for empty answers, cancellation and missing batch token', async () => {
  const empty = harness()
  empty.options.classifyAnswers = () => ({
    answeredCount: 0,
    completedQuestions: [],
    partialQuestionIds: [],
    skippedQuestionIds: [],
    unanswered: 2,
  })
  assert.equal(await empty.controller.prepare(false), null)
  assert.deepEqual(empty.state.toasts, [{ title: '请至少完成或填写 1 题再提交', icon: 'none' }])

  const cancelled = harness()
  cancelled.state.pausedResult = false
  assert.equal(await cancelled.controller.prepare(false), null)
  assert.equal(cancelled.state.calls.length, 0)

  const invalidBatch = harness()
  invalidBatch.state.batchToken = ''
  assert.equal(await invalidBatch.controller.prepare(true), null)
  assert.deepEqual(invalidBatch.state.prompts, [{
    scenario: 'info',
    title: '练习批次已失效',
    message: '请返回后重新获取本组题目。',
    showCancel: false,
    confirmText: '知道了',
    hideEyebrow: true,
  }])
  assert.equal(invalidBatch.state.submission, undefined)
})
