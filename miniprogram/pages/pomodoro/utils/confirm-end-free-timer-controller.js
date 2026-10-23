/**
 * Controller for confirming the free-timer end action.
 *
 * Increments confirm sequence, clears the overlay, optionally cleans
 * up state when no session exists, or clears the interval and
 * completes the free timer session — all through injected callbacks.
 */

function createConfirmEndFreeTimerController(options) {
  return {
    confirm: () => confirm(options),
  }
}

function confirm(options) {
  if (options.isActionLoading()) return
  const sessionId = options.getSessionId()
  if (!sessionId) {
    options.incrementConfirmActionSeq()
    options.setConfirmTimerSnapshot(null)
    options.safeRemoveStorage('pomodoro_confirm_pause')
    options.setData({ showEndConfirm: false, actionLoading: false })
    return
  }
  options.incrementConfirmActionSeq()
  options.setData({ showEndConfirm: false, actionLoading: false })
  options.clearFreeTimerInterval()
  options.completeFreeTimerSession()
}

module.exports = { createConfirmEndFreeTimerController }
