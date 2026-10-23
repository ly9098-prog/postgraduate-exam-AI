/**
 * Controller for showing the free-timer end confirmation overlay.
 *
 * Builds the confirm snapshot, persists it, optionally fires a backend
 * pause, and updates timer state + view — all through injected callbacks
 * without holding a page reference.
 */

const { buildFreeConfirmSnapshot } = require('./end-confirm-snapshot')
const { buildEndConfirmViewModel } = require('./end-confirm-view-model')

function createShowEndFreeConfirmController(options) {
  return {
    show: () => show(options),
  }
}

function show(options) {
  if (!options.getSessionId() || options.isActionLoading()) return

  const now = options.now()
  const wasPaused = options.isPaused()
  const elapsed = Math.max(0, options.getElapsedSec() || 0)
  const fmt = options.formatElapsedSec(elapsed)

  const confirmActionSeq = options.incrementConfirmActionSeq()
  const snapshot = buildFreeConfirmSnapshot({
    confirmActionSeq,
    sessionId: options.getSessionId(),
    openedAt: now,
    wasPaused,
    elapsedSec: elapsed,
    totalPausedMs: options.getTotalPausedMs(),
    pauseStartTime: options.getPauseStartTime(),
    sessionStartTime: options.getSessionStartTime(),
  })

  if (!options.safeSetStorage('pomodoro_confirm_pause', snapshot)) {
    options.showPersistenceError()
    return
  }
  if (!wasPaused && !options.setPendingSync('pause', options.getSessionId(), now)) {
    options.safeRemoveStorage('pomodoro_confirm_pause')
    options.showPersistenceError()
    return
  }

  options.setConfirmTimerSnapshot(snapshot)
  options.clearFreeTimerInterval()
  options.setTimerFields({
    elapsedSec: elapsed,
    pauseStartTime: now,
    freeFriendlyText: fmt.friendly,
    endConfirmMode: 'free-complete',
  })
  options.setData({
    ...buildEndConfirmViewModel('free-complete', snapshot),
    ringCanvasVisible: true,
    freeDisplayTime: fmt.display,
    isPaused: true,
  })

  if (!wasPaused) {
    options.postPauseWithRetry(snapshot).catch(e =>
      options.warn('free confirm pause backend sync failed', e))
  }
}

module.exports = { createShowEndFreeConfirmController }
