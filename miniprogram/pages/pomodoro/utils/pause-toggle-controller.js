function createPauseToggleController(options) {
  const state = { locked: false, unlockTimer: null }
  return {
    acquire: () => acquire(options, state),
    release: () => release(options, state),
    toggle: () => toggle(options, state),
  }
}

function acquire(options, state) {
  if (state.locked) return false
  state.locked = true
  state.unlockTimer = options.setTimeout(() => {
    state.unlockTimer = null
    state.locked = false
  }, options.cooldownMs)
  return true
}

function release(options, state) {
  if (state.unlockTimer) {
    options.clearTimeout(state.unlockTimer)
    state.unlockTimer = null
  }
  state.locked = false
}

function toggle(options, state) {
  if (
    options.phase() !== options.runningPhase ||
    !options.sessionId() ||
    options.actionLoading() ||
    options.showEndConfirm() ||
    !acquire(options, state)
  ) return

  if (options.isFreeTimer()) {
    if (options.isPaused()) options.resumeFree()
    else options.pauseFree()
  } else if (options.isPaused()) {
    options.resumeCountdown()
  } else {
    options.pauseCountdown()
  }
}

module.exports = { createPauseToggleController }
