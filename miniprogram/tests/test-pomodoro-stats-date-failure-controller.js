const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDateFailureController,
} = require('../subpackages/productivity/pomodoro-stats/date-failure-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    dateSeq: 8,
    patches: [],
    logs: [],
    toasts: [],
  }
  const options = {
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getDateRequestSeq: () => state.dateSeq,
    logError: (message, error) => state.logs.push([message, error]),
    setData: patch => state.patches.push(patch),
    showToast: title => state.toasts.push(title),
    ...overrides,
  }
  const error = new Error('timeout')
  const context = {
    seq: state.dateSeq,
    logMessage: '加载指定日期数据失败',
    toastText: '该日期数据加载失败',
  }
  return { controller: createDateFailureController(options), options, state, context, error }
}

test('clears date loading and shows the failure toast', () => {
  const harness = createHarness()
  harness.controller.handle(harness.error, harness.context)
  assert.deepEqual(harness.state.logs, [['加载指定日期数据失败', harness.error]])
  assert.deepEqual(harness.state.patches, [{ pieLoading: false, durationValueAnimating: false }])
  assert.deepEqual(harness.state.toasts, ['该日期数据加载失败'])
})

test('discards stale, dead, or hidden date failures', () => {
  for (const key of ['alive', 'visible', 'dateSeq']) {
    const harness = createHarness()
    if (key === 'dateSeq') harness.state.dateSeq = 9
    else harness.state[key] = false

    harness.controller.handle(harness.error, harness.context)
    assert.deepEqual(harness.state.logs, [])
    assert.deepEqual(harness.state.patches, [])
    assert.deepEqual(harness.state.toasts, [])
  }
})
