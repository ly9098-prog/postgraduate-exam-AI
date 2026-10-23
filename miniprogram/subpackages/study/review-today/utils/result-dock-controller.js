function createResultDockController(options) {
  return {
    show() {
      if (options.getPhase() !== 'group-result' || options.getTodayRemainingCount() > 0) return false
      options.clearFadeTimer()
      if (!options.getResultDockVisible()) {
        options.setData({ resultDockVisible: true })
      }
      options.setFadeTimer(options.setTimeout(() => {
        options.clearFadeTimer()
        if (
          options.isPageAlive() &&
          options.getPhase() === 'group-result' &&
          options.getTodayRemainingCount() <= 0
        ) {
          options.setData({ resultDockVisible: false })
        }
      }, options.getFadeDelay()))
      return true
    },
  }
}

module.exports = {
  createResultDockController,
}
