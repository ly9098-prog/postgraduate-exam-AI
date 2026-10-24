function createExamSubmitRetryController(options) {
  return {
    postWithRetry: finalAnswers => postWithRetryImpl(options, finalAnswers),
  }
}

async function postWithRetryImpl(options, finalAnswers) {
  // POST /submit is server-idempotent: once the attempt is terminal it returns
  // the immutable result snapshot. That lets us safely retry ambiguous network
  // failures (request committed but response lost) without duplicate records.
  const delays = options.getRetryDelays()
  let lastError = null
  for (let i = 0; i < delays.length; i += 1) {
    if (!options.isPageAlive() || options.isTerminalNavigation()) {
      throw lastError || new Error(options.getPageClosedMessage())
    }
    if (delays[i] > 0) await options.sleep(delays[i])
    try {
      return await options.postSubmit(finalAnswers)
    } catch (error) {
      lastError = error
      if (!options.isPageAlive()) throw error
      // The attempt GET is side-effect free, so reconciliation cannot
      // accidentally grade an expired draft before its pending answers arrive.
      if (await options.reconcileAttemptState(error)) return { _reconciled: true }
      if (!options.isRetryableSubmitError(error) || i === delays.length - 1) throw error
    }
  }
  throw lastError || new Error(options.getSubmitFailedMessage())
}

module.exports = {
  createExamSubmitRetryController,
}
