const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createStartBatchController,
} = require('../subpackages/study/review-today/utils/start-batch-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    flowSeq: 7,
    currentFlowSeq: 7,
    starting: false,
    continuing: false,
    todayRemainingCount: 6,
    todayDueCount: 6,
    todayCompletedCount: 0,
    totalBatchCount: 2,
    batchSize: 10,
    response: {
      questions: [
        { schedule_id: 1 },
        null,
        { schedule_id: 3 },
      ],
      session_id: 'session-1',
      group_id: 'group-1',
      batch_no: 4,
      total_batch_count: 9,
      today_due_count: 8,
      today_completed_count: 2,
    },
    data: undefined,
    applied: false,
    restored: {
      answers: { 1: 'A', 3: 'C' },
      currentIndex: 2,
      restoredCount: 2,
    },
    baseData: {
      todayDueCount: 6,
      todayCompletedCount: 0,
      totalBatchCount: 2,
    },
    session: {
      answers: {},
      sessionId: '',
      currentGroupId: '',
      allGroupResults: [{}],
      totalCorrect: 1,
      totalWrong: 1,
      totalCompleted: 1,
      safeModeActive: true,
      renderTraces: [{}],
      allQuestions: [],
      todayTaskTotalCount: 0,
      completedBeforeSession: 0,
      optionKeys: null,
    },
    callbacks: [],
    toasts: [],
    errors: [],
    sizes: [],
  }
  const enrichedQuestion = question => ({
    ...question,
    enriched: true,
    _optionKeys: Object.keys(question.options || {}),
    _blankOptionGroups: [],
    _hasBlankOptionGroups: false,
    _renderModel: { renderTrace: 'trace' },
  })
  const controller = createStartBatchController({
    getTodayRemainingCount: () => state.todayRemainingCount,
    isStarting: () => state.starting,
    isContinuing: () => state.continuing,
    nextFlowSeq: () => ++state.flowSeq,
    getCurrentFlowSeq: () => state.flowSeq,
    isFlowCurrent: seq => seq === state.currentFlowSeq,
    isPageAlive: () => state.alive,
    setData: patch => {
      state.data = state.data || { ...state.baseData }
      Object.assign(state.data, patch)
    },
    getBatchSize: () => state.batchSize,
    postNextBatch: async payload => {
      state.request = payload
      if (overrides.throwOnPost) throw new Error('network failed')
      return state.response
    },
    loadOverview: async () => { state.callbacks.push('load-overview') },
    normalizeQuestion: question => question ? { ...question, normalized: true } : null,
    restoreDraft: questions => {
      if (!state.applied) {
        state.restoredQuestions = questions
      }
      return state.restored
    },
    getSession: () => state.session,
    getData: () => state.data,
    enrichQuestion: enrichedQuestion,
    buildOptionList: () => ['A'],
    getBlankOptionGroups: question => question.blankGroups || [],
    enrichBlankOptionGroups: groups => groups,
    computeAnsweredCount: () => 2,
    getTotalBatchCount: () => state.data.totalBatchCount,
    checkSetDataSize: patch => { state.sizes.push(patch) },
    syncAnsweredFlags: () => { state.applied = true; state.callbacks.push('sync') },
    updateRunnerFields: () => { state.callbacks.push('runner') },
    checkRenderInvariant: renderModel => { state.callbacks.push(['render', renderModel]) },
    recordRenderTrace: trace => { state.callbacks.push(['trace', trace]) },
    startReviewTimer: () => { state.callbacks.push('timer') },
    showToast: options => { state.toasts.push(options) },
    logError: (...args) => { state.errors.push(args) },
    ...overrides,
  })
  return { controller, state }
}

test('starts a batch and restores draft state without changing ordering', async () => {
  const { controller, state } = createHarness()
  state.currentFlowSeq = 8
  await controller.start()

  assert.deepEqual(state.request, { batch_size: 10 })
  assert.equal(state.flowSeq, 8)
  assert.deepEqual(state.restoredQuestions, [
    { schedule_id: 1, normalized: true },
    { schedule_id: 3, normalized: true },
  ])
  assert.deepEqual(state.session.allQuestions.map(q => q.schedule_id), [1, 3])
  assert.equal(state.session.sessionId, 'session-1')
  assert.equal(state.session.currentGroupId, 'group-1')
  assert.equal(state.session.todayTaskTotalCount, 8)
  assert.equal(state.session.completedBeforeSession, 2)
  assert.deepEqual(state.session.allGroupResults, [])
  assert.deepEqual(state.session.renderTraces, [])
  assert.equal(state.session.safeModeActive, false)
  assert.deepEqual(state.data, {
    todayDueCount: 8,
    todayCompletedCount: 2,
    totalBatchCount: 9,
    phase: 'reviewing',
    groups: [state.session.allQuestions],
    currentGroupIdx: 0,
    groupQuestions: state.session.allQuestions,
    currentIndex: 1,
    currentQuestion: {
      ...state.session.allQuestions[1],
      _optionList: ['A'],
    },
    _answeredCount: 2,
    currentBatchNo: 4,
    todayRemainingCount: 6,
    groupResults: [],
    groupWrongResults: [],
    groupCorrect: 0,
    groupWrong: 0,
    _groupSkipped: 0,
    groupAccuracyPercent: 0,
    showGroupDetails: false,
    masterConfirmId: null,
    submittingGroup: false,
    resultTransitioning: false,
    batchLoading: false,
    isStarting: false,
    isContinuing: false,
  })
  assert.deepEqual(state.sizes, [{
    phase: 'reviewing',
    currentQuestion: {
      ...state.session.allQuestions[1],
      _optionList: ['A'],
    },
  }])
  assert.deepEqual(state.callbacks, ['sync', 'runner', ['render', { renderTrace: 'trace' }], ['trace', 'trace'], 'timer'])
  assert.deepEqual(state.toasts, [{ title: '已恢复 2 题草稿', icon: 'none' }])
})

test('guards duplicate starts and zero remaining tasks', async () => {
  const zero = createHarness()
  zero.state.todayRemainingCount = 0
  await zero.controller.start()
  assert.equal(zero.state.flowSeq, 7)
  assert.equal(zero.state.request, undefined)

  const busy = createHarness()
  busy.state.starting = true
  await busy.controller.start()
  assert.equal(busy.state.flowSeq, 7)
  assert.equal(busy.state.request, undefined)
})

test('empty responses return to the overview loader', async () => {
  const { controller, state } = createHarness()
  state.response = { questions: [] }
  state.currentFlowSeq = 8
  await controller.start()

  assert.deepEqual(state.callbacks, ['load-overview'])
  assert.equal(state.data.phase, 'loading')
})

test('rejects batches where every normalized question is invalid', async () => {
  const { controller, state } = createHarness({ throwOnPost: true })
  state.currentFlowSeq = 8
  await controller.start()

  assert.equal(state.errors.length, 1)
  assert.equal(state.errors[0][0], '[REVIEW_ERROR] startTodayReview failed')
  assert.deepEqual(state.data, {
    todayDueCount: 6,
    todayCompletedCount: 0,
    totalBatchCount: 2,
    isStarting: false,
    isContinuing: false,
    batchLoading: false,
    phase: 'error',
    errorText: '获取复习题失败，请检查网络后重试',
  })
  assert.deepEqual(state.toasts, [{ title: '获取复习题失败，请重试', icon: 'none' }])
})

test('ignores errors from a superseded start flow', async () => {
  const stale = createHarness({ throwOnPost: true })
  stale.state.currentFlowSeq = 9
  await stale.controller.start()

  assert.equal(stale.data, undefined)
  assert.deepEqual(stale.state.errors, [])
  assert.deepEqual(stale.state.toasts, [])
})

test('stops on stale responses before applying a batch', async () => {
  const stale = createHarness()
  stale.state.currentFlowSeq = 99
  stale.state.flowSeq = 99
  stale.state.isFlowCurrent = seq => seq === stale.state.currentFlowSeq
  await stale.controller.start()
  assert.equal(stale.data, undefined)
  assert.equal(stale.state.session.sessionId, '')

  const dead = createHarness()
  dead.state.alive = false
  dead.state.currentFlowSeq = 8
  await dead.controller.start()
  assert.equal(dead.data, undefined)
  assert.equal(dead.state.session.sessionId, '')
})
