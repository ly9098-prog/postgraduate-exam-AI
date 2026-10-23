const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createNextGroupController,
} = require('../subpackages/study/review-today/utils/next-group-controller')

function createHarness(overrides = {}) {
  const state = {
    data: { resultTransitioning: false, todayRemainingCount: 1, currentGroupIdx: 0 },
    alive: true,
    flowCurrent: true,
    flowSeq: 0,
    syncDay: true,
    remoteCalled: false,
    syncCall: 0,
    retryEntered: false,
    remoteStatus: 'entered',
    undoCleared: 0,
    fadeCleared: 0,
    callbacks: [],
    logged: [],
    toasts: [],
    patches: [],
  }
  const controller = createNextGroupController({
    getData: () => state.data,
    setData: (patch, callback) => {
      state.patches.push(patch)
      Object.assign(state.data, patch)
      if (callback) callback()
    },
    clearMasterUndo: () => { state.undoCleared++ },
    clearResultDockFadeTimer: () => { state.fadeCleared++ },
    nextFlowSeq: () => ++state.flowSeq,
    isPageAlive: () => state.alive,
    isFlowCurrent: seq => state.flowCurrent && seq === state.flowSeq,
    syncReviewSessionDay: async () => {
      state.syncCall++
      if (state.overrideSync) return state.overrideSync()
      return state.syncDay
    },
    getCurrentGroupIdx: () => state.data.currentGroupIdx,
    getTodayRemainingCount: () => state.data.todayRemainingCount,
    retryGroupController: {
      enter: () => {
        state.retryEntered = true
        return overrides.retryEnter || false
      },
    },
    remoteBatchController: {
      next: async () => {
        state.remoteCalled = true
        if (overrides.throwOnRemote) throw new Error('network failed')
        return { status: state.remoteStatus }
      },
    },
    logError: (message, error) => { state.logged.push([message, error]) },
    showToast: options => { state.toasts.push(options) },
    showResultDockAndRefreshTimer: () => { state.callbacks.push('dock') },
    ...overrides,
  })
  return { controller, state }
}

test('clears transient state and blocks duplicate transitions', async () => {
  const { controller, state } = createHarness()
  assert.equal((await controller.next()).status, 'entered')
  assert.equal(state.undoCleared, 1)
  assert.equal(state.fadeCleared, 1)

  state.data.resultTransitioning = true
  assert.equal((await controller.next()).status, 'busy')
  assert.equal(state.flowSeq, 1)
})

test('enters a local retry group before requesting a remote batch', async () => {
  const { controller, state } = createHarness({ retryEnter: true })
  const result = await controller.next()

  assert.equal(result.status, 'retry-group')
  assert.equal(state.retryEntered, true)
  assert.equal(state.remoteCalled, false)
})

test('rolls back only a live current flow when day sync fails', async () => {
  const { controller, state } = createHarness()
  state.syncDay = false
  assert.equal((await controller.next()).status, 'sync-failed')
  assert.equal(state.data.resultTransitioning, false)

  const dead = createHarness()
  dead.state.syncDay = false
  dead.state.overrideSync = async () => { dead.state.alive = false; return false }
  assert.equal((await dead.controller.next()).status, 'sync-failed')
  assert.equal(dead.state.data.resultTransitioning, true)

  const stale = createHarness()
  stale.state.syncDay = false
  stale.state.flowCurrent = false
  stale.state.overrideSync = async () => { stale.state.flowCurrent = false; return false }
  assert.equal((await stale.controller.next()).status, 'sync-failed')
  assert.equal(stale.state.data.resultTransitioning, true)
})

test('returns remote statuses without overwriting them', async () => {
  const retry = createHarness({ retryEnter: true })
  assert.equal((await retry.controller.next()).status, 'retry-group')

  const remote = createHarness()
  remote.state.remoteStatus = 'retry'
  assert.equal((await remote.controller.next()).status, 'retry')

  const dead = createHarness()
  dead.state.remoteStatus = 'dead'
  assert.equal((await dead.controller.next()).status, 'dead')
})

test('handles remote errors and completion state', async () => {
  const failed = createHarness({ throwOnRemote: true })
  const error = new Error('network failed')
  assert.equal((await failed.controller.next()).status, 'error')
  assert.deepEqual(failed.state.logged, [['获取下一组失败', error]])
  assert.deepEqual(failed.state.toasts, [{ title: '获取下一组失败', icon: 'none' }])
  assert.equal(failed.state.data.resultTransitioning, false)

  const staleError = createHarness({ throwOnRemote: true })
  staleError.state.flowCurrent = false
  assert.equal((await staleError.controller.next()).status, 'dead')
  assert.deepEqual(staleError.state.logged, [])

  const complete = createHarness()
  complete.state.remoteStatus = 'complete'
  complete.state.data.todayRemainingCount = 0
  const result = await complete.controller.next()

  assert.equal(result.status, 'complete')
  assert.equal(complete.state.data.todayRemainingCount, 0)
  assert.equal(complete.state.data.resultTransitioning, false)
  assert.equal(complete.state.data.resultDockVisible, true)
  assert.deepEqual(complete.state.callbacks, ['dock'])

  const noRemaining = createHarness()
  noRemaining.state.data.todayRemainingCount = 0
  assert.equal((await noRemaining.controller.next()).status, 'complete')
  assert.equal(noRemaining.state.remoteCalled, false)
})
