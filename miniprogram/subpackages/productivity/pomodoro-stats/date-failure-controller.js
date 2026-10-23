function createDateFailureController(options) {
  return {
    handle(error, context) {
      if (
        !options.isAlive() ||
        !options.isVisible() ||
        context.seq !== options.getDateRequestSeq()
      ) return

      options.logError(context.logMessage, error)
      options.setData({ pieLoading: false, durationValueAnimating: false })
      options.showToast(context.toastText)
    },
  }
}

module.exports = {
  createDateFailureController,
}
