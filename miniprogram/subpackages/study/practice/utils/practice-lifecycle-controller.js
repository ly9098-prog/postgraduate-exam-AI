/**
 * Practice page visibility timing.  Keep the two clock reads in show() at
 * their original moments so foreground/background time remains monotonic.
 */
function createPracticeLifecycleController(options) {
  return {
    show: () => showImpl(options),
    hide: () => hideImpl(options),
  }
}

function showImpl(options) {
  const session = options.getSession()
  if (!session || session._timingPauseActive) return

  if (session.activeStartedMonoMs && session._backgroundStartedMonoMs !== null) {
    session.backgroundMs = (session.backgroundMs || 0) +
      (options.monotonicNow() - session._backgroundStartedMonoMs)
    session._backgroundStartedMonoMs = null
  }

  if (session.activeStartedMonoMs && options.isQuestionActive(session)) {
    session.currentQuestionStartedMonoMs = options.monotonicNow()
  }
}

function hideImpl(options) {
  const session = options.getSession()
  if (!session || session._timingPauseActive) return

  if (session.activeStartedMonoMs && session._backgroundStartedMonoMs === null) {
    if (options.isQuestionActive(session)) {
      options.settleQuestionTime(true)
    }
    session._backgroundStartedMonoMs = options.monotonicNow()
  }
}

module.exports = {
  createPracticeLifecycleController,
}
