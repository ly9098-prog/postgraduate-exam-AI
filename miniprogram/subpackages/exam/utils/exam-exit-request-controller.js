function createExamExitRequestController(options) {
  return {
    request: requestImpl.bind(null, options),
  }
}

async function requestImpl(options) {
  if (options.isSubmitting() || options.isNavigationLocked()) return undefined
  options.settleCurrentTime().catch(() => {})
  const confirmed = await options.showExitDialog()
  if (confirmed) options.navigateBack({ delta: 1 })
  return undefined
}

module.exports = {
  createExamExitRequestController,
}
