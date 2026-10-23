/**
 * Controller for resuming a paused free-timer session.
 *
 * Accumulates pause duration, persists resume intent and adjustment,
 * restarts the free timer interval, and retries pending sync.
 */

function createResumeFreeTimerController(options) {
  return {
    resume: () => resume(options),
  }
}

function resume(options) {
  if (!options.getSessionId() || options.isActionLoading()) return
  const sessionId = options.getSessionId()
  const now = options.now()
  const openPauseMs = options.getPauseStartTime()
    ? Math.max(0, now - options.getPauseStartTime())
    : 0
  const localTotalPausedMs = Math.max(0, Number(options.getTotalPausedMs()) + openPauseMs)

  if (!options.setPendingSync('resume', sessionId, now)) {
    options.showPersistenceError()
    return
  }

  options.safeSetStorage('pomodoro_pause_adjustment', {
    sessionId,
    totalPausedMs: localTotalPausedMs,
    savedAt: now,
  })
  options.safeRemoveStorage('pomodoro_free_pause')
  options.setTimerFields({ totalPausedMs: localTotalPausedMs, pauseStartTime: null })
  options.setData({ isPaused: false, ringCanvasVisible: true, actionLoading: true })
  options.startFreeTimerInterval()
  options.setData({ actionLoading: false })
  options.retryPendingSync().then(synced => {
    if (!synced) options.showToast({ title: '已继续计时，网络恢复后自动同步', icon: 'none' })
  })
}

module.exports = { createResumeFreeTimerController }
