/**
 * Controller for starting and ticking the work countdown.
 *
 * Resolves the initial remaining time, initializes canvas/timer state,
 * and owns the recursive tick while all page effects are injected.
 */

const { createCountdownController } = require('./countdown-controller')

function createStartTimerController(options) {
  return {
    start: (totalSec, startOptions = {}) => start(totalSec, startOptions, options),
  }
}

function resolveRemainingMs(totalSec, startOptions, options) {
  if (Number.isFinite(startOptions.remainingMs)) {
    return Math.max(0, startOptions.remainingMs)
  }
  const remainSec = Number.isFinite(startOptions.remainingSec)
    ? Math.max(0, startOptions.remainingSec)
    : Math.max(0, options.getRemainingSec() || totalSec)
  return remainSec * 1000
}

function initialize(totalSec, startOptions, remainMs, options) {
  options.clearTimer()
  options.initCanvas(!startOptions.reuseCanvas)
  const controller = createCountdownController({
    setTimeout: options.setTimeout,
    clearTimeout: options.clearTimeout,
    clearInterval: options.clearInterval,
  })
  options.setTimerController(controller)

  const totalMs = Math.max(1, totalSec * 1000)
  const displayRemainingSec = remainMs <= 0 ? 0 : Math.ceil(remainMs / 1000)
  const progress = totalMs > 0 ? remainMs / totalMs : 0
  const fmt = options.formatCountdownDisplay(displayRemainingSec)

  options.setCountdownTotalSec(totalSec)
  options.setCountdownEndAt(options.now() + remainMs)
  options.setTimerFields({ remainingSec: displayRemainingSec, progress })
  const update = { displayMin: fmt.min, displaySec: fmt.sec, ringCanvasVisible: true }
  if (startOptions.forceRunning) update.isPaused = false
  options.setData(update)
  return { controller, totalMs }
}

function tick(totalSec, context, options) {
  if (options.isPaused() || options.showEndConfirm()) {
    context.controller.stop()
    return
  }

  const remainingMs = Math.max(0, options.getCountdownEndAt() - options.now())
  const displayRemainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
  const progress = context.totalMs > 0 ? remainingMs / context.totalMs : 0
  const fmt = options.formatCountdownDisplay(displayRemainingSec)

  if (displayRemainingSec !== options.getRemainingSec() ||
      Math.abs(progress - options.getProgress()) > 0.002) {
    options.setTimerFields({ remainingSec: displayRemainingSec, progress })
    options.setData({ displayMin: fmt.min, displaySec: fmt.sec })
  }

  options.drawRing(totalSec, options.isBreakPhase())

  if (remainingMs <= 0) {
    options.clearTimer()
    options.onWorkComplete()
    return
  }

  const nextDelay = Math.max(80, Math.min(250, remainingMs % 1000 || 250))
  context.controller.scheduleTick(() => tick(totalSec, context, options), nextDelay)
}

function start(totalSec, startOptions, options) {
  const remainMs = resolveRemainingMs(totalSec, startOptions, options)
  const context = initialize(totalSec, startOptions, remainMs, options)
  tick(totalSec, context, options)
}

module.exports = { createStartTimerController }
