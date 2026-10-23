function createCelebrationDismissController(options) {
  return {
    dismiss: () => dismiss(options),
  }
}

function dismiss(options) {
  const completionStored = options.getStorage('pomodoro_completion', 'dismiss celebration')
  if (!completionStored.ok) {
    options.persistenceError()
    return
  }
  const completionFlag = completionStored.value
  const breakSec = options.resolveBreakSec(completionFlag, options.getCompletionBreakSec(), options.view())
  options.removeStorage('pomodoro_completion', 'best-effort cleanup')
  options.setCompletionBreakSec(null)
  options.setData({ showCelebration: false })
  if (breakSec > 0) {
    options.startBreak(breakSec)
  } else {
    options.resetIdle()
  }
}

module.exports = { createCelebrationDismissController }
