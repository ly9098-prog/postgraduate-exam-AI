function buildConflictToast(conflict) {
  return {
    title: conflict.serverStatus === 'completed'
      ? '已同步其他设备的完成状态'
      : '已同步其他设备的结束状态',
    icon: 'none',
    duration: 2000,
  }
}

function handleTerminalConflict(options, sessionId, conflict) {
  if (!conflict) return false
  if (options.isStorageError(conflict)) {
    options.persistenceError()
    return false
  }
  if (!options.dropSessionActions(sessionId)) {
    options.persistenceError()
    return false
  }
  const completionStored = options.getStorage('pomodoro_completion', 'terminal conflict completion')
  if (!completionStored.ok) {
    options.persistenceError()
    return false
  }
  const completion = completionStored.value
  if (
    completion && completion.sessionId === sessionId &&
    !options.removeStorage('pomodoro_completion', 'terminal conflict completion')
  ) {
    options.persistenceError()
    return false
  }
  options.removeStorage('pomodoro_break', 'best-effort cleanup')
  options.removeStorage('pomodoro_pause_adjustment', 'best-effort cleanup')
  if (!options.ackConflict(conflict)) {
    options.persistenceError()
    return false
  }
  options.completionBreakSec = null
  options.clearTimer()
  options.setData({ showCelebration: false, showEndConfirm: false })
  options.resetIdle()
  options.showToast(buildConflictToast(conflict))
  options.loadStats()
  return true
}

module.exports = { buildConflictToast, handleTerminalConflict }
