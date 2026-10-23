const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSelectDateController,
} = require('../subpackages/productivity/pomodoro-stats/select-date-controller')

function createHarness(overrides = {}) {
  const state = {
    todayDate: '2024-06-01',
    selectedDate: '2024-05-15',
    customRangeStartDate: '2024-05-15',
    deferredCancelled: false,
    dataPatch: null,
    dataCallback: null,
    loadedDate: null,
  }
  const options = {
    getTodayDate: () => state.todayDate,
    getSelectedDate: () => state.selectedDate,
    getCustomRangeStartDate: () => state.customRangeStartDate,
    cancelDeferredHistory: () => { state.deferredCancelled = true },
    formatPieDateLabel: date => `pie-${date}`,
    formatSelectedDurationLabel: date => `label-${date}`,
    shiftDate: (date, delta) => `${date}+${delta}`,
    setData: (patch, callback) => {
      state.dataPatch = patch
      state.dataCallback = callback
    },
    loadDateData: date => { state.loadedDate = date },
    ...overrides,
  }
  return { controller: createSelectDateController(options), state, options }
}

test('selects a date, clears selection and loads date data', () => {
  const h = createHarness()
  h.controller.select('2024-05-20')

  assert.equal(h.state.deferredCancelled, true)
  assert.deepEqual(h.state.dataPatch, {
    selectedDate: '2024-05-20',
    pieDateLabel: 'pie-2024-05-20',
    selectedDurationLabel: 'label-2024-05-20',
    canGoNextDate: true,
    customRangePickerStartDate: '2024-05-20+-365',
    customRangeStartDate: '2024-05-20+-365',
    selectedSubjectDetail: null,
    _selectedSubject: null,
    durationValueAnimating: true,
  })
  assert.equal(h.state.loadedDate, null)

  h.state.dataCallback()
  assert.equal(h.state.loadedDate, '2024-05-20')
})

test('clamps a custom range start that is later than the new date', () => {
  const h = createHarness()
  h.state.customRangeStartDate = '2099-01-01'
  h.controller.select('2024-05-20')
  assert.equal(h.state.dataPatch.customRangeStartDate, '2024-05-20')
})

test('clamps a custom range start that is earlier than the 365-day window', () => {
  const h = createHarness()
  h.state.customRangeStartDate = '2000-01-01'
  h.controller.select('2024-05-20')
  assert.equal(h.state.dataPatch.customRangeStartDate, '2024-05-20+-365')
})

test('ignores an empty, duplicate, or future date', () => {
  const h = createHarness()
  h.controller.select('')
  assert.equal(h.state.dataPatch, null)

  h.controller.select('2024-05-15')
  assert.equal(h.state.dataPatch, null)

  h.controller.select('2099-01-01')
  assert.equal(h.state.dataPatch, null)
})

test('trims whitespace from the input date', () => {
  const h = createHarness()
  h.controller.select('  2024-05-20  ')
  assert.equal(h.state.dataPatch.selectedDate, '2024-05-20')
})

test('allows selecting today exactly', () => {
  const h = createHarness()
  h.controller.select('2024-06-01')
  assert.equal(h.state.dataPatch.selectedDate, '2024-06-01')
  assert.equal(h.state.dataPatch.canGoNextDate, false)
})
