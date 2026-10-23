function createDynamicRefreshController(options) {
  const clearTimer = () => {
    if (!options.getTimer()) return
    options.clearTimeout(options.getTimer())
    options.setTimer(null)
  }

  return {
    cancel() {
      clearTimer()
    },
    schedule(delayMs) {
      clearTimer()
      if (!options.isAlive() || !options.isVisible() || !options.isViewReady()) return
      const delay = Math.max(1000, Number(delayMs) || options.getDefaultDelayMs())
      options.setTimer(options.setTimeout(async () => {
        options.setTimer(null)
        if (!options.isAlive() || !options.isVisible() || !options.isViewReady()) return
        // Do not race a date/settings/manual refresh. Try again shortly instead of
        // invalidating a user-triggered request with a background request id.
        if (options.getStatsLoadInFlight() > 0 || options.isCumulativeLoading()) {
          options.schedule(3000)
          return
        }
        options.incrementRequestId()
        try {
          await options.loadBackground()
        } finally {
          options.schedule()
        }
      }, delay))
    },
  }
}

module.exports = {
  createDynamicRefreshController,
}
