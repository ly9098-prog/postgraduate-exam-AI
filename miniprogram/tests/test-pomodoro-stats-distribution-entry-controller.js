const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDistributionEntryController,
} = require('../subpackages/productivity/pomodoro-stats/distribution-entry-controller')

function createHarness(overrides = {}) {
  const state = {
    selectedDate: '2026-10-24',
    todayDate: '2026-10-25',
    distributionPeriod: 'day',
    customRangePickerStartDate: '2025-10-24',
    patches: [],
    callbacks: [],
    loads: [],
  }
  const options = {
    getSelectedDate: () => state.selectedDate,
    getTodayDate: () => state.todayDate,
    getDistributionPeriod: () => state.distributionPeriod,
    getCustomRangePickerStartDate: () => state.customRangePickerStartDate,
    shiftDate: (date, delta) => `${date}+${delta}`,
    setData: (patch, callback) => {
      state.patches.push(patch)
      state.callbacks.push(callback)
    },
    loadDistributionForPeriod: (period, animate) => state.loads.push({ period, animate }),
    ...overrides,
  }
  return { controller: createDistributionEntryController(options), state }
}

test('loads a newly selected distribution period', () => {
  const h = createHarness()
  const event = { currentTarget: { dataset: { period: 'week' } } }
  assert.equal(h.controller.tapPeriod(event), 'week')
  assert.deepEqual(h.state.loads, [{ period: 'week', animate: true }])
})

test('ignores missing and duplicate distribution periods', () => {
  const h = createHarness()
  assert.equal(h.controller.tapPeriod({}), null)
  assert.equal(h.controller.tapPeriod({ currentTarget: {} }), null)
  assert.equal(h.controller.tapPeriod({ currentTarget: { dataset: { period: 'day' } } }), null)
  assert.deepEqual(h.state.loads, [])
})

test('clamps and loads a custom range start', () => {
  const h = createHarness()
  assert.equal(h.controller.changeCustomStart({ detail: { value: '2020-01-01' } }), '2025-10-24')
  assert.equal(h.controller.changeCustomStart({ detail: { value: '2099-01-01' } }), '2026-10-24')

  assert.deepEqual(h.state.patches, [
    { customRangeStartDate: '2025-10-24', distributionPeriod: 'custom' },
    { customRangeStartDate: '2026-10-24', distributionPeriod: 'custom' },
  ])
  h.state.callbacks[0]()
  h.state.callbacks[1]()
  assert.deepEqual(h.state.loads, [
    { period: 'custom', animate: true },
    { period: 'custom', animate: true },
  ])
})

test('falls back to today and a 365-day lower bound', () => {
  const h = createHarness({ getSelectedDate: () => '', getCustomRangePickerStartDate: () => '' })
  assert.equal(h.controller.changeCustomStart({ detail: { value: '2000-01-01' } }), '2026-10-25')
})

test('ignores an empty custom range date', () => {
  const h = createHarness()
  assert.equal(h.controller.changeCustomStart({ detail: { value: '' } }), null)
  assert.equal(h.controller.changeCustomStart({ detail: {} }), null)
  assert.deepEqual(h.state.patches, [])
  assert.deepEqual(h.state.loads, [])
})
