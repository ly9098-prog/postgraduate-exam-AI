function nextFreeTimerDelay(elapsedMs) {
  const remainder = elapsedMs % 1000
  const delay = remainder === 0 ? 1000 : 1000 - remainder
  return Math.max(100, Math.min(delay, 1000))
}

function createFreeTimerController(options) {
  const state = { timer: null }

  function clear() {
    if (!state.timer) return false
    options.clearTimeout(state.timer)
    state.timer = null
    return true
  }

  function start() {
    if (state.timer) return false

    const scheduleNext = () => {
      const delay = nextFreeTimerDelay(options.getElapsedMs())
      state.timer = options.setTimeout(tick, delay)
    }

    const tick = () => {
      state.timer = null
      if (options.isBlocked()) return
      options.onTick()
      if (options.shouldFinalize()) return
      scheduleNext()
    }

    scheduleNext()
    return true
  }

  function restart() {
    clear()
    return start()
  }

  return { clear, start, restart }
}

module.exports = { createFreeTimerController, nextFreeTimerDelay }
