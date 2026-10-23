function createWorkCompleteController(options) {
  return {
    complete: () => complete(options),
  }
}

async function complete(options) {
  const sessionId = options.timer().sessionId
  if (!sessionId) {
    options.resetIdle()
    return
  }

  const completedAt = options.now()
  options.clearTimer()
  options.vibrateLong()
  options.completeWithRetry(sessionId, completedAt).then(synced => {
    const conflict = options.consumeTerminalConflict(sessionId, 'complete')
    if (conflict) {
      options.handleTerminalConflict(sessionId, conflict)
      return
    }
    if (synced) {
      options.loadStats()
    } else {
      options.showToast({ title: '已完成，网络恢复后自动同步', icon: 'none' })
    }
  })

  options.showCompletionCelebration(sessionId)
}

module.exports = { createWorkCompleteController }
