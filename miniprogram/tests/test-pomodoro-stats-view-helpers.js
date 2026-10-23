const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  easeOutCubic,
  easeInOutCubic,
  formatPieDateLabel,
  formatSelectedDurationLabel,
  hasDistributionData,
  shadeColor,
} = require('../subpackages/productivity/pomodoro-stats/view-helpers')

test('easeOutCubic returns 0 at t=0 and 1 at t=1', () => {
  assert.equal(easeOutCubic(0), 0)
  assert.equal(easeOutCubic(1), 1)
})

test('easeInOutCubic returns 0 at t=0 and 1 at t=1', () => {
  assert.equal(easeInOutCubic(0), 0)
  assert.equal(easeInOutCubic(1), 1)
})

test('formatPieDateLabel returns 今日 for today', () => {
  assert.equal(formatPieDateLabel('2026-10-23', '2026-10-23'), '今日')
  assert.equal(formatPieDateLabel('', '2026-10-23'), '今日')
})

test('formatPieDateLabel returns 昨日 for yesterday', () => {
  assert.equal(formatPieDateLabel('2026-10-22', '2026-10-23'), '昨日')
})

test('formatPieDateLabel returns month/day for other dates', () => {
  assert.equal(formatPieDateLabel('2026-10-20', '2026-10-23'), '10月20日')
})

test('formatPieDateLabel returns raw value for invalid date', () => {
  assert.equal(formatPieDateLabel('bad', '2026-10-23'), 'bad')
})

test('formatSelectedDurationLabel appends 学习', () => {
  assert.equal(formatSelectedDurationLabel('2026-10-23', '2026-10-23'), '今日学习')
  assert.equal(formatSelectedDurationLabel('2026-10-22', '2026-10-23'), '昨日学习')
  assert.equal(formatSelectedDurationLabel('2026-10-20', '2026-10-23'), '10月20日学习')
})

test('hasDistributionData detects positive duration', () => {
  assert.equal(hasDistributionData([{ duration_sec: 10 }]), true)
  assert.equal(hasDistributionData([{ duration_sec: 0 }]), false)
  assert.equal(hasDistributionData(null), false)
  assert.equal(hasDistributionData([]), false)
})

test('shadeColor clamps rgb values', () => {
  assert.equal(shadeColor('#000000', 10), 'rgb(10, 10, 10)')
  assert.equal(shadeColor('#ffffff', -10), 'rgb(245, 245, 245)')
  assert.equal(shadeColor('bad', 10), 'rgb(69, 140, 255)') // fallback #3B82F6 + 10
})
