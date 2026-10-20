const RETRY_DELAYS_MS = [2000, 5000, 15000, 30000, 60000]

function isRetryableSyncError(error) {
  const statusCode = Number(error && error.statusCode) || 0
  return !!(
    (error && error.code === 'NETWORK_ERROR') ||
    statusCode === 0 || statusCode === 408 ||
    statusCode === 429 || statusCode >= 500
  )
}

function handleReconnectResult(options, synced) {
  if (!options.isVisible()) return
  const conflict = options.consumeConflict()
  if (conflict) {
    options.handleConflict(conflict.sessionId, conflict)
    return
  }
  if (synced) options.loadStats()
}

function createSyncRetryController(options) {
  const state = { timer: null, attempt: 0, networkHandler: null }

  function clear(resetAttempt = false) {
    if (state.timer) {
      options.clearTimeout(state.timer)
      state.timer = null
    }
    if (resetAttempt) state.attempt = 0
  }

  function schedule(error) {
    if (!options.isVisible() || !options.hasPending() || !isRetryableSyncError(error)) return
    if (state.timer) return
    const attempt = Math.max(0, Number(state.attempt || 0))
    const delay = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)]
    state.attempt = attempt + 1
    state.timer = options.setTimeout(() => {
      state.timer = null
      if (!options.isVisible() || !options.hasPending()) return
      options.retry().catch(error => options.warn('pomodoro delayed sync retry failed', error))
    }, delay)
  }

  function reconnect(status) {
    if (!status || !status.isConnected || !options.isVisible()) return
    if (!options.hasPending()) return
    clear(true)
    options.retry().then(synced => handleReconnectResult(options, synced))
      .catch(error => options.warn('pomodoro reconnect sync failed', error))
  }

  function register() {
    if (state.networkHandler || !options.canListen()) return
    state.networkHandler = reconnect
    options.onNetworkStatusChange(state.networkHandler)
  }

  function unregister() {
    if (!state.networkHandler) return
    try {
      options.offNetworkStatusChange(state.networkHandler)
    } catch (_) {}
    state.networkHandler = null
  }

  return { clear, schedule, register, unregister }
}

module.exports = { createSyncRetryController, isRetryableSyncError }
