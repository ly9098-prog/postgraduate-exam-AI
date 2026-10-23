const assert = require('node:assert/strict')
const { test } = require('node:test')
const { reconcileFromServer } = require('../subpackages/productivity/pomodoro-stats/reconcile-controller')

function baseOptions(overrides = {}) {
  return {
    stats: { day_start_minute: 30, today_date: '2024-06-01' },
    summary: null,
    dayStartMinute: 0,
    todayDate: '2024-01-01',
    selectedDate: '2024-01-01',
    customRangeStartDate: '2024-01-01',
    minuteToTimeText: minute => `time-${minute}`,
    getStudyDayRangeText: minute => `range-${minute}`,
    shiftDate: (date, delta) => `${date}+${delta}`,
    ...overrides,
  }
}

test('updates day-start fields when the server value differs', () => {
  const result = reconcileFromServer(baseOptions())
  assert.equal(result.patch.dayStartMinute, 30)
  assert.equal(result.patch.dayStartTime, 'time-30')
  assert.equal(result.patch.studyDayRangeText, 'range-30')
})

test('keeps the existing day-start when the server value matches', () => {
  const result = reconcileFromServer(baseOptions({ dayStartMinute: 30 }))
  assert.equal(result.patch.dayStartMinute, undefined)
  assert.equal(result.patch.dayStartTime, undefined)
})

test('clamps an out-of-range server day_start_minute', () => {
  const over = reconcileFromServer(baseOptions({ stats: { day_start_minute: 9999, today_date: '2024-06-01' } }))
  assert.equal(over.patch.dayStartMinute, 1439)

  const under = reconcileFromServer(baseOptions({ stats: { day_start_minute: -5, today_date: '2024-06-01' } }))
  // -5 clamps to 0 which equals the current dayStartMinute, so no patch is emitted.
  assert.equal(under.patch.dayStartMinute, undefined)
})

test('falls back to the current day-start for a non-numeric server value', () => {
  const result = reconcileFromServer(baseOptions({
    dayStartMinute: 42,
    stats: { day_start_minute: 'bad', today_date: '2024-06-01' },
  }))
  assert.equal(result.patch.dayStartMinute, undefined)
})

test('follows the server today and reports changedToday', () => {
  const result = reconcileFromServer(baseOptions())
  assert.equal(result.patch._todayDate, '2024-06-01')
  assert.equal(result.patch.selectedDate, '2024-06-01')
  assert.equal(result.patch.pieDateLabel, '今日')
  assert.equal(result.changedToday, true)
  assert.equal(result.today, '2024-06-01')
  assert.equal(result.selectedDate, '2024-06-01')
})

test('keeps a selected date within the new today', () => {
  const result = reconcileFromServer(baseOptions({ selectedDate: '2024-05-15' }))
  assert.equal(result.patch.selectedDate, undefined)
  assert.equal(result.changedToday, true)
  assert.equal(result.selectedDate, '2024-05-15')
})

test('clamps the custom range start to the selected date window', () => {
  const tooLate = reconcileFromServer(baseOptions({ customRangeStartDate: '2099-01-01' }))
  assert.equal(tooLate.patch.customRangeStartDate, '2024-06-01')

  const tooEarly = reconcileFromServer(baseOptions({ customRangeStartDate: '2000-01-01' }))
  assert.equal(tooEarly.patch.customRangeStartDate, '2024-06-01+-365')
})

test('uses summary.date as a fallback today when stats.today_date is missing', () => {
  const result = reconcileFromServer(baseOptions({
    stats: { day_start_minute: 0 },
    summary: { date: '2024-06-02' },
  }))
  assert.equal(result.patch._todayDate, '2024-06-02')
  assert.equal(result.today, '2024-06-02')
})

test('returns an empty patch when nothing changes', () => {
  const result = reconcileFromServer(baseOptions({
    stats: { day_start_minute: 0, today_date: '2024-01-01' },
    dayStartMinute: 0,
    todayDate: '2024-01-01',
    selectedDate: '2023-12-15',
    customRangeStartDate: '2023-12-15',
  }))
  assert.deepEqual(result.patch, {
    cumulativePickerStartDate: '2024-01-01+-365',
    canGoNextDate: true,
    customRangePickerStartDate: '2023-12-15+-365',
    customRangeStartDate: '2023-12-15+-365',
  })
  assert.equal(result.changedToday, false)
})
