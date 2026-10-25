const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDayStartEntryController,
} = require('../subpackages/productivity/pomodoro-stats/day-start-entry-controller')

function createHarness(overrides = {}) {
  const state = { saved: [] }
  const controller = createDayStartEntryController({
    timeTextToMinute: value => {
      if (typeof value !== 'string' || !/^\d{2}:\d{2}$/.test(value)) return NaN
      return Number(value.split(':')[0]) * 60 + Number(value.split(':')[1])
    },
    getDayStartMinute: () => 0,
    saveDayStart: minute => state.saved.push(minute),
    ...overrides,
  })
  return { controller, state }
}

test('ignores malformed and non-string picker values', () => {
  for (const event of [undefined, null, {}, { detail: null }, { detail: { value: null } },
    { detail: { value: 30 } }]) {
    const { controller, state } = createHarness()
    controller.change(event)
    assert.deepEqual(state.saved, [])
  }
})

test('does not save when the selected minute is unchanged', () => {
  const { controller, state } = createHarness({
    getDayStartMinute: () => 30,
  })

  controller.change({ detail: { value: '00:30' } })

  assert.deepEqual(state.saved, [])
})

test('converts the picker value and delegates to save', () => {
  const { controller, state } = createHarness()

  controller.change({ detail: { value: '01:05' } })

  assert.deepEqual(state.saved, [65])
})
