const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSaveDayStartController,
} = require('../subpackages/productivity/pomodoro-stats/save-day-start-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    viewReady: true,
    selectedDate: '2024-01-01',
    customRangeStartDate: '2024-01-01',
    settingsLoaded: false,
    loadingShown: 0,
    loadingHidden: 0,
    toastShown: null,
    errors: [],
    dataPatch: null,
    dataCallback: null,
    loadDataCalls: 0,
    saveCalls: [],
  }
  const options = {
    isAlive: () => state.alive,
    isViewReady: () => state.viewReady,
    getSelectedDate: () => state.selectedDate,
    getCustomRangeStartDate: () => state.customRangeStartDate,
    markSettingsLoaded: () => { state.settingsLoaded = true },
    showLoading: () => { state.loadingShown += 1 },
    hideLoading: () => { state.loadingHidden += 1 },
    showToast: title => { state.toastShown = title },
    logError: (message, e) => state.errors.push({ message, e }),
    saveSettings: async minute => { state.saveCalls.push(minute) },
    getChinaStudyDate: minute => `2024-06-0${String(minute).length}`,
    minuteToTimeText: minute => `time-${minute}`,
    getStudyDayRangeText: minute => `range-${minute}`,
    formatPieDateLabel: date => `pie-${date}`,
    formatSelectedDurationLabel: date => `label-${date}`,
    setData: (patch, callback) => {
      state.dataPatch = patch
      state.dataCallback = callback
    },
    loadData: () => { state.loadDataCalls += 1 },
    ...overrides,
  }
  return { controller: createSaveDayStartController(options), state, options }
}

test('saves day-start and reloads stats after the view patch', async () => {
  const h = createHarness()
  await h.controller.save(30)

  assert.deepEqual(h.state.saveCalls, [30])
  assert.equal(h.state.settingsLoaded, true)
  assert.equal(h.state.loadingShown, 1)
  assert.equal(h.state.loadingHidden, 1)
  assert.equal(h.state.toastShown, null)
  assert.equal(h.state.loadDataCalls, 0)

  assert.deepEqual(h.state.dataPatch, {
    dayStartMinute: 30,
    dayStartTime: 'time-30',
    studyDayRangeText: 'range-30',
    _todayDate: '2024-06-02',
    selectedDate: '2024-01-01',
    pieDateLabel: 'pie-2024-01-01',
    selectedDurationLabel: 'label-2024-01-01',
    canGoNextDate: true,
    customRangeStartDate: '2024-01-01',
    selectedSubjectDetail: null,
    _selectedSubject: null,
  })

  h.state.dataCallback()
  assert.equal(h.state.loadDataCalls, 1)
})

test('collapses a selected date beyond the new today', async () => {
  const h = createHarness()
  h.state.selectedDate = '2099-01-01'
  h.state.customRangeStartDate = '2099-01-01'
  await h.controller.save(30)

  assert.equal(h.state.dataPatch.selectedDate, '2024-06-02')
  assert.equal(h.state.dataPatch.customRangeStartDate, '2024-06-02')
  assert.equal(h.state.dataPatch.canGoNextDate, false)
})

test('keeps a custom range start no later than the selected date', async () => {
  const h = createHarness()
  h.state.customRangeStartDate = '2023-01-01'
  await h.controller.save(30)
  assert.equal(h.state.dataPatch.customRangeStartDate, '2023-01-01')
})

test('skips reload when the page is dead or the view is not ready', async () => {
  const dead = createHarness()
  dead.state.alive = false
  await dead.controller.save(30)
  dead.state.dataCallback()
  assert.equal(dead.state.loadDataCalls, 0)

  const notReady = createHarness()
  notReady.state.viewReady = false
  await notReady.controller.save(30)
  notReady.state.dataCallback()
  assert.equal(notReady.state.loadDataCalls, 0)
})

test('shows an error toast and always hides loading on failure', async () => {
  const h = createHarness({ saveSettings: async () => { throw new Error('network') } })
  await h.controller.save(30)

  assert.equal(h.state.toastShown, '保存失败，请重试')
  assert.equal(h.state.loadingShown, 1)
  assert.equal(h.state.loadingHidden, 1)
  assert.equal(h.state.errors.length, 1)
  assert.equal(h.state.settingsLoaded, false)
  assert.equal(h.state.dataPatch, null)
})
