const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const root = path.resolve(__dirname, '../subpackages/study/wrong-detail')
const plain = value => JSON.parse(JSON.stringify(value))

function fixture() {
  let definition, now = 1000, nextTimer = 0
  const timers = new Map(), cleared = [], patches = [], calls = [], cache = new Map()
  const context = vm.createContext({
    Page: value => { definition = value }, Date: { now: () => now },
    console: { warn: (...args) => calls.push(['warn', ...args]) },
    setTimeout: (fn, ms) => { timers.set(++nextTimer, { fn, ms }); return nextTimer },
    clearTimeout: id => { cleared.push(id); timers.delete(id) },
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const required = request => {
      if (request === '../../../utils/api' || request === '../../../config') return {}
      if (request === '../utils/stem-render') return { resetRenderGuard: () => calls.push(['reset']) }
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      return resolved.startsWith(root + path.sep) ? load(resolved) : require(resolved)
    }
    const source = fs.readFileSync(filename, 'utf8')
    vm.runInContext(`(function(require,module,exports) {\n${source}\n})`,
      context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'wrong-detail.js'))
  const page = Object.assign({}, definition, {
    data: plain(definition.data), _alive: true, _navigationSeq: 4,
    setData(patch) { patches.push(plain(patch)); Object.assign(this.data, patch) },
  })
  return { page, context, timers, cleared, patches, calls,
    advance: ms => { now += ms },
    fire: id => { const timer = timers.get(id); timers.delete(id); timer.fn() } }
}

test('transition start cancels old timer and keeps direction and alive guard', () => {
  const f = fixture(), { page } = f
  page._contentTransitionTimer = f.context.setTimeout(() => {}, 9)
  page._beginContentSwitchTransition('right')
  assert.deepEqual(f.cleared, [1])
  assert.equal(page._contentTransitionTimer, null)
  assert.equal(page._contentTransitionStartedAt, 1000)
  assert.equal(page._contentTransitionDirection, 'right')
  assert.equal(page.data.contentTransitionClass, 'content-slide-out-right')
  page._beginContentSwitchTransition('anything')
  assert.equal(page.data.contentTransitionClass, 'content-slide-out-left')
  page._alive = false
  page._beginContentSwitchTransition('right')
  assert.equal(f.patches.length, 2)
})

test('outgoing wait preserves elapsed time, clamps and default delays', async () => {
  for (const [animMs, elapsed, expected] of [
    [200, 40, 110], [80, 20, 60], [0, 0, 150], [-1, 0, 150],
    ['bad', 0, 150], [Infinity, 0, 150], [20, 40, null],
  ]) {
    const f = fixture()
    f.page._beginContentSwitchTransition('left')
    f.advance(elapsed)
    const pending = f.page._waitForContentSwitchOut('left', animMs)
    if (expected === null) assert.equal(f.timers.size, 0)
    else {
      assert.equal(f.timers.get(1).ms, expected)
      f.fire(1)
    }
    await pending
  }
})

test('waiting for a changed direction starts a fresh outgoing transition', async () => {
  const f = fixture()
  f.page._beginContentSwitchTransition('left')
  f.advance(100)
  const pending = f.page._waitForContentSwitchOut('right', 50)
  assert.equal(f.page._contentTransitionStartedAt, 1100)
  assert.equal(f.page.data.contentTransitionClass, 'content-slide-out-right')
  assert.equal(f.timers.get(1).ms, 50)
  f.fire(1)
  await pending
})

test('incoming animation keeps lock until timer and invokes current clear method', () => {
  const f = fixture(), { page } = f
  page._switching = true
  page._armSwitchWatchdog(5000)
  const watchdog = page._switchWatchdogTimer
  page._finishContentSwitchTransition('left')
  const incoming = page._contentTransitionTimer
  assert.equal(page.data.contentTransitionClass, 'content-slide-in-right')
  assert.equal(page._contentTransitionStartedAt, 0)
  assert.equal(page._contentTransitionDirection, '')
  assert.equal(f.timers.get(incoming).ms, 170)
  assert.equal(page._switching, true)
  const original = page._clearSwitchWatchdog
  page._clearSwitchWatchdog = function () { f.calls.push(['clear-current']); original.call(this) }
  f.fire(incoming)
  assert.equal(page._switching, false)
  assert.equal(page._contentTransitionTimer, null)
  assert.equal(page.data.contentTransitionClass, '')
  assert.deepEqual(f.calls, [['clear-current']])
  assert.ok(f.cleared.includes(watchdog))
})

test('unload cancels transition and watchdog without late view writes', () => {
  const f = fixture(), { page } = f
  page._armSwitchWatchdog()
  page._finishContentSwitchTransition('right')
  assert.equal(page.data.contentTransitionClass, 'content-slide-in-left')
  const late = f.timers.get(page._contentTransitionTimer).fn
  const count = f.patches.length
  page.onUnload()
  assert.equal(f.timers.size, 0)
  assert.equal(page._alive, false)
  late()
  assert.equal(f.patches.length, count)
  assert.equal(page._switching, false)
})

test('watchdog replacement uses default and callback sees current reset method', () => {
  const f = fixture(), { page } = f
  page._armSwitchWatchdog(40)
  const first = page._switchWatchdogTimer
  page._armSwitchWatchdog(-1)
  const second = page._switchWatchdogTimer
  assert.ok(f.cleared.includes(first))
  assert.equal(f.timers.get(second).ms, 35000)
  page._forceResetSwitchLock = () => f.calls.push(['current-reset'])
  f.fire(second)
  assert.equal(page._switchWatchdogTimer, null)
  assert.equal(f.calls.at(-1)[0], 'current-reset')
})

test('forced reset invalidates navigation and clears all switch timers', () => {
  const f = fixture(), { page } = f
  page._armSwitchWatchdog(50)
  page._finishContentSwitchTransition('left')
  page._switchMaskTimer = f.context.setTimeout(() => {}, 20)
  page._switching = true
  page._forceResetSwitchLock()
  assert.equal(page._navigationSeq, 5)
  assert.equal(page._switching, false)
  assert.equal(page._switchMaskTimer, null)
  assert.equal(page._contentTransitionTimer, null)
  assert.equal(page._switchWatchdogTimer, null)
  assert.equal(f.timers.size, 0)
  assert.deepEqual(f.patches.at(-1), {
    contentTransitionClass: '', showSwitchMask: false, aiRegenerating: false,
  })
})

test('swipe thresholds, bounds and locks preserve navigation direction', () => {
  for (const [dx, dy, idx, switching, expected] of [
    [-56, 0, 1, false, [2, 150, 'left']], [56, 0, 1, false, [0, 150, 'right']],
    [-55, 0, 1, false, null], [-60, 50, 1, false, null],
    [60, 0, 0, false, null], [-60, 0, 2, false, null],
    [-60, 0, 1, true, null],
  ]) {
    const f = fixture(), { page } = f
    page.data.questionIds = [11, 12, 13]
    page.data.currentIdx = idx
    page._navigateTo = (...args) => f.calls.push(args)
    page.onAiSwipeStart({ touches: [{ clientX: '100', clientY: '100' }] })
    assert.equal(page._aiSwipeStart.ts, 1000)
    page._switching = switching
    page.onAiSwipeEnd({ changedTouches: [{ clientX: 100 + dx, clientY: 100 + dy }] })
    assert.equal(page._aiSwipeStart, null)
    assert.deepEqual(f.calls, expected ? [expected] : [])
  }
})

test('swipe cancellation and missing touches do not navigate or share state', () => {
  const a = fixture(), b = fixture()
  a.page.onAiSwipeStart({ touches: [{ clientX: 100, clientY: 100 }] })
  assert.equal(b.page._aiSwipeStart, null)
  a.page.onAiSwipeCancel()
  assert.equal(a.page._aiSwipeStart, null)
  a.page.onAiSwipeStart(null)
  a.page.onAiSwipeEnd({})
  assert.deepEqual(a.calls, [])
  a.page._alive = false
  a.page._cancelContentSwitchTransition()
  a.page._forceResetSwitchLock()
  assert.deepEqual(a.patches, [])
})

test('expired watchdog resets the lock and invalidates a pending navigation', () => {
  const f = fixture(), { page } = f
  page._switching = true
  page._contentTransitionDirection = 'left'
  page._switchMaskTimer = f.context.setTimeout(() => {}, 20)
  page._armSwitchWatchdog()
  f.fire(page._switchWatchdogTimer)
  assert.equal(page._navigationSeq, 5)
  assert.equal(page._switching, false)
  assert.equal(page._contentTransitionDirection, '')
  assert.equal(f.timers.size, 0)
  assert.deepEqual(f.patches.at(-1), {
    contentTransitionClass: '', showSwitchMask: false, aiRegenerating: false,
  })
  assert.equal(f.calls[0][0], 'warn')
})

test('transition reads current global clock and timers after module loading', () => {
  const f = fixture(), { page } = f
  f.context.Date.now = () => 777
  page._beginContentSwitchTransition('left')
  assert.equal(page._contentTransitionStartedAt, 777)
  const timers = [], cleared = []
  f.context.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return 900 }
  f.context.clearTimeout = id => cleared.push(id)
  page._contentTransitionTimer = 800
  page._finishContentSwitchTransition('right')
  assert.deepEqual(cleared, [800])
  assert.equal(page._contentTransitionTimer, 900)
  assert.equal(timers[0].ms, 170)
  timers[0].fn()
  assert.equal(page.data.contentTransitionClass, '')
})
