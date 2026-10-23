const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSequentialRestartController,
} = require('../subpackages/study/practice/utils/sequential-restart-controller')

function harness(overrides = {}) {
  const state = {
    session: { traceId: 'trace-1' },
    views: [],
    calls: [],
    pageAlive: true,
    requestSeq: 1,
    confirmResult: true,
    resetError: null,
  }
  const options = {
    clearTimer: () => state.calls.push('clearTimer'),
    setUnloadGuard: value => state.calls.push(['unload', value]),
    setData: view => { state.views.push(view) },
    buildResetView: () => ({ reset: true }),
    showRestartConfirm: async view => {
      state.confirm = view
      return state.confirmResult
    },
    isPageAlive: () => state.pageAlive,
    getRequestSeq: () => state.requestSeq,
    getTraceId: () => state.session.traceId,
    resetSequentialProgress: async payload => {
      state.resetPayload = payload
      if (state.resetError) throw state.resetError
    },
    logError: (...args) => { state.errors = args },
    showToast: view => { state.toast = view },
    getSession: () => state.session,
    resetSequentialTiming: session => Object.assign(session, {
      activeStartedMonoMs: 0,
      startedAtMs: 0,
      backgroundMs: 0,
      _backgroundStartedMonoMs: null,
    }),
    buildSequentialRestartView: () => ({ restart: true }),
    reloadQuestions: async () => state.calls.push('reload'),
    ...overrides,
  }
  return { options, state, get controller() { return createSequentialRestartController(options) } }
}

test('restarts a completed sequential cycle with original prompt and guards', async () => {
  const h = harness()
  const session = h.state.session
  const result = await h.controller.restart({
    total_questions: 12,
  }, 12, '数据结构', 1)
  assert.equal(result, true)
  assert.deepEqual(h.state.calls, ['clearTimer', ['unload', false], ['unload', true], 'reload'])
  assert.deepEqual(h.state.views, [{ reset: true }, { restart: true }])
  assert.equal(h.state.confirm.title, '本轮顺序刷题已完成')
  assert.equal(h.state.confirm.message.includes('「数据结构」本轮 12 题'), true)
  assert.deepEqual(h.state.resetPayload, { subject_id: 12, _traceId: 'trace-1' })
  assert.deepEqual(session, {
    traceId: 'trace-1',
    activeStartedMonoMs: 0,
    startedAtMs: 0,
    backgroundMs: 0,
    _backgroundStartedMonoMs: null,
  })
})

test('cancel, stale response and unload stop the restart flow', async () => {
  const cancelled = harness()
  cancelled.state.confirmResult = false
  assert.equal(await cancelled.controller.restart({ total_questions: 1 }, 1, '', 1), false)
  assert.deepEqual(cancelled.state.calls, ['clearTimer', ['unload', false]])

  const stale = harness()
  stale.state.requestSeq = 2
  assert.equal(await stale.controller.restart({ total_questions: 1 }, 1, '', 1), false)
  assert.equal(stale.state.resetPayload, undefined)

  const hidden = harness()
  hidden.options.isPageAlive = () => false
  assert.equal(await hidden.controller.restart({ total_questions: 1 }, 1, '', 1), false)
  assert.equal(hidden.state.resetPayload, undefined)
})

test('reset failure and stale failure paths preserve original messaging', async () => {
  const failed = harness()
  failed.state.resetError = new Error('network')
  assert.equal(await failed.controller.restart({ total_questions: 1 }, 1, '', 1), false)
  assert.deepEqual(failed.state.views, [{ reset: true }, { errorText: '重置进度失败，请稍后重试' }])
  assert.deepEqual(failed.state.toast, { title: '重置进度失败', icon: 'none' })
  assert.equal(failed.state.errors[0], '重置顺序刷题进度失败')

  const staleFailure = harness()
  staleFailure.state.resetError = new Error('network')
  staleFailure.state.requestSeq = 2
  assert.equal(await staleFailure.controller.restart({ total_questions: 1 }, 1, '', 1), false)
  assert.deepEqual(staleFailure.state.views, [{ reset: true }])
  assert.equal(staleFailure.state.toast, undefined)
})
