const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDateNavigationController,
} = require('../subpackages/productivity/pomodoro-stats/date-navigation-controller')

function createHarness(overrides = {}) {
  const state = {
    todayDate: '2026-10-25',
    selectedDate: '2026-10-24',
    canGoNextDate: true,
    selections: [],
  }
  const options = {
    getTodayDate: () => state.todayDate,
    getSelectedDate: () => state.selectedDate,
    canGoNextDate: () => state.canGoNextDate,
    shiftDate: (date, delta) => `${date}+${delta}`,
    selectDate: date => {
      state.selections.push(date)
      state.selectedDate = date
      return date
    },
    ...overrides,
  }
  return { controller: createDateNavigationController(options), state }
}

test('moves to the previous date and falls back to today', () => {
  const h = createHarness()
  assert.equal(h.controller.previous(), '2026-10-24+-1')
  assert.deepEqual(h.state.selections, ['2026-10-24+-1'])

  h.state.selectedDate = ''
  assert.equal(h.controller.previous(), '2026-10-25+-1')
})

test('does not move previous without a date', () => {
  const h = createHarness({ getTodayDate: () => '', getSelectedDate: () => '' })
  assert.equal(h.controller.previous(), null)
  assert.deepEqual(h.state.selections, [])
})

test('moves next and clamps to today', () => {
  const h = createHarness()
  assert.equal(h.controller.next(), '2026-10-24+1')

  h.state.selectedDate = '2026-10-25'
  h.state.todayDate = '2026-10-25'
  h.state.canGoNextDate = true
  assert.equal(h.controller.next(), '2026-10-25')
})

test('does not move next when disabled or dates are unavailable', () => {
  const disabled = createHarness({ canGoNextDate: () => false })
  assert.equal(disabled.controller.next(), null)

  const noCurrent = createHarness({ getSelectedDate: () => '', getTodayDate: () => '' })
  assert.equal(noCurrent.controller.next(), null)

  const noToday = createHarness({ getTodayDate: () => '' })
  assert.equal(noToday.controller.next(), null)
})

test('jumps to today only when another date is selected', () => {
  const h = createHarness()
  assert.equal(h.controller.today(), '2026-10-25')

  h.state.selectedDate = '2026-10-25'
  assert.equal(h.controller.today(), null)

  const noToday = createHarness({ getTodayDate: () => '' })
  assert.equal(noToday.controller.today(), null)
})
