function createPieLabelRevealController(options) {
  return {
    reveal() {
      const ctx = options.getPieCtx()
      const rect = options.getPieRect()
      const layout = options.getLabelLayout()
      if (!ctx || !rect || !layout || !layout.length) return

      const token = options.incrementPieLabelToken()
      const geometry = options.getGeometry(rect)
      const node = options.getPieCanvasNode()
      const raf = node && node.requestAnimationFrame
        ? cb => node.requestAnimationFrame(cb)
        : cb => options.setTimeout(cb, 16)
      let index = 0

      const drawNext = () => {
        if (!options.isAlive() || !options.isVisible() || token !== options.getPieLabelToken()) return
        const end = Math.min(layout.length, index + 2)
        options.drawPieLabels(ctx, geometry, layout, 1, index, end)
        index = end
        if (index < layout.length) {
          options.setPieLabelRafId(raf(drawNext))
        } else {
          options.setPieLabelRafId(null)
        }
      }

      options.setPieLabelRafId(raf(drawNext))
    },
  }
}

module.exports = {
  createPieLabelRevealController,
}
