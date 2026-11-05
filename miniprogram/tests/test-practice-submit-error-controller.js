const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubmitErrorController,
} = require('../subpackages/study/practice/utils/submit-error-controller')

function harness(overrides = {}) {
  const state = {
    pageAlive: true,
    views: [],
    errors: [],
    confirms: [],
    loginPrompts: [],
    persisted: [],
    guards: [],
  }
  const submission = {
    pendingPersisted: false,
    retryBlocked: false,
  }
  const options = {
    isPageAlive: () => state.pageAlive,
    logError: (...args) => state.errors.push(args),
    pauseQuestionTiming: () => { state.questionTimingPaused = true },
    setData: view => { state.views.push(view) },
    isDeterministicReject: error => error.deterministic,
    persistPendingSubmission: (submission, status, resultUrl) => {
      state.persisted.push({ submission, status, resultUrl })
      return state.persistResult
    },
    setUnloadGuard: (enabled, message) => state.guards.push({ enabled, message }),
    resolveRejectMessage: code => ({ title: 'title-' + code, content: 'content-' + code }),
    showConfirm: async options => { state.confirms.push(options) },
    promptLogin: async options => { state.loginPrompts.push(options); return false },
    ...overrides,
  }
  return { options, state, submission, get controller() { return createSubmitErrorController(options) } }
}

test('deterministic rejects block retries and persist blocked state', async () => {
  const h = harness()
  h.state.persistResult = true
  assert.equal(await h.controller.handle(h.submission, { deterministic: true, code: 'PRACTICE_BATCH_INVALID' }), false)
  assert.equal(h.submission.retryBlocked, true)
  assert.equal(h.submission.pendingPersisted, true)
  assert.deepEqual(h.state.persisted[0], {
    submission: h.submission,
    status: 'blocked',
    resultUrl: '',
  })
  assert.deepEqual(h.state.guards, [{ enabled: true, message: '本次提交未通过。' }])
  assert.deepEqual(h.state.confirms, [{
    scenario: 'danger',
    title: 'title-PRACTICE_BATCH_INVALID',
    message: 'content-PRACTICE_BATCH_INVALID',
    showCancel: false,
    confirmText: '知道了',
    hideEyebrow: true,
  }])
})

test('retryable failures keep pending state and preserve previous persistence', async () => {
  const h = harness()
  h.state.persistResult = false
  assert.equal(await h.controller.handle(h.submission, { deterministic: false }), false)
  assert.equal(h.submission.retryBlocked, false)
  assert.equal(h.submission.pendingPersisted, false)
  assert.deepEqual(h.state.persisted[0], {
    submission: h.submission,
    status: 'pending',
    resultUrl: '',
  })
  assert.deepEqual(h.state.guards, [{ enabled: true, message: '交卷仍在确认中。' }])
  assert.equal(h.state.confirms[0].message, '暂未保存交卷进度，请保持当前页面并重试。')
})

test('stops silently when the page is no longer alive', async () => {
  const h = harness()
  h.state.pageAlive = false
  assert.equal(await h.controller.handle(h.submission, { deterministic: true }), false)
  assert.equal(h.state.questionTimingPaused, undefined)
  assert.equal(h.state.views.length, 0)
  assert.equal(h.state.persisted.length, 0)
  assert.equal(h.state.confirms.length, 0)
  assert.equal(h.state.loginPrompts.length, 0)
})

for (const error of [{ code: 'AUTH_REQUIRED' }, { statusCode: 401 }]) {
  for (const confirmed of [false, true]) {
    test(`authentication failure offers cancellable login and keeps pending submission (${JSON.stringify(error)}, ${confirmed})`, async () => {
      const h = harness()
      h.options.promptLogin = async options => {
        h.state.loginPrompts.push(options)
        return confirmed
      }
      h.state.persistResult = true
      const answers = [{ question_id: 1, user_answer: 'A' }]
      Object.assign(h.submission, { requestId: 'fixed', batchToken: 'batch', answers })
      assert.equal(await h.controller.handle(h.submission, error), false)
      assert.equal(h.state.loginPrompts.length, 1)
      assert.match(h.state.loginPrompts[0].content, /重新登录/)
      assert.match(h.state.loginPrompts[0].content, /手动/)
      assert.equal(h.state.confirms.length, 0)
      assert.equal(h.state.persisted[0].status, 'pending')
      assert.equal(h.submission.pendingPersisted, true)
      assert.equal(h.submission.retryBlocked, false)
      assert.equal(h.submission.requestId, 'fixed')
      assert.equal(h.submission.answers, answers)
      assert.deepEqual(h.state.views, [{ submitting: false }])
      assert.equal(h.state.guards[0].enabled, true)
    })
  }
}

test('authentication failure reports when progress could not be saved', async () => {
  const h = harness()
  h.state.persistResult = false
  await h.controller.handle(h.submission, { code: 'AUTH_REQUIRED' })
  assert.equal(h.state.loginPrompts.length, 1)
  assert.match(h.state.loginPrompts[0].content, /未能保存/)
  assert.match(h.state.loginPrompts[0].content, /暂不登录/)
})
