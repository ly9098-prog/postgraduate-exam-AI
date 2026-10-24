function createExamSubmitOutcomeController(options) {
  return {
    applySuccess: result => applySuccessImpl(options, result),
    applyFailure: (error, auto) => applyFailureImpl(options, error, auto),
  }
}

function applySuccessImpl(options, result) {
  if (result && result._reconciled) {
    options.setAttemptTerminal(true)
    options.navigateReconciled()
    return
  }

  options.clearPending()
  options.setAttemptTerminal(true)
  options.navigateToResult()
}

async function applyFailureImpl(options, error, auto) {
  // Keep pending intact on uncertain failures; reconnect can retry the same
  // idempotent submit payload safely.
  if (!options.isPageAlive()) return false
  if (await options.reconcileAttemptState()) {
    options.setAttemptTerminal(true)
    options.navigateReconciled()
    return
  }
  options.setSubmitting(false)
  if (auto) {
    options.showAutoSubmitPending()
  } else {
    options.showManualSubmitError(error)
  }
  return false
}

module.exports = {
  createExamSubmitOutcomeController,
}
