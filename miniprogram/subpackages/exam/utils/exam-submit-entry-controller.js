function createExamSubmitEntryController(options) {
  return {
    request: requestImpl.bind(null, options),
  }
}

async function requestImpl(options, requestOptions = {}) {
  if (options.isAttemptTerminal() || options.isNavigationLocked()) return false
  if (options.getSubmitPromise()) return options.getSubmitPromise()
  if (options.isSubmitting()) return undefined

  const auto = !!requestOptions.auto || options.isTimeExpired()
  if (!auto) {
    if (options.isConfirmingSubmit()) return undefined
    options.setConfirmingSubmit(true)
    let confirmed = false
    try {
      confirmed = await options.showConfirmDialog(options.buildConfirmDialog())
    } finally {
      options.setConfirmingSubmit(false)
    }
    if (!confirmed) return undefined
  }

  // The countdown can expire while the confirmation modal is open. In that
  // case the auto-submit path may already own the single-flight task.
  if (options.getSubmitPromise()) return options.getSubmitPromise()
  if (options.isSubmitting() || options.isAttemptTerminal() || options.isNavigationLocked()) {
    return false
  }

  const task = options.performSubmit(auto)
  options.setSubmitPromise(task)
  try {
    return await task
  } finally {
    options.clearSubmitPromise(task)
  }
}

module.exports = {
  createExamSubmitEntryController,
}
