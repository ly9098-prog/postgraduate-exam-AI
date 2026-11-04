function createExitGuardController(options) {
  return {
    setUnloadGuard: (enabled, message) => setUnloadGuard(options, enabled, message),
    syncVisibility: () => syncVisibility(options),
    shouldInterceptSystemBack: () => shouldInterceptSystemBack(options),
    rearm: () => rearm(options),
    handleGuardLeave: () => handleGuardLeave(options),
  }
}

function setUnloadGuard(options, enabled, message) {
  const session = options.getSession()
  if (session) {
    session.exitGuardActive = !!enabled
    session.exitGuardMessage = message || ''
  }
  try {
    if (options.hasDisableAlertBeforeUnload()) options.disableAlertBeforeUnload()
  } catch (_) {}
  if (!enabled) {
    options.setRearming(false)
    const timer = options.getRearmTimer()
    if (timer) {
      options.clearTimeout(timer)
      options.setRearmTimer(null)
    }
  }
  syncVisibility(options)
}

function syncVisibility(options) {
  if (!options.isPageAlive()) return
  const visible = !options.isNavigationLocked()
  if (options.isGuardVisible() !== visible) {
    options.setData({ practiceExitGuardVisible: visible })
  }
}

function shouldInterceptSystemBack(options) {
  const session = options.getSession()
  return !!(
    options.isPageAlive() &&
    !options.isNavigationLocked() &&
    session &&
    session.exitGuardActive &&
    options.isStarted() &&
    !options.isSubmitted()
  )
}

function rearm(options) {
  if (!shouldInterceptSystemBack(options) || options.isRearming()) return
  options.setRearming(true)
  const showGuard = () => {
    if (!shouldInterceptSystemBack(options)) {
      options.setRearming(false)
      return
    }
    options.setData({ practiceExitGuardVisible: true }, () => {
      options.setRearming(false)
    })
  }
  options.setData({ practiceExitGuardVisible: false }, () => {
    if (!shouldInterceptSystemBack(options)) {
      options.setRearming(false)
      return
    }
    if (options.hasNextTick()) {
      options.nextTick(showGuard)
      return
    }
    options.setRearmTimer(options.setTimeout(() => {
      options.setRearmTimer(null)
      showGuard()
    }, 0))
  })
}

function handleGuardLeave(options) {
  if (!options.isPageAlive() || options.isNavigationLocked()) return
  if (!shouldInterceptSystemBack(options)) {
    options.returnToOrigin()
    return
  }
  rearm(options)
  if (options.isPromptQueued() || options.isExitConfirmInFlight()) return
  options.setPromptQueued(true)
  options.queueMicrotask(async () => {
    options.setPromptQueued(false)
    if (!shouldInterceptSystemBack(options)) return
    await options.requestExit({ source: 'system-back' })
  }).catch((err) => {
    options.setPromptQueued(false)
    options.logWarn('系统返回退出确认处理失败', err)
  })
}

module.exports = { createExitGuardController }
