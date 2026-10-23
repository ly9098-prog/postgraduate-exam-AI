const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSettingsController,
} = require('../subpackages/productivity/pomodoro-stats/settings-controller')

function createHarness(overrides = {}) {
  const state = {
    loaded: false,
    settings: { day_start_minute: 30 },
    todayDate: '2024-01-01',
    selectedDate: '2024-01-01',
    customRangeStartDate: '2024-01-01',
    dataPatch: null,
    loadedMarks: 0,
    errors: [],
  }
  const options = {
    isLoaded: () => state.loaded,
    markLoaded: () => { state.loaded = true; state.loadedMarks += 1 },
    getSettings: async () => state.settings,
    getTodayDate: () => state.todayDate,
    getSelectedDate: () => state.selectedDate,
    getCustomRangeStartDate: () => state.customRangeStartDate,
    getChinaStudyDate: minute => `2024-06-0${minute}`,
    minuteToTimeText: minute => `time-${minute}`,
    getStudyDayRangeText: minute => `range-${minute}`,
    shiftDate: (date, delta) => `${date}+${delta}`,
    setData: patch => { state.dataPatch = patch },
    logError: (message, e) => state.errors.push({ message, e }),
    ...overrides,
  }
  return { controller: createSettingsController(options), state, options }
}

test('loads settings once and marks the page loaded', async () => {
  const h = createHarness()
  await h.controller.ensure()

  assert.equal(h.state.loadedMarks, 1)
  assert.deepEqual(h.state.dataPatch, {
    dayStartMinute: 30,
    dayStartTime: 'time-30',
    studyDayRangeText: 'range-30',
    cumulativePickerStartDate: '2024-06-030+-365',
    _todayDate: '2024-06-030',
    selectedDate: '2024-06-030',
    pieDateLabel: '今日',
    selectedDurationLabel: '今日学习',
    canGoNextDate: false,
    customRangePickerStartDate: '2024-06-030+-365',
    customRangeStartDate: '2024-06-030+-365',
  })
})

test('does not refetch after the page is already loaded', async () => {
  const h = createHarness()
  h.state.loaded = true
  await h.controller.ensure()
  assert.equal(h.state.dataPatch, null)
  assert.equal(h.state.loadedMarks, 0)
})

test('caches an in-flight request and does not double-fetch', async () => {
  const h = createHarness()
  let resolveGet
  let getCalls = 0
  h.options.getSettings = () => {
    getCalls += 1
    return new Promise(resolve => { resolveGet = resolve })
  }
  const first = h.controller.ensure()
  const second = h.controller.ensure()
  assert.equal(getCalls, 1)
  resolveGet({ day_start_minute: 30 })
  await Promise.all([first, second])
  assert.equal(getCalls, 1)
})

test('clamps day_start_minute to the 0..1439 range', async () => {
  const h = createHarness()
  h.state.settings = { day_start_minute: -10 }
  await h.controller.ensure()
  assert.equal(h.state.dataPatch.dayStartMinute, 0)

  const over = createHarness()
  over.state.settings = { day_start_minute: 9999 }
  await over.controller.ensure()
  assert.equal(over.state.dataPatch.dayStartMinute, 1439)
})

test('defaults a non-numeric day_start_minute to zero', async () => {
  const h = createHarness()
  h.state.settings = { day_start_minute: 'not-a-number' }
  await h.controller.ensure()
  assert.equal(h.state.dataPatch.dayStartMinute, 0)
})

test('keeps a selected date within the new today and clamps the custom range', async () => {
  const h = createHarness()
  h.state.todayDate = '2024-01-01'
  h.state.selectedDate = '2024-06-030'
  h.state.customRangeStartDate = '2023-01-01'
  await h.controller.ensure()
  assert.equal(h.state.dataPatch.selectedDate, undefined)
  assert.equal(h.state.dataPatch.customRangeStartDate, '2024-06-030+-365')
})

test('bails out when the page becomes loaded while the GET is in flight', async () => {
  const h = createHarness()
  let resolveGet
  h.options.getSettings = () => new Promise(resolve => { resolveGet = resolve })
  const first = h.controller.ensure()
  h.state.loaded = true
  resolveGet({ day_start_minute: 30 })
  await first
  assert.equal(h.state.dataPatch, null)
})

test('logs an error and clears the promise on failure', async () => {
  const h = createHarness({ getSettings: async () => { throw new Error('network') } })
  await h.controller.ensure()
  assert.equal(h.state.errors.length, 1)
  assert.equal(h.state.loadedMarks, 0)
  assert.equal(h.state.dataPatch, null)

  // A second ensure should retry rather than staying locked.
  h.state.settings = { day_start_minute: 30 }
  h.options.getSettings = async () => ({ day_start_minute: 30 })
  await h.controller.ensure()
  assert.equal(h.state.loadedMarks, 1)
})
