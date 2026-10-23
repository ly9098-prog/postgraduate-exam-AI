/**
 * Controller for starting and ticking a break countdown.
 *
 * Preserves the original break start time and total duration across page
 * restores, owns the recursive tick, and delegates all page effects to
 * injected callbacks.
 */

const { createCountdownController } = require('./countdown-controller')

function createStartBreakController(options) {
  return {
    start: (totalSec, restartOptions = {}) => start(totalSec, restartOptions, options),
  }
}

function buildContext(totalSec, restartOptions, options) {
  const originalTotalSec = Math.max(1, Number(totalSec) || 1)
  const breakStartTime = Number.isFinite(restartOptions.startTime)
    ? restartOptions.startTime
    : options.now()
  const totalMs = originalTotalSec * 1000
  const naturalRemainingMs = Math.max(0, breakStartTime + totalMs - options.now())
  const remainingMs = Number.isFinite(restartOptions.remainingMs)
    ? Math.max(0, Math.min(totalMs, restartOptions.remainingMs))
    : naturalRemainingMs
  return { originalTotalSec, breakStartTime, totalMs, remainingMs }
}

function initializeBreak(context, options) {
  options.safeSetStorage('pomodoro_break', {
    startTime: context.breakStartTime,
    totalSec: context.originalTotalSec,
  })
  options.setTimerFields({
    breakStartTime: context.breakStartTime,
    remainingSec: Math.ceil(context.remainingMs / 1000),
    progress: context.remainingMs / context.totalMs,
  })
  const firstFmt = options.formatCountdownDisplay(Math.ceil(context.remainingMs / 1000))
  options.setData({
    phase: options.breakPhase(),
    ringCanvasVisible: true,
    displayMin: firstFmt.min,
    displaySec: firstFmt.sec,
  })
  options.clearTimer()
  options.initCanvas(true)
  options.setCountdownTotalSec(context.originalTotalSec)
  options.setCountdownEndAt(context.breakStartTime + context.totalMs)
  options.drawRing(context.originalTotalSec, true)
}

function tick(context, options) {
  const currentRemainingMs = Math.max(0, options.getCountdownEndAt() - options.now())
  const displayRemainingSec = currentRemainingMs <= 0 ? 0 : Math.ceil(currentRemainingMs / 1000)
  const progress = currentRemainingMs / context.totalMs
  const fmt = options.formatCountdownDisplay(displayRemainingSec)

  if (displayRemainingSec !== options.getRemainingSec() ||
      Math.abs(progress - options.getProgress()) > 0.002) {
    options.setTimerFields({ remainingSec: displayRemainingSec, progress })
    options.setData({ displayMin: fmt.min, displaySec: fmt.sec })
  }
  options.drawRing(context.originalTotalSec, true)

  if (currentRemainingMs <= 0) {
    options.clearTimer()
    options.safeRemoveStorage('pomodoro_break')
    options.resetToIdle()
    return
  }

  const nextDelay = Math.max(80, Math.min(250, currentRemainingMs % 1000 || 250))
  if (!options.getTimerController()) {
    options.setTimerController(createCountdownController({
      setTimeout: options.setTimeout,
      clearTimeout: options.clearTimeout,
      clearInterval: options.clearInterval,
    }))
  }
  options.getTimerController().scheduleTick(() => tick(context, options), nextDelay)
}

function start(totalSec, restartOptions, options) {
  const context = buildContext(totalSec, restartOptions, options)
  if (context.remainingMs <= 0) {
    options.safeRemoveStorage('pomodoro_break')
    options.resetToIdle()
    return
  }
  initializeBreak(context, options)
  tick(context, options)
}

module.exports = { createStartBreakController }
