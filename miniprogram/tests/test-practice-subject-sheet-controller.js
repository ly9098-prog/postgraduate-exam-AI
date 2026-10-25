const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubjectSheetController,
  SUBJECT_DOUBLE_TAP_INTERVAL,
} = require('../subpackages/study/practice/utils/subject-sheet-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    visible: false,
    closing: false,
    closeTimer: null,
    lastTap: null,
    patches: [],
    callbacks: [],
    timers: [],
    closed: 0,
    cleared: [],
  }
  const controller = createSubjectSheetController({
    getCloseTimer: () => state.closeTimer,
    setCloseTimer: timer => { state.closeTimer = timer },
    clearTimeout: timer => state.cleared.push(timer),
    setData: (patch, callback) => {
      state.patches.push(patch)
      if (callback) state.callbacks.push(callback)
    },
    isVisible: () => state.visible,
    isClosing: () => state.closing,
    isPageAlive: () => state.alive,
    setTimeout: (callback, delay) => {
      const timer = { callback, delay }
      state.timers.push(timer)
      return timer
    },
    getLastTap: () => state.lastTap,
    setLastTap: value => { state.lastTap = value },
    now: () => 1000,
    closeSheet: () => { state.closed += 1 },
    ...overrides,
  })
  return { controller, state }
}

test('open clears a pending close timer and resets view flags', () => {
  const { controller, state } = createHarness()
  const timer = { id: 1 }
  state.closeTimer = timer

  controller.open()

  assert.deepEqual(state.cleared, [timer])
  assert.equal(state.closeTimer, null)
  assert.deepEqual(state.patches, [{ subjectSheetVisible: true, subjectSheetClosing: false }])
})

test('hide invokes callback immediately when already hidden', () => {
  const { controller, state } = createHarness()
  let called = false

  controller.hide(() => { called = true })

  assert.equal(called, true)
  assert.deepEqual(state.patches, [])
})

test('hide schedules one 180ms close and invokes callback after commit', () => {
  const { controller, state } = createHarness()
  state.visible = true
  let called = false

  controller.hide(() => { called = true })

  assert.deepEqual(state.patches, [{ subjectSheetClosing: true }])
  state.callbacks[0]()
  assert.equal(state.timers.length, 1)
  assert.equal(state.timers[0].delay, 180)
  state.timers[0].callback()
  assert.deepEqual(state.patches[1], {
    subjectSheetVisible: false,
    subjectSheetClosing: false,
  })
  state.callbacks[1]()
  assert.equal(called, true)
})

test('hide is idempotent while closing and ignores page death', () => {
  const { controller, state } = createHarness()
  state.visible = true
  state.closing = true
  controller.hide()
  assert.equal(state.patches.length, 0)
  state.closing = false
  controller.hide()
  state.callbacks[0]()
  const patchCount = state.patches.length
  state.closing = true

  controller.hide()
  assert.equal(state.patches.length, patchCount)

  state.timers[0].callback()
  assert.equal(state.closeTimer, null)
  assert.equal(state.patches.length, patchCount + 1)
})

test('option tap tracks source and closes on same-key double tap', () => {
  const { controller, state } = createHarness()
  state.visible = true

  controller.handleOptionTap(408, 'parent')
  assert.deepEqual(state.lastTap, { key: 'parent:408', time: 1000 })
  assert.equal(state.closed, 0)

  controller.handleOptionTap(408, 'parent')
  assert.equal(state.lastTap, null)
  assert.equal(state.closed, 1)
  assert.equal(SUBJECT_DOUBLE_TAP_INTERVAL, 320)
})

test('option tap ignores hidden, closing and invalid targets', () => {
  const { controller, state } = createHarness()
  controller.handleOptionTap(408, 'parent')
  assert.equal(state.lastTap, null)

  state.visible = true
  state.closing = true
  controller.handleOptionTap(408, 'parent')
  assert.equal(state.lastTap, null)

  state.closing = false
  controller.handleOptionTap(0, 'parent')
  assert.equal(state.lastTap, null)
})
