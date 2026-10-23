/**
 * Controller for confirming the end-timer action from the end-confirm overlay.
 *
 * Dispatches to the appropriate sub-action based on endConfirmMode,
 * or shows an error toast for invalid modes — all through injected
 * callbacks.
 */

function createConfirmEndTimerController(options) {
  return {
    confirm: () => confirm(options),
  }
}

function confirm(options) {
  if (options.isActionLoading()) return

  const mode = options.getEndConfirmMode()

  if (mode === 'free-complete') {
    return options.confirmEndFreeTimer()
  }

  if (mode === 'countdown-interrupt') {
    return options.confirmInterruptCountdown()
  }

  options.warn('[pomodoro] invalid end confirm mode', {
    mode,
    sessionId: options.getSessionId(),
    snapshotMode: options.getSnapshotMode(),
  })
  options.showToast({
    title: '结束状态异常，请重新操作',
    icon: 'none',
  })
}

module.exports = { createConfirmEndTimerController }
