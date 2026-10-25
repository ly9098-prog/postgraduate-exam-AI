function createPomodoroSessionActionDropper(options) {
  return {
    drop: dropImpl.bind(null, options),
  }
}

function dropImpl(options, sessionId) {
  const queue = options.getPendingPomodoroSyncQueue()
  if (queue === null) return false
  const persisted = options.writePendingPomodoroSyncQueue(
    queue.filter(item => item.sessionId !== sessionId)
  )
  if (!persisted) return false

  // Also remove stale per-session optimistic snapshots. Never touch a newer
  // session's cache when reconciliation discovers an old cross-device row.
  const staleSnapshotKeys = ['pomodoro_pause', 'pomodoro_free_pause', 'pomodoro_pause_adjustment']
  for (var keyIndex = 0; keyIndex < staleSnapshotKeys.length; keyIndex += 1) {
    const key = staleSnapshotKeys[keyIndex]
    const stored = options.safeGetPomodoroStorage(key, 'drop reconciled session snapshot')
    if (!stored.ok) return false
    if (stored.value && stored.value.sessionId === sessionId) {
      if (!options.safeRemovePomodoroStorage(key, 'drop reconciled session snapshot')) return false
    }
  }
  const running = options.safeGetPomodoroStorage('pomodoro_running_state', 'drop reconciled running snapshot')
  if (!running.ok) return false
  if (running.value && running.value.sessionId === sessionId) {
    if (!options.safeRemovePomodoroStorage('pomodoro_running_state', 'drop reconciled running snapshot')) return false
  }
  return true
}

module.exports = {
  createPomodoroSessionActionDropper,
}
