/**
 * Controller for interrupting a pomodoro session.
 *
 * Dispatches to the free-timer end confirm or countdown interrupt confirm
 * based on the current timer mode — all through injected callbacks.
 */

function createInterruptSessionController(options) {
  return {
    interrupt: () => interrupt(options),
  }
}

function interrupt(options) {
  if (!options.getSessionId()) return
  if (options.isFreeTimer()) {
    options.showEndFreeConfirm()
    return
  }
  options.showCountdownInterruptConfirm()
}

module.exports = { createInterruptSessionController }
