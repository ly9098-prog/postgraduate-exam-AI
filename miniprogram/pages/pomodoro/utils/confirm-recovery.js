const { formatElapsedSec, formatCountdownDisplay } = require('./timer-math')

function buildConfirmRecovery(snapshot, sessionStartTime) {
  const free = snapshot.mode === 'free-complete'
  const timer = {
    sessionId: snapshot.sessionId,
    sessionStartTime: snapshot.sessionStartTime || sessionStartTime,
    endConfirmMode: free ? 'free-complete' : 'countdown-interrupt',
    totalPausedMs: snapshot.totalPausedMs || 0,
  }
  const view = { phase: free ? 'running' : (snapshot.phase || 'running'),
    isPaused: true, ringCanvasVisible: true }
  if (free) {
    const fmt = formatElapsedSec(snapshot.elapsedSec || 0)
    Object.assign(timer, {
      elapsedSec: snapshot.elapsedSec || 0, freeFriendlyText: fmt.friendly, freeDisplayOffsetMs: 0,
    })
    Object.assign(view, { isFreeTimer: true, freeDisplayTime: fmt.display })
  } else {
    const fmt = formatCountdownDisplay(snapshot.remainingSec)
    Object.assign(timer, { remainingSec: snapshot.remainingSec, progress: snapshot.progress })
    Object.assign(view, { displayMin: fmt.min, displaySec: fmt.sec })
  }
  return { timer, view, free }
}

function retryConfirmPause(options, snapshot) {
  if (!snapshot.pausedByConfirm || snapshot.backendPauseDone) return
  options.pause(snapshot.sessionId, snapshot.openedAt)
    .then(() => {
      if (snapshot.confirmActionSeq !== options.currentSequence() || !options.isConfirmVisible()) return
      snapshot.backendPauseDone = true
      options.persist(snapshot)
    })
    .catch(() => {})
}

function restoreConfirmSnapshot(options, snapshot) {
  snapshot.confirmActionSeq = options.nextSequence()
  options.setSnapshot(snapshot)
  const recovery = buildConfirmRecovery(snapshot, options.sessionStartTime())
  options.applyTimer(recovery.timer)
  options.applyView({
    ...options.buildView(recovery.timer.endConfirmMode, snapshot),
    ...recovery.view,
  })
  if (!recovery.free) options.nextTick(() => options.draw(snapshot))
  retryConfirmPause(options, snapshot)
  options.deferStats()
}

module.exports = { buildConfirmRecovery, restoreConfirmSnapshot }
