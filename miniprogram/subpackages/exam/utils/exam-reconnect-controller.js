function createExamReconnectController(options) {
  return {
    recoverPending: recoverPendingImpl.bind(null, options),
  }
}

async function recoverPendingImpl(options) {
  if (!options.isPageAlive()
    || !options.isAttemptLoaded()
    || options.isReconnectSyncing()
    || options.isAttemptTerminal()
    || options.isTerminalNavigation()) return

  options.setReconnectSyncing(true)
  try {
    options.tickTimer()
    if (options.isTimeExpired()) {
      if (!options.isSubmitting()) await options.submitExam({ auto: true })
    } else {
      await options.flushAllPending({ quiet: true })
    }
  } catch (_) {
    // Keep pending answers; the next reconnect, show, or user action retries.
  } finally {
    options.setReconnectSyncing(false)
  }
}

module.exports = {
  createExamReconnectController,
}
