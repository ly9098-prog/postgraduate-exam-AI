function createPomodoroActiveSessionReconciler(options) {
  return {
    fetchActive: fetchActiveImpl.bind(null, options),
  }
}

async function fetchActiveImpl(options) {
  const stored = options.safeGetPomodoroStorage('pomodoro_running_state', 'fetch active session')
  if (!stored.ok) return { storageUnreadable: true }
  const local = stored.value
  const cached = options.buildCachedActiveSession(local)
  try {
    const server = await options.getActive('/pomodoro/active')
    if (server) {
      if (!options.safeRemovePomodoroStorage('pomodoro_running_state', 'server active reconcile')) {
        return { storageUnreadable: true }
      }
      if (!options.hasPendingPomodoroAction(server.id, ['pause', 'resume'])) {
        if (!options.clearLocalPauseAdjustment(server.id)) return { storageUnreadable: true }
      }
      return server
    }
    if (!options.safeRemovePomodoroStorage('pomodoro_running_state', 'server no-active reconcile')) {
      return { storageUnreadable: true }
    }
    return null
  } catch (_) {
    // Weak/offline network: keep the timer usable from a fresh local snapshot.
    if (cached) return cached
  }
  if (!options.safeRemovePomodoroStorage('pomodoro_running_state', 'invalid cached active session')) {
    return { storageUnreadable: true }
  }
  return null
}

module.exports = {
  createPomodoroActiveSessionReconciler,
}
