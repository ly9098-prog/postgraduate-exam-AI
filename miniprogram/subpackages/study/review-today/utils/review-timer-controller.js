const {
  safeReviewTickDelta,
  startSession,
  pauseSession,
  resumeSession,
  resetSession,
  clearSession,
  buildTimingSession,
} = require('./review-timer-state')

function createReviewTimerController(options) {
  const session = options.getSession()

  return {
    start: () => startSession(session, options),
    pause: () => pauseSession(session, options),
    resume: () => resumeSession(session, options),
    reset: () => resetSession(session, options),
    clear: () => clearSession(session, options),
    buildTimingSession: () => buildTimingSession(session, options),
  }
}

module.exports = {
  createReviewTimerController,
  safeReviewTickDelta,
}
