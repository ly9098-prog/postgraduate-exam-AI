// Light sync reconciles the local timer with the authoritative server session
// without a full restore. It never touches storage directly; the page injects
// every side effect (view, timer state, canvas, free interval, completion).
function createActiveSyncController(options) {
  return {
    canLightSync: active => canLightSync(active, options),
    syncLight: (active, failClosed) => syncLight(active, failClosed, options),
  }
}

function canLightSync(active, options) {
  const timer = options.timer()
  const view = options.view()
  if (!timer.sessionId) return false
  if (active.id !== timer.sessionId) return false
  if (view.phase !== options.runningPhase) return false
  if ((active.status === 'paused') !== view.isPaused) return false
  if ((active.preset === 'free') !== view.isFreeTimer) return false
  if (typeof timer.sessionStartTime !== 'number' || timer.sessionStartTime <= 0) return false
  return true
}

function syncLight(active, failClosed, options) {
  const now = options.now()
  const parsedStartTime = options.parseServerTime(active.start_time)
  if (Number.isFinite(parsedStartTime) && parsedStartTime > 0) {
    options.timer().sessionStartTime = parsedStartTime
  }
  applyAllocation(active, options)
  const totalPausedMs = mergePausedMs(active, failClosed, options)
  if (totalPausedMs === null) {
    if (failClosed) options.persistenceError()
    return false
  }
  options.timer().totalPausedMs = totalPausedMs
  if (options.view().isFreeTimer) return syncFreeTimer(now, totalPausedMs, options)
  return syncCountdownTimer(now, totalPausedMs, options)
}

function applyAllocation(active, options) {
  const view = options.view()
  const allocationMode = active.allocation_mode === 'equal_408_core_v1'
    ? 'equal_408_core_v1'
    : 'single'
  if (allocationMode === view.allocationMode) return
  const subjectId = active.subject_id || view.selectedSubjectId
  const subject = (view.subjects || []).find(
    item => Number(item.id) === Number(subjectId)
  ) || view.selectedSubject
  options.setData({
    allocationMode,
    selectedSubject: subject
      ? { ...subject, _isAggregate: allocationMode === 'equal_408_core_v1' }
      : subject,
  })
  options.updateComputedFields()
}

function mergePausedMs(active, failClosed, options) {
  const serverPausedMs = Math.max(0, Number(active.total_paused_sec || 0) * 1000)
  const localPausedMs = Math.max(0, Number(options.timer().totalPausedMs || 0))
  return options.mergeLocalPauseAdjustment(
    options.timer().sessionId,
    Math.max(serverPausedMs, localPausedMs),
    failClosed,
  )
}

function ensureFreeCanvas(totalPausedMs, options) {
  options.timer().progress = 1
  options.nextTick(() => {
    if (!options.isPageVisible() || options.view().phase !== options.runningPhase ||
        !options.view().isFreeTimer) return
    options.initCanvas(true)
    options.drawRing(0, false)
  })
}

function syncFreeTimer(now, totalPausedMs, options) {
  if (!options.canvasReady() || !options.ctx()) ensureFreeCanvas(totalPausedMs, options)
  if (!options.view().isPaused) {
    const elapsedMs = Math.max(0, now - options.timer().sessionStartTime - totalPausedMs)
    const cappedMs = Math.min(elapsedMs, options.maxMs)
    const elapsed = Math.floor(cappedMs / 1000)
    if (elapsed !== options.timer().elapsedSec) {
      const fmt = options.formatElapsedSec(elapsed)
      options.timer().elapsedSec = elapsed
      options.setData({ freeDisplayTime: fmt.display })
    }
    if (elapsedMs >= options.maxMs) {
      options.autoFinishFreeTimer()
      return true
    }
    // onHide clears the interval, so onShow must always restart it.
    options.startFreeTimerInterval()
  }
  return true
}

function syncCountdownTimer(now, totalPausedMs, options) {
  const view = options.view()
  const totalSec = view.selectedPreset === 'debug' ? 10 : (view.workDuration ?? 25) * 60
  if (view.isPaused) {
    if (!options.canvasReady() || !options.ctx()) {
      options.nextTick(() => {
        if (!options.isPageVisible() || options.view().phase !== options.runningPhase ||
            !options.view().isPaused) return
        options.initCanvas(true)
        options.drawRing(totalSec, false)
      })
    }
    return true
  }
  const elapsedMs = Math.max(0, now - options.timer().sessionStartTime - totalPausedMs)
  const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)
  if (remainingMs <= 0) {
    options.clearTimer()
    options.onWorkComplete()
    return true
  }
  // onHide clears the timeout. Restart from wall-clock-derived remaining time
  // instead of repainting only one frame and leaving the countdown stopped.
  options.startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })
  return true
}

module.exports = { createActiveSyncController }
