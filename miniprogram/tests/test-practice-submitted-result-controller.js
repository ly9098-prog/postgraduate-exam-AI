const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubmittedResultController,
} = require('../subpackages/study/practice/utils/submitted-result-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    session: { submissionSnapshot: null },
    payload: { id: 'result' },
    pendingResultUrl: '',
    redirects: [],
    confirms: [],
    warnings: [],
    errors: [],
    views: [],
    guards: [],
    cacheWrites: [],
  }
  const controller = createSubmittedResultController({
    isPageAlive: () => state.alive,
    getSubmittedResultPayload: () => state.payload,
    writeResultCache: payload => {
      if (state.cacheWriteThrows) throw new Error('storage failed')
      state.cacheWrites.push(payload)
    },
    logWarn: (...args) => state.warnings.push(args),
    logError: (...args) => state.errors.push(args),
    showConfirm: options => state.confirms.push(options),
    getSession: () => state.session,
    setPendingResultUrl: value => { state.pendingResultUrl = value },
    setData: patch => state.views.push(patch),
    setUnloadGuard: enabled => state.guards.push(enabled),
    redirectTo: options => state.redirects.push(options),
    ...overrides,
  })
  return { controller, state }
}

test('ignores an empty result URL or dead page', () => {
  const empty = createHarness()
  empty.controller.open('', { requestId: 'req' })
  assert.deepEqual(empty.state.redirects, [])

  const dead = createHarness()
  dead.state.alive = false
  dead.controller.open('/result', { requestId: 'req' })
  assert.deepEqual(dead.state.redirects, [])
})

test('persists an unpersisted in-memory result before navigation', () => {
  const { controller, state } = createHarness()
  const submission = { keepPendingUntilResult: true, pendingPersisted: false }
  state.session.submissionSnapshot = submission

  controller.open('/result', submission)

  assert.deepEqual(state.cacheWrites, [{ id: 'result' }])
  assert.equal(submission.keepPendingUntilResult, false)
  assert.equal(state.pendingResultUrl, '/result')
  assert.equal(state.redirects[0].url, '/result')

  state.redirects[0].success()
  assert.equal(state.session.submissionSnapshot, null)
  assert.equal(state.pendingResultUrl, '')
})

test('does not rewrite the cache when the pending submission was already persisted', () => {
  const { controller, state } = createHarness()
  const submission = { keepPendingUntilResult: true, pendingPersisted: true }

  controller.open('/result', submission)

  assert.deepEqual(state.cacheWrites, [])
  assert.equal(submission.keepPendingUntilResult, true)
  assert.equal(state.redirects.length, 1)
})

test('warns and stops navigation when the fallback result cache write fails', () => {
  const { controller, state } = createHarness()
  const submission = { keepPendingUntilResult: true, pendingPersisted: false }
  state.cacheWriteThrows = true

  controller.open('/result', submission)

  assert.equal(state.warnings.length, 1)
  assert.equal(state.warnings[0][0], '结果缓存与待确认快照均不可持久化')
  assert.deepEqual(state.confirms, [{
    scenario: 'info',
    title: '复盘数据暂未保存',
    message: '成绩已保存。请保持当前页面，释放设备存储后再次打开复盘。',
    showCancel: false,
    confirmText: '知道了',
    hideEyebrow: true,
  }])
  assert.equal(state.pendingResultUrl, '')
  assert.deepEqual(state.redirects, [])
})

test('open remains synchronous and does not await the fallback prompt', () => {
  const { controller, state } = createHarness({
    showConfirm: options => {
      state.confirms.push(options)
      return new Promise(() => {})
    },
  })
  state.payload = null

  const result = controller.open('/result', {
    keepPendingUntilResult: true,
    pendingPersisted: false,
  })

  assert.equal(result, undefined)
  assert.equal(state.confirms.length, 1)
})

test('navigation failure restores the submitted view and guard', () => {
  const { controller, state } = createHarness()
  const submission = { pendingPersisted: true }

  controller.open('/result', submission)
  state.redirects[0].fail(new Error('redirect failed'))

  assert.deepEqual(state.errors[0][0], '结果页打开失败')
  assert.deepEqual(state.views, [{ submitting: false, submitted: true }])
  assert.deepEqual(state.guards, [false])
  assert.equal(state.confirms[0].message, '成绩已保存，可稍后再次打开复盘。')
})

test('navigation failure evaluates persistence when the callback fires', () => {
  const { controller, state } = createHarness()
  const submission = { pendingPersisted: false }

  controller.open('/result', submission)
  submission.pendingPersisted = true
  state.redirects[0].fail(new Error('redirect failed'))

  assert.equal(state.confirms[0].message, '成绩已保存，可稍后再次打开复盘。')
})

test('navigation failure after page death stops view updates', () => {
  const { controller, state } = createHarness()
  controller.open('/result', {})
  state.alive = false
  state.redirects[0].fail(new Error('redirect failed'))

  assert.equal(state.errors.length, 1)
  assert.deepEqual(state.views, [])
  assert.deepEqual(state.guards, [])
  assert.deepEqual(state.confirms, [])
})

test('navigation success only clears the matching submission snapshot', () => {
  const { controller, state } = createHarness()
  const submission = { requestId: 'same' }
  state.session.submissionSnapshot = { requestId: 'other' }

  controller.open('/result', submission)
  state.redirects[0].success()

  assert.deepEqual(state.session.submissionSnapshot, { requestId: 'other' })
  assert.equal(state.pendingResultUrl, '')
})
