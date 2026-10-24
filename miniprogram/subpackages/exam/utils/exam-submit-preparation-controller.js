function createExamSubmitPreparationController(options) {
  return {
    prepare: requestedAuto => prepareImpl(options, requestedAuto),
  }
}

async function prepareImpl(options, requestedAuto) {
  const remaining = options.getCurrentRemainingSec()
  const auto = !!requestedAuto
    || options.isTimeExpired()
    || (remaining != null && remaining <= 0)
  if (auto) {
    options.setRetainPendingForSubmit(true)
    options.persistPending()
  }
  options.setSubmitting(true)
  options.clearTimer()
  // Only settle the local final time slice. All still-pending rows are embedded
  // in the single submit request and persisted atomically on the server.
  await options.settleCurrentTime({ sync: false })
  options.onAutoResolved(auto)
  return {
    auto,
    finalAnswers: options.buildFinalSubmitAnswers(),
  }
}

module.exports = {
  createExamSubmitPreparationController,
}
