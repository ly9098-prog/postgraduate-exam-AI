function createThemeController(options) {
  const state = { switchTimer: null }
  return {
    viewModel: mode => viewModel(mode, options),
    sync: () => sync(options, state),
    apply: (mode, persist, animate) => apply(mode, persist, animate, options, state),
    toggle: () => toggle(options, state),
    clearSwitchTimer: () => clearSwitchTimer(options, state),
  }
}

function viewModel(mode, options) {
  const themeMode = options.normalizeTheme(mode)
  const isLight = themeMode === 'light'
  return {
    themeMode,
    sliderBlockColor: isLight ? '#153323' : '#ffffff',
    sliderTrackColor: isLight ? 'rgba(21,51,35,0.12)' : 'rgba(255,255,255,0.06)',
    celebrationTheme: isLight ? 'light' : 'dark',
  }
}

function clearSwitchTimer(options, state) {
  if (!state.switchTimer) return
  options.clearTimeout(state.switchTimer)
  state.switchTimer = null
}

// Restoring from storage must not re-patch the view when the live mode already
// matches, but it still reapplies the native navigation/background theme so a
// stale native bar cannot survive a page re-entry.
function sync(options, state) {
  const themeMode = options.getTheme()
  options.applyNativeTheme(themeMode)
  if (themeMode === options.getCurrentMode()) return
  apply(themeMode, false, false, options, state)
}

function apply(mode, persist, animate, options, state) {
  const themeMode = options.normalizeTheme(mode)
  if (persist) options.setTheme(themeMode)
  options.applyNativeTheme(themeMode)
  clearSwitchTimer(options, state)

  const patch = viewModel(themeMode, options)
  if (animate) patch.themeSwitching = true
  options.setData(patch, () => options.afterThemeApplied())

  if (animate) {
    state.switchTimer = options.setTimeout(() => {
      state.switchTimer = null
      options.setData({ themeSwitching: false })
    }, 520)
  }
}

function toggle(options, state) {
  const next = options.getCurrentMode() === 'dark' ? 'light' : 'dark'
  apply(next, true, true, options, state)
}

module.exports = { createThemeController }
