const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  formatDuration,
  formatHourMinute,
  formatMin,
  buildDurationSegments,
} = require('../subpackages/productivity/pomodoro-stats/duration-formatter')

test('formatDuration floors to minutes', () => {
  assert.equal(formatDuration(41), '0分钟')
  assert.equal(formatDuration(2460), '41分钟')
  assert.equal(formatDuration(15540), '4时19分')
})

test('formatDuration handles zero and negative', () => {
  assert.equal(formatDuration(0), '0分钟')
  assert.equal(formatDuration(-100), '0分钟')
  assert.equal(formatDuration(null), '0分钟')
})

test('formatHourMinute always uses hour-minute format', () => {
  assert.equal(formatHourMinute(0), '0时0分')
  assert.equal(formatHourMinute(3600), '1时0分')
  assert.equal(formatHourMinute(7260), '2时1分')
})

test('formatMin uses minutes under one hour', () => {
  assert.equal(formatMin(0), '0分钟')
  assert.equal(formatMin(3000), '50分钟')
  assert.equal(formatMin(7260), '2时1分')
})

test('buildDurationSegments splits numbers and units', () => {
  assert.deepEqual(buildDurationSegments('4时19分'), [
    { type: 'num', text: '4' },
    { type: 'unit', text: '时' },
    { type: 'num', text: '19' },
    { type: 'unit', text: '分' },
  ])
})

test('buildDurationSegments handles 小时 unit', () => {
  assert.deepEqual(buildDurationSegments('3小时'), [
    { type: 'num', text: '3' },
    { type: 'unit', text: '小时' },
  ])
})

test('buildDurationSegments defaults to 0分钟', () => {
  assert.deepEqual(buildDurationSegments(''), [{ type: 'num', text: '0' }, { type: 'unit', text: '分钟' }])
})

test('buildDurationSegments returns raw text for non-matching input', () => {
  assert.deepEqual(buildDurationSegments('abc'), [{ type: 'num', text: 'abc' }])
})
