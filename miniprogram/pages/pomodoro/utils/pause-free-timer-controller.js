/**
 * Controller for pausing a free-timer session.
 *
 * Persists pause intent, updates elapsed display, stops the free timer
 * interval, saves the pause snapshot, and retries pending sync.
 */

const { formatElapsedSec } = require('./timer-math')

function createPauseFreeTimerController(options) {
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

  options.updateFreeElapsed()
  options.clearFreeTimerInterval()
  options.setTimerFields({
    pauseStartTime: pauseStartedAt,
    freeFriendlyText: formatElapsedSec(options.getElapsedSec()).friendly,
  })
  options.setData({ isPaused: true, actionLoading: true })
  options.safeSetStorage('pomodoro_free_pause', {
    totalPausedMs: options.getTotalPausedMs(),
    pauseStartTime: pauseStartedAt,
    sessionId,
    elapsedSec: options.getElapsedSec(),
    freeDisplayOffsetMs: 0,
  })
  options.setData({ actionLoading: false })
  options.retryPendingSync().then(synced => {
    if (!synced) options.showToast({ title: '已暂停，网络恢复后自动同步', icon: 'none' })
  })
}

module.exports = { createPauseFreeTimerController }
