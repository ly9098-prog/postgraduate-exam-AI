const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExitGuardController,
} = require('../subpackages/study/practice/utils/exit-guard-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    session: { exitGuardActive: false, exitGuardMessage: '' },
    visible: false,
    started: false,
    submitted: false,
    rearming: false,
    rearmTimer: null,
    promptQueued: false,
    exitInFlight: false,
    disableAvailable: true,
    disableCalls: 0,
    disableThrows: false,
    nextTickAvailable: true,
    patches: [],
    callbacks: [],
    timers: [],
    nextTicks: [],
    microtasks: [],
    warnings: [],
    exitRequests: [],
    clearedTimers: [],
  }
  const controller = createExitGuardController({
    getSession: () => state.session,
    hasDisableAlertBeforeUnload: () => state.disableAvailable,
    disableAlertBeforeUnload: () => {
      state.disableCalls += 1
      if (state.disableThrows) throw new Error('disable failed')
    },
    isPageAlive: () => state.alive,
    isGuardVisible: () => state.visible,
    isStarted: () => state.started,
    isSubmitted: () => state.submitted,
    isRearming: () => state.rearming,
    setRearming: value => { state.rearming = value },
    getRearmTimer: () => state.rearmTimer,
    setRearmTimer: timer => { state.rearmTimer = timer },
    clearTimeout: timer => state.clearedTimers.push(timer),
    isPromptQueued: () => state.promptQueued,
    setPromptQueued: value => { state.promptQueued = value },
    isExitConfirmInFlight: () => state.exitInFlight,
    hasNextTick: () => state.nextTickAvailable,
    nextTick: callback => state.nextTicks.push(callback),
    setData: (patch, callback) => {
      state.patches.push(patch)
      if (Object.prototype.hasOwnProperty.call(patch, 'practiceExitGuardVisible')) {
        state.visible = patch.practiceExitGuardVisible
      }
      if (callback) state.callbacks.push(callback)
    },
    setTimeout: (callback, delay) => {
      const timer = { callback, delay }
      state.timers.push(timer)
      return timer
    },
    queueMicrotask: callback => {
      const promise = Promise.resolve().then(callback)
      state.microtasks.push(promise)
      return promise
    },
    requestExit: async options => state.exitRequests.push(options),
    logWarn: (...args) => state.warnings.push(args),
    ...overrides,
  })
  return { controller, state }
}

test('setUnloadGuard updates session, disables native guard, and only commits changed visibility', () => {
  const { controller, state } = createHarness()
  state.visible = true

  controller.setUnloadGuard(true, '交卷仍在确认中。')
  assert.equal(state.session.exitGuardActive, true)
  assert.equal(state.session.exitGuardMessage, '交卷仍在确认中。')
  assert.equal(state.disableCalls, 1)
  assert.deepEqual(state.patches, [])

  controller.setUnloadGuard(false, '')
  assert.equal(state.session.exitGuardActive, false)
  assert.equal(state.session.exitGuardMessage, '')
  assert.deepEqual(state.patches, [{ practiceExitGuardVisible: false }])
})

test('setUnloadGuard tolerates missing session and disableAlertBeforeUnload failures', () => {
  const { controller, state } = createHarness({ getSession: () => null })
  state.disableThrows = true

  controller.setUnloadGuard(true, 'message')
  controller.setUnloadGuard(false)

  assert.equal(state.disableCalls, 2)
  assert.equal(state.session.exitGuardActive, false)
  assert.deepEqual(state.patches, [
    { practiceExitGuardVisible: true },
    { practiceExitGuardVisible: false },
  ])
})

test('setUnloadGuard clears pending rearm state only when disabling', () => {
  const { controller, state } = createHarness()
  const timer = { id: 1 }
  state.rearming = true
  state.rearmTimer = timer

  controller.setUnloadGuard(true)
  assert.equal(state.rearming, true)
  assert.equal(state.rearmTimer, timer)
  assert.deepEqual(state.clearedTimers, [])

  controller.setUnloadGuard(false)
  assert.equal(state.rearming, false)
  assert.equal(state.rearmTimer, null)
  assert.deepEqual(state.clearedTimers, [timer])
})

test('setUnloadGuard stops view updates after page death', () => {
  const { controller, state } = createHarness()
  state.alive = false

  controller.setUnloadGuard(true)

  assert.equal(state.session.exitGuardActive, true)
  assert.deepEqual(state.patches, [])
})

test('system-back interception requires alive page, active guard, started and unsubmitted state', () => {
  const { controller, state } = createHarness()
  assert.equal(controller.shouldInterceptSystemBack(), false)

  state.alive = true
  state.session.exitGuardActive = true
  assert.equal(controller.shouldInterceptSystemBack(), false)

  state.started = true
  assert.equal(controller.shouldInterceptSystemBack(), true)

  state.submitted = true
  assert.equal(controller.shouldInterceptSystemBack(), false)

  state.submitted = false
  state.alive = false
  assert.equal(controller.shouldInterceptSystemBack(), false)
})

test('rearm hides, waits for nextTick, and shows once with idempotency', () => {
  const { controller, state } = createHarness()
  state.session.exitGuardActive = true
  state.started = true

  controller.rearm()
  assert.equal(state.rearming, true)
  assert.deepEqual(state.patches, [{ practiceExitGuardVisible: false }])
  state.callbacks[0]()
  assert.equal(state.nextTicks.length, 1)
  state.nextTicks[0]()
  assert.deepEqual(state.patches[1], { practiceExitGuardVisible: true })
  state.callbacks[1]()
  assert.equal(state.rearming, false)

  const patchCount = state.patches.length
  state.rearming = true
  controller.rearm()
  assert.equal(state.patches.length, patchCount)
})

test('rearm falls back to a zero-delay timer without nextTick', () => {
  const { controller, state } = createHarness({ hasNextTick: () => false })
  state.session.exitGuardActive = true
  state.started = true

  controller.rearm()
  state.callbacks[0]()
  assert.equal(state.timers.length, 1)
  assert.equal(state.timers[0].delay, 0)
  assert.equal(state.rearmTimer, state.timers[0])

  state.timers[0].callback()
  assert.equal(state.rearmTimer, null)
  assert.deepEqual(state.patches[1], { practiceExitGuardVisible: true })
  state.callbacks[1]()
  assert.equal(state.rearming, false)
})

test('disabling the guard clears a scheduled fallback rearm timer and prevents a later show', () => {
  const { controller, state } = createHarness({ hasNextTick: () => false })
  state.session.exitGuardActive = true
  state.started = true

  controller.rearm()
  state.callbacks[0]()
  assert.equal(state.timers.length, 1)
  assert.equal(state.rearmTimer, state.timers[0])

  controller.setUnloadGuard(false)
  assert.equal(state.rearming, false)
  assert.equal(state.rearmTimer, null)
  assert.deepEqual(state.clearedTimers, [state.timers[0]])

  state.timers[0].callback()
  assert.deepEqual(state.patches, [{ practiceExitGuardVisible: false }])
})

test('rearm resets state when interception becomes invalid before showing', () => {
  const { controller, state } = createHarness()
  state.session.exitGuardActive = true
  state.started = true

  controller.rearm()
  state.submitted = true
  state.callbacks[0]()
  assert.equal(state.rearming, false)
  assert.deepEqual(state.nextTicks, [])

  state.submitted = false
  state.alive = true
  controller.rearm()
  state.alive = false
  state.callbacks[1]()
  assert.equal(state.rearming, false)
  assert.deepEqual(state.nextTicks, [])
})

test('guard leave queues one prompt, resets the flag, and requests system-back exit', async () => {
  const { controller, state } = createHarness()
  state.session.exitGuardActive = true
  state.started = true

  controller.handleGuardLeave()
  assert.equal(state.rearming, true)
  assert.equal(state.promptQueued, true)
  controller.handleGuardLeave()
  assert.equal(state.microtasks.length, 1)

  await state.microtasks[0]
  assert.equal(state.promptQueued, false)
  assert.deepEqual(state.exitRequests, [{ source: 'system-back' }])
})

test('guard leave skips prompt while exit confirmation is already in flight', () => {
  const { controller, state } = createHarness()
  state.session.exitGuardActive = true
  state.started = true
  state.exitInFlight = true

  controller.handleGuardLeave()

  assert.equal(state.rearming, true)
  assert.equal(state.promptQueued, false)
  assert.deepEqual(state.microtasks, [])
})

test('guard leave resets the queue flag and warns when the prompt fails', async () => {
  const { controller, state } = createHarness({
    requestExit: async () => { throw new Error('exit failed') },
  })
  state.session.exitGuardActive = true
  state.started = true

  controller.handleGuardLeave()
  await state.microtasks[0].catch(() => {})

  assert.equal(state.promptQueued, false)
  assert.equal(state.warnings.length, 1)
  assert.equal(state.warnings[0][0], '系统返回退出确认处理失败')
})
