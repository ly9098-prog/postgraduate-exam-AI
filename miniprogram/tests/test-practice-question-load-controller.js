const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createQuestionLoadController,
} = require('../subpackages/study/practice/utils/question-load-controller')

function createLoadState() {
  return {
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
}

function harness(overrides = {}) {
  const state = createLoadState()
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

function tracedHarness(overrides = {}) {
  const h = harness(overrides)
  h.calls = []
  for (const name of Object.keys(h.options)) {
    const original = h.options[name]
    h.options[name] = function (...args) {
      assert.equal(this, h.options, `${name} receiver`)
      h.calls.push({ name, args })
      return original(...args)
    }
  }
  h.names = () => h.calls.map(call => call.name)
  h.args = name => h.calls.find(call => call.name === name).args
  return h
}

test('valid batch ports keep their exact order and object identities', async () => {
  const questions = [{ id: 2, _renderModel: {} }]
  const viewModel = { question: questions[0], answerState: {}, optionKeys: ['B'] }
  const view = { loaded: true }
  const params = { include_children: true }
  const h = tracedHarness({
    buildRequestParams: () => params,
    applyAnsweredFlags: response => {
      assert.equal(response, h.state.response)
      return questions
    },
    buildFirstViewModel: question => {
      assert.equal(question, questions[0])
      return viewModel
    },
    buildLoadedView: (batch, model) => {
      assert.equal(batch, questions)
      assert.equal(model, viewModel)
      return view
    },
  })
  assert.equal(await h.controller.load(), true)
  assert.deepEqual(h.names(), [
    'nextRequestSeq', 'isLoading', 'setData', 'getSubjectId', 'getSelectedMode',
    'buildRequestParams', 'requestQuestions', 'isPageAlive', 'getRequestSeq', 'validateKnowledgeScope',
    'applyKnowledgeScope', 'findBatchError', 'resolveBatchErrorRecovery',
    'applyAnsweredFlags', 'setData', 'debugAfterApi', 'applyBatchCredentials',
    'hasMissingBatchCredentials', 'warmQuestionImages', 'buildFirstViewModel',
    'buildLoadedView', 'setData', 'startLoadedSession', 'checkRenderInvariant',
  ])
  assert.equal(h.args('requestQuestions')[0], params)
  assert.equal(h.args('validateKnowledgeScope')[0], h.state.response)
  assert.equal(h.args('applyBatchCredentials')[0], h.state.response)
  assert.deepEqual(h.args('applyBatchCredentials').slice(1), ['random'])
  assert.equal(h.args('warmQuestionImages')[0], questions)
  assert.equal(h.args('startLoadedSession')[0], viewModel)
  assert.equal(h.args('checkRenderInvariant')[0], questions[0]._renderModel)
  assert.equal(h.state.views.at(-1), view)
})

test('scope recovery stops before applying scope or inspecting batch errors', async () => {
  const recovery = {
    logTag: 'SCOPE', logDetail: {}, resetMessage: 'scope failed', toastTitle: 'scope unavailable',
  }
  const h = tracedHarness({ validateKnowledgeScope: () => recovery })
  assert.equal(await h.controller.load(), false)
  assert.deepEqual(h.names().slice(h.names().indexOf('validateKnowledgeScope')), [
    'validateKnowledgeScope', 'logError', 'resetToSetup', 'showToast',
  ])
  assert.equal(h.args('logError')[1], recovery.logDetail)
  assert.deepEqual(h.args('resetToSetup'), [recovery.resetMessage])
  assert.deepEqual(h.args('showToast'), [{ title: recovery.toastTitle, icon: 'none' }])
})

test('batch recovery applies scope first and preserves batch error and response identity', async () => {
  const batchError = { reason: 'invalid question' }
  const recovery = {
    logTag: 'BATCH', logDetail: {}, resetMessage: 'batch failed', toastTitle: 'batch unavailable',
  }
  const h = tracedHarness({
    findBatchError: () => batchError,
    resolveBatchErrorRecovery: () => recovery,
  })
  assert.equal(await h.controller.load(), false)
  assert.deepEqual(h.names().slice(h.names().indexOf('validateKnowledgeScope')), [
    'validateKnowledgeScope', 'applyKnowledgeScope', 'findBatchError',
    'resolveBatchErrorRecovery', 'logError', 'resetToSetup', 'showToast',
  ])
  assert.equal(h.args('resolveBatchErrorRecovery')[0], batchError)
  assert.equal(h.args('resolveBatchErrorRecovery')[1], h.state.response)
  assert.equal(h.args('logError')[1], recovery.logDetail)
})

test('missing credentials fail before warming or rendering and preserve the original error', async () => {
  const h = tracedHarness({ hasMissingBatchCredentials: () => true })
  assert.equal(await h.controller.load(), false)
  assert.deepEqual(h.names().slice(h.names().indexOf('debugAfterApi')), [
    'debugAfterApi', 'applyBatchCredentials', 'hasMissingBatchCredentials',
    'isPageAlive', 'getRequestSeq', 'logError', 'resetToSetup', 'showToast',
  ])
  assert.equal(h.args('logError')[1].message, '服务器未返回可提交的练习批次凭据')
  assert.equal(h.state.warmed, undefined)
})

test('render failure happens after credentials and warming with no loaded view or toast', async () => {
  const h = tracedHarness({ buildFirstViewModel: () => null })
  assert.equal(await h.controller.load(), false)
  assert.deepEqual(h.names().slice(h.names().indexOf('debugAfterApi')), [
    'debugAfterApi', 'applyBatchCredentials', 'hasMissingBatchCredentials',
    'warmQuestionImages', 'buildFirstViewModel', 'isPageAlive', 'getRequestSeq',
    'logError', 'resetToSetup',
  ])
  assert.equal(h.args('logError')[1].message, '_buildQuestionViewModel returned null')
  assert.equal(h.args('logError')[1].renderFailure, true)
  assert.equal(h.state.sessionStarted, undefined)
  assert.equal(h.state.views.length, 2)
  assert.deepEqual(h.state.toasts, [])
})

test('dead and stale successful responses stop before scope validation', async () => {
  for (const kind of ['dead', 'stale']) {
    const h = tracedHarness()
    h.options.requestQuestions = async () => {
      if (kind === 'dead') h.state.pageAlive = false
      else h.state.requestSeq += 1
      return h.state.response
    }
    assert.equal(await h.controller.load(), false)
    assert.equal(h.names().includes('validateKnowledgeScope'), false)
    assert.deepEqual(h.state.errors, [])
    assert.deepEqual(h.state.toasts, [])
    assert.equal(h.state.debugged, undefined)
  }
})

test('dead and stale rejected requests leave recovery state untouched', async () => {
  for (const kind of ['dead', 'stale']) {
    const h = tracedHarness()
    h.options.requestQuestions = async () => {
      if (kind === 'dead') h.state.pageAlive = false
      else h.state.requestSeq += 1
      throw new Error('late network failure')
    }
    assert.equal(await h.controller.load(), false)
    assert.equal(h.names().includes('resetToSetup'), false)
    assert.deepEqual(h.state.errors, [])
    assert.deepEqual(h.state.toasts, [])
  }
})

test('sequential restart waits for completion with the original progress, subject and sequence', async () => {
  let finishRestart
  const h = tracedHarness({
    restartSequential: () => new Promise(resolve => { finishRestart = resolve }),
  })
  const progress = { cycle_completed: true }
  h.state.selectedMode = 'sequential'
  h.state.response = { questions: [], sequential_progress: progress }
  let settled = false
  const pending = h.controller.load().then(result => { settled = true; return result })
  await Promise.resolve()
  assert.equal(settled, false)
  assert.deepEqual(h.args('restartSequential'), [progress, 12, 1])
  assert.equal(h.args('restartSequential')[0], progress)
  assert.equal(h.state.views.at(-1).sequentialProgress, progress)
  assert.equal(h.names().includes('debugAfterApi'), false)
  finishRestart()
  assert.equal(await pending, false)
})

test('sequential restart rejection follows ordinary load recovery with the same error', async () => {
  const error = new Error('restart failed')
  const h = tracedHarness({ restartSequential: async () => { throw error } })
  h.state.selectedMode = 'sequential'
  h.state.response = { questions: [], sequential_progress: { cycle_completed: true } }
  assert.equal(await h.controller.load(), false)
  assert.equal(h.args('logError')[1], error)
  assert.equal(h.state.reset, '加载题目失败，请重试或返回重新选择科目')
  assert.deepEqual(h.state.toasts, [{ title: '加载题目失败', icon: 'none' }])
})

test('request captures its mode and subject before awaiting and skips an existing loading patch', async () => {
  const h = tracedHarness()
  h.state.loading = true
  h.state.selectedMode = 'sequential'
  const progress = { cycle_completed: true }
  h.state.response = { questions: [], sequential_progress: progress }
  h.options.requestQuestions = async () => {
    h.state.subjectId = 99
    h.state.selectedMode = 'random'
    return h.state.response
  }
  assert.equal(await h.controller.load(), false)
  assert.deepEqual(h.state.views, [{ sequentialProgress: progress }])
  assert.equal(h.args('restartSequential')[0], progress)
  assert.deepEqual(h.args('restartSequential').slice(1), [12, 1])
})

test('nonsequential progress is ignored and empty batches use the current subject', async () => {
  const h = tracedHarness()
  h.state.selectedMode = ''
  h.state.response = { questions: [], sequential_progress: { cycle_completed: true } }
  h.options.requestQuestions = async () => {
    h.state.subjectId = 99
    return h.state.response
  }
  assert.equal(await h.controller.load(), true)
  assert.equal(h.state.views[1].sequentialProgress, null)
  assert.equal(h.args('applyBatchCredentials')[1], 'random')
  assert.equal(h.names().includes('restartSequential'), false)
  assert.equal(h.names().includes('buildFirstViewModel'), false)
  assert.equal(h.names().includes('startLoadedSession'), false)
  assert.equal(h.state.noQuestions, 99)
})

test('an older overlapping request cannot replace the newer loaded batch', async () => {
  const pending = []
  const h = tracedHarness({
    requestQuestions: () => new Promise(resolve => pending.push(resolve)),
  })
  const controller = h.controller
  const first = controller.load()
  const second = controller.load()
  const latest = { ...h.state.response, questions: [{ id: 2 }] }
  pending[1](latest)
  assert.equal(await second, true)
  pending[0](h.state.response)
  assert.equal(await first, false)
  assert.equal(h.state.views.at(-1).questions, latest.questions)
  assert.equal(h.names().filter(name => name === 'applyKnowledgeScope').length, 1)
})
