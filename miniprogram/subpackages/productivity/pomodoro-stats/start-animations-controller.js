const viewHelpers = require('./view-helpers')

function createStartAnimationsController(options) {
  return {
    start(reqId) {
      startImpl(options, reqId)
    },
  }
}

function startImpl(options, reqId) {
  if (!options.isAlive() || !options.isVisible() || reqId !== options.getRequestId() || options.getChartMode() !== 'pie') return
  options.setAnimActive(true)
  options.setFinalDrawn(false)
  options.incrementPieLabelToken()
  startNumberAnimation(options, reqId)
  startPieAnimation(options, reqId)
}

function startNumberAnimation(options, reqId) {
  const targetSessions = options.getTodaySessions()
  const totalSteps = 7
  let step = 0
  const numTick = () => {
    if (!options.getAnimActive() || !options.isAlive() || !options.isVisible() || reqId !== options.getRequestId()) return
    step += 1
    const progress = Math.min(1, step / totalSteps)
    const eased = viewHelpers.easeOutCubic(progress)
    const displayDurationSec = Math.round(options.getRawTodayDurationSec() * eased)
    options.setDisplayDurationSec(displayDurationSec)
    options.setData({
      _dispTodaySessions: Math.round(targetSessions * eased),
      ...options.getDurationDisplayPatch(options.formatMin(displayDurationSec)),
      durationValueAnimating: progress < 1,
    })
    if (step < totalSteps) {
      options.setAnimTimer(options.setTimeout(numTick, Math.round(420 / totalSteps)))
    } else {
      options.setAnimTimer(null)
    }
  }
  numTick()
}

function startPieAnimation(options, reqId) {
  const startTime = options.now()
  const node = options.getPieCanvasNode()
  const raf = node && node.requestAnimationFrame
    ? callback => node.requestAnimationFrame(callback)
    : callback => options.setTimeout(callback, 16)
  let lastPieDraw = -Infinity
  const tick = () => {
    if (
      !options.getAnimActive() ||
      !options.isAlive() ||
      !options.isVisible() ||
      reqId !== options.getRequestId() ||
      options.getChartMode() !== 'pie'
    ) return
    const elapsed = options.now() - startTime
    const raw = Math.min(1, elapsed / 980)
    if (raw < 1 && elapsed - lastPieDraw >= 28) {
      lastPieDraw = elapsed
      options.renderPie(viewHelpers.easeInOutCubic(raw), false)
    }
    if (raw < 1) {
      options.setRafId(raf(tick))
    } else if (!options.getFinalDrawn()) {
      options.setFinalDrawn(true)
      options.setAnimActive(false)
      options.renderPie(1, false)
      options.setRafId(raf(() => {
        options.setRafId(null)
        if (!options.isAlive() || !options.isVisible() || reqId !== options.getRequestId() || options.getChartMode() !== 'pie') return
        options.revealPieLabelsIncrementally()
      }))
    }
  }
  options.setRafId(raf(tick))
}

module.exports = {
  createStartAnimationsController,
}
