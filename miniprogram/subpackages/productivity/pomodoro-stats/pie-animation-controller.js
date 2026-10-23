const viewHelpers = require('./view-helpers')

function createPieAnimationController(options) {
  return {
    animate() {
      if (!options.getPieCtx() || !options.getPieRect()) return
      const token = options.incrementPieAnimationToken()
      options.incrementPieLabelToken()
      const duration = 980
      const start = options.now()
      const node = options.getPieCanvasNode()
      const raf = node && node.requestAnimationFrame
        ? cb => node.requestAnimationFrame(cb)
        : cb => options.setTimeout(cb, 16)
      let lastDraw = 0

      options.renderPie(0, false)
      const tick = () => {
        if (!options.isAlive() || !options.isVisible() || token !== options.getPieAnimationToken()) return
        const elapsed = options.now() - start
        const raw = Math.min(1, elapsed / duration)
        if (raw < 1 && elapsed - lastDraw >= 28) {
          lastDraw = elapsed
          options.renderPie(viewHelpers.easeInOutCubic(raw), false)
        }
        if (raw < 1) {
          options.setPieDateRafId(raf(tick))
        } else {
          // Keep the expensive percentage badges out of the final motion frame.
          options.renderPie(1, false)
          options.setPieDateRafId(null)
          options.revealPieLabelsIncrementally()
        }
      }
      options.setPieDateRafId(raf(tick))
    },
  }
}

module.exports = {
  createPieAnimationController,
}
