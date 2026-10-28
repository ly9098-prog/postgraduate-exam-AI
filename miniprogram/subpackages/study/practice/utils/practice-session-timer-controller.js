/**
 * Practice elapsed-time loop. The timer id remains on the page so existing
 * clear calls keep the same observable state.
 */
function createPracticeSessionTimerController(options) {
  return {
    start: () => startImpl(options),
    stop: () => stopImpl(options),
  }
}

function startImpl(options) {
  stopImpl(options)
  options.setTimer(options.setInterval(() => tick(options), 1000))
}

function stopImpl(options) {
  const timer = options.getTimer()
  if (timer) {
    options.clearInterval(timer)
    options.setTimer(null)
  }
}

function tick(options) {
  const session = options.getSession()
  if (!options.isPageAlive() || !session.activeStartedMonoMs) return

  const now = options.monotonicNow()
  const backgroundMs = (session.backgroundMs || 0) + (
    session._backgroundStartedMonoMs !== null
      ? Math.max(0, now - session._backgroundStartedMonoMs)
      : 0
  )
  const elapsedSec = Math.max(
    0,
    Math.floor((now - session.activeStartedMonoMs - backgroundMs) / 1000),
  )
  session.elapsedSec = elapsedSec
  options.setData({ elapsedText: options.formatElapsed(elapsedSec) })
}

module.exports = {
  createPracticeSessionTimerController,
}
