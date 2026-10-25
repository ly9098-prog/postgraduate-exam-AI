function createSkipBreakController(options) {
  return {
    skip: () => skip(options),
  }
}

function skip(options) {
  options.clearTimer()
  options.removeStorage('pomodoro_break', 'best-effort cleanup')
  options.resetIdle()
}

module.exports = { createSkipBreakController }
