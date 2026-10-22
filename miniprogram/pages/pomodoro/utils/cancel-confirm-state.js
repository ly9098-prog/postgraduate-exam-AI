const { formatElapsedSec, formatCountdownDisplay } = require('./cancel-confirm-format')

function closedView(extra) {
  return {
    showEndConfirm: false,
    ringCanvasVisible: true,
    endConfirmTheme: '',
    endConfirmTitle: '',
    endConfirmText: '',
    endConfirmLine1: '',
    endConfirmLine2: '',
    endConfirmLine3: '',
    ...extra,
  }
}

function countdownPlan(options, snapshot) {
  const fmt = formatCountdownDisplay(snapshot.remainingSec)
  const pausedTimer = {
    remainingSec: snapshot.remainingSec,
    progress: snapshot.progress,
    pauseStartTime: snapshot.pauseStartTime || options.now,
    totalPausedMs: snapshot.totalPausedMs || 0,
    endConfirmMode: '',
  }
  const pausedView = {
    displayMin: fmt.min,
    displaySec: fmt.sec,
    isPaused: true,
  }
  if (snapshot.wasPaused) {
    return countdownPausedPlan(snapshot, pausedTimer, pausedView)
  }
  const pauseDelta = Math.max(0, options.now - snapshot.openedAt)
  const localTotalPausedMs = (snapshot.totalPausedMs || 0) + pauseDelta
  return countdownResumePlan(options, snapshot, fmt, localTotalPausedMs)
}

function countdownPausedPlan(snapshot, timer, view) {
  return {
    kind: 'countdown-paused',
    snapshot,
    timer,
    view: closedView(view),
    redraw: { totalSec: snapshot.totalSec, phase: snapshot.phase },
    removeConfirmStorage: true,
    clearSnapshot: true,
  }
}

function countdownResumePlan(options, snapshot, fmt, localTotalPausedMs) {
  return {
    kind: 'countdown-resume',
    snapshot,
    timer: {
      remainingSec: snapshot.remainingSec,
      progress: snapshot.progress,
      totalPausedMs: localTotalPausedMs,
      pauseStartTime: null,
      endConfirmMode: '',
    },
    view: closedView({
      displayMin: fmt.min,
      displaySec: fmt.sec,
      isPaused: false,
      actionLoading: false,
    }),
    adjustment: {
      sessionId: snapshot.sessionId,
      totalPausedMs: localTotalPausedMs,
      savedAt: options.now,
      source: 'cancel_end_confirm',
    },
    pendingResume: true,
    startTimer: {
      totalSec: snapshot.totalSec,
      remainingMs: snapshot.remainingMs,
    },
    redraw: { totalSec: snapshot.totalSec, phase: snapshot.phase },
    removeConfirmStorage: true,
    clearSnapshot: true,
    retryPending: true,
  }
}

function freePlan(options, snapshot) {
  if (!snapshot || snapshot.mode !== 'free-complete') {
    return freeInvalidPlan(options)
  }

  const freeNow = options.freeNow === undefined ? options.now : options.freeNow
  const fmt = formatElapsedSec(snapshot.elapsedSec || 0)
  const pausedTimer = {
    pauseStartTime: snapshot.pauseStartTime || options.now,
    totalPausedMs: snapshot.totalPausedMs || 0,
    elapsedSec: snapshot.elapsedSec || 0,
    freeFriendlyText: fmt.friendly,
    endConfirmMode: '',
    freeDisplayOffsetMs: 0,
  }
  if (snapshot.wasPaused) {
    return freePausedPlan(snapshot, pausedTimer, fmt)
  }
  const pauseDelta = Math.max(0, freeNow - snapshot.openedAt)
  const localTotalPausedMs = (snapshot.totalPausedMs || 0) + pauseDelta
  return freeResumePlan(snapshot, fmt, freeNow, localTotalPausedMs)
}

function freeInvalidPlan(options) {
  return {
    kind: 'free-invalid',
    timer: { endConfirmMode: '' },
    view: closedView(),
    startFreeTimer: !options.isPaused,
    redrawFree: true,
    clearSnapshot: false,
  }
}

function freePausedPlan(snapshot, timer, fmt) {
  return {
    kind: 'free-paused',
    snapshot,
    timer,
    view: closedView({
      isPaused: true,
      freeDisplayTime: fmt.display,
    }),
    redrawFree: true,
    removeConfirmStorage: true,
    clearSnapshot: true,
  }
}

function freeResumePlan(snapshot, fmt, freeNow, localTotalPausedMs) {
  return {
    kind: 'free-resume',
    snapshot,
    timer: {
      pauseStartTime: null,
      totalPausedMs: localTotalPausedMs,
      elapsedSec: snapshot.elapsedSec || 0,
      freeFriendlyText: '',
      endConfirmMode: '',
      freeDisplayOffsetMs: 0,
    },
    view: closedView({
      isPaused: false,
      freeDisplayTime: fmt.display,
    }),
    adjustment: {
      sessionId: snapshot.sessionId,
      totalPausedMs: localTotalPausedMs,
      savedAt: freeNow,
      source: 'cancel_free_end_confirm',
    },
    pendingResume: true,
    restartFreeTimer: true,
    redrawFree: true,
    removeConfirmStorage: true,
    clearSnapshot: true,
    retryPending: true,
  }
}

function buildCancelEndConfirmPlan(options) {
  const mode = options.mode
  const snapshot = options.snapshot

  if (mode === 'countdown-interrupt' && snapshot && snapshot.sessionId) {
    return countdownPlan(options, snapshot)
  }

  if (mode === 'free-complete') {
    return freePlan(options, snapshot)
  }

  return {
    kind: 'fallback',
    timer: { endConfirmMode: '' },
    view: closedView(),
    clearSnapshot: true,
  }
}

module.exports = { buildCancelEndConfirmPlan, closedView }
