function restoreLocalSession(options) {
  const cached = options.readCached()
  if (options.isStorageError(cached)) {
    options.persistenceError()
    return null
  }
  let restoredFromCache = false
  if (cached) {
    if (restoreSession(options, cached) === false) return null
    restoredFromCache = options.isRunning() && options.sessionId() === cached.id
  }
  let restoredBreak = false
  if (!cached && !options.isRunning()) restoredBreak = options.restoreBreak()
  return { restoredFromCache, restoredBreak }
}

function restoreSession(options, session) {
  return options.canLightSync(session)
    ? options.syncLight(session, true)
    : options.restoreSession(session)
}

async function syncPendingSession(options) {
  const synced = await options.retryPending()
  if (!options.isCurrent()) return false
  const conflict = options.consumeConflict()
  if (conflict) {
    options.handleConflict(conflict.sessionId, conflict)
    return false
  }
  if (!synced) {
    // Keep the local optimistic pause/completion while the server is unreachable.
    options.deferStats()
    return false
  }
  return true
}

function applyServerSession(options, active, local) {
  if (active && options.hasPendingTerminal(active.id, ['complete', 'interrupt'])) {
    options.removeStorage('pomodoro_running_state', 'best-effort cleanup')
  } else if (active) {
    if (local.restoredBreak) {
      options.clearTimer()
      options.removeStorage('pomodoro_break', 'best-effort cleanup')
    }
    if (restoreSession(options, active) === false) return false
  } else if (local.restoredFromCache && options.isRunning()) {
    options.resetIdle()
    options.restoreBreak()
  } else if (!options.isRunning() && !local.restoredBreak) {
    options.restoreBreak()
  }
  return true
}

async function recoverActiveSession(options, pendingSync) {
  // Restore the first frame before any queue drain or active-session request.
  const local = restoreLocalSession(options)
  if (!local) return
  if (pendingSync && !await syncPendingSession(options)) return
  const active = await options.fetchActive()
  if (!options.isCurrent()) return
  if (options.isStorageError(active)) {
    options.persistenceError()
    return
  }
  if (!applyServerSession(options, active, local)) return
  options.deferStats()
}

module.exports = { recoverActiveSession }
