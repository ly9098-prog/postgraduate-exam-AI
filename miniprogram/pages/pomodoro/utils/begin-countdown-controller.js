/**
 * Controller for beginning a countdown session from a server-issued
 * start_time.
 *
 * Computes remaining time, sets timer state and view, then either
 * auto-completes (if time already elapsed) or starts the countdown
 * timer — all through injected callbacks.
 */

function createBeginCountdownController(options) {
  return {
    begin: session => begin(session, options),
  }
}

function begin(session, options) {
  const startTime = options.parseServerTime(session.start_time)
  const totalSec = options.isDebugPreset() ? 10 : options.getWorkDurationMinutes() * 60
  const totalPausedMs = Math.max(0, Number(session.total_paused_sec || 0) * 1000)
  const elapsedMs = Math.max(0, options.now() - startTime - totalPausedMs)
  const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)

  options.setTimerFields({
    sessionId: session.id,
    sessionStartTime: startTime,
    remainingSec: remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000),
    progress: totalSec > 0 ? remainingMs / (totalSec * 1000) : 0,
    totalPausedMs,
    pauseStartTime: null,
  })
  options.setData({
    phase: options.runningPhase(),
    ringCanvasVisible: true,
    isPaused: false,
  })
  options.updateComputedFields()

  if (remainingMs <= 0) {
    options.onWorkComplete()
    return
  }
  options.startTimer(totalSec, { remainingMs, forceRunning: true })
}

module.exports = { createBeginCountdownController }
