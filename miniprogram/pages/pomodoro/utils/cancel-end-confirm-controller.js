/**
 * Controller for cancelling the end-confirm overlay.
 *
 * Orchestrates the pure `buildCancelEndConfirmPlan` with page capabilities
 * (storage, timer state, canvas, sync) without holding a reference to the
 * page instance.
 *
 * Exported factory returns an object with a single `cancel()` method.
 * All page interactions are injected via the `options` object.
 */

const { buildCancelEndConfirmPlan } = require('./cancel-confirm-state')

function createCancelEndConfirmController(options) {
  return {
    cancel: () => cancel(options),
  }
}

function resolveSnapshot(options) {
  let snapshot = options.getConfirmTimerSnapshot()
  if (snapshot) return snapshot
  const storedConfirm = options.safeGetStorage('pomodoro_confirm_pause')
  if (!storedConfirm.ok) return null
  return storedConfirm.value
}

function buildPlan(options, mode, snapshot) {
  const now = options.now()
  options.incrementConfirmActionSeq()
  return buildCancelEndConfirmPlan({
    mode,
    snapshot,
    now,
    freeNow: mode === 'free-complete' ? options.now() : now,
    isPaused: options.isPaused(),
  })
}

function applyAdjustment(options, plan, now) {
  if (!plan.adjustment) return true
  if (!options.setPendingSync('resume', plan.adjustment.sessionId, now)) {
    options.showPersistenceError()
    return false
  }
  options.safeSetStorage('pomodoro_pause_adjustment', plan.adjustment)
  return true
}

function executePlan(options, plan) {
  options.setData(plan.view)
  if (plan.removeConfirmStorage) options.safeRemoveStorage('pomodoro_confirm_pause')
  if (plan.clearSnapshot) options.setConfirmTimerSnapshot(null)
  if (plan.startTimer) {
    options.setCountdownTotalSec(plan.startTimer.totalSec)
    options.startTimer(plan.startTimer.totalSec, {
      remainingMs: plan.startTimer.remainingMs,
      forceRunning: true,
    })
  }
  if (plan.startFreeTimer) options.startFreeTimerInterval()
  if (plan.restartFreeTimer) options.restartFreeTimerInterval()
  if (plan.redraw) {
    options.nextTick(() => {
      options.initCanvas(true)
      options.drawRing(plan.redraw.totalSec, plan.redraw.phase === 'break')
    })
  }
  if (plan.redrawFree) options.redrawFreeRingAfterOverlay()
  if (plan.retryPending) {
    options.retryPendingSync().then(synced => {
      if (!synced) options.warn('resume after cancel confirm pending; keep local timer')
    })
  }
}

function cancel(options) {
  if (options.isActionLoading()) return
  const mode = options.getEndConfirmMode()
  const snapshot = resolveSnapshot(options)
  if (!snapshot) {
    options.showPersistenceError()
    return
  }
  const plan = buildPlan(options, mode, snapshot)
  if (plan.snapshot) options.setConfirmTimerSnapshot(plan.snapshot)
  options.applyTimerState(plan.timer)
  if (!applyAdjustment(options, plan, options.now())) return
  executePlan(options, plan)
}

module.exports = { createCancelEndConfirmController }
