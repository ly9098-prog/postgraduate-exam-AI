const assert = require('node:assert/strict')
const { test } = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, '../pages/login/login.js'), 'utf8')

function fixture() {
  let definition, completeCount = 0, resolveCount = 0, finish
  const timers = new Map(), navigations = []
  const values = { token: 't', user: { id: 1 } }
  const resume = {
    resolve: () => { resolveCount++; return new Promise(resolve => { finish = resolve }) },
    complete: () => { completeCount++ },
  }
  const mocks = {
    '../../utils/auth': { isLoggedIn: () => Boolean(values.token) },
    '../../utils/api': { normalizeExpiresAt: value => value, now: () => Date.now() },
    '../../utils/storage': { KEYS: { TOKEN: 'token', TOKEN_EXPIRES_AT: 'expires', USER: 'user' },
      get: key => values[key] },
    '../../utils/privacy': { hasAcceptedCurrentPrivacy: () => true },
    '../../config': {},
    '../../utils/navigation': { getNavigationMetrics: () => ({}) },
    '../../utils/launch-resume': { createLoginResume: () => resume },
    '../../utils/launch-session-store': {
      userId: () => String((values.user || {}).id || ''),
    },
  }
  vm.runInNewContext(source, {
    Page: value => { definition = value },
    require: name => { assert.ok(Object.hasOwn(mocks, name), name); return mocks[name] },
    wx: { reLaunch: options => { navigations.push(options.url); if (options.success) options.success() } },
    setTimeout: callback => { const id = timers.size + 1; timers.set(id, callback); return id },
    clearTimeout: id => timers.delete(id),
    console, Date,
  })
  const page = { ...definition, data: structuredClone(definition.data),
    setData(patch) { Object.assign(this.data, patch) } }
  page.onLoad()
  return {
    page, values, navigations,
    runTimer: () => { const [id, callback] = [...timers][0]; timers.delete(id); return callback() },
    finish: target => finish(target),
    get resolveCount() { return resolveCount },
    get completeCount() { return completeCount },
  }
}

test('login redirects directly to resolved target only after auth and consent succeed', async () => {
  const harness = fixture()
  const running = harness.runTimer()
  assert.deepEqual(harness.navigations, [])
  harness.finish('/subpackages/study/practice/practice?resume=1')
  await running
  assert.deepEqual(harness.navigations, ['/subpackages/study/practice/practice?resume=1'])
  assert.equal(harness.completeCount, 1)
})

test('hidden login defers redirect and retries on show without becoming stuck', async () => {
  const harness = fixture()
  const running = harness.runTimer()
  harness.page.onHide()
  harness.finish('/pages/pomodoro/pomodoro')
  await running
  assert.deepEqual(harness.navigations, [])
  assert.equal(harness.page._pendingHomeRedirect, true)
  harness.page.onShow()
  const retry = harness.runTimer()
  harness.finish('/pages/pomodoro/pomodoro')
  await retry
  assert.deepEqual(harness.navigations, ['/pages/pomodoro/pomodoro'])
})

test('unload and logout during startup cannot commit a delayed redirect', async () => {
  for (const action of [
    harness => harness.page.onUnload(),
    harness => { harness.values.token = '' },
    harness => { harness.values.user = { id: 2 } },
  ]) {
    const harness = fixture()
    const running = harness.runTimer()
    action(harness)
    harness.finish('/pages/pomodoro/pomodoro')
    await running
    assert.deepEqual(harness.navigations, [])
    assert.equal(harness.completeCount, 0)
  }
})

test('show while target resolution is pending coalesces redirect attempts', async () => {
  const harness = fixture()
  const running = harness.runTimer()
  harness.page.onHide()
  harness.page.onShow()
  if (harness.page._homeRedirectTimer) await harness.runTimer()
  assert.equal(harness.resolveCount, 1)
  harness.finish('/pages/home/home')
  await running
  assert.deepEqual(harness.navigations, ['/pages/home/home'])
})

test('a profile refresh for the same identity does not strand the login redirect', async () => {
  const harness = fixture()
  const running = harness.runTimer()
  harness.values.user = { id: 1, nickname: 'updated-profile' }
  harness.finish('/pages/home/home')
  await running
  assert.deepEqual(harness.navigations, ['/pages/home/home'])
})
