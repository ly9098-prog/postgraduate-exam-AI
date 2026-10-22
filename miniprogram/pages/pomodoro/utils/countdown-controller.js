function createCountdownController(options) {
  const state = { timer: null }

  function clear() {
    if (!state.timer) return false
    options.clearTimeout(state.timer)
    options.clearInterval(state.timer)
    state.timer = null
    return true
  }

  function scheduleTick(tick, delay) {
    state.timer = options.setTimeout(tick, delay)
    return state.timer
  }

  function stop() {
    if (!state.timer) return false
    options.clearTimeout(state.timer)
    state.timer = null
    return true
  }

  return { clear, scheduleTick, stop }
}

module.exports = { createCountdownController }
