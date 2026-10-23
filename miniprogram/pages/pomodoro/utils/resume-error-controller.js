// Reconciles local state after a /resume 404 by fetching the authoritative
// active session. The page injects every side effect; this module only owns the
// branching and view/timer mutations through explicit callbacks.
function createResumeErrorController(options) {
  return {
    reconcile: (error, sessionId) => reconcile(error, sessionId, options),
  }
}

async function reconcile(error, sessionId, options) {
  if (!error || error.code !== 404) {
    options.showToast({ title: '继续失败，请重试', icon: 'none' })
    return
  }
  try {
    const active = await options.getActive('/pomodoro/active')
    if (!active || active.id !== sessionId) {
      options.resetIdle()
      options.showToast({ title: '当前专注已结束或失效', icon: 'none' })
      return
    }
    if (active.status !== 'running') {
      options.showToast({ title: '继续失败，请稍后重试', icon: 'none' })
      return
    }
    // Server says running — fix local state and continue.
    const startTime = options.parseServerTime(active.start_time)
    const totalPausedMs = (active.total_paused_sec || 0) * 1000
    if (options.isFreeTimer()) {
      reconcileFree(startTime, totalPausedMs, active.id, options)
    } else {
      reconcileCountdown(startTime, totalPausedMs, active.id, options)
    }
    options.showToast({ title: '已恢复计时', icon: 'none' })
  } catch (_) {
    options.showToast({ title: '继续失败，请重试', icon: 'none' })
  }
}

function reconcileFree(startTime, totalPausedMs, activeId, options) {
  options.timer().sessionStartTime = startTime
  options.timer().totalPausedMs = options.mergeLocalPauseAdjustment(activeId, totalPausedMs)
  options.timer().pauseStartTime = null

  const elapsedMs = options.getEffectiveFreeElapsedMs()
  const elapsed = Math.floor(elapsedMs / 1000)
  const fmt = options.formatElapsedSec(elapsed)
  options.timer().elapsedSec = elapsed
  options.setData({
    isPaused: false,
    freeDisplayTime: fmt.display,
    ringCanvasVisible: true,
  })
  options.startFreeTimerInterval()
  options.removeStorage('pomodoro_free_pause', 'best-effort cleanup')
}

function reconcileCountdown(startTime, totalPausedMs, activeId, options) {
  const now = options.now()
  const totalSec = options.getCurrentTotalSec()

  // Merge with local pause adjustment.
  const effectiveTotalPausedMs = options.mergeLocalPauseAdjustment(activeId, totalPausedMs)

  const elapsed = Math.floor((now - startTime - effectiveTotalPausedMs) / 1000)
  const remainingSec = Math.max(0, totalSec - elapsed)
  options.timer().sessionStartTime = startTime
  options.timer().totalPausedMs = effectiveTotalPausedMs
  options.timer().pauseStartTime = null
  options.timer().remainingSec = remainingSec
  options.timer().progress = totalSec > 0 ? remainingSec / totalSec : 0
  options.setData({
    isPaused: false,
    remainingSec,
    displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
    displaySec: String(remainingSec % 60).padStart(2, '0'),
    ringCanvasVisible: true,
  })
  options.startTimer(totalSec)
  options.removeStorage('pomodoro_pause', 'best-effort cleanup')
}

module.exports = { createResumeErrorController }
