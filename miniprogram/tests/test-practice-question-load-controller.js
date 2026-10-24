const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createQuestionLoadController,
} = require('../subpackages/study/practice/utils/question-load-controller')

function harness(overrides = {}) {
  const state = {
    requestSeq: 0,
    pageAlive: true,
    loading: false,
    subjectId: 12,
    selectedMode: 'random',
    response: {
      trace_id: 'trace-1',
      questions: [{ id: 1 }],
      knowledge_scope: { subject_id: 12 },
      request_id: 'recommendation',
      batch_token: 'batch',
      submission_request_id: 'submission',
    },
    views: [],
    toasts: [],
    errors: [],
  }

  const options = {
    nextRequestSeq: () => ++state.requestSeq,
    getRequestSeq: () => state.requestSeq,
    isPageAlive: () => state.pageAlive,
    isLoading: () => state.loading,
    setData: view => { state.views.push(view); Object.assign(state, view) },
    getSubjectId: () => state.subjectId,
    getSelectedMode: () => state.selectedMode,
    buildRequestParams: () => ({ include_children: false }),
    requestQuestions: async params => { state.requestParams = params; return state.response },
    validateKnowledgeScope: () => null,
    applyKnowledgeScope: res => { state.knowledgeScope = res.knowledge_scope },
    findBatchError: () => null,
    resolveBatchErrorRecovery: () => null,
    applyAnsweredFlags: res => res.questions,
    restartSequential: async () => { state.restarted = true },
    debugAfterApi: () => { state.debugged = true },
    applyBatchCredentials: (res, mode) => {
      state.credentials = { res, mode }
    },
    hasMissingBatchCredentials: () => false,
    warmQuestionImages: (questions, index) => { state.warmed = { questions, index } },
    buildFirstViewModel: q => ({ question: q, optionKeys: ['A'] }),
    buildLoadedView: (questions, viewModel) => ({ loaded: true, questions, viewModel }),
    startLoadedSession: viewModel => { state.sessionStarted = viewModel },
    checkRenderInvariant: model => { state.checkedModel = model },
    showNoQuestions: subjectId => { state.noQuestions = subjectId },
    resetToSetup: errorText => { state.reset = errorText },
    logError: (...args) => state.errors.push(args),
    showToast: options => state.toasts.push(options),
    ...overrides,
  }
  return { options, state, get controller() { return createQuestionLoadController(options) } }
}

test('loads a valid batch and starts the first question session', async () => {
  const h = harness()
  assert.equal(await h.controller.load(), true)
  assert.equal(h.state.requestSeq, 1)
  assert.equal(h.state.loading, true)
  assert.deepEqual(h.state.requestParams, { include_children: false })
  assert.deepEqual(h.state.knowledgeScope, { subject_id: 12 })
  assert.equal(h.state.debugged, true)
  assert.deepEqual(h.state.credentials.mode, 'random')
  assert.deepEqual(h.state.warmed, { questions: [{ id: 1 }], index: 0 })
  assert.equal(h.state.views.at(-1).loaded, true)
  assert.equal(h.state.sessionStarted.optionKeys[0], 'A')
})

test('rejects missing subject and stale responses without mutating loaded state', async () => {
  const missing = harness()
  missing.state.subjectId = null
  assert.equal(await missing.controller.load(), false)
  assert.equal(missing.state.reset, undefined)
  assert.deepEqual(missing.state.toasts, [{ title: '请选择科目', icon: 'none' }])

  const stale = harness({
    requestQuestions: async () => {
      stale.state.requestSeq = 2
      return stale.state.response
    },
  })
  assert.equal(await stale.controller.load(), false)
  assert.equal(stale.state.debugged, undefined)
})

test('maps scope, batch and load failures to the original reset views', async () => {
  const scope = harness({
    validateKnowledgeScope: () => ({
      logTag: 'SCOPE',
      logDetail: { id: 12 },
      resetMessage: 'scope failed',
      toastTitle: 'scope unavailable',
    }),
  })
  assert.equal(await scope.controller.load(), false)
  assert.equal(scope.state.reset, 'scope failed')
  assert.deepEqual(scope.state.toasts, [{ title: 'scope unavailable', icon: 'none' }])

  const batch = harness({
    resolveBatchErrorRecovery: () => ({
      logTag: 'BATCH',
      logDetail: {},
      resetMessage: 'batch failed',
      toastTitle: 'batch unavailable',
    }),
  })
  assert.equal(await batch.controller.load(), false)
  assert.equal(batch.state.reset, 'batch failed')

  const failed = harness({ requestQuestions: async () => { throw new Error('network') } })
  assert.equal(await failed.controller.load(), false)
  assert.equal(failed.state.reset, '加载题目失败，请重试或返回重新选择科目')
  assert.equal(failed.state.errors[0][0], '加载题目失败')
})

test('keeps the original first-question render failure recovery', async () => {
  const h = harness({ buildFirstViewModel: () => null })
  assert.equal(await h.controller.load(), false)
  assert.equal(h.state.reset, '题目解析失败，可重试或返回选题')
  assert.equal(h.state.errors[0][0], '首题渲染失败')
  assert.deepEqual(h.state.toasts, [])
})

test('delegates sequential completion and empty batches', async () => {
  const sequential = harness()
  sequential.state.selectedMode = 'sequential'
  sequential.state.response = {
    questions: [],
    sequential_progress: { cycle_completed: true },
  }
  assert.equal(await sequential.controller.load(), false)
  assert.equal(sequential.state.restarted, true)

  const empty = harness()
  empty.state.response = { questions: [] }
  assert.equal(await empty.controller.load(), true)
  assert.equal(empty.state.noQuestions, 12)
})
