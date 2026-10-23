const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createNextRemoteBatchController,
} = require('../subpackages/study/review-today/utils/next-remote-batch-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    flowCurrent: true,
    batchSize: 10,
    currentBatchNo: 1,
    totalBatchCount: 2,
    todayDueCount: 8,
    todayCompletedCount: 2,
    todayRemainingCount: 6,
    response: { questions: [] },
    session: {
      todayTaskTotalCount: 8,
      allQuestions: [],
      answers: {},
    },
    data: {},
    restored: { answers: { 1: 'A' }, currentIndex: 1, restoredCount: 1 },
    callbacks: [],
    toasts: [],
    refreshed: false,
  }
  const controller = createNextRemoteBatchController({
    getBatchSize: () => state.batchSize,
    postNextBatch: async payload => {
      state.request = payload
      if (overrides.throwOnPost) throw new Error('network failed')
      return state.response
    },
    isPageAlive: () => state.alive,
    isFlowCurrent: () => state.flowCurrent,
    normalizeQuestion: question => question ? ({ ...question, normalized: true }) : null,
    restoreDraft: questions => {
      state.restoredQuestions = questions
      return state.restored
    },
    getSession: () => state.session,
    setData: patch => { Object.assign(state.data, patch) },
    getCurrentBatchNo: () => state.currentBatchNo,
    getTotalBatchCount: () => state.totalBatchCount,
    getTodayDueCount: () => state.todayDueCount,
    getTodayCompletedCount: () => state.todayCompletedCount,
    getTodayRemainingCount: () => state.todayRemainingCount,
    syncAnsweredFlags: () => { state.callbacks.push('sync') },
    showQuestion: index => { state.callbacks.push(['show', index]) },
    startReviewTimer: () => { state.callbacks.push('start') },
    showToast: options => { state.toasts.push(options) },
    refreshOverviewStatsSilently: async () => { state.refreshed = true },
    ...overrides,
  })
  return { controller, state }
}

test('requests, normalizes, restores, and enters a remote batch', async () => {
  const { controller, state } = createHarness()
  state.response = {
    questions: [{ schedule_id: 1 }, null, { schedule_id: 2 }],
    batch_no: 5,
    total_batch_count: 9,
  }
  const result = await controller.next(7)

  assert.equal(result.status, 'entered')
  assert.deepEqual(state.request, { batch_size: 10 })
  assert.deepEqual(state.restoredQuestions, [
    { schedule_id: 1, normalized: true },
    { schedule_id: 2, normalized: true },
  ])
  assert.deepEqual(state.session.allQuestions, state.restoredQuestions)
  assert.equal(state.session.answers, state.restored.answers)
  assert.equal(state.data.phase, 'reviewing')
  assert.equal(state.data.currentBatchNo, 5)
  assert.equal(state.data.totalBatchCount, 9)
  assert.equal(state.data.todayDueCount, 8)
  assert.equal(state.data.resultTransitioning, false)
  assert.deepEqual(state.callbacks, ['sync', ['show', 1], 'start'])
  assert.deepEqual(state.toasts, [{ title: '已恢复 1 题草稿', icon: 'none' }])
})

test('falls back to current batch counters and suppresses empty draft toast', async () => {
  const { controller, state } = createHarness()
  state.response = { questions: [{ schedule_id: 1 }] }
  state.restored = { answers: {}, currentIndex: 0, restoredCount: 0 }
  await controller.next(7)

  assert.equal(state.data.currentBatchNo, 2)
  assert.equal(state.data.totalBatchCount, 2)
  assert.deepEqual(state.toasts, [])
})

test('asks for retry when an empty batch leaves remaining tasks', async () => {
  const { controller, state } = createHarness()
  const result = await controller.next(7)

  assert.equal(result.status, 'retry')
  assert.equal(state.refreshed, true)
  assert.deepEqual(state.toasts, [{ title: '任务状态已更新，请稍后重试', icon: 'none' }])
  assert.equal(state.data.resultTransitioning, false)
})

test('reports completion when an empty batch exhausts today tasks', async () => {
  const { controller, state } = createHarness()
  state.todayRemainingCount = 0
  const result = await controller.next(7)

  assert.equal(result.status, 'complete')
  assert.equal(state.refreshed, true)
  assert.deepEqual(state.toasts, [])
})

test('stops on stale responses and propagates request errors', async () => {
  const stale = createHarness()
  stale.state.response = { questions: [{ schedule_id: 1 }] }
  stale.state.flowCurrent = false
  assert.equal((await stale.controller.next(7)).status, 'dead')

  const emptyStale = createHarness()
  emptyStale.state.alive = false
  assert.equal((await emptyStale.controller.next(7)).status, 'dead')

  const failed = createHarness({ throwOnPost: true })
  await assert.rejects(() => failed.controller.next(7), /network failed/)
})
