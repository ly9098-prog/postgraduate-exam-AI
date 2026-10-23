function createFreeTimerBeginController(options) {
  return {
    begin: session => begin(session, options),
  }
}

function begin(session, options) {
  const startTime = options.parseServerTime(session.start_time)
  const totalPausedMs = Math.max(0, Number(session.total_paused_sec || 0) * 1000)
  const now = options.now()
  const elapsedMs = Math.max(0, now - startTime - totalPausedMs)
  const elapsedSec = Math.min(Math.floor(elapsedMs / 1000), Math.floor(options.maxMs / 1000))
  const fmt = options.formatElapsedSec(elapsedSec)

  options.clearTimer()
  const timer = options.timer()
  timer.sessionId = session.id
  timer.sessionStartTime = startTime
  timer.totalPausedMs = totalPausedMs
  // Server start_time is the single clock origin. Do not hide /start network
  // latency behind a client-only display offset, otherwise UI and statistics
  // diverge by the request round-trip time.
  timer.freeDisplayOffsetMs = 0
  timer.pauseStartTime = null
  timer.elapsedSec = elapsedSec
  timer.freeFriendlyText = fmt.friendly
  timer.progress = 1
  options.setData({
    phase: options.runningPhase,
    ringCanvasVisible: true,
    isFreeTimer: true,
    isPaused: false,
    freeDisplayTime: fmt.display,
    showEndConfirm: false,
  })
  options.updateComputedFields()
  if (elapsedMs >= options.maxMs) {
    options.autoFinishFreeTimer()
    return
  }
  options.startFreeTimerInterval()
  options.nextTick(() => {
    options.initCanvas(true)
    options.drawRing(0, false)
  })
}

module.exports = { createFreeTimerBeginController }
