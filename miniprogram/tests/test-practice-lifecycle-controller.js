const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPracticeLifecycleController,
} = require('../subpackages/study/practice/utils/practice-lifecycle-controller')
const {
  createPracticeLifecyclePageController,
} = require('../subpackages/study/practice/utils/practice-lifecycle-page-adapter')

function createHarness(overrides = {}) {
  const calls = []
  const session = {
    activeStartedMonoMs: 100,
    _backgroundStartedMonoMs: null,
    _timingPauseActive: false,
    backgroundMs: 0,
    currentQuestionStartedMonoMs: 0,
    ...overrides.session,
  }
  const clock = {
    now: 500,
    calls: 0,
  }
  const controller = createPracticeLifecycleController({
    getSession: () => session,
    monotonicNow: () => {
      clock.calls += 1
      return clock.now
    },
    isQuestionActive: value => Boolean(value && value.isActive),
    settleQuestionTime: pause => calls.push(['settle', pause]),
  })
  return { controller, session, clock, calls }
}

test('show repairs background time and resets the current question start', () => {
  const harness = createHarness({
    session: {
      _backgroundStartedMonoMs: 200,
      isActive: true,
    },
  })
  harness.clock.now = 500
  harness.session.currentQuestionStartedMonoMs = 300

  harness.controller.show()

  assert.equal(harness.session.backgroundMs, 300)
  assert.equal(harness.session._backgroundStartedMonoMs, null)
  assert.equal(harness.session.currentQuestionStartedMonoMs, 500)
  assert.equal(harness.clock.calls, 2)
})

test('show is a no-op while timing pause is active', () => {
  const harness = createHarness({
    session: {
      _timingPauseActive: true,
      _backgroundStartedMonoMs: 200,
      isActive: true,
    },
  })

  harness.controller.show()

  assert.equal(harness.session.backgroundMs, 0)
  assert.equal(harness.session._backgroundStartedMonoMs, 200)
  assert.equal(harness.session.currentQuestionStartedMonoMs, 0)
  assert.equal(harness.clock.calls, 0)
})

test('hide settles the active question before starting background timing', () => {
  const harness = createHarness({
    session: { isActive: true },
  })
  harness.clock.now = 900

  harness.controller.hide()

  assert.deepEqual(harness.calls, [['settle', true]])
  assert.equal(harness.session._backgroundStartedMonoMs, 900)
})

test('hide does not settle an inactive page or restart an already hidden timer', () => {
  const inactive = createHarness()
  inactive.controller.hide()
  assert.deepEqual(inactive.calls, [])
  assert.equal(inactive.session._backgroundStartedMonoMs, 500)

  const hidden = createHarness({
    session: {
      _backgroundStartedMonoMs: 200,
      isActive: true,
    },
  })
  hidden.controller.hide()
  assert.deepEqual(hidden.calls, [])
  assert.equal(hidden.session._backgroundStartedMonoMs, 200)
})

test('page adapter binds the active-question guard to page data', () => {
  const calls = []
  const page = {
    _practiceSession: {
      activeStartedMonoMs: 100,
      _backgroundStartedMonoMs: null,
      _timingPauseActive: false,
      backgroundMs: 0,
      currentQuestionStartedMonoMs: 0,
    },
    data: {
      started: true,
      loading: false,
      submitting: false,
    },
    _settleQuestionTime: pause => calls.push(pause),
  }
  const controller = createPracticeLifecyclePageController(page, () => 900)

  controller.hide()
  page.data.started = false
  controller.hide()

  assert.deepEqual(calls, [true])
  assert.equal(page._practiceSession._backgroundStartedMonoMs, 900)
})
