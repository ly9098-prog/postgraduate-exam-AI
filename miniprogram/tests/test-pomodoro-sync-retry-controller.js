const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSyncRetryController,
  isRetryableSyncError
} = require('../pages/pomodoro/utils/sync-retry-controller')

function fixture() {
  const timers = new Map()
  const events = []
  let nextId = 0
  const options = {
    setTimeout(fn, delay) {
      const id = ++nextId
      timers.set(id, { fn, delay })
      return id
    },
    clearTimeout: id => timers.delete(id),
    isVisible: () => true,
    hasPending: () => true,
    retry: async () => { events.push('retry'); return true },
    warn: (...args) => events.push(args),
    consumeConflict: () => null,
    handleConflict: (...args) => events.push(args),
    loadStats: () => events.push('stats'),
    canListen: () => true,
    onNetworkStatusChange: handler => events.push(['on', handler]),
    offNetworkStatusChange: handler => events.push(['off', handler])
  }
  const controller = createSyncRetryController(options)
  function fire() {
    const [id, timer] = timers.entries().next().value
    timers.delete(id)
    timer.fn()
  }
  return { controller, options, timers, events, fire }
}

const flush = () => new Promise(resolve => setImmediate(resolve))

test('classifies network errors and retryable HTTP statuses', () => {
  for (const error of [null, {}, { code: 'NETWORK_ERROR', statusCode: 400 },
    ...[0, 408, 429, 500, 503, '503'].map(statusCode => ({ statusCode }))]) {
    assert.equal(isRetryableSyncError(error), true)
  }
  for (const statusCode of [200, 400, 401, 403, 404, 409, 422]) {
    assert.equal(isRetryableSyncError({ statusCode }), false)
  }
})

test('uses capped backoff and suppresses duplicate timers', async () => {
  const f = fixture()
  for (const delay of [2000, 5000, 15000, 30000, 60000, 60000]) {
    f.controller.schedule({})
    f.controller.schedule({})
    assert.equal(f.timers.size, 1)
    assert.equal([...f.timers.values()][0].delay, delay)
    f.fire()
    await flush()
  }
  assert.equal(f.events.filter(event => event === 'retry').length, 6)
})

test('clear preserves attempt unless reset is requested', () => {
  const f = fixture()
  f.controller.schedule({})
  f.controller.clear()
  assert.equal(f.timers.size, 0)
  f.controller.schedule({})
  assert.equal([...f.timers.values()][0].delay, 5000)
  f.controller.clear(true)
  f.controller.schedule({})
  assert.equal([...f.timers.values()][0].delay, 2000)
})

test('checks visibility and pending work before scheduling and firing', () => {
  for (const key of ['isVisible', 'hasPending']) {
    const f = fixture()
    f.options[key] = () => false
    f.controller.schedule({})
    assert.equal(f.timers.size, 0)
    f.options[key] = () => true
    f.controller.schedule({ statusCode: 403 })
    assert.equal(f.timers.size, 0)
    f.controller.schedule({})
    f.options[key] = () => false
    f.fire()
    assert.deepEqual(f.events, [])
  }
})

test('reconnect resets backoff and handles conflict before stats', async () => {
  const f = fixture()
  f.controller.register()
  const handler = f.events[0][1]
  f.controller.schedule({})
  handler({ isConnected: false })
  assert.equal(f.timers.size, 1)
  const conflict = { sessionId: 'test-session' }
  f.options.consumeConflict = () => conflict
  handler({ isConnected: true })
  await flush()
  assert.equal(f.timers.size, 0)
  assert.deepEqual(f.events.slice(1), ['retry', ['test-session', conflict]])
  f.controller.schedule({})
  assert.equal([...f.timers.values()][0].delay, 2000)
  f.options.consumeConflict = () => null
  handler({ isConnected: true })
  await flush()
  assert.deepEqual(f.events.slice(-2), ['retry', 'stats'])
})

test('reconnect observes visibility after async retry', async () => {
  const f = fixture()
  let resolve
  f.options.retry = () => new Promise(done => { resolve = done })
  f.controller.register()
  f.events[0][1]({ isConnected: true })
  f.options.isVisible = () => false
  resolve(true)
  await flush()
  assert.equal(f.events.length, 1)
})

test('retry rejection is reported for timer and reconnect', async () => {
  const f = fixture()
  const error = new Error('synthetic failure')
  f.options.retry = async () => { throw error }
  f.controller.schedule({})
  f.fire()
  await flush()
  assert.deepEqual(f.events[0], ['pomodoro delayed sync retry failed', error])
  f.controller.register()
  f.events[1][1]({ isConnected: true })
  await flush()
  assert.deepEqual(f.events[2], ['pomodoro reconnect sync failed', error])
})

test('registration is idempotent and unregister uses the same callback', () => {
  const f = fixture()
  f.options.canListen = () => false
  f.controller.register()
  assert.deepEqual(f.events, [])
  f.options.canListen = () => true
  f.controller.register()
  f.controller.register()
  f.controller.unregister()
  f.controller.unregister()
  assert.equal(f.events.length, 2)
  assert.equal(f.events[0][1], f.events[1][1])
  f.controller.register()
  f.options.offNetworkStatusChange = () => { throw new Error('synthetic failure') }
  f.controller.unregister()
  f.controller.register()
  assert.equal(f.events.length, 4)
})

test('instances do not share timers, attempts or registrations', () => {
  const first = fixture()
  const second = fixture()
  first.controller.schedule({})
  first.controller.clear()
  first.controller.schedule({})
  second.controller.schedule({})
  assert.equal([...first.timers.values()][0].delay, 5000)
  assert.equal([...second.timers.values()][0].delay, 2000)
  first.controller.clear(true)
  assert.equal(second.timers.size, 1)
  first.controller.register()
  second.controller.register()
  assert.notEqual(first.events[0][1], second.events[0][1])
})
