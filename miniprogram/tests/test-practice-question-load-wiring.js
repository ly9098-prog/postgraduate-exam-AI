const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createQuestionLoadWiring,
} = require('../subpackages/study/practice/utils/question-load-wiring')

function createHarness(overrides = {}) {
  const calls = {
    setData: [],
    toasts: [],
    errors: [],
    apiGets: [],
    debugLogs: [],
    debugSnapshots: [],
  }
  const page = {
    _questionsRequestSeq: 0,
    _pageAlive: true,
    data: {
      loading: false,
      selectedSubjectId: 12,
      selectedMode: 'random',
      selectedSubjectName: '数据结构',
    },
    _practiceSession: { traceId: 'trace-1' },
    _launchIncludeDescendants: false,
    _launchKnowledgePointId: 7,
    setData: (data, callback) => {
      calls.setData.push(data)
      Object.assign(page.data, data)
      if (callback) callback()
    },
    _buildQuestionRequestParams: () => ({ include_children: false }),
    _getPracticeSubjectScopeIds: () => ['12', '34'],
    _sequentialRestartController: () => ({
      restart: (...args) => { calls.sequentialRestart = args },
    }),
    _warmQuestionImages: (questions, index) => { calls.warmed = { questions, index } },
    _buildQuestionViewModel: question => ({ question, optionKeys: ['A'] }),
    _setPracticeUnloadGuard: value => { calls.unloadGuard = value },
    _startTimer: () => { calls.timerStarted = true },
    _updateComputedFields: () => { calls.computedUpdated = true },
    _checkRenderInvariant: model => { calls.renderChecked = model },
    _clearTimer: () => { calls.timerCleared = true },
    _showSubmitConfirm: payload => { calls.submitConfirm = payload },
  }
  const deps = {
    api: {
      get: (path, params) => {
        calls.apiGets.push({ path, params })
        return Promise.resolve({ questions: [] })
      },
      now: () => 12345,
    },
    validateKnowledgeScope: (scope, rootId) => scope && scope.root_id === rootId,
    findQuestionBatchError: (questions, config) => {
      calls.batchErrorConfig = config
      return null
    },
    resolveBatchErrorRecovery: (error, context) => {
      calls.recoveryContext = context
      return null
    },
    adapter: {
      applyAnsweredFlags: (questions, flags, idField) => {
        calls.answeredFlags = { questions, flags, idField }
        return questions
      },
    },
    debugLog: (...args) => calls.debugLogs.push(args),
    saveDebugSnapshot: (...args) => calls.debugSnapshots.push(args),
    applyBatchCredentials: (session, response, mode) => {
      calls.credentials = { session, response, mode }
    },
    hasMissingBatchCredentials: (session, count) => {
      calls.missingCredentials = { session, count }
      return false
    },
    monotonicNow: () => 777,
    buildLoadedView: (questions, viewModel) => ({ loaded: true, questions, viewModel }),
    buildResetView: errorText => ({ reset: errorText || 'reset' }),
    practiceAnswerableTypes: ['single_choice'],
    wx: {
      showToast: options => calls.toasts.push(options),
    },
    ...overrides.deps,
  }
  const wiring = createQuestionLoadWiring(page, deps)
  return { page, deps, wiring, calls }
}

test('wiring exposes the exact question-load controller port set', () => {
  const { wiring } = createHarness()
  assert.deepEqual(Object.keys(wiring).sort(), [
    'applyAnsweredFlags',
    'applyBatchCredentials',
    'applyKnowledgeScope',
    'buildFirstViewModel',
    'buildLoadedView',
    'buildRequestParams',
    'checkRenderInvariant',
    'debugAfterApi',
    'findBatchError',
    'getRequestSeq',
    'getSelectedMode',
    'getSubjectId',
    'hasMissingBatchCredentials',
    'isLoading',
    'isPageAlive',
    'logError',
    'nextRequestSeq',
    'requestQuestions',
    'resetToSetup',
    'resolveBatchErrorRecovery',
    'restartSequential',
    'setData',
    'showNoQuestions',
    'showToast',
    'startLoadedSession',
    'validateKnowledgeScope',
    'warmQuestionImages',
  ])
})

test('request and sequence ports delegate to the page', async () => {
  const h = createHarness()
  assert.equal(h.wiring.nextRequestSeq(), 1)
  assert.equal(h.wiring.getRequestSeq(), 1)
  assert.equal(h.wiring.isPageAlive(), true)
  assert.equal(h.wiring.isLoading(), false)
  assert.equal(h.wiring.getSubjectId(), 12)
  assert.equal(h.wiring.getSelectedMode(), 'random')
  assert.deepEqual(h.wiring.buildRequestParams(), { include_children: false })
  await h.wiring.requestQuestions({ include_children: false })
  assert.deepEqual(h.calls.apiGets, [{ path: '/practice/questions', params: { include_children: false } }])
})

test('knowledge scope validation is skipped unless launch requests descendants', () => {
  const h = createHarness()
  assert.equal(h.wiring.validateKnowledgeScope({}), null)

  h.page._launchIncludeDescendants = true
  const valid = h.wiring.validateKnowledgeScope({ knowledge_scope: { root_id: 7 } })
  assert.equal(valid, null)

  const invalid = h.wiring.validateKnowledgeScope({
    trace_id: 'trace-9',
    knowledge_scope: { root_id: 8 },
  })
  assert.equal(invalid.logTag, '[PRACTICE_KNOWLEDGE_SCOPE_MISMATCH]')
  assert.deepEqual(invalid.logDetail, {
    requestedRootId: 7,
    requestedIncludeDescendants: true,
    receivedScope: { root_id: 8 },
    traceId: 'trace-9',
  })
  assert.equal(invalid.resetMessage, '章节专项范围校验失败，请更新后端服务后重试。')
  assert.equal(invalid.toastTitle, '章节专项暂不可用')
})

test('batch error and recovery ports preserve scope and trace context', () => {
  const h = createHarness()
  const response = { questions: [{ id: 1 }], trace_id: 'trace-2' }
  h.wiring.findBatchError(response)
  assert.deepEqual(h.calls.batchErrorConfig.allowedScopeIds, new Set([12, 34]))
  assert.deepEqual(h.calls.batchErrorConfig.answerableTypes, ['single_choice'])

  h.wiring.resolveBatchErrorRecovery('batch-error', response)
  assert.deepEqual(h.calls.recoveryContext, {
    subjectId: 12,
    includeChildren: false,
    traceId: 'trace-2',
  })
})

test('startLoadedSession initializes session timing exactly once', () => {
  const h = createHarness()
  const viewModel = { optionKeys: ['A', 'B'] }
  h.wiring.startLoadedSession(viewModel)
  assert.equal(h.page._practiceSession.activeStartedMonoMs, 777)
  assert.equal(h.page._practiceSession.startedAtMs, 12345)
  assert.equal(h.page._practiceSession.backgroundMs, 0)
  assert.equal(h.page._practiceSession._backgroundStartedMonoMs, null)
  assert.equal(h.page._practiceSession.elapsedSec, 0)
  assert.equal(h.page._practiceSession.optionKeys[1], 'B')
  assert.equal(h.page._practiceSession.currentQuestionStartedMonoMs, 777)
  assert.equal(h.calls.unloadGuard, true)
  assert.equal(h.calls.timerStarted, true)
  assert.equal(h.calls.computedUpdated, true)

  h.page._practiceSession.activeStartedMonoMs = 999
  h.wiring.startLoadedSession(viewModel)
  assert.equal(h.page._practiceSession.activeStartedMonoMs, 999)
})

test('showNoQuestions resets timer, guard, view and opens the original dialog', () => {
  const h = createHarness()
  h.wiring.showNoQuestions(12)
  assert.equal(h.calls.timerCleared, true)
  assert.equal(h.calls.unloadGuard, false)
  assert.deepEqual(h.calls.setData.at(-1), { reset: 'reset' })
  assert.equal(h.calls.submitConfirm.scenario, 'info')
  assert.equal(h.calls.submitConfirm.eyebrow, 'NO QUESTIONS')
  assert.equal(h.calls.submitConfirm.title, '该科目暂无可练题目')
  assert.equal(h.calls.submitConfirm.confirmText, '返回选择科目')
  assert.equal(h.calls.submitConfirm.hideCancel, true)
  assert.ok(h.calls.submitConfirm.message.includes('「数据结构」'))
})

test('resetToSetup clears timer and guard and writes the reset view', () => {
  const h = createHarness()
  h.wiring.resetToSetup('加载题目失败')
  assert.equal(h.calls.timerCleared, true)
  assert.equal(h.calls.unloadGuard, false)
  assert.deepEqual(h.calls.setData.at(-1), { reset: '加载题目失败' })
})

test('debugAfterApi preserves trace id, tag and payload arguments', () => {
  const h = createHarness()
  const response = { trace_id: 'trace-api' }
  const questions = [{ id: 3 }, { id: 8 }]
  h.wiring.debugAfterApi(response, questions)
  assert.deepEqual(h.calls.debugLogs, [[
    'trace-1',
    'STATE_AFTER_API',
    { total: 2, responseTraceId: 'trace-api' },
  ]])
  assert.deepEqual(h.calls.debugSnapshots, [[
    'trace-1',
    'state_after_api',
    { total: 2, questionIds: [3, 8] },
  ]])
})
