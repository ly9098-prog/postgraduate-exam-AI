const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createThemeController,
} = require('../pages/pomodoro/utils/theme-controller')

function createHarness(overrides = {}) {
  const calls = { native: [], persisted: [], setData: [], after: 0 }
  const timers = { scheduled: [], cleared: [] }
  let nextTimerId = 1
  let currentMode = overrides.currentMode || 'light'
  const options = {
    normalizeTheme: mode => (mode === 'dark' || mode === 'light' ? mode : 'light'),
    getTheme: () => overrides.storedTheme || 'light',
    setTheme(value) {
      calls.persisted.push(value)
    },
    applyNativeTheme(value) {
      calls.native.push(value)
    },
    getCurrentMode: () => currentMode,
    setData(data, callback) {
      calls.setData.push(data)
      if (callback) callback()
    },
    setTimeout(callback, delay) {
      const id = nextTimerId++
      timers.scheduled.push({ id, delay, callback })
      return id
    },
    clearTimeout(id) {
      timers.cleared.push(id)
    },
    afterThemeApplied() {
      calls.after += 1
    },
  }
  return {
    controller: createThemeController(options),
    calls,
    timers,
    setCurrentMode(mode) { currentMode = mode },
  }
}

test('viewModel normalizes the mode and maps light/dark tokens', () => {
  const harness = createHarness()

  assert.deepEqual(harness.controller.viewModel('light'), {
    themeMode: 'light',
    sliderBlockColor: '#153323',
    sliderTrackColor: 'rgba(21,51,35,0.12)',
    celebrationTheme: 'light',
  })
  assert.deepEqual(harness.controller.viewModel('dark'), {
    themeMode: 'dark',
    sliderBlockColor: '#ffffff',
    sliderTrackColor: 'rgba(255,255,255,0.06)',
    celebrationTheme: 'dark',
  })
  assert.equal(harness.controller.viewModel('unknown').themeMode, 'light')
})

test('sync always reapplies the native theme but only patches a changed mode', () => {
  const unchanged = createHarness({ storedTheme: 'light', currentMode: 'light' })
  unchanged.controller.sync()
  assert.deepEqual(unchanged.calls.native, ['light'])
  assert.deepEqual(unchanged.calls.setData, [])

  const changed = createHarness({ storedTheme: 'dark', currentMode: 'light' })
  changed.controller.sync()
  assert.deepEqual(changed.calls.native, ['dark', 'dark'])
  assert.deepEqual(changed.calls.setData, [{
    themeMode: 'dark',
    sliderBlockColor: '#ffffff',
    sliderTrackColor: 'rgba(255,255,255,0.06)',
    celebrationTheme: 'dark',
  }])
  assert.equal(changed.calls.persisted.length, 0)
})

test('apply persists, animates, and clears the switch flag after 520ms', () => {
  const harness = createHarness({ currentMode: 'light' })

  harness.controller.apply('dark', true, true)

  assert.deepEqual(harness.calls.persisted, ['dark'])
  assert.deepEqual(harness.calls.native, ['dark'])
  assert.deepEqual(harness.calls.setData[0], {
    themeMode: 'dark',
    sliderBlockColor: '#ffffff',
    sliderTrackColor: 'rgba(255,255,255,0.06)',
    celebrationTheme: 'dark',
    themeSwitching: true,
  })
  assert.equal(harness.calls.after, 1)
  assert.equal(harness.timers.scheduled.length, 1)
  assert.equal(harness.timers.scheduled[0].delay, 520)

  harness.timers.scheduled[0].callback()
  assert.deepEqual(harness.calls.setData[1], { themeSwitching: false })
})

test('a non-animated apply omits the switch flag and schedules no timer', () => {
  const harness = createHarness({ currentMode: 'light' })

  harness.controller.apply('dark', false, false)

  assert.equal(harness.calls.persisted.length, 0)
  assert.equal(harness.calls.setData[0].themeSwitching, undefined)
  assert.equal(harness.timers.scheduled.length, 0)
})

test('apply cancels a pending switch timer before scheduling the next one', () => {
  const harness = createHarness({ currentMode: 'light' })

  harness.controller.apply('dark', true, true)
  const firstId = harness.timers.scheduled[0].id
  harness.controller.apply('light', true, true)

  assert.deepEqual(harness.timers.cleared, [firstId])
  assert.equal(harness.timers.scheduled.length, 2)
})

test('toggle flips the current mode, persists and animates', () => {
  const toDark = createHarness({ currentMode: 'light' })
  toDark.controller.toggle()
  assert.deepEqual(toDark.calls.persisted, ['dark'])
  assert.deepEqual(toDark.calls.native, ['dark'])
  assert.equal(toDark.calls.setData[0].themeSwitching, true)

  const toLight = createHarness({ currentMode: 'dark' })
  toLight.controller.toggle()
  assert.deepEqual(toLight.calls.persisted, ['light'])
})

test('clearSwitchTimer cancels a pending timer and is a no-op when idle', () => {
  const harness = createHarness({ currentMode: 'light' })

  harness.controller.clearSwitchTimer()
  assert.deepEqual(harness.timers.cleared, [])

  harness.controller.apply('dark', true, true)
  const id = harness.timers.scheduled[0].id
  harness.controller.clearSwitchTimer()
  assert.deepEqual(harness.timers.cleared, [id])

  // A second clear must not double-cancel the already-cleared timer.
  harness.controller.clearSwitchTimer()
  assert.deepEqual(harness.timers.cleared, [id])
})
