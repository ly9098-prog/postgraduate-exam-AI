/**
 * Controller for ending a pomodoro session.
 *
 * Clears the timer, completes with retry, handles terminal conflict,
 * loads stats, and resets to idle — all through injected callbacks.
 */

function createEndSessionController(options) {
  return {
    end: () => end(options),
  }
}

function end(options) {
  if (!options.getSessionId()) return
  const sessionId = options.getSessionId()
  options.clearTimer()
  options.completeWithRetry(sessionId, options.now()).then(synced => {
    const conflict = options.consumeTerminalConflict(sessionId, 'complete')
    if (conflict) {
      options.handleTerminalConflict(sessionId, conflict)
      return
    }
    if (synced) options.loadTodayStats()
  })
  options.resetToIdle()
}

module.exports = { createEndSessionController }
