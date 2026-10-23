/**
 * Controller for pausing the countdown timer when the end-confirm
 * overlay is about to be shown.
 *
 * Builds the interrupt snapshot, persists it, optionally fires a
 * backend pause, stops the local timer, and updates the view —
 * all through injected callbacks without holding a page reference.
 *
 * Returns true on success, false on early-exit / persistence failure.
 */

const { buildCountdownInterruptSnapshot } = require('./end-confirm-snapshot')

function createPauseCountdownEndConfirmController(options) {
  return {
    pause: () => pause(options),
  }
}

function computeRemaining(options, now) {
  const totalSec = options.getCurrentTotalSec()
  const totalMs = Math.max(1, totalSec * 1000)
  const remainingMs = options.getCountdownEndAt()
    ? Math.max(0, options.getCountdownEndAt() - now)
    : Math.max(0, (options.getRemainingSec() || 0) * 1000)
  const remainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
  const progress = totalMs > 0 ? remainingMs / totalMs : 0
  return { totalSec, totalMs, remainingMs, remainingSec, progress }
}

function buildSnapshot(options, now, ctx) {
  const confirmActionSeq = options.incrementConfirmActionSeq()
  return buildCountdownInterruptSnapshot({
    confirmActionSeq,
    sessionId: options.getSessionId(),
    openedAt: now,
    wasPaused: options.isPaused(),
    phase: options.getPhase(),
    totalSec: ctx.totalSec,
    totalMs: ctx.totalMs,
    remainingMs: ctx.remainingMs,
    remainingSec: ctx.remainingSec,
    progress: ctx.progress,
    sessionStartTime: options.getSessionStartTime(),
    countdownEndAt: options.getCountdownEndAt(),
    totalPausedMs: options.getTotalPausedMs(),
    pauseStartTime: options.getPauseStartTime(),
  })
}

function persistSnapshot(options, snapshot, wasPaused, now) {
  if (!options.safeSetStorage('pomodoro_confirm_pause', snapshot)) {
    options.showPersistenceError()
    return false
  }
  if (!wasPaused && !options.setPendingSync('pause', options.getSessionId(), now)) {
    options.safeRemoveStorage('pomodoro_confirm_pause')
    options.showPersistenceError()
    return false
  }
  return true
}

function applyPause(options, snapshot, ctx, now) {
  options.setConfirmTimerSnapshot(snapshot)
  options.clearTimer()
  options.setCountdownEndAt(0)
  const fmt = options.formatCountdownDisplay(ctx.remainingSec)
  options.setTimerFields({
    pauseStartTime: now,
    remainingSec: ctx.remainingSec,
    progress: ctx.progress,
    endConfirmMode: 'countdown-interrupt',
  })
  options.setData({ isPaused: true, displayMin: fmt.min, displaySec: fmt.sec })
  options.drawRing(ctx.totalSec, options.getPhase() === 'break')
}

function pause(options) {
  if (!options.getSessionId() || options.isActionLoading()) return false
  const now = options.now()
  const ctx = computeRemaining(options, now)
  const wasPaused = options.isPaused()
  const snapshot = buildSnapshot(options, now, ctx)
  if (!persistSnapshot(options, snapshot, wasPaused, now)) return false
  applyPause(options, snapshot, ctx, now)
  if (!wasPaused) {
    options.postPauseWithRetry(snapshot).catch(e =>
      options.warn('confirm pause backend sync failed', e))
  }
  return true
}

module.exports = { createPauseCountdownEndConfirmController }
