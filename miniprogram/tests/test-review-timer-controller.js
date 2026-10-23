const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createReviewTimerController,
  safeReviewTickDelta,
} = require('../subpackages/study/review-today/utils/review-timer-controller')

const toIso = ms => new Date(ms).toISOString()

function createHarness() {
  const state = {
    session: {
      timerElapsedMs: 0,
      timerStartedAt: 0,
      timerLastTickAt: 0,
      timerRunning: false,
      timingSegmentId: '',
      timingStartedAtMs: 0,
    },
    alive: true,
    now: 10000,
    serverNow: 1000000,
    timerId: null,
    ticks: [],
    data: {},
  }
  const controller = createReviewTimerController({
    getSession: () => state.session,
    isPageAlive: () => state.alive,
    monotonicNow: () => state.now,
    serverNow: () => state.serverNow,
    getTimerId: () => state.timerId,
    setTimerId: id => { state.timerId = id },
    setInterval: callback => {
      state.ticks.push(callback)
      return state.ticks.length
    },
    clearInterval: id => { state.cleared = id },
    setData: patch => { Object.assign(state.data, patch) },
    formatElapsed: seconds => `${seconds}s`,
    createRequestId: () => 'request-id',
  })
  return { controller, state }
}

test('clamps tick deltas to a ten second window', () => {
  assert.equal(safeReviewTickDelta(-1), 0)
  assert.equal(safeReviewTickDelta(1000), 1000)
  assert.equal(safeReviewTickDelta(10001), 10000)
})

test('starts a fresh timer and updates elapsed state on each live tick', () => {
  const { controller, state } = createHarness()
  controller.start()
  assert.deepEqual(state.session, {
    timerElapsedMs: 0,
    timerStartedAt: 10000,
    timerLastTickAt: 10000,
    timerRunning: true,
    timingSegmentId: '',
    timingStartedAtMs: 1000000,
  })
  assert.equal(state.ticks.length, 1)
  assert.equal(state.timerId, 1)

  controller.start()
  assert.equal(state.ticks.length, 1)

  state.now = 11500
  state.ticks[0]()
  assert.equal(state.session.timerElapsedMs, 1500)
  assert.equal(state.session.timerLastTickAt, 11500)
  assert.deepEqual(state.data, { elapsedText: '1s' })

  state.alive = false
  state.now = 13000
  state.ticks[0]()
  assert.equal(state.session.timerLastTickAt, 11500)
})

test('pause and resume preserve elapsed time while replacing interval ownership', () => {
  const { controller, state } = createHarness()
  controller.start()
  state.now = 13000
  controller.pause()
  assert.equal(state.session.timerElapsedMs, 3000)
  assert.equal(state.session.timerLastTickAt, 0)
  assert.equal(state.session.timerRunning, false)
  assert.equal(state.timerId, null)
  assert.equal(state.cleared, 1)

  controller.pause()
  assert.equal(state.session.timerElapsedMs, 3000)

  state.now = 14000
  controller.resume()
  assert.equal(state.session.timerElapsedMs, 3000)
  assert.equal(state.session.timerStartedAt, 14000)
  assert.equal(state.session.timerLastTickAt, 14000)
  assert.equal(state.session.timerRunning, true)
  assert.equal(state.timerId, 2)

  controller.resume()
  assert.equal(state.ticks.length, 2)
})

test('reset clears time and view while clear only stops the interval', () => {
  const reset = createHarness()
  reset.controller.start()
  reset.state.now = 12000
  reset.controller.reset()
  assert.deepEqual(reset.state.session, {
    timerElapsedMs: 0,
    timerStartedAt: 0,
    timerLastTickAt: 0,
    timerRunning: false,
    timingSegmentId: '',
    timingStartedAtMs: 1000000,
  })
  assert.deepEqual(reset.state.data, { elapsedText: '00:00' })

  const clear = createHarness()
  clear.controller.start()
  clear.state.now = 12000
  clear.controller.clear()
  assert.equal(clear.state.timerId, null)
  assert.equal(clear.state.session.timerElapsedMs, 0)
  assert.equal(clear.state.session.timerStartedAt, 10000)
  assert.equal(clear.state.session.timerLastTickAt, 0)
  assert.equal(clear.state.session.timerRunning, false)
})

test('builds and reuses immutable timing snapshots', () => {
  const { controller, state } = createHarness()
  assert.equal(controller.buildTimingSession(), null)

  controller.start()
  assert.equal(controller.buildTimingSession(), null)

  state.session.timerElapsedMs = 1500
  state.session.timerRunning = true
  state.session.timerLastTickAt = 10000
  state.now = 11500
  state.serverNow = 2000000
  const first = controller.buildTimingSession()
  assert.deepEqual(first, {
    request_id: 'request-id',
    started_at: toIso(1000000),
    finished_at: toIso(2000000),
    duration_sec: 3,
  })
  assert.equal(state.session.timingSegmentId, 'request-id')

  state.serverNow = 2001000
  const second = controller.buildTimingSession()
  assert.equal(second.request_id, first.request_id)
  // A retry keeps the same rounded duration and request id for server idempotency.
  assert.equal(second.duration_sec, first.duration_sec)
})
