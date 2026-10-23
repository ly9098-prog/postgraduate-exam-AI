/**
 * Controller for pausing a countdown session.
 *
 * Persists the pause intent, stops the local timer, saves the pause
 * snapshot, and retries pending sync — all through injected callbacks.
 */

function createPauseSessionController(options) {
  return {
    pause: () => pause(options),
  }
}

function pause(options) {
  if (!options.getSessionId() || options.isActionLoading()) return
  const sessionId = options.getSessionId()
  const pauseStartedAt = options.now()

  if (!options.setPendingSync('pause', sessionId, pauseStartedAt)) {
    options.showPersistenceError()
    return
  }

  options.clearTimer()
  options.setPauseStartTime(pauseStartedAt)
  options.setData({ isPaused: true, actionLoading: true })
  options.safeSetStorage('pomodoro_pause', {
    totalPausedMs: options.getTotalPausedMs(),
    pauseStartTime: pauseStartedAt,
    sessionId,
  })
  options.setData({ actionLoading: false })
  options.retryPendingSync().then(synced => {
    if (!synced) options.showToast({ title: '已暂停，网络恢复后自动同步', icon: 'none' })
  })
}

module.exports = { createPauseSessionController }
