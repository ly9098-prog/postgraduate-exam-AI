const viewHelpers = require('./view-helpers')

function createTrendAnimationController(options) {
  return {
    animate() {
      if (!options.getTrendCtx() || !options.getTrendBarsRect()) {
        options.setData({ barRendering: false })
        return
      }
      const token = options.incrementBarAnimationToken()
      const duration = 620
      const startedAt = options.now()
      const node = options.getTrendCanvasNode()
      const raf = node && node.requestAnimationFrame
        ? cb => node.requestAnimationFrame(cb)
        : cb => options.setTimeout(cb, 16)
      let lastDrawAt = -Infinity
      options.renderTrendBars(0)

      const tick = () => {
        if (!options.isAlive() || !options.isVisible() || token !== options.getBarAnimationToken() || options.getChartMode() !== 'bar') return
        const elapsed = options.now() - startedAt
        const raw = Math.min(1, elapsed / duration)
        if (raw < 1 && elapsed - lastDrawAt >= 40) {
          lastDrawAt = elapsed
          options.renderTrendBars(viewHelpers.easeOutCubic(raw))
        }
        if (raw < 1) {
          options.setBarRafId(raf(tick))
        } else {
          options.renderTrendBars(1)
          options.setBarRafId(null)
          options.markBarRenderedOnce()
          options.setData({ barRendering: false })
        }
      }
      options.setBarRafId(raf(tick))
    },
  }
}

module.exports = {
  createTrendAnimationController,
}
