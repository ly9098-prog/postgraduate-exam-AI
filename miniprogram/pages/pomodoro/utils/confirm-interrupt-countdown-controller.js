/**
 * Controller for confirming countdown interruption from the end-confirm
 * overlay.
 *
 * Calculates accumulated pause, persists the terminal intent, retries
 * pending sync, handles terminal conflict, shows a toast, cleans up
 * storage, and resets to idle — all through injected callbacks.
 */

function createConfirmInterruptCountdownController(options) {
  return {
    confirm: () => confirm(options),
  }
}

function confirm(options) {
  if (!options.getSessionId() || options.isActionLoading()) return

  const sessionId = options.getSessionId()
  const snapshot = options.getConfirmTimerSnapshot()
  let totalPausedMs = options.getTotalPausedMs()
  if (snapshot && snapshot.openedAt) {
    totalPausedMs = Math.max(0, Number(snapshot.totalPausedMs || 0) + (options.now() - snapshot.openedAt))
  }
  options.setTotalPausedMs(totalPausedMs)
  options.incrementConfirmActionSeq()

  if (!options.setPendingSync('interrupt', sessionId, options.now())) {
    options.showPersistenceError()
    options.setData({ actionLoading: false })
    return
  }
  options.retryPendingSync().then(synced => {
    const conflict = options.consumeTerminalConflict(sessionId, 'interrupt')
    if (conflict) {
      options.handleTerminalConflict(sessionId, conflict)
      return
    }
    if (!synced) options.showToast({ title: '网络恢复后将自动同步', icon: 'none' })
    else options.loadTodayStats()
  })

  options.showToast({ title: '已结束本次专注', icon: 'none' })
  options.safeRemoveStorage('pomodoro_pause_adjustment')
  options.safeRemoveStorage('pomodoro_confirm_pause')
  options.setConfirmTimerSnapshot(null)
  options.setData({ showEndConfirm: false, actionLoading: false })
  options.resetToIdle()
}

module.exports = { createConfirmInterruptCountdownController }
