const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubmitSuccessController,
} = require('../subpackages/study/practice/utils/submit-success-controller')

function createHarness(overrides = {}) {
  const state = {
    nowValue: 123,
    traceId: 'trace-page',
    launchSource: 'home',
    launchReturnTo: '/dashboard',
    submittedPayload: null,
    pendingResultUrl: '',
    cacheWrites: [],
    warnings: [],
    persisted: [],
    guards: [],
    views: [],
    opened: [],
    events: [],
  }
  const submission = {
    requestId: 'request-1',
    partialQuestionIds: [2],
    pendingPersisted: false,
    retryBlocked: true,
  }
  const controller = createSubmitSuccessController({
    getCurrentUserId: () => 'user-1',
    now: () => state.nowValue,
    buildCacheKey: createdAt => `pr_${createdAt}_abc`,
    getTraceId: () => state.traceId,
    buildResultPayload: options => ({
      correct: 3,
      wrong: 1,
      skipped: 1,
      total: 5,
      subject_id: 12,
      subject_name: '数据结构',
      duration: 120,
      _cacheKey: options.cacheKey,
      _userId: options.userId,
      _createdAt: options.createdAt,
    }),
    setSubmittedResultPayload: payload => { state.submittedPayload = payload },
    writeResultCache: payload => {
      state.events.push(['cache-write', state.submittedPayload === payload])
      if (state.cacheWriteThrows) throw new Error('storage failed')
      state.cacheWrites.push(payload)
    },
    logWarn: (...args) => state.warnings.push(args),
    buildResultUrl: options => options,
    getLaunchSource: () => state.launchSource,
    getLaunchReturnTo: () => state.launchReturnTo,
    setPendingResultUrl: value => { state.pendingResultUrl = value },
    persistPendingSubmission: (submission, status, resultUrl) => {
      state.events.push(['persist', {
        keepPendingUntilResult: submission.keepPendingUntilResult,
        pendingResultUrl: state.pendingResultUrl,
        resultUrl,
      }])
      state.persisted.push({ submission, status, resultUrl })
      return state.persistResult
    },
    setUnloadGuard: enabled => state.guards.push(enabled),
    setData: patch => state.views.push(patch),
    openSubmittedResult: (resultUrl, submission) => state.opened.push({ resultUrl, submission }),
    ...overrides,
  })
  return { controller, state, submission }
}

test('builds, persists and opens a successful result', () => {
  const { controller, state, submission } = createHarness()
  state.persistResult = true
  const submitResult = { id: 'server' }
  const questions = [{ id: 1 }]

  controller.complete(submission, submitResult, questions)

  assert.equal(submission.serverAccepted, true)
  assert.equal(submission.retryBlocked, false)
  assert.equal(submission.keepPendingUntilResult, false)
  assert.equal(submission.pendingPersisted, true)
  assert.deepEqual(state.cacheWrites, [state.submittedPayload])
  assert.equal(state.submittedPayload._cacheKey, 'pr_123_abc')
  assert.equal(state.submittedPayload._userId, 'user-1')
  assert.equal(state.submittedPayload._createdAt, 123)
  assert.deepEqual(state.persisted, [{
    submission,
    status: 'submitted',
    resultUrl: state.pendingResultUrl,
  }])
  assert.deepEqual(state.guards, [false])
  assert.deepEqual(state.views, [{ submitting: false, submitted: true }])
  assert.deepEqual(state.opened, [{
    resultUrl: state.pendingResultUrl,
    submission,
  }])
  assert.equal(state.pendingResultUrl.partial, 1)
  assert.equal(state.pendingResultUrl.skipped, 1)
  assert.equal(state.pendingResultUrl.resultCacheStored, true)
  assert.equal(state.pendingResultUrl.source, 'home')
  assert.equal(state.pendingResultUrl.returnTo, '/dashboard')
})

test('sets the in-memory payload before attempting the result cache write', () => {
  const { controller, state, submission } = createHarness()
  state.cacheWriteThrows = true
  state.persistResult = true

  controller.complete(submission, {}, [])

  assert.equal(state.submittedPayload._cacheKey, 'pr_123_abc')
  assert.deepEqual(state.events[0], ['cache-write', true])
  assert.equal(state.warnings.length, 1)
  assert.equal(submission.keepPendingUntilResult, true)
  assert.equal(submission.pendingPersisted, true)
  assert.deepEqual(state.persisted, [{
    submission,
    status: 'submitted',
    resultUrl: state.pendingResultUrl,
  }])
  assert.equal(state.pendingResultUrl.resultCacheStored, false)
  assert.equal(state.opened.length, 1)
})

test('updates pending-result state before persisting the submitted snapshot', () => {
  const { controller, state, submission } = createHarness()

  controller.complete(submission, {}, [])

  assert.deepEqual(state.events[1], ['persist', {
    keepPendingUntilResult: false,
    pendingResultUrl: state.pendingResultUrl,
    resultUrl: state.pendingResultUrl,
  }])
})

test('keeps pending-until-result fallback when the cache write fails', () => {
  const { controller, state, submission } = createHarness()
  state.cacheWriteThrows = true
  state.persistResult = false

  controller.complete(submission, {}, [])

  assert.equal(state.warnings.length, 1)
  assert.equal(state.warnings[0][0], '答题已提交成功，但本地结果缓存失败')
  assert.equal(submission.keepPendingUntilResult, true)
  assert.equal(submission.pendingPersisted, false)
  assert.equal(state.pendingResultUrl.resultCacheStored, false)
  assert.equal(state.opened.length, 1)
})

test('preserves an earlier pending persistence flag when the new write fails', () => {
  const { controller, state, submission } = createHarness()
  state.cacheWriteThrows = true
  state.persistResult = false
  submission.pendingPersisted = true

  controller.complete(submission, {}, [])

  assert.equal(submission.pendingPersisted, true)
})
