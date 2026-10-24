function createExamTimerController(options) {
  return {
    start: startImpl.bind(null, options),
    tick: tickImpl.bind(null, options),
    clear: clearImpl.bind(null, options),
    currentRemainingSec: () => currentRemainingSecImpl(options),
  }
}

function startImpl(options, initialRemaining) {
  clearImpl(options)
  const remaining = initialRemaining == null ? null : Math.max(0, Number(initialRemaining) || 0)
  options.setBaseRemaining(remaining)
  options.setStartedAt(options.now())
  tickImpl(options)
  if (!options.isTimeExpired() && remaining != null) {
    options.setTimer(options.setInterval(() => tickImpl(options), 1000))
  }
}

function currentRemainingSecImpl(options) {
  const baseRemaining = options.getBaseRemaining()
  if (baseRemaining == null) return null
  const elapsed = Math.max(0, Math.floor((options.now() - options.getStartedAt()) / 1000))
  return Math.max(0, baseRemaining - elapsed)
}

function tickImpl(options) {
  if (!options.isPageAlive() || options.isAttemptTerminal() || options.isTerminalNavigation()) return
  if (options.getBaseRemaining() == null) {
    if (options.getRemainingText() !== '不限时') options.setData({ remainingText: '不限时' })
    return
  }

  const left = currentRemainingSecImpl(options)
  if (left > 0) {
    const text = `剩余 ${options.formatClock(left)}`
    if (options.getRemainingText() !== text || options.isTimeExpired()) {
      options.setData({ remainingText: text, timeExpired: false })
    }
    return
  }

  clearImpl(options)
  if (!options.isTimeExpired() || options.getRemainingText() !== '已到时 · 正在交卷') {
    options.setData({ timeExpired: true, remainingText: '已到时 · 正在交卷' })
  }
  options.onExpired()
}

function clearImpl(options) {
  const timer = options.getTimer()
  if (timer) options.clearInterval(timer)
  options.setTimer(null)
}

module.exports = {
  createExamTimerController,
}
