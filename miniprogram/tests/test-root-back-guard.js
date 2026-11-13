const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const miniRoot = path.resolve(__dirname, '..')
const componentFile = path.join(miniRoot, 'components/root-back-guard/index.js')
const flush = () => new Promise(resolve => setImmediate(resolve))

function fixture({ pages = [{}], enabled = true, delegate = false } = {}) {
  let definition
  const calls = []
  const platform = {
    reLaunch: options => calls.push(['home', options]),
    showToast: options => calls.push(['toast', options]),
    nextTick: callback => callback(),
  }
  vm.runInNewContext(fs.readFileSync(componentFile, 'utf8'), {
    Component: value => { definition = value },
    getCurrentPages: () => pages,
    wx: platform,
  }, { filename: componentFile })
  const component = {
    properties: { enabled, delegate },
    data: { ...definition.data },
    setData(patch, callback) { Object.assign(this.data, patch); if (callback) callback() },
    triggerEvent: name => calls.push(['event', name]),
    ...definition.methods,
  }
  const update = value => {
    component.properties.enabled = value
    definition.observers.enabled.call(component, value)
  }
  definition.lifetimes.attached.call(component)
  return { component, definition, calls, platform, update }
}

test('system-back guard is enabled only on a single-page stack', () => {
  for (const pages of [[], [{}], [{}, {}]]) {
    const { component } = fixture({ pages })
    assert.equal(component.data.visible, pages.length === 1)
  }
  assert.equal(fixture({ enabled: false }).component.data.visible, false)
})

test('delegated guards also protect pushed pages', () => {
  assert.equal(fixture({ pages: [{}, {}], delegate: true }).component.data.visible, true)
  assert.equal(fixture({ pages: [], delegate: true }).component.data.visible, false)
  assert.equal(fixture({ pages: [{}, {}] }).component.data.visible, false)

  const toggled = fixture({ pages: [{}, {}], delegate: true })
  toggled.component.properties.delegate = false
  toggled.definition.observers.delegate.call(toggled.component, false)
  assert.equal(toggled.component.data.visible, false)
})

test('root system back relaunches home once and reports failure with a retryable guard', () => {
  const { component, calls } = fixture()
  component.onAfterLeave()
  component.onAfterLeave()
  assert.equal(component.data.visible, false)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].url, '/pages/home/home')
  calls[0][1].fail()
  assert.equal(component.data.visible, true)
  assert.equal(calls[1][0], 'toast')
  component.onAfterLeave()
  assert.equal(calls[2][0], 'home')
})

test('programmatic dismissal, backgrounding and detached callbacks do not navigate', () => {
  const disabled = fixture()
  disabled.update(false)
  disabled.component.onAfterLeave()
  assert.deepEqual(disabled.calls, [])
  const hidden = fixture()
  hidden.definition.pageLifetimes.hide.call(hidden.component)
  hidden.component.onAfterLeave()
  assert.deepEqual(hidden.calls, [])
  hidden.definition.pageLifetimes.show.call(hidden.component)
  assert.equal(hidden.component.data.visible, true)
  const detached = fixture()
  detached.definition.lifetimes.detached.call(detached.component)
  detached.component.onAfterLeave()
  assert.deepEqual(detached.calls, [])
})

test('a deferred confirmation rearm cannot reactivate a hidden or detached page', () => {
  for (const detach of [false, true]) {
    const harness = fixture({ delegate: true })
    let rearm
    harness.platform.nextTick = callback => { rearm = callback }
    harness.component.onAfterLeave()
    assert.equal(harness.component.data.visible, false)
    if (detach) harness.definition.lifetimes.detached.call(harness.component)
    else harness.definition.pageLifetimes.hide.call(harness.component)
    rearm()
    assert.equal(harness.component.data.visible, false)
    assert.equal(harness.calls.filter(call => call[0] === 'home').length, 0)
  }
})

test('delegated root back uses the shared exit prompt for repeated, cancelled and confirmed exits', async () => {
  const { createNavBackController } = require('../subpackages/study/review-today/utils/nav-back-controller')
  const harness = fixture({ delegate: true })
  let cleared = 0
  let prompts = 0
  let resolvePrompt
  let pending = false
  const controller = createNavBackController({
    getPhase: () => 'reviewing',
    clearMasterUndo() {},
    clearReviewTimer() {},
    clearReviewActivity: () => { cleared++ },
    getCurrentPages: () => [{}],
    reLaunch: harness.platform.reLaunch,
    isExitConfirmPending: () => pending,
    setExitConfirmPending: value => { pending = value },
    isSubmittingGroup: () => false,
    logWarn: () => {},
    showConfirm: () => {
      prompts++
      return new Promise(resolve => { resolvePrompt = resolve })
    },
  })
  harness.component.triggerEvent = () => controller.onNavBack()
  harness.component.onAfterLeave()
  await flush()
  assert.equal(prompts, 1)
  assert.equal(harness.component.data.visible, true)
  harness.component.onAfterLeave()
  await flush()
  assert.equal(prompts, 1)
  assert.equal(cleared, 0)
  assert.deepEqual(harness.calls, [])
  resolvePrompt(false)
  await flush()
  assert.equal(pending, false)
  assert.equal(cleared, 0)
  assert.deepEqual(harness.calls, [])
  harness.component.onAfterLeave()
  await flush()
  assert.equal(prompts, 2)
  resolvePrompt(true)
  await flush()
  assert.equal(cleared, 1)
  assert.equal(harness.calls.length, 1)
  assert.equal(harness.calls[0][1].url, '/pages/home/home')
})

test('restored and terminal pages wire the root guard', () => {
  const app = JSON.parse(fs.readFileSync(path.join(miniRoot, 'app.json'), 'utf8'))
  assert.equal(app.usingComponents['root-back-guard'], '/components/root-back-guard/index')
  const routes = [
    'subpackages/study/review-today/review-today',
    'pages/pomodoro/pomodoro',
    'subpackages/study/practice-result/index',
  ]
  for (const route of routes) {
    const config = JSON.parse(fs.readFileSync(path.join(miniRoot, `${route}.json`), 'utf8'))
    assert.equal(config.usingComponents['root-back-guard'], '/components/root-back-guard/index')
    assert.match(fs.readFileSync(path.join(miniRoot, `${route}.wxml`), 'utf8'), /<root-back-guard\b/)
  }
  const review = fs.readFileSync(path.join(miniRoot, `${routes[0]}.wxml`), 'utf8')
  assert.doesNotMatch(review, /enabled="\{\{!exitConfirmVisible\}\}"/)
  assert.doesNotMatch(review, /exitConfirmVisible/)
  assert.match(review, /<submit-confirm\b[^>]*id="submitConfirm"/)
  assert.match(review, /delegate="\{\{phase === 'reviewing'\}\}"/)
  assert.match(review, /bind:back="onNavBack"/)
})

test('practice keeps exactly one native back container mounted across setup and active phases', () => {
  const practice = fs.readFileSync(path.join(miniRoot, 'subpackages/study/practice/practice.wxml'), 'utf8')
  const containers = [...practice.matchAll(/<page-container\b[\s\S]*?\/>/g)]
  assert.equal(containers.length, 1)
  assert.doesNotMatch(containers[0][0], /wx:(if|elif|for)=/)
  assert.doesNotMatch(practice, /<root-back-guard\b/)
  assert.match(containers[0][0], /bind:afterleave="onPracticeExitGuardLeave"/)
})
