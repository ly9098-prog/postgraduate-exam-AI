function safeReviewTickDelta(rawMs) {
  if (rawMs < 0) return 0
  if (rawMs > 10000) return 10000
  return rawMs
}

function createReviewTimerController(options) {
  const session = options.getSession()

  function tick() {
    if (!options.isPageAlive()) return
    const now = options.monotonicNow()
    const lastTickAt = session.timerLastTickAt || session.timerStartedAt || now
    session.timerElapsedMs += safeReviewTickDelta(now - lastTickAt)
    session.timerLastTickAt = now
    options.setData({ elapsedText: options.formatElapsed(Math.floor(session.timerElapsedMs / 1000)) })
  }

  return {
    start() {
      if (options.getTimerId()) return
      session.timerElapsedMs = 0
      session.timerStartedAt = options.monotonicNow()
      session.timerLastTickAt = session.timerStartedAt
      session.timerRunning = true
      session.timingSegmentId = ''
      session.timingStartedAtMs = options.serverNow()
      options.setTimerId(options.setInterval(tick, 1000))
    },

    pause() {
      const timerId = options.getTimerId()
      if (!timerId) return
      const now = options.monotonicNow()
      const lastTickAt = session.timerLastTickAt || session.timerStartedAt || now
      session.timerElapsedMs += safeReviewTickDelta(now - lastTickAt)
      session.timerLastTickAt = 0
      session.timerRunning = false
      options.clearInterval(timerId)
      options.setTimerId(null)
    },

    resume() {
      if (options.getTimerId() || session.timerRunning) return
      session.timerStartedAt = options.monotonicNow()
      session.timerLastTickAt = session.timerStartedAt
      session.timerRunning = true
      options.setTimerId(options.setInterval(tick, 1000))
    },

    reset() {
      this.pause()
      session.timerElapsedMs = 0
      session.timerStartedAt = 0
      session.timerLastTickAt = 0
      session.timerRunning = false
      options.setData({ elapsedText: '00:00' })
    },

    clear() {
      const timerId = options.getTimerId()
      if (timerId) {
        options.clearInterval(timerId)
        options.setTimerId(null)
      }
      session.timerLastTickAt = 0
      session.timerRunning = false
    },

    buildTimingSession() {
      return buildTimingSession(session, options)
    },
  }
}

function buildTimingSession(session, options) {
  if (!session || !session.timingStartedAtMs) return null
  let elapsedMs = session.timerElapsedMs || 0
  if (session.timerRunning && session.timerLastTickAt) {
    elapsedMs += safeReviewTickDelta(options.monotonicNow() - session.timerLastTickAt)
  }
  const durationSec = Math.floor(elapsedMs / 1000)
  if (durationSec <= 0) return null
  if (!session.timingSegmentId) {
    session.timingSegmentId = typeof options.createRequestId === 'function'
      ? options.createRequestId()
      : ('req_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10))
  }
  const finishedAtMs = options.serverNow()
  const startedAtMs = Math.min(session.timingStartedAtMs, finishedAtMs - durationSec * 1000)
  return {
    request_id: session.timingSegmentId,
    started_at: new Date(startedAtMs).toISOString(),
    finished_at: new Date(finishedAtMs).toISOString(),
    duration_sec: durationSec,
  }
}

module.exports = {
  createReviewTimerController,
  safeReviewTickDelta,
}
