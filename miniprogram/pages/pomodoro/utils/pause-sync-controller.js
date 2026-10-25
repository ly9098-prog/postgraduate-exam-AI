function createPomodoroPauseSyncController(options) {
  return {
    postPause: postPauseImpl.bind(null, options),
  }
}

async function postPauseImpl(options, sessionId, clientActionAt) {
  const pending = options.setPendingPomodoroSync('pause', sessionId, clientActionAt)
  if (!pending) throw new Error('pomodoro local persistence unavailable')
  const synced = await options.retryPendingPomodoroSync()
  if (!synced) throw new Error('pomodoro pause sync pending')
  return true
}

module.exports = {
  createPomodoroPauseSyncController,
}
