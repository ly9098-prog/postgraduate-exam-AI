function createExamAttemptReconcileController(options) {
  return {
    reconcile: () => reconcileImpl(options),
  }
}

async function reconcileImpl(options) {
  if (!options.isPageAlive()) return false
  try {
    const payload = await options.getAttempt()
    if (!payload || payload.status === 'in_progress') return false
    if (payload.status === 'abandoned') {
      options.clearPending()
      options.setAttemptTerminal(true)
      options.setAttemptAbandoned(true)
      options.onAbandoned()
      return true
    }
    if (payload.status !== 'submitted' && payload.status !== 'expired') return false
    options.clearPending()
    options.setAttemptTerminal(true)
    options.setAttemptAbandoned(false)
    options.onTerminal()
    return true
  } catch (_) {
    return false
  }
}

module.exports = {
  createExamAttemptReconcileController,
}
