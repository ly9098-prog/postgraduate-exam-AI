const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const homeRoot = path.join(__dirname, '../pages/home')
const guideSource = fs.readFileSync(path.join(homeRoot, 'utils/guest-login-guide.js'), 'utf8')
const pageSource = fs.readFileSync(path.join(homeRoot, 'home.js'), 'utf8')

function launch(memory = new Map(), options = {}) {
  const pendingLayouts = []
  const listeners = new Set()
  const timers = new Map()
  let clock = 0
  let timerId = 0
  let authenticated = false
  let width = 375
  const navigation = []
  const exported = { exports: {} }
  const storage = { get: key => memory.get(key), set: (key, value) => memory.set(key, value) }
  const wx = {
    getWindowInfo: () => ({ windowWidth: width, windowHeight: options.height || 800 }),
    getMenuButtonBoundingClientRect: () => options.menu || { left: width - 100, top: 50, width: 88, height: 32 },
    onKeyDown: listener => listeners.add(listener),
    offKeyDown: listener => listeners.delete(listener),
    createSelectorQuery() {
      const query = {
        in() { return query },
        select() { return query },
        boundingClientRect() { return query },
        exec(callback) {
          const deliver = () => callback(options.noRects ? [] : [
            { left: width - 168, top: 52, width: 60, height: 28 }, { width: 220, height: 94 },
          ])
          if (options.deferLayouts) pendingLayouts.push(deliver)
          else deliver()
        },
      }
      return query
    },
  }
  if (options.mobile) {
    delete wx.onKeyDown
    delete wx.offKeyDown
  }
  if (options.noMeasurement) delete wx.createSelectorQuery
  if (options.noViewport) delete wx.getWindowInfo
  vm.runInNewContext(guideSource, {
    module: exported, wx,
    require(name) {
      assert.equal(name, '../../../utils/storage')
      return storage
    },
    setTimeout(callback, delay) {
      timers.set(++timerId, { callback, deadline: clock + delay })
      return timerId
    },
    clearTimeout: handle => timers.delete(handle),
  })
  const growthPageMethods = {
    async _validateHomeSession() { this._authed = authenticated },
    _guestBasePatch: () => ({ guestMode: true }),
    _clearAnimTimer() {},
    openLoginFromHome() { navigation.push(this.data.showLoginGuide) },
  }
  const mocks = {
    '../../utils/auth': {
      isLoggedIn: () => authenticated,
      isAdmin: () => false,
      getUser: () => ({}),
    },
    './utils/growth-page-controller': { TODAY_GOAL_TOTAL: 30, GOAL_OPTIONS: [], growthPageMethods },
    './utils/home-canvas': { homeCanvasMethods: {} },
    './utils/guest-login-guide': exported.exports,
  }
  function page() {
    let definition
    vm.runInNewContext(pageSource, {
      require: name => {
        assert.ok(mocks[name], name)
        return mocks[name]
      },
      Page: value => { definition = value },
      clearTimeout() {},
    })
    const instance = { ...definition, data: structuredClone(definition.data) }
    instance.setData = (patch, callback) => {
      Object.assign(instance.data, patch)
      if (callback) callback()
    }
    for (const method of ['getDisplayName', 'getUserInitial', 'getGreeting', 'getDateStr', 'getMotto']) {
      instance[method] = () => ''
    }
    instance.getGrowthFallback = () => ({})
    instance._syncHomeUser = async () => true
    instance.loadGrowthSnapshot = async () => {}
    instance._maybeResumeColdLaunch = () => {}
    instance.measureNavigation = callback => { if (callback) callback() }
    instance.detectRuntime = () => {}
    instance.onLoad()
    return instance
  }
  return {
    page, pendingLayouts, navigation, memory, listeners, timers,
    advance(milliseconds) {
      clock += milliseconds
      for (const [handle, timer] of timers) {
        if (timer.deadline <= clock) {
          timers.delete(handle)
          timer.callback()
        }
      }
    },
    exports: exported.exports,
    authenticate: value => { authenticated = value },
    resize: value => { width = value },
    key(key) {
      for (const listener of listeners) listener({ key })
    },
  }
}

test('guest home shows the measured guide for six seconds without persisting timeout dismissal', async () => {
  const runtime = launch()
  const page = runtime.page()
  assert.equal(page.data.showLoginGuide, false)
  const showing = page.onShow()
  assert.equal(page.data.showLoginGuide, false)
  await showing
  assert.equal(page.data.showLoginGuide, true)
  assert.equal(runtime.listeners.size, 1)
  assert.equal(page.data.loginGuideReady, true)
  assert.equal(page.data.loginGuideLeft, -80)
  assert.equal(page.data.loginGuideArrowLeft, 110)
  assert.equal(runtime.timers.size, 1)
  runtime.advance(5999)
  assert.equal(page.data.showLoginGuide, true)
  runtime.advance(1)
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.timers.size, 0)
  assert.equal(runtime.listeners.size, 0)
  assert.equal(runtime.memory.size, 0)
  const freshLaunch = launch(runtime.memory).page()
  await freshLaunch.onShow()
  assert.equal(freshLaunch.data.showLoginGuide, true)
})

test('the guide is once per launch across repeated shows and recreated home pages', async () => {
  const runtime = launch()
  const first = runtime.page()
  await first.onShow()
  await first.onShow()
  assert.equal(first.data.showLoginGuide, false)
  first.onUnload()
  const second = runtime.page()
  await second.onShow()
  assert.equal(second.data.showLoginGuide, false)
  const freshLaunch = launch().page()
  await freshLaunch.onShow()
  assert.equal(freshLaunch.data.showLoginGuide, true)
  freshLaunch.onUnload()
})

test('authenticated home never shows or consumes the first guest hint', async () => {
  const runtime = launch()
  runtime.authenticate(true)
  const page = runtime.page()
  await page.onShow()
  assert.equal(page.data.guestMode, false)
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.listeners.size, 0)
  runtime.authenticate(false)
  await page.onShow()
  assert.equal(page.data.showLoginGuide, true)
  runtime.authenticate(true)
  await page.onShow()
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.listeners.size, 0)
})

for (const handler of ['openProfileSheet', 'openLoginGuide']) {
  test(`${handler} dismisses the hint before using the existing login path`, async () => {
    const runtime = launch()
    const page = runtime.page()
    await page.onShow()
    await page[handler]()
    assert.equal(page.data.showLoginGuide, false)
    assert.equal(runtime.listeners.size, 0)
    assert.deepEqual(runtime.navigation, [false])
    assert.equal(runtime.memory.size, 0)
    page.onHide()
    await page.onShow()
    assert.equal(page.data.showLoginGuide, false)
  })
}

for (const lifecycle of ['onHide', 'onUnload']) {
  test(`${lifecycle} removes key listeners and invalidates pending layouts without a state write`, async () => {
    const runtime = launch(new Map(), { deferLayouts: true })
    const page = runtime.page()
    await page.onShow()
    let writes = 0
    const setData = page.setData
    page.setData = patch => { writes++; setData(patch) }
    page[lifecycle]()
    assert.equal(writes, 0)
    assert.equal(runtime.listeners.size, 0)
    const restore = page.setData
    page.setData = () => assert.fail('late timer write')
    runtime.pendingLayouts[0]()
    page.setData = restore
    if (lifecycle === 'onHide') {
      await page.onShow()
      assert.equal(page.data.showLoginGuide, false)
    }
  })
}

test('a late session validation cannot show the hint after leaving home', async () => {
  const runtime = launch()
  const page = runtime.page()
  let finish
  page._validateHomeSession = () => new Promise(resolve => { finish = resolve })
  const showing = page.onShow()
  page.onHide()
  finish()
  await showing
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.listeners.size, 0)
  const nextPage = runtime.page()
  await nextPage.onShow()
  assert.equal(nextPage.data.showLoginGuide, true)
  nextPage.onUnload()
})

test('the hint stays anchored to the guest profile control and respects reduced motion', () => {
  const template = fs.readFileSync(path.join(homeRoot, 'home.wxml'), 'utf8')
  const styles = fs.readFileSync(path.join(homeRoot, 'home.wxss'), 'utf8')
  assert.match(template, /class="profile-entry">\s*<view id="home-profile-chip" class="profile-chip"/)
  assert.match(template, /aria-label="\{\{guestMode \? '登录' : '编辑个人资料'\}\}"/)
  assert.match(template, /<\/view>\s*<view wx:if="\{\{guestMode && showLoginGuide\}\}" id="home-login-guide" class="login-guide /)
  assert.match(template, /<button[^>]*size="mini"[^>]*catchtap="openLoginGuide"[^>]*><text class="login-guide-action-label">立即登录<\/text>/)
  assert.match(template, /class="login-guide-action" size="mini" style="display: flex; font-size: 12px; line-height: 20px;"/)
  assert.doesNotMatch(template, /<button id="home-profile-chip"/)
  assert.match(template, /class="home-page" bindtap="dismissLoginGuideFromPage"/)
  assert.match(template, /class="login-guide[^>]+catchtap="noop"/)
  assert.match(template, /loginGuideReady \? '' : 'login-guide-pending'/)
  assert.match(template, /<button[^>]*catchtap="closeLoginGuide"[^>]*aria-label="关闭登录引导，不再提示"/)
  assert.match(template, /line-icon icon-close/)
  assert.match(template, /登录后保存学习记录/)
  assert.doesNotMatch(template, /login-guide-slot|login-guide-description|login-guide-dot|login-guide-connector|autofocus/)
  const guideStyle = styles.match(/\.login-guide \{([^}]+)\}/)[1]
  assert.match(styles, /\.profile-entry \{\s*position: relative;/)
  assert.match(guideStyle, /position: absolute;/)
  assert.match(guideStyle, /top: calc\(100% \+ 8px\);/)
  assert.match(guideStyle, /width: 216px;/)
  assert.match(guideStyle, /max-width: calc\(100vw - 32px\);/)
  assert.match(guideStyle, /background: #F1FAF3;/)
  assert.match(guideStyle, /opacity: 1;/)
  assert.doesNotMatch(guideStyle, /backdrop-filter|rgba\(255/)
  assert.doesNotMatch(styles.match(/@keyframes loginGuideReveal \{([\s\S]*?)\n\}/)[1], /opacity/)
  assert.match(styles, /\.login-guide-arrow \{[^}]+background: #F1FAF3;/)
  assert.doesNotMatch(template, /class="btn login-guide-action"/)
  assert.doesNotMatch(guideStyle, /(?:margin|height|min-height):/)
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.login-guide,[\s\S]*?animation: none/)
  assert.match(styles, /animation: loginGuideReveal 180ms/)
  assert.match(styles, /\.login-guide-close \{[^}]*top: 8px;[^}]*right: 4px;[^}]*justify-content: flex-end;[^}]*width: 44px;[^}]*padding: 0 2px 0 0 !important;/)
  assert.doesNotMatch(styles, /loginGuideDotBreathe|loginGuideFloat|\.login-guide-dot/)
})

test('closing never navigates and persists across new launches and account session cleanup', async () => {
  const runtime = launch()
  const page = runtime.page()
  await page.onShow()
  page.closeLoginGuide()
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.listeners.size, 0)
  assert.equal(runtime.memory.get(runtime.exports.DISMISSED_KEY), true)
  await page.openLoginGuide()
  assert.deepEqual(runtime.navigation, [])
  const core = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../utils/storage-core.js'), 'utf8'), {
    module: core,
    wx: {
      getStorageInfoSync: () => ({ keys: [...runtime.memory.keys()] }),
      removeStorageSync: key => runtime.memory.delete(key),
    },
  })
  core.exports.clearSession()
  const newLaunch = launch(runtime.memory)
  const next = newLaunch.page()
  await next.onShow()
  assert.equal(next.data.showLoginGuide, false)
  assert.equal(newLaunch.listeners.size, 0)
})

test('Escape closes without login, other keys do not hijack normal keyboard navigation', async () => {
  const runtime = launch()
  const page = runtime.page()
  await page.onShow()
  runtime.key('Tab')
  runtime.key('Enter')
  assert.equal(page.data.showLoginGuide, true)
  runtime.key('Escape')
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.memory.get(runtime.exports.DISMISSED_KEY), true)
  assert.deepEqual(runtime.navigation, [])
})

test('mobile hosts without keyboard APIs retain both touch actions', async () => {
  const runtime = launch(new Map(), { mobile: true })
  const page = runtime.page()
  await page.onShow()
  assert.equal(page.data.showLoginGuide, true)
  page.closeLoginGuide()
  assert.equal(page.data.showLoginGuide, false)
})

test('resize updates measured placement and late queries cannot reopen a closed guide', async () => {
  const runtime = launch(new Map(), { deferLayouts: true })
  const page = runtime.page()
  await page.onShow()
  runtime.resize(320)
  page.onResize()
  runtime.pendingLayouts[1]()
  const anchorLeft = 320 - 168
  assert.ok(anchorLeft + page.data.loginGuideLeft >= 16)
  assert.ok(anchorLeft + page.data.loginGuideLeft + 220 <= 304)
  let writes = 0
  page.closeLoginGuide()
  page.setData = () => { writes++ }
  runtime.pendingLayouts[0]()
  assert.equal(writes, 0)
  assert.equal(page.data.showLoginGuide, false)
})

test('resize measures only after navigation renders, and skips a hidden or closed guide', async () => {
  const runtime = launch()
  const page = runtime.page()
  await page.onShow()
  let rendered
  let measurements = 0
  page.measureNavigation = callback => { rendered = callback }
  page._positionLoginGuide = () => { measurements++ }
  page.onResize()
  assert.equal(measurements, 0)
  rendered()
  assert.equal(measurements, 1)
  page.onResize()
  page.onHide()
  rendered()
  assert.equal(measurements, 1)
  page.onResize()
  page.closeLoginGuide()
  rendered()
  assert.equal(measurements, 1)
})

test('only a measured guest guide becomes visible or accepts a login click', async () => {
  const runtime = launch(new Map(), { deferLayouts: true })
  const page = runtime.page()
  await page.onShow()
  assert.equal(page.data.loginGuideReady, false)
  assert.equal(runtime.listeners.size, 0)
  await page.openLoginGuide()
  assert.deepEqual(runtime.navigation, [])
  runtime.pendingLayouts[0]()
  assert.equal(page.data.loginGuideReady, true)
  assert.equal(runtime.listeners.size, 1)
  await page.openLoginGuide()
  assert.deepEqual(runtime.navigation, [false])
})

for (const options of [{ noMeasurement: true }, { noViewport: true }, { noRects: true },
  { height: 160 }, { menu: { left: 200, top: 40, width: 100, height: 140 } }]) {
  test(`unmeasurable or unsafe placements stay hidden: ${JSON.stringify(options)}`, async () => {
    const runtime = launch(new Map(), options)
    const page = runtime.page()
    await page.onShow()
    assert.equal(page.data.showLoginGuide, false)
    assert.equal(page.data.loginGuideReady, false)
    assert.equal(runtime.listeners.size, 0)
    assert.deepEqual(runtime.navigation, [])
    assert.equal(runtime.memory.size, 0)
  })
}

test('outside taps dismiss without login or changing the explicit-close preference', async () => {
  const runtime = launch(new Map(), { deferLayouts: true })
  const page = runtime.page()
  await page.onShow()
  runtime.pendingLayouts[0]()
  assert.equal(page.data.showLoginGuide, true)
  page._positionLoginGuide()
  page.dismissLoginGuideFromPage()
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(page.data.loginGuideReady, false)
  assert.equal(runtime.listeners.size, 0)
  assert.equal(runtime.memory.size, 0)
  assert.deepEqual(runtime.navigation, [])
  runtime.pendingLayouts[1]()
  assert.equal(page.data.showLoginGuide, false)
  await page.onShow()
  assert.equal(page.data.showLoginGuide, false)
})

test('scrolling away and back before six seconds does not dismiss the anchored guide', async () => {
  const runtime = launch()
  const page = runtime.page()
  await page.onShow()
  runtime.advance(2000)
  page.onPageScroll?.({ scrollTop: 100 })
  runtime.advance(2000)
  page.onPageScroll?.({ scrollTop: 0 })
  assert.equal(page.data.showLoginGuide, true)
  assert.equal(page.data.loginGuideReady, true)
  runtime.advance(2000)
  assert.equal(page.data.showLoginGuide, false)
  assert.equal(runtime.memory.size, 0)
})

test('the six second countdown starts after measurement and resize never restarts it', async () => {
  const runtime = launch(new Map(), { deferLayouts: true })
  const page = runtime.page()
  await page.onShow()
  runtime.advance(10000)
  assert.equal(runtime.timers.size, 0)
  runtime.pendingLayouts[0]()
  runtime.advance(4000)
  page.onResize()
  runtime.pendingLayouts[1]()
  assert.equal(runtime.timers.size, 1)
  runtime.advance(1999)
  assert.equal(page.data.showLoginGuide, true)
  runtime.advance(1)
  assert.equal(page.data.showLoginGuide, false)
})

for (const handler of ['onHide', 'onUnload', 'closeLoginGuide', 'openLoginGuide', 'dismissLoginGuideFromPage']) {
  test(`${handler} clears an active countdown without later state writes`, async () => {
    const runtime = launch()
    const page = runtime.page()
    await page.onShow()
    assert.equal(runtime.timers.size, 1)
    page[handler]()
    assert.equal(runtime.timers.size, 0)
    page.setData = () => assert.fail('late countdown write')
    runtime.advance(6000)
  })
}

test('intrinsic overlay widths stay within 16px screen edges with anchor-relative arrows', () => {
  const { loginGuideLayout } = launch().exports
  for (const width of [280, 320, 375, 390, 430, 768, 1280]) {
    for (const center of [40, width / 2, width - 40]) {
      for (const guideWidth of [178, 220, 232]) {
        const anchor = { left: center - 24, top: 52, width: 48, height: 28 }
        const layout = loginGuideLayout({ windowWidth: width, windowHeight: 800 }, anchor, { width: guideWidth, height: 94 })
        assert.ok(layout)
        const screenLeft = anchor.left + layout.loginGuideLeft
        assert.ok(screenLeft >= 16)
        assert.ok(screenLeft + guideWidth <= width - 16)
        assert.equal(screenLeft + layout.loginGuideArrowLeft, center)
        assert.equal(Object.hasOwn(layout, 'loginGuideOffset'), false)
      }
    }
  }
})

test('clamping cannot sacrifice arrow alignment or overflow a native menu or viewport', () => {
  const { loginGuideLayout } = launch().exports
  const viewport = { windowWidth: 320, windowHeight: 800 }
  const guide = { width: 232, height: 94 }
  assert.equal(loginGuideLayout(viewport, { left: 0, top: 52, width: 24, height: 28 }, guide), null)
  assert.equal(loginGuideLayout(viewport, { left: 130, top: 52, width: 60, height: 28 }, { width: 240, height: 94 }), null)
  assert.equal(loginGuideLayout(viewport, { left: 130, top: -28, width: 60, height: 28 }, guide), null)
  assert.equal(loginGuideLayout(viewport, { left: 130, top: 52, width: 60, height: 28 }, guide,
    { left: 200, top: 90, width: 88, height: 32 }), null)
  assert.ok(loginGuideLayout(viewport, { left: 156, top: 54, width: 56, height: 24 }, { width: 178, height: 94 },
    { left: 220, top: 50, width: 88, height: 32 }))
})
