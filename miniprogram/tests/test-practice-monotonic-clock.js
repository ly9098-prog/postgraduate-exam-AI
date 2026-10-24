const assert = require('node:assert/strict')
const { test } = require('node:test')
const freshClock = require.resolve('../subpackages/study/practice/utils/monotonic-clock')

function withWx(clock, run) {
  delete require.cache[freshClock]
  const { monotonicNow } = require(freshClock)
  const previousWx = global.wx
  global.wx = { getPerformance: () => clock }
  try {
    return run(monotonicNow)
  } finally {
    global.wx = previousWx
  }
}

test('uses WeChat performance clock when available', () => {
  withWx({ now: () => 12345 }, (monotonicNow) => {
    assert.equal(monotonicNow(), 12345)
  })
})

test('caches the performance clock between calls', () => {
  let reads = 0
  withWx({
    get now() {
      reads += 1
      return 12345
    },
  }, (monotonicNow) => {
    monotonicNow()
    monotonicNow()
  })
  assert.equal(reads, 1)
})

test('falls back to Date.now without a usable performance clock', () => {
  const before = Date.now()
  const value = withWx({ now: null }, (monotonicNow) => monotonicNow())
  assert.ok(value >= before)
})

test('falls back to Date.now when WeChat throws', () => {
  const before = Date.now()
  const value = withWx({
    get now() {
      throw new Error('clock unavailable')
    },
  }, (monotonicNow) => monotonicNow())
  assert.ok(value >= before)
})

test('retries only once after a broken performance clock', () => {
  let reads = 0
  withWx({
    get now() {
      reads += 1
      throw new Error('clock unavailable')
    },
  }, (monotonicNow) => {
    monotonicNow()
    monotonicNow()
  })
  assert.equal(reads, 2)
})
