const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCumulativeStartController,
} = require('../subpackages/productivity/pomodoro-stats/cumulative-start-controller')

function createHarness(overrides = {}) {
  const state = {
    todayDate: '2026-10-25',
    pickerStartDate: '2025-10-25',
    cumulativeStartDate: '2026-01-01',
    customized: false,
    patches: [],
    callbacks: [],
    refreshes: [],
  }
  const options = {
    getTodayDate: () => state.todayDate,
    getPickerStartDate: () => state.pickerStartDate,
    getCumulativeStartDate: () => state.cumulativeStartDate,
    shiftDate: (date, delta) => `${date}+${delta}`,
    markCustomized: () => { state.customized = true },
    setData: (patch, callback) => {
      state.patches.push(patch)
      state.callbacks.push(callback)
    },
    refreshCumulativeSummary: (date, silent) => state.refreshes.push({ date, silent }),
    ...overrides,
  }
  return { controller: createCumulativeStartController(options), state }
}

test('clamps and refreshes a new cumulative start date', () => {
  const h = createHarness()
  assert.equal(h.controller.change({ detail: { value: '2026-03-01' } }), '2026-03-01')

  assert.equal(h.state.customized, true)
  assert.deepEqual(h.state.patches, [{ cumulativeStartDate: '2026-03-01', cumulativeLoading: true }])
  h.state.callbacks[0]()
  assert.deepEqual(h.state.refreshes, [{ date: '2026-03-01', silent: false }])
})

test('clamps the selected date to the picker and today bounds', () => {
  const h = createHarness()
  assert.equal(h.controller.change({ detail: { value: '2020-01-01' } }), '2025-10-25')
  assert.equal(h.controller.change({ detail: { value: '2099-01-01' } }), '2026-10-25')
})

test('falls back to a 365-day lower bound when the picker bound is absent', () => {
  const h = createHarness({ getPickerStartDate: () => '' })
  assert.equal(h.controller.change({ detail: { value: '2000-01-01' } }), '2026-10-25')
})

test('ignores empty and duplicate dates', () => {
  const h = createHarness()
  assert.equal(h.controller.change({ detail: { value: '' } }), null)
  assert.equal(h.controller.change({ detail: {} }), null)
  assert.equal(h.controller.change({ detail: { value: '2026-01-01' } }), null)
  assert.deepEqual(h.state.patches, [])
  assert.equal(h.state.customized, false)
})
