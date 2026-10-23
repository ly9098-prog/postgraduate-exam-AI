function createLifecycleController(options) {
  const warmCanvases = () => {
    if (!options.isAlive() || !options.isVisible()) return
    options.initCanvases(() => {})
  }

  return {
    show() {
      options.setVisible(true)
      options.syncTheme()
      if (!options.isViewReady()) return
      options.incrementRequestId()
      options.loadData()
      options.scheduleDynamicRefresh()
    },
    ready() {
      options.setViewReady(true)
      options.setVisible(true)
      options.incrementRequestId()
      options.loadData()
      options.scheduleDynamicRefresh()
      options.nextTick(warmCanvases)
    },
    hide() {
      options.setVisible(false)
      options.clearDynamicRefresh()
      options.cancelDurationAnimation(false)
      options.cancelDeferredHistory(true)
    },
    unload() {
      options.setAlive(false)
      options.setVisible(false)
      options.cancelPendingWork()
    },
  }
}

module.exports = {
  createLifecycleController,
}
