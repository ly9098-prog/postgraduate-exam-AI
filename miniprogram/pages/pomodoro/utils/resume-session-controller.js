/**
 * Controller for resuming a paused countdown session.
 *
 * Validates session state, accumulates pause duration, persists the
 * resume intent and adjustment, restarts the countdown timer, and
 * retries pending sync — all through injected callbacks.
 */

function createResumeSessionController(options) {
  return {
    resume: () => resume(options),
  }
}

function resume(options) {
  if (typeof options.getSessionStartTime() !== 'number' || options.getSessionStartTime() <= 0) {
    options.warn('resume aborted: invalid sessionStartTime', options.getSessionStartTime())
    options.resetToIdle()
    return
  }
  if (!options.getSessionId() || options.isActionLoading()) return

  const sessionId = options.getSessionId()
  const now = options.now()
  const openPauseMs = options.getPauseStartTime()
    ? Math.max(0, now - options.getPauseStartTime())
    : 0
  const localTotalPausedMs = Math.max(0, Number(options.getTotalPausedMs()) + openPauseMs)
  const totalSec = options.isDebugPreset() ? 10 : (options.getWorkDurationMinutes() ?? 25) * 60

  if (!options.setPendingSync('resume', sessionId, now)) {
    options.showPersistenceError()
    return
  }

  options.safeSetStorage('pomodoro_pause_adjustment', {
    sessionId,
    totalPausedMs: localTotalPausedMs,
    savedAt: now,
  })
  options.safeRemoveStorage('pomodoro_pause')
  options.setTimerFields({ totalPausedMs: localTotalPausedMs, pauseStartTime: null })
  options.setData({ isPaused: false, ringCanvasVisible: true, actionLoading: true })

  const elapsedMs = Math.max(0, now - options.getSessionStartTime() - localTotalPausedMs)
  const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)
  options.startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })

  options.setData({ actionLoading: false })
  options.retryPendingSync().then(synced => {
    if (!synced) options.showToast({ title: '已继续计时，网络恢复后自动同步', icon: 'none' })
  })
}

module.exports = { createResumeSessionController }
