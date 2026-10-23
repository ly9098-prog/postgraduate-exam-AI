const assert = require('node:assert/strict')
const { test } = require('node:test')
const { formatStudyDayRangeText } = require('../subpackages/productivity/pomodoro-stats/study-day-range-text')

const minuteToTimeText = minute => {
  const h = Math.floor(minute / 60)
  const m = minute % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

test('returns the default label for a zero day-start', () => {
  assert.equal(formatStudyDayRangeText(0, minuteToTimeText), '统计日从 00:00 开始')
})

test('formats a non-zero day-start as a cycle range', () => {
  assert.equal(formatStudyDayRangeText(30, minuteToTimeText), '统计周期 00:30 - 次日 00:30')
  assert.equal(formatStudyDayRangeText(90, minuteToTimeText), '统计周期 01:30 - 次日 01:30')
  assert.equal(formatStudyDayRangeText(600, minuteToTimeText), '统计周期 10:00 - 次日 10:00')
})

test('clamps the minute to the 0..1439 range', () => {
  assert.equal(formatStudyDayRangeText(-10, minuteToTimeText), '统计日从 00:00 开始')
  assert.equal(formatStudyDayRangeText(1440, minuteToTimeText), '统计周期 23:59 - 次日 23:59')
})

test('defaults a non-numeric input to zero', () => {
  assert.equal(formatStudyDayRangeText('bad', minuteToTimeText), '统计日从 00:00 开始')
  assert.equal(formatStudyDayRangeText(null, minuteToTimeText), '统计日从 00:00 开始')
  assert.equal(formatStudyDayRangeText(undefined, minuteToTimeText), '统计日从 00:00 开始')
})
