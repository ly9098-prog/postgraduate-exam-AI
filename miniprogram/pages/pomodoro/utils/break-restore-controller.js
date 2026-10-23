function createBreakRestoreController(options) {
  return {
    restore: () => restore(options),
  }
}

function restore(options) {
  try {
    const saved = options.getStorageSync('pomodoro_break')
    if (!saved || !saved.startTime || !saved.totalSec) return false
    const totalMs = Math.max(1, Number(saved.totalSec) * 1000)
    const remainingMs = Math.max(0, Number(saved.startTime) + totalMs - options.now())
    if (remainingMs <= 0) {
      options.removeStorage('pomodoro_break', 'best-effort cleanup')
      options.resetIdle()
      return false
    }
    options.startBreak(Number(saved.totalSec), {
      startTime: Number(saved.startTime),
      remainingMs,
    })
    return true
  } catch (_) {
    return false
  }
}

module.exports = { createBreakRestoreController }
