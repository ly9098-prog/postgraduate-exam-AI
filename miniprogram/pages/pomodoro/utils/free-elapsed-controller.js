/**
 * Controller for free-timer elapsed-time calculations.
 *
 * Owns the effective elapsed rules; clock, storage, and page state are
 * injected callbacks.
 */

const { calculateElapsedMs } = require('./timer-math')

function createFreeElapsedController(options) {
  return {
    getElapsedMs: now => getElapsedMs(now, options),
    getEffectiveElapsedMs: now => getEffectiveElapsedMs(now, options),
  }
}

function getElapsedMs(now, options) {
  const currentTime = resolveNow(now, options)
  return calculateElapsedMs(
    currentTime,
    options.getSessionStartTime(),
    options.getTotalPausedMs() || 0,
  )
}

function getEffectiveElapsedMs(now, options) {
  const currentTime = resolveNow(now, options)
  const startTime = Number(options.getSessionStartTime())
  if (!Number.isFinite(startTime) || startTime <= 0) return 0
  const totalPausedMs = options.mergeLocalPauseAdjustment(
    options.getSessionId(),
    options.getTotalPausedMs() || 0,
  )
  return calculateElapsedMs(currentTime, startTime, totalPausedMs)
}

function resolveNow(now, options) {
  return typeof now === 'number' ? now : options.now()
}

module.exports = { createFreeElapsedController }
