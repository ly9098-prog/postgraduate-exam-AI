function createCancelWorkController(options) {
  return {
    cancel() {
      options.clearDynamicRefresh()
      options.cancelDurationAnimation(false)
      options.cancelDeferredHistory(true)
      options.setAnimActive(false)
      options.setFinalDrawn(false)
      options.incrementRequestId()

      options.cancelFrame(options.getMainRafId(), options.getPieCanvasNode())
      options.cancelFrame(options.getPieDateRafId(), options.getPieCanvasNode())
      options.cancelFrame(options.getPieLabelRafId(), options.getPieCanvasNode())
      options.cancelFrame(options.getBarRafId(), options.getTrendCanvasNode())
      options.setMainRafId(null)
      options.setPieDateRafId(null)
      options.setPieLabelRafId(null)
      options.setBarRafId(null)
      options.incrementPieAnimationToken()
      options.incrementPieLabelToken()
      options.incrementBarAnimationToken()
      options.clearAnimTimer()
    },
  }
}

module.exports = {
  createCancelWorkController,
}
