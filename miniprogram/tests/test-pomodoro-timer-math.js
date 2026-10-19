const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  formatElapsedSec,
  formatCountdownDisplay,
  calculateElapsedMs,
} = require('../pages/pomodoro/utils/timer-math')

for (const [seconds, display, friendly] of [
  [0, '00:00:00', '0秒'],
  [-1, '00:00:00', '0秒'],
  [59, '00:00:59', '59秒'],
  [60, '00:01:00', '1分00秒'],
  [3599, '00:59:59', '59分59秒'],
  [3600, '01:00:00', '1小时00分00秒'],
  [17999, '04:59:59', '4小时59分59秒'],
  [18000, '05:00:00', '5小时00分00秒'],
]) {
  test(`elapsed display at ${seconds} seconds`, () => {
    assert.deepEqual(formatElapsedSec(seconds), { display, friendly })
  })
}

test('formatters preserve existing coercion and fractional seconds', () => {
  assert.equal(formatElapsedSec('61').display, '00:01:01')
  assert.equal(formatElapsedSec(null).display, '00:00:00')
  assert.equal(formatElapsedSec(1.5).display, '00:00:1.5')
  assert.deepEqual(formatCountdownDisplay(1.5), { min: '00', sec: '1.5' })
})

for (const [seconds, min, sec] of [
  [null, '00', '00'], ['invalid', '00', '00'], [-10, '00', '00'],
  [59, '00', '59'], [60, '01', '00'], ['61', '01', '01'], [3600, '60', '00'],
]) {
  test(`countdown display for ${seconds}`, () => {
    assert.deepEqual(formatCountdownDisplay(seconds), { min, sec })
  })
}

test('elapsed duration subtracts pauses and clamps future starts', () => {
  assert.equal(calculateElapsedMs(10000, 1000, 2500), 6500)
  assert.equal(calculateElapsedMs(10000, '1000', '2500'), 6500)
  assert.equal(calculateElapsedMs(10000, 1000), 9000)
  assert.equal(calculateElapsedMs(10000, 11000, 0), 0)
  assert.equal(calculateElapsedMs(10000, 1000, 10000), 0)
})

test('elapsed calculation rejects invalid session starts', () => {
  for (const start of [null, undefined, 0, -1, '', 'invalid', Infinity, NaN]) {
    assert.equal(calculateElapsedMs(10000, start, 0), 0)
  }
})

test('elapsed calculation does not mask invalid merged pause values', () => {
  assert.ok(Number.isNaN(calculateElapsedMs(10000, 1000, NaN)))
  assert.ok(Number.isNaN(calculateElapsedMs(10000, 1000, 'invalid')))
})

test('elapsed calculation keeps millisecond precision across the five hour boundary', () => {
  assert.equal(calculateElapsedMs(18001000, 1001, 0), 17999999)
  assert.equal(calculateElapsedMs(18001000, 1000, 0), 18000000)
  assert.equal(calculateElapsedMs(18001000, 1000, 1), 17999999)
})
