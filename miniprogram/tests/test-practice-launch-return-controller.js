const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createLaunchReturnController,
} = require('../subpackages/study/practice/utils/launch-return-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    locked: false,
    exitGuardVisible: false,
    returnTo: '',
    patches: [],
    timers: [],
    nextTicks: [],
    calls: [],
    pages: [],
  }
  const controller = createLaunchReturnController({
    safeDecodeURIComponent: (value, fallback) => {
      if (typeof value !== 'string') return fallback
      try { return decodeURIComponent(value) } catch (_) { return fallback }
    },
    isPageAlive: () => state.alive,
    getCurrentPages: () => state.pages,
    setNavigationLocked: value => { state.locked = value },
    isNavigationLocked: () => state.locked,
    redirectTo: options => state.calls.push({ kind: 'redirect', options }),
    reLaunch: options => state.calls.push({ kind: 'reLaunch', options }),
    navigateBack: options => state.calls.push({ kind: 'navigateBack', options }),
    showToast: options => state.calls.push({ kind: 'toast', options }),
    setTimeout: (callback, delay) => {
      state.timers.push({ callback, delay })
      return state.timers.length
    },
    hasNextTick: () => true,
    nextTick: callback => state.nextTicks.push(callback),
    getReturnTo: () => state.returnTo,
    isExitGuardVisible: () => state.exitGuardVisible,
    setData: (patch, callback) => {
      state.patches.push(patch)
      if (callback) state.patches.push(callback)
    },
    ...overrides,
  })
  return { controller, state }
}

test('findStackIndex validates input and matches knowledge page identity', () => {
  const { controller } = createHarness()
  const subjectRoute = '/subpackages/knowledge/knowledge-subject/index?subject_id=7'
  const detailRoute = '/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9'

  assert.equal(controller.findStackIndex(null, subjectRoute), -1)
  assert.equal(controller.findStackIndex([{}], subjectRoute), -1)
  assert.equal(controller.findStackIndex([{}, {}], ''), -1)
  assert.equal(controller.findStackIndex([{}, {}], '/?x=1'), -1)

  assert.equal(controller.findStackIndex([
    { route: 'subpackages/knowledge/knowledge-subject/index', subjectId: 8 },
    { route: 'subpackages/knowledge/knowledge-subject/index', subjectId: 7 },
    { route: 'subpackages/study/practice/practice' },
  ], subjectRoute), 1)

  assert.equal(controller.findStackIndex([
    { route: 'subpackages/knowledge/knowledge-detail/index', options: { knowledge_point_id: '9' } },
    { route: 'subpackages/study/practice/practice' },
  ], detailRoute), 0)

  assert.equal(controller.findStackIndex([
    { route: 'pages/home/home' },
    { route: 'subpackages/knowledge/knowledge-detail/index', options: { knowledge_point_id: '9' } },
    { route: 'subpackages/knowledge/knowledge-detail/index', options: { knowledge_point_id: '9' } },
    { route: 'subpackages/study/practice/practice' },
  ], detailRoute), 1)
})

test('navigateBack falls back through redirect, back and relaunch when no stack target exists', () => {
  const { controller, state } = createHarness()
  state.pages = [{ route: 'pages/home/home' }, { route: 'subpackages/study/practice/practice' }]
  state.locked = true

  controller.navigateBack('/subpackages/knowledge/knowledge-detail/index?id=1')
  assert.equal(state.locked, false)
  assert.equal(state.calls[0].kind, 'redirect')
  state.calls[0].options.fail()
  assert.equal(state.calls[1].kind, 'reLaunch')
  assert.equal(state.calls[1].options.url, '/pages/home/home')

  controller.navigateBack('')
  assert.equal(state.calls[2].kind, 'navigateBack')
  assert.equal(state.calls[2].options.delta, 1)
  state.calls[2].options.fail()
  assert.equal(state.calls[3].options.url, '/pages/home/home')

  state.pages = [{ route: 'subpackages/study/practice/practice' }]
  controller.navigateBack('')
  assert.equal(state.calls[4].kind, 'reLaunch')
})

test('navigateBack retries when the practice page remains after a successful back', () => {
  const { controller, state } = createHarness()
  const target = { route: 'subpackages/knowledge/knowledge-detail/index', options: { knowledge_point_id: '9' } }
  state.pages = [target, { route: 'subpackages/study/practice/practice' }]

  controller.navigateBack('/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9', 0)
  assert.equal(state.calls[0].options.delta, 1)
  state.calls[0].options.success()
  assert.equal(state.timers[0].delay, 64)
  state.pages = [target, { route: 'subpackages/study/practice/practice' }]
  state.timers[0].callback()
  assert.equal(state.calls.length, 1)
  assert.equal(state.timers[1].delay, 44)
  state.timers[1].callback()
  assert.equal(state.locked, true)
  assert.equal(state.calls.length, 2)
  assert.equal(state.calls[1].options.delta, 1)

  state.calls[1].options.fail()
  assert.equal(state.timers[2].delay, 96)
  state.timers[2].callback()
  assert.equal(state.calls.length, 3)
  state.calls[2].options.fail()
  assert.equal(state.timers[3].delay, 180)
  state.timers[3].callback()
  assert.equal(state.calls.length, 4)
  state.calls[3].options.fail()
  assert.equal(state.locked, false)
  assert.deepEqual(state.calls[4], {
    kind: 'toast',
    options: { title: '返回失败，请再试一次', icon: 'none' },
  })
})

test('navigateBack unlocks when the page dies before a retry fires', () => {
  const { controller, state } = createHarness()
  const target = { route: 'subpackages/knowledge/knowledge-detail/index', options: { knowledge_point_id: '9' } }
  state.pages = [target, { route: 'subpackages/study/practice/practice' }]
  state.locked = true

  controller.navigateBack('/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9', 0)
  state.calls[0].options.fail()
  assert.equal(state.timers[0].delay, 44)
  state.alive = false
  state.timers[0].callback()
  assert.equal(state.locked, false)
  assert.equal(state.calls.length, 1)

  state.alive = true
  state.locked = true
  controller.navigateBack('/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9', 0)
  state.alive = false
  state.calls[1].options.fail()
  assert.equal(state.locked, false)
  assert.equal(state.calls.length, 2)
})

test('navigateBack unlocks when the page dies before initial or success-delay navigation', () => {
  const { controller, state } = createHarness()
  const target = { route: 'subpackages/knowledge/knowledge-detail/index', options: { knowledge_point_id: '9' } }
  state.pages = [target, { route: 'subpackages/study/practice/practice' }]
  state.locked = true
  state.alive = false

  controller.navigateBack('/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9', 0)
  assert.equal(state.locked, false)
  assert.deepEqual(state.calls, [])

  state.alive = true
  controller.navigateBack('/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9', 0)
  state.calls[0].options.success()
  state.alive = false
  state.timers[0].callback()
  assert.equal(state.locked, false)
  assert.equal(state.calls.length, 1)
})

test('returnToOrigin locks once and waits for nextTick before navigation', () => {
  const { controller, state } = createHarness()
  state.returnTo = ''
  state.pages = []

  controller.returnToOrigin()
  assert.equal(state.locked, true)
  assert.equal(state.nextTicks.length, 1)
  state.nextTicks[0]()
  assert.equal(state.timers[0].delay, 20)
  state.timers[0].callback()
  assert.equal(state.calls[0].kind, 'navigateBack')
})

test('returnToOrigin falls back to immediate scheduling without nextTick', () => {
  const { controller, state } = createHarness({ hasNextTick: () => false })

  controller.returnToOrigin()
  assert.deepEqual(state.nextTicks, [])
  assert.equal(state.timers[0].delay, 20)
})

test('returnToOrigin hides a visible exit guard before navigation and respects the lock', () => {
  const { controller, state } = createHarness()
  state.exitGuardVisible = true
  state.locked = true
  controller.returnToOrigin()
  assert.deepEqual(state.patches, [])

  state.locked = false
  state.pages = []
  controller.returnToOrigin()
  assert.deepEqual(state.patches[0], { practiceExitGuardVisible: false })
  state.patches[1]()
  state.nextTicks[0]()
  state.timers[0].callback()
  assert.equal(state.calls[0].kind, 'navigateBack')
})
