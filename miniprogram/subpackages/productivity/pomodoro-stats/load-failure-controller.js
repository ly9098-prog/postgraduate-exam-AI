function createLoadFailureController(options) {
  return {
    handle(error, context) {
      if (
        !options.isAlive() ||
        context.reqId !== options.getRequestId() ||
        context.dateSeq !== options.getDateRequestSeq() ||
        context.requestedDate !== options.getSelectedDate()
      ) return

      options.logError(context.logMessage, error)
      const keepSnapshot = context.background && options.isContentReady()
      const patch = keepSnapshot
        ? { loading: false, pieLoading: false, cumulativeLoading: false }
        : {
            loading: false,
            pieLoading: false,
            cumulativeLoading: false,
            errorText: context.errorText,
          }
      options.setData(patch)
    },
  }
}

module.exports = {
  createLoadFailureController,
}
