const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPracticeSessionTimerController,
} = require('../subpackages/study/practice/utils/practice-session-timer-controller')
const {
  createPracticeSessionTimerPageController,
} = require('../subpackages/study/practice/utils/practice-session-timer-page-adapter')

function createHarness(overrides = {}) {
  const calls = {
    cleared: [],
    setData: [],
    elapsedText: [],
  }
  let timer = null
  let scheduled = null
  const session = {
    activeStartedMonoMs: 100,
    backgroundMs: 0,
    _backgroundStartedMonoMs: null,
    elapsedSec: 0,
    ...overrides.session,
  }
  const controller = createPracticeSessionTimerController({
    getSession: () => session,
    isPageAlive: () => overrides.pageAlive !== false,
    monotonicNow: () => overrides.now || 1100,
    getTimer: () => timer,
    setTimer: value => {
      timer = value
    },
    setInterval: (callback, delay) => {
      scheduled = { callback, delay }
      return 'timer-1'
    },
    clearInterval: value => calls.cleared.push(value),
    formatElapsed: seconds => {
      calls.elapsedText.push(seconds)
      return `formatted:${seconds}`
    },
    setData: patch => calls.setData.push(patch),
  })
  return { calls, controller, session, get timer() { return timer }, get scheduled() { return scheduled } }
}

test('start clears an existing timer and schedules the 1 second loop', () => {
  const harness = createHarness()
  harness.controller.start()

  assert.equal(harness.scheduled.delay, 1000)
  assert.equal(harness.timer, 'timer-1')
  harness.controller.start()
  assert.deepEqual(harness.calls.cleared, ['timer-1'])
  assert.equal(harness.timer, 'timer-1')
})

test('tick skips inactive pages and sessions without an active start', () => {
  const dead = createHarness({ pageAlive: false })
  dead.controller.start()
  dead.scheduled.callback()
  assert.deepEqual(dead.calls.elapsedText, [])

  const inactive = createHarness({ session: { activeStartedMonoMs: 0 } })
  inactive.controller.start()
  inactive.scheduled.callback()
  assert.deepEqual(inactive.calls.elapsedText, [])
})

test('tick applies background exclusion and publishes elapsed text', () => {
  const harness = createHarness({
    now: 3000,
    session: {
      activeStartedMonoMs: 100,
      backgroundMs: 250,
      _backgroundStartedMonoMs: 1500,
    },
  })
  harness.controller.start()
  harness.scheduled.callback()

  assert.equal(harness.session.elapsedSec, 1)
  assert.deepEqual(harness.calls.elapsedText, [1])
  assert.deepEqual(harness.calls.setData, [{ elapsedText: 'formatted:1' }])
})

test('stop clears only a live timer and resets the page timer id', () => {
  const harness = createHarness()
  harness.controller.start()
  harness.controller.stop()

  assert.deepEqual(harness.calls.cleared, ['timer-1'])
  assert.equal(harness.timer, null)
  harness.controller.stop()
  assert.deepEqual(harness.calls.cleared, ['timer-1'])
})

test('page adapter binds page state, formatting and timer storage', () => {
  const calls = []
  const page = {
    _pageAlive: true,
    _practiceSession: {
      activeStartedMonoMs: 100,
      backgroundMs: 0,
      _backgroundStartedMonoMs: null,
      elapsedSec: 0,
    },
    _timer: null,
    _fmt: seconds => {
      calls.push(['format', seconds])
      return `page:${seconds}`
    },
    setData: patch => calls.push(['setData', patch]),
  }
  const scheduled = []
  const controller = createPracticeSessionTimerPageController(
    page,
    () => 1100,
    {
      setInterval: (callback, delay) => {
        scheduled.push({ callback, delay })
        return 'page-timer'
      },
      clearInterval: timer => calls.push(['clear', timer]),
    },
  )

  controller.start()
  assert.equal(page._timer, 'page-timer')
  assert.equal(scheduled[0].delay, 1000)
  scheduled[0].callback()
  assert.deepEqual(calls, [
    ['format', 1],
    ['setData', { elapsedText: 'page:1' }],
  ])
  controller.stop()
  assert.deepEqual(calls.at(-1), ['clear', 'page-timer'])
  assert.equal(page._timer, null)
})
