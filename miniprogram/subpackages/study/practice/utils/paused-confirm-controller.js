function createPausedConfirmController(options) {
  return {
    show: showImpl.bind(null, options),
  }
}

async function showImpl(options, opts) {
  const session = options.getSession()
  const pauseStartedMonoMs = options.monotonicNow()
  if (session) session._timingPauseActive = true
  options.settleQuestionTime(true)
  options.clearTimer()
  let confirmed = false
  try {
    confirmed = await options.showConfirm(opts)
  } finally {
    const pausedMs = Math.max(0, options.monotonicNow() - pauseStartedMonoMs)
    if (session) {
      session.backgroundMs = (session.backgroundMs || 0) + pausedMs
      session._timingPauseActive = false
    }
  }
  if (
    !confirmed && options.isPageAlive() && options.getSession() === session &&
    options.isStarted() && !options.isSubmitted() && !options.isSubmitting() &&
    session && !session.submissionSnapshot
  ) {
    session.currentQuestionStartedMonoMs = options.monotonicNow()
    options.startTimer()
  }
  return !!confirmed
}

module.exports = {
  createPausedConfirmController,
}
