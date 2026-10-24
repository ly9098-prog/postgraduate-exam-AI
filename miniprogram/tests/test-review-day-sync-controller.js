const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createReviewDaySyncController,
} = require('../subpackages/study/review-today/utils/day-sync-controller')

function harness(overrides = {}) {
  const state = {
    alive: true,
    sameDay: false,
    views: [],
    dateStrSet: false,
    toasts: [],
    errors: [],
  }
  const options = {
    isSameDay: () => state.sameDay,
    isPageAlive: () => state.alive,
    getOverview: async () => ({ date: '2026-10-25', remaining_question_ids: [1] }),
    buildOverviewVM: overview => ({ sourceDate: overview.date }),
    applyOverviewWithDayReset: () => {},
    setDateStr: () => { state.dateStrSet = true },
    setData: patch => { state.views.push(patch) },
    showSuccessToast: () => { state.toasts.push('success') },
    showFailureToast: () => { state.toasts.push('failure') },
    logError: (...args) => { state.errors.push(args) },
    ...overrides,
  }
  return { options, state, get controller() { return createReviewDaySyncController(options) } }
}

test('same-day sessions skip the network request', async () => {
  const h = harness()
  h.state.sameDay = true
  assert.equal(await h.controller.syncIfNeeded(), true)
  assert.deepEqual(h.state.views, [])
  assert.deepEqual(h.state.toasts, [])
})

test('changed day resets session state and updates the view', async () => {
  const h = harness()
  assert.equal(await h.controller.syncIfNeeded(), true)

  assert.deepEqual(h.state.views, [{ sourceDate: '2026-10-25' }])
  assert.equal(h.state.dateStrSet, true)
  assert.deepEqual(h.state.toasts, ['success'])
  assert.deepEqual(h.state.errors, [])
})

test('closed pages do not apply a changed-day response', async () => {
  const h = harness({
    getOverview: async () => {
      h.state.alive = false
      return { date: '2026-10-25' }
    },
  })
  assert.equal(await h.controller.syncIfNeeded(), false)
  assert.deepEqual(h.state.views, [])
  assert.equal(h.state.dateStrSet, false)
  assert.deepEqual(h.state.toasts, [])
})

test('sync failure keeps the user online-required state', async () => {
  const failure = new Error('network')
  const h = harness({ getOverview: async () => { throw failure } })
  assert.equal(await h.controller.syncIfNeeded(), false)
  assert.deepEqual(h.state.views, [])
  assert.deepEqual(h.state.toasts, ['failure'])
  assert.deepEqual(h.state.errors[0], ['跨天同步复习进度失败', failure])
})

test('closed pages suppress the failure toast', async () => {
  const h = harness({
    getOverview: async () => {
      h.state.alive = false
      throw new Error('network')
    },
  })
  assert.equal(await h.controller.syncIfNeeded(), false)
  assert.deepEqual(h.state.toasts, [])
  assert.deepEqual(h.state.errors, [])
})
