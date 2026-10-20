function recoverCompletion(options, pendingSync) {
  const stored = options.readStorage('pomodoro_completion', 'onShow completion')
  if (!stored.ok) {
    options.persistenceError()
    return true
  }
  const completion = stored.value
  if (!completion) return false
  if (!completion.sessionId) {
    options.removeStorage('pomodoro_completion', 'best-effort cleanup')
    return false
  }
  // A valid completion marker stays authoritative until celebration dismissal.
  options.showCompletion(completion)
  if (pendingSync) {
    options.retryPending().then(synced => {
      const conflict = options.consumeConflict()
      if (conflict) {
        options.handleConflict(conflict.sessionId, conflict)
        return
      }
      if (synced) options.loadStats()
    })
  }
  options.deferStats()
  return true
}

function recoverConfirmation(options) {
  if (options.isNavigatingToStats()) {
    options.resetNavigation()
    options.clearConfirmation()
    return false
  }
  let snapshot = options.confirmSnapshot()
  if (!snapshot) {
    const stored = options.readStorage('pomodoro_confirm_pause', 'onShow confirm snapshot')
    if (!stored.ok) {
      options.persistenceError()
      return true
    }
    snapshot = stored.value
  }
  if (snapshot && snapshot.sessionId) {
    if (options.isValidConfirmation(snapshot)) {
      options.restoreConfirmation(snapshot)
      return true
    }
    options.clearConfirmation()
  }
  return false
}

async function recoverOnShow(options, pendingSync) {
  if (pendingSync && pendingSync.storageUnreadable) {
    options.persistenceError()
    return
  }
  // Resolve an uncertain start before trusting any completion or running cache.
  const resolution = await options.reconcileStart()
  if (!options.isCurrent()) return
  if (resolution === 'storage_error') {
    options.persistenceError()
    return
  }
  if (resolution === 'cancelled' || resolution === 'restored') {
    options.deferStats()
    return
  }
  const conflict = options.consumeConflict()
  if (conflict) {
    options.handleConflict(conflict.sessionId, conflict)
    return
  }
  if (recoverCompletion(options, pendingSync)) return
  if (recoverConfirmation(options)) return
  await options.recoverActive(pendingSync)
}

module.exports = { recoverOnShow }
