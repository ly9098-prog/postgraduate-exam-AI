const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLoadFailureController,
} = require('../subpackages/productivity/pomodoro-stats/load-failure-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    requestId: 3,
    dateSeq: 2,
    selectedDate: '2026-10-24',
    contentReady: true,
    patches: [],
    logs: [],
  }
  const options = {
    isAlive: () => state.alive,
    getRequestId: () => state.requestId,
    getDateRequestSeq: () => state.dateSeq,
    getSelectedDate: () => state.selectedDate,
    isContentReady: () => state.contentReady,
    logError: (message, error) => state.logs.push([message, error]),
    setData: patch => state.patches.push(patch),
    ...overrides,
  }
  const error = new Error('network')
  const context = {
    background: true,
    logMessage: '加载统计失败',
    errorText: '加载失败，请检查网络后重试',
    reqId: state.requestId,
    dateSeq: state.dateSeq,
    requestedDate: state.selectedDate,
  }
  return { controller: createLoadFailureController(options), options, state, context, error }
}

test('keeps the last valid snapshot when a background refresh fails', () => {
  const harness = createHarness()
  harness.controller.handle(harness.error, harness.context)
  assert.deepEqual(harness.state.logs, [['加载统计失败', harness.error]])
  assert.deepEqual(harness.state.patches, [{
    loading: false,
    pieLoading: false,
    cumulativeLoading: false,
  }])
})

test('shows the full error state on a foreground failure', () => {
  const harness = createHarness()
  harness.context.background = false
  harness.controller.handle(harness.error, harness.context)
  assert.deepEqual(harness.state.patches, [{
    loading: false,
    pieLoading: false,
    cumulativeLoading: false,
    errorText: '加载失败，请检查网络后重试',
  }])
})

test('shows the full error state when no valid snapshot is ready', () => {
  const harness = createHarness()
  harness.state.contentReady = false
  harness.controller.handle(harness.error, harness.context)
  assert.deepEqual(harness.state.patches, [{
    loading: false,
    pieLoading: false,
    cumulativeLoading: false,
    errorText: '加载失败，请检查网络后重试',
  }])
})

test('discards stale failures', () => {
  for (const key of ['alive', 'requestId', 'dateSeq', 'selectedDate']) {
    const harness = createHarness()
    if (key === 'requestId') harness.state.requestId = 4
    else if (key === 'dateSeq') harness.state.dateSeq = 3
    else if (key === 'selectedDate') harness.state.selectedDate = '2026-10-25'
    else harness.state[key] = false

    harness.controller.handle(harness.error, harness.context)
    assert.deepEqual(harness.state.logs, [])
    assert.deepEqual(harness.state.patches, [])
  }
})
