const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDeferredHistoryController,
} = require('../subpackages/productivity/pomodoro-stats/deferred-history-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: true,
    requestId: 7,
    dateSeq: 3,
    selectedDate: '2026-10-24',
    timer: null,
    pending: null,
    patches: [],
    timers: [],
  }

  const options = {
    getTimer: () => state.timer,
    setTimer: timer => { state.timer = timer },
    getPending: () => state.pending,
    setPending: value => { state.pending = value },
    clearTimeout: timer => { state.timers.push(['clear', timer]) },
    setTimeout: (callback, delay) => {
      const handle = { callback, delay }
      state.timers.push(['set', handle])
      return handle
    },
    isAlive: () => state.alive,
    isVisible: () => state.visible,
    getRequestId: () => state.requestId,
    getDateRequestSeq: () => state.dateSeq,
    getSelectedDate: () => state.selectedDate,
    formatSession: item => ({ ...item, formatted: true }),
    setData: patch => state.patches.push(patch),
    ...overrides,
  }
  return { controller: createDeferredHistoryController(options), options, state }
}

function fireLatestTimer(state) {
  const timer = state.timer
  state.timer = null
  timer.callback()
}

test('queues a normalized history commit after 1300ms', () => {
  const harness = createHarness()

  harness.controller.queue(7, 3, '2026-10-24', [{ id: 1 }, { id: 2 }], '12')

  const [, timer] = harness.state.timers[0]
  assert.equal(timer.delay, 1300)
  assert.equal(harness.state.pending.total, 12)
  assert.deepEqual(harness.state.patches, [])

  fireLatestTimer(harness.state)
  assert.deepEqual(harness.state.patches, [{
    history: [
      { id: 1, formatted: true },
      { id: 2, formatted: true },
    ],
    historyTotal: 12,
    historyReady: true,
  }])
  assert.equal(harness.state.pending, null)
})

test('normalizes missing sessions and totals', () => {
  const harness = createHarness()
  harness.controller.queue(1, 1, '2026-10-24', null, null)
  assert.deepEqual(harness.state.pending, {
    reqId: 1,
    dateSeq: 1,
    selectedDate: '2026-10-24',
    sessions: [],
    total: 0,
  })
})

test('cancel clears the timer and optionally keeps the pending commit', () => {
  const harness = createHarness()
  harness.controller.queue(7, 3, '2026-10-24', [], 1)
  harness.controller.cancel(false)
  assert.equal(harness.state.timer, null)
  assert.ok(harness.state.pending)

  harness.controller.cancel(true)
  assert.equal(harness.state.pending, null)
})

test('queueing twice cancels the previous timer and commit', () => {
  const harness = createHarness()
  harness.controller.queue(7, 3, '2026-10-24', [], 1)
  const [, firstTimer] = harness.state.timers[0]
  harness.controller.queue(8, 4, '2026-10-25', [], 2)

  assert.deepEqual(harness.state.timers.map(([kind, value]) => [kind, value]), [
    ['set', firstTimer],
    ['clear', firstTimer],
    ['set', harness.state.timer],
  ])
  assert.equal(harness.state.pending.reqId, 8)
})

test('discards stale commits on request, date sequence, selected date, or lifecycle', () => {
  for (const key of ['alive', 'visible', 'requestId', 'dateSeq', 'selectedDate']) {
    const harness = createHarness()
    harness.controller.queue(7, 3, '2026-10-24', [{ id: 1 }], 1)
    if (key === 'requestId') harness.state.requestId = 8
    else if (key === 'dateSeq') harness.state.dateSeq = 4
    else if (key === 'selectedDate') harness.state.selectedDate = '2026-10-25'
    else harness.state[key] = false

    fireLatestTimer(harness.state)
    assert.deepEqual(harness.state.patches, [])
    assert.equal(harness.state.pending, null)
  }
})
