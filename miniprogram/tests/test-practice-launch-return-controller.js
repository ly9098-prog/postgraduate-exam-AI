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
  const options = {
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
  }
  const controller = createLaunchReturnController(options)
  return { controller, state, options }
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

function matchingStack(state) {
  const returnTo = '/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=9'
  state.pages = [
    { route: 'subpackages/knowledge/knowledge-detail/index', knowledgePointId: 9 },
    { route: 'subpackages/study/practice/practice' },
  ]
  return returnTo
}

test('fail and success rechecks deduplicate retries separately for each attempt', () => {
  const { controller, state } = createHarness()
  const returnTo = matchingStack(state)
  controller.navigateBack(returnTo)
  const first = state.calls[0].options
  first.fail()
  first.fail()
  first.success()
  assert.deepEqual(state.timers.map(timer => timer.delay), [44, 64])
  state.timers[1].callback()
  assert.deepEqual(state.timers.map(timer => timer.delay), [44, 64])
  state.timers[0].callback()
  state.calls[1].options.fail()
  state.calls[1].options.fail()
  assert.deepEqual(state.timers.map(timer => timer.delay), [44, 64, 96])
})

test('success recheck accepts a changed route or an empty stack without retrying', () => {
  for (const pages of [[{ route: 'pages/home/home' }], []]) {
    const { controller, state } = createHarness()
    const returnTo = matchingStack(state)
    state.locked = true
    controller.navigateBack(returnTo)
    state.calls[0].options.success()
    assert.equal(state.timers[0].delay, 64)
    state.pages = pages
    state.timers[0].callback()
    assert.equal(state.timers.length, 1)
    assert.equal(state.calls.length, 1)
    assert.equal(state.locked, true)
  }
})

test('retry re-reads the stack and falls back if the target disappears', () => {
  const { controller, state } = createHarness()
  const returnTo = matchingStack(state)
  controller.navigateBack(returnTo)
  state.calls[0].options.fail()
  state.pages = [{ route: 'subpackages/study/practice/practice' }]
  state.timers[0].callback()
  assert.equal(state.locked, false)
  assert.equal(state.calls[1].kind, 'redirect')
  assert.equal(state.calls[1].options.url, returnTo)
})

test('exhausted retry unlocks and shows its toast only once', () => {
  const { controller, state } = createHarness()
  const returnTo = matchingStack(state)
  state.locked = true
  controller.navigateBack(returnTo, 3)
  state.calls[0].options.fail()
  state.calls[0].options.fail()
  assert.equal(state.locked, false)
  assert.deepEqual(state.timers, [])
  assert.deepEqual(state.calls[1], {
    kind: 'toast', options: { title: '返回失败，请再试一次', icon: 'none' },
  })
  assert.equal(state.calls.length, 2)
})

test('stack matching stops at identity gaps and preserves undecoded fallback rules', () => {
  const { controller } = createHarness()
  const route = 'subpackages/knowledge/knowledge-subject/index'
  const pages = [
    { route, subjectId: 7 },
    { route, subjectId: 8 },
    { route: `/${route}`, options: { subject_id: '7' } },
    { route: 'subpackages/study/practice/practice' },
  ]
  assert.equal(controller.findStackIndex(pages, `/${route}?subject_id=%37`), 2)
  assert.equal(controller.findStackIndex(pages, `/${route}?subject_id=%ZZ`), 0)
  pages[1] = { route }
  assert.equal(controller.findStackIndex(pages, `/${route}?subject_id=7`), 0)
  pages[0] = { route, subjectId: 8 }
  assert.equal(controller.findStackIndex(pages, `/${route}?subject_id=7`), 1)
})

test('returnToOrigin waits for guard completion and retains the navigation port identity', () => {
  const h = createHarness()
  const returnTo = matchingStack(h.state)
  h.state.exitGuardVisible = true
  h.state.returnTo = returnTo
  const calls = []
  h.options.navigateBack = function (...args) {
    assert.equal(this, h.options)
    calls.push(args)
  }
  h.controller.returnToOrigin()
  h.controller.returnToOrigin()
  assert.equal(h.state.patches.length, 2)
  assert.equal(h.state.nextTicks.length, 0)
  assert.equal(h.state.timers.length, 0)
  h.state.returnTo = '/pages/home/home'
  h.state.patches[1]()
  assert.equal(h.state.nextTicks.length, 1)
  assert.equal(h.state.timers.length, 0)
  h.state.nextTicks[0]()
  assert.deepEqual(h.state.timers.map(timer => timer.delay), [20])
  assert.deepEqual(calls, [])
  h.state.timers[0].callback()
  assert.deepEqual(calls, [[returnTo, 0]])
})

test('navigation and retry ports preserve their receiver and lock ordering', () => {
  const h = createHarness()
  const returnTo = matchingStack(h.state)
  const calls = []
  for (const name of Object.keys(h.options)) {
    const original = h.options[name]
    h.options[name] = function (...args) {
      assert.equal(this, h.options)
      calls.push([name, ...args])
      return original(...args)
    }
  }
  h.controller.navigateBack(returnTo)
  h.state.calls[0].options.fail()
  h.state.timers[0].callback()
  assert.deepEqual(calls.map(call => call[0]), [
    'isPageAlive', 'getCurrentPages', 'safeDecodeURIComponent', 'navigateBack',
    'isPageAlive', 'setTimeout', 'isPageAlive', 'setNavigationLocked',
    'isPageAlive', 'getCurrentPages', 'safeDecodeURIComponent', 'navigateBack',
  ])
  assert.deepEqual(calls.find(call => call[0] === 'setNavigationLocked'),
    ['setNavigationLocked', true])
})
