const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPendingSubmissionController,
} = require('../subpackages/study/practice/utils/pending-submission-controller')

function harness(overrides = {}) {
  const state = {
    key: 'practice_pending_submission_v1:user',
    storage: new Map(),
    now: 1000,
    ttl: 100,
    pageAlive: true,
    confirms: [],
    warnings: [],
  }
  const options = {
    getStorageKey: () => state.key,
    readStorage: key => state.storage.get(key),
    writeStorage: (key, value) => state.storage.set(key, value),
    removeStorage: key => state.storage.delete(key),
    now: () => state.now,
    getTtlMs: () => state.ttl,
    isPageAlive: () => state.pageAlive,
    showConfirm: async options => { state.confirms.push(options); return state.confirmResult },
    logWarn: (...args) => state.warnings.push(args),
    restoreSubmittedSnapshot: (submission, resultUrl) => {
      state.restored = { submission, resultUrl }
    },
    resumePendingSubmission: async submission => {
      state.resumed = submission
      return state.resumeResult
    },
    ...overrides,
  }
  return { options, state, get controller() { return createPendingSubmissionController(options) } }
}

test('read validates version, freshness and removes expired records', () => {
  const h = harness()
  const item = {
    version: 1,
    createdAt: 900,
    updatedAt: 950,
    submission: { requestId: 'request' },
  }
  h.state.storage.set(h.state.key, item)
  assert.equal(h.controller.read(), item)

  h.state.now = 1051
  assert.equal(h.controller.read(), null)
  assert.equal(h.state.storage.has(h.state.key), false)

  h.state.storage.set(h.state.key, { version: 2, submission: {} })
  assert.equal(h.controller.read(), null)
  assert.equal(h.state.storage.has(h.state.key), true)
})

test('persist preserves createdAt for the same request and rolls back on failure', () => {
  const h = harness()
  h.state.storage.set(h.state.key, {
    version: 1,
    createdAt: 900,
    submission: { requestId: 'same' },
  })
  const submission = { requestId: 'same' }
  assert.equal(h.controller.persist(submission, 'pending', ''), true)
  assert.equal(submission.pendingPersisted, true)
  assert.equal(h.state.storage.get(h.state.key).createdAt, 900)

  const failed = harness({ writeStorage: () => { throw new Error('full') } })
  const failedSubmission = { requestId: 'next', pendingPersisted: false }
  assert.equal(failed.controller.persist(failedSubmission, 'pending', ''), false)
  assert.equal(failedSubmission.pendingPersisted, false)
  assert.equal(failed.state.warnings[0][0], '保存待确认交卷失败')
})

test('clear only removes an empty slot or the exact request', () => {
  const h = harness()
  h.controller.clear('request')
  assert.equal(h.state.storage.size, 0)

  h.state.storage.set(h.state.key, { submission: { requestId: 'other' } })
  h.controller.clear('request')
  assert.equal(h.state.storage.size, 1)
  h.controller.clear('other')
  assert.equal(h.state.storage.size, 0)
})

test('recovery restores submitted results, clears rejects and resumes pending submissions', async () => {
  const submitted = harness()
  submitted.state.confirmResult = true
  submitted.state.storage.set(submitted.state.key, {
    version: 1,
    createdAt: 900,
    updatedAt: 950,
    status: 'submitted',
    resultUrl: '/result',
    submission: { requestId: 'submitted' },
  })
  assert.equal(await submitted.controller.offerRecovery(), true)
  assert.equal(submitted.state.restored.resultUrl, '/result')

  const blocked = harness()
  blocked.state.confirmResult = true
  blocked.state.storage.set(blocked.state.key, {
    version: 1,
    createdAt: 900,
    updatedAt: 950,
    status: 'blocked',
    submission: { requestId: 'blocked' },
  })
  assert.equal(await blocked.controller.offerRecovery(), false)
  assert.equal(blocked.state.storage.size, 0)

  const pending = harness()
  pending.state.confirmResult = true
  pending.state.resumeResult = true
  pending.state.storage.set(pending.state.key, {
    version: 1,
    createdAt: 900,
    updatedAt: 950,
    status: 'pending',
    submission: { requestId: 'pending' },
  })
  assert.equal(await pending.controller.offerRecovery(), true)
  assert.equal(pending.state.resumed.requestId, 'pending')
})

test('cancelled or stale recovery does not mutate the page session', async () => {
  const cancelled = harness()
  cancelled.state.confirmResult = false
  cancelled.state.storage.set(cancelled.state.key, {
    version: 1,
    createdAt: 900,
    updatedAt: 950,
    status: 'submitted',
    resultUrl: '/result',
    submission: { requestId: 'submitted' },
  })
  assert.equal(await cancelled.controller.offerRecovery(), false)
  assert.equal(cancelled.state.restored, undefined)

  const stale = harness()
  stale.state.confirmResult = true
  stale.state.storage.set(stale.state.key, {
    version: 1,
    createdAt: 900,
    updatedAt: 950,
    status: 'submitted',
    resultUrl: '/result',
    submission: { requestId: 'submitted' },
  })
  stale.options.isPageAlive = () => false
  assert.equal(await stale.controller.offerRecovery(), false)
  assert.equal(stale.state.restored, undefined)
})
