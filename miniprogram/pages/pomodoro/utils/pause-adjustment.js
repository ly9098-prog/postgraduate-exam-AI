function getLocalPauseAdjustment(storage, sessionId, failClosed) {
  const stored = storage.read('pomodoro_pause_adjustment', 'pause adjustment')
  if (!stored.ok) return failClosed ? null : 0
  const adjust = stored.value
  if (!adjust || adjust.sessionId !== sessionId) return 0
  const value = Number(adjust.totalPausedMs || 0)
  return Number.isFinite(value) && value >= 0 ? value : 0
}

function mergeLocalPauseAdjustment(storage, sessionId, serverPausedMs, failClosed) {
  const localPausedMs = getLocalPauseAdjustment(storage, sessionId, failClosed)
  if (localPausedMs === null) return null
  return Math.max(Number(serverPausedMs || 0), Number(localPausedMs || 0))
}

function clearLocalPauseAdjustment(storage, sessionId) {
  const stored = storage.read('pomodoro_pause_adjustment', 'pause adjustment cleanup')
  if (!stored.ok) return false
  const adjust = stored.value
  if (!adjust || adjust.sessionId === sessionId) {
    return storage.remove('pomodoro_pause_adjustment', 'best-effort cleanup')
  }
  return true
}

module.exports = {
  getLocalPauseAdjustment,
  mergeLocalPauseAdjustment,
  clearLocalPauseAdjustment,
}
