const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPaperCancelResumeController,
} = require('../subpackages/exam/utils/paper-cancel-resume-controller')

function harness(overrides = {}) {
  const calls = {
    confirms: [],
    abandons: [],
    cacheClears: [],
    optimisticClears: [],
    reconciles: [],
    refreshes: [],
    mismatchRefreshes: [],
    toasts: [],
    cancellingIds: [],
    errorMessages: [],
  }
  const state = {
    pageAlive: true,
    startingId: 0,
    cancellingAttemptId: 0,
    papers: [{
      id: 11,
      canResume: true,
      latest_attempt_id: 55,
    }],
    confirmResult: true,
    abandonResult: { id: 55, status: 'abandoned' },
    abandonError: null,
    reconcileStatus: '',
  }
  const options = {
    getStartingId: () => state.startingId,
    getCancellingAttemptId: () => state.cancellingAttemptId,
    setCancellingAttemptId: value => {
      state.cancellingAttemptId = value
      calls.cancellingIds.push(value)
    },
    isPageAlive: () => state.pageAlive,
    findPaper: paperId => state.papers.find(item => Number(item.id) === paperId),
    refreshAfterStateMismatch: async () => { calls.mismatchRefreshes.push(true) },
    confirmCancel: async () => { calls.confirms.push(true); return state.confirmResult },
    abandonAttempt: async attemptId => {
      calls.abandons.push(attemptId)
      if (state.abandonError) throw state.abandonError
      return state.abandonResult
    },
    clearAttemptCache: attemptId => calls.cacheClears.push(attemptId),
    optimisticallyClearResume: (paperId, attemptId) =>
      calls.optimisticClears.push({ paperId, attemptId }),
    refreshAfterCancel: async () => { calls.refreshes.push(true) },
    reconcileAttemptCache: async attemptId => {
      calls.reconciles.push(attemptId)
      return state.reconcileStatus
    },
    getErrorMessage: error => `msg:${error && error.message}`,
    showToast: payload => calls.toasts.push(payload),
    ...overrides.options,
  }
  return {
    state,
    options,
    calls,
    get controller() { return createPaperCancelResumeController(options) },
  }
}

function event(paperId = 11, attemptId = 55) {
  return { currentTarget: { dataset: { id: paperId, attemptId } } }
}

test(
  'happy path validates paper, confirms, abandons, clears cache, refreshes and resets flag',
  async () => {
    const h = harness()
    await h.controller.cancel(event())
    assert.deepEqual(h.calls.confirms, [true])
    assert.deepEqual(h.calls.abandons, [55])
    assert.deepEqual(h.calls.cacheClears, [55])
    assert.deepEqual(h.calls.optimisticClears, [{ paperId: 11, attemptId: 55 }])
    assert.deepEqual(h.calls.refreshes, [true])
    assert.deepEqual(h.calls.toasts, [{ title: '已取消本次作答', icon: 'success' }])
    assert.deepEqual(h.calls.cancellingIds, [55, 0])
    assert.deepEqual(h.calls.mismatchRefreshes, [])
  }
)

test('invalid ids and busy page state are rejected without side effects', async () => {
  const h = harness()
  await h.controller.cancel({ currentTarget: { dataset: {} } })
  await h.controller.cancel(event(0, 55))
  await h.controller.cancel(event(11, 0))
  h.state.startingId = 9
  await h.controller.cancel(event())
  h.state.startingId = 0
  h.state.cancellingAttemptId = 77
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.confirms, [])
  assert.deepEqual(h.calls.abandons, [])
  assert.deepEqual(h.calls.cancellingIds, [])
})

test('paper mismatch or non-resume triggers silent force refresh only', async () => {
  const h = harness()
  h.state.papers = []
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.mismatchRefreshes, [true])
  assert.deepEqual(h.calls.confirms, [])
  assert.deepEqual(h.calls.abandons, [])

  const noResume = harness()
  noResume.state.papers[0].canResume = false
  await noResume.controller.cancel(event())
  assert.deepEqual(noResume.calls.mismatchRefreshes, [true])

  const wrongAttempt = harness()
  wrongAttempt.state.papers[0].latest_attempt_id = 66
  await wrongAttempt.controller.cancel(event())
  assert.deepEqual(wrongAttempt.calls.mismatchRefreshes, [true])
})

test('declined confirmation or dead page stops before setting cancelling flag', async () => {
  const declined = harness()
  declined.state.confirmResult = false
  await declined.controller.cancel(event())
  assert.deepEqual(declined.calls.confirms, [true])
  assert.deepEqual(declined.calls.abandons, [])
  assert.deepEqual(declined.calls.cancellingIds, [])

  const dead = harness()
  dead.state.pageAlive = false
  await dead.controller.cancel(event())
  assert.deepEqual(dead.calls.cancellingIds, [])
  assert.deepEqual(dead.calls.abandons, [])
})

test('invalid abandon response is treated as an error and preserves cache', async () => {
  const h = harness()
  h.state.abandonResult = { id: 55, status: 'submitted' }
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.abandons, [55])
  assert.deepEqual(h.calls.cacheClears, [])
  assert.deepEqual(h.calls.optimisticClears, [])
  assert.equal(h.calls.toasts[0].title, 'msg:INVALID_ABANDON_RESPONSE')
  assert.deepEqual(h.calls.cancellingIds, [55, 0])
})

test('server error shows the safe message and resets the cancelling flag', async () => {
  const h = harness()
  h.state.abandonError = new Error('network')
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.cacheClears, [])
  assert.deepEqual(h.calls.optimisticClears, [])
  assert.deepEqual(h.calls.toasts, [{ title: 'msg:network', icon: 'none' }])
  assert.deepEqual(h.calls.cancellingIds, [55, 0])
})

test('409 error reconciles attempt cache before silent force refresh and toast', async () => {
  const h = harness()
  h.state.abandonError = { statusCode: 409, message: 'conflict' }
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.cacheClears, [])
  assert.deepEqual(h.calls.reconciles, [55])
  assert.deepEqual(h.calls.refreshes, [true])
  assert.deepEqual(h.calls.toasts, [{ title: '作答状态已变化，请重新确认', icon: 'none' }])
  assert.deepEqual(h.calls.cancellingIds, [55, 0])
})

test('dead page during abandon prevents optimistic update, refresh and toast', async () => {
  const h = harness()
  h.options.isPageAlive = () => {
    // Alive during validation and abandon, dead after the server accepts.
    return h.calls.abandons.length === 0
  }
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.abandons, [55])
  // The server durably accepted, so the cache is cleared before the guard.
  assert.deepEqual(h.calls.cacheClears, [55])
  assert.deepEqual(h.calls.optimisticClears, [])
  assert.deepEqual(h.calls.refreshes, [])
  assert.deepEqual(h.calls.toasts, [])
})

test('dead page after cache clear still prevents optimistic update and refresh', async () => {
  const h = harness()
  h.options.isPageAlive = () => h.calls.cacheClears.length === 0
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.cacheClears, [55])
  assert.deepEqual(h.calls.optimisticClears, [])
  assert.deepEqual(h.calls.refreshes, [])
})

test('cancelling flag is only reset when the page still owns the attempt', async () => {
  const h = harness()
  h.state.abandonError = new Error('network')
  // Simulate a newer action changing the flag after our request set it.
  h.options.setCancellingAttemptId = value => {
    if (value === 55) {
      h.state.cancellingAttemptId = 99
      h.calls.cancellingIds.push(value)
    } else if (h.state.cancellingAttemptId === 55) {
      h.state.cancellingAttemptId = value
      h.calls.cancellingIds.push(value)
    }
  }
  await h.controller.cancel(event())
  assert.deepEqual(h.calls.cancellingIds, [55]) // no reset because ownership changed
  assert.equal(h.state.cancellingAttemptId, 99)
})
