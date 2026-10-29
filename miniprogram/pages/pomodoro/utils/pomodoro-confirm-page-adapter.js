// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { formatElapsedSec } = require('./timer-math')

function buildCancelEndConfirmPageCapabilities(page, deps) {
  const { api } = deps
  return {
    isActionLoading: () => page.data.actionLoading,
    getEndConfirmMode: () => page._timerState.endConfirmMode,
    getConfirmTimerSnapshot: () => page._confirmTimerSnapshot,
    setConfirmTimerSnapshot: v => { page._confirmTimerSnapshot = v },
    now: () => api.now(),
    incrementConfirmActionSeq: () => { page._confirmActionSeq = (page._confirmActionSeq || 0) + 1 },
    isPaused: () => page.data.isPaused,
    applyTimerState: patch => Object.assign(page._timerState, patch),
    safeGetStorage: key => page._safeGetPomodoroStorage(key, 'cancel end confirm'),
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'cancel confirm resume adjustment'),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    setPendingSync: (action, sessionId, now) => page._setPendingPomodoroSync(action, sessionId, now),
    setData: data => page.setData(data),
    setCountdownTotalSec: v => { page._countdownTotalSec = v },
    startTimer: (totalSec, opts) => page._startTimer(totalSec, opts),
    startFreeTimerInterval: () => page._startFreeTimerInterval(),
    restartFreeTimerInterval: () => page._restartFreeTimerInterval(),
    nextTick: callback => wx.nextTick(callback),
    initCanvas: force => page._initCanvas(force),
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
    redrawFreeRingAfterOverlay: () => page._redrawFreeRingAfterOverlay(),
    retryPendingSync: () => page._retryPendingPomodoroSync(),
    warn: msg => console.warn(msg),
  }
}

function buildShowEndFreeConfirmPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    now: () => api.now(),
    isPaused: () => !!page.data.isPaused,
    getElapsedSec: () => page._timerState.elapsedSec,
    formatElapsedSec,
    incrementConfirmActionSeq: () => {
      page._confirmActionSeq = (page._confirmActionSeq || 0) + 1
      return page._confirmActionSeq
    },
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    getPauseStartTime: () => page._timerState.pauseStartTime || null,
    getSessionStartTime: () => page._timerState.sessionStartTime,
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'free confirm snapshot'),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    setPendingSync: (action, sessionId, now) => page._setPendingPomodoroSync(action, sessionId, now),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'free confirm rollback'),
    setConfirmTimerSnapshot: v => { page._confirmTimerSnapshot = v },
    clearFreeTimerInterval: () => page._clearFreeTimerInterval(),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    setData: data => page.setData(data),
    postPauseWithRetry: snapshot =>
      page._postPauseWithRetry(page._timerState.sessionId, snapshot.openedAt)
        .then(() => {
          if (snapshot.confirmActionSeq !== page._confirmActionSeq || !page.data.showEndConfirm) return
          snapshot.backendPauseDone = true
          page._confirmTimerSnapshot = snapshot
          page._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'confirm snapshot refresh')
        }),
    warn: (msg, e) => console.warn(msg, e),
  }
}

function buildPauseCountdownEndConfirmPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    now: () => api.now(),
    getCurrentTotalSec: () => page._getCurrentTotalSec(),
    getCountdownEndAt: () => page._countdownEndAt,
    getRemainingSec: () => page._timerState.remainingSec,
    isPaused: () => !!page.data.isPaused,
    getPhase: () => page.data.phase,
    incrementConfirmActionSeq: () => {
      page._confirmActionSeq = (page._confirmActionSeq || 0) + 1
      return page._confirmActionSeq
    },
    getSessionStartTime: () => page._timerState.sessionStartTime,
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    getPauseStartTime: () => page._timerState.pauseStartTime || null,
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'countdown confirm snapshot'),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    setPendingSync: (action, sessionId, now) => page._setPendingPomodoroSync(action, sessionId, now),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'countdown confirm rollback'),
    setConfirmTimerSnapshot: v => { page._confirmTimerSnapshot = v },
    clearTimer: () => page._clearTimer(),
    setCountdownEndAt: v => { page._countdownEndAt = v },
    formatCountdownDisplay: sec => page._formatCountdownDisplay(sec),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    setData: data => page.setData(data),
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
    postPauseWithRetry: snapshot =>
      page._postPauseWithRetry(page._timerState.sessionId, snapshot.openedAt)
        .then(() => {
          if (snapshot.confirmActionSeq !== page._confirmActionSeq || !page.data.showEndConfirm) return
          snapshot.backendPauseDone = true
          page._confirmTimerSnapshot = snapshot
          page._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'confirm snapshot refresh')
        }),
    warn: (msg, e) => console.warn(msg, e),
  }
}

function buildConfirmInterruptCountdownPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    getConfirmTimerSnapshot: () => page._confirmTimerSnapshot,
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    setTotalPausedMs: v => { page._timerState.totalPausedMs = v },
    now: () => api.now(),
    incrementConfirmActionSeq: () => { page._confirmActionSeq = (page._confirmActionSeq || 0) + 1 },
    setPendingSync: (action, sessionId, now) => page._setPendingPomodoroSync(action, sessionId, now),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    setData: data => page.setData(data),
    retryPendingSync: () => page._retryPendingPomodoroSync(),
    consumeTerminalConflict: (sessionId, action) => page._consumePomodoroTerminalConflict(sessionId, action),
    handleTerminalConflict: (sessionId, conflict) => page._handlePomodoroTerminalConflict(sessionId, conflict),
    showToast: toast => wx.showToast(toast),
    loadTodayStats: () => page.loadTodayStats(),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
    setConfirmTimerSnapshot: v => { page._confirmTimerSnapshot = v },
    resetToIdle: () => page._resetToIdle(),
  }
}

function buildShowCountdownInterruptConfirmPageCapabilities(page, deps) {
  return {
    isActionLoading: () => page.data.actionLoading,
    pauseCountdown: () => page._pauseCountdownForEndConfirm(),
    getConfirmTimerSnapshot: () => page._confirmTimerSnapshot,
    setData: data => page.setData(data),
    nextTick: callback => wx.nextTick(callback),
    initCanvas: force => page._initCanvas(force),
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
  }
}

function buildConfirmEndTimerPageCapabilities(page, deps) {
  return {
    isActionLoading: () => page.data.actionLoading,
    getEndConfirmMode: () => page._timerState.endConfirmMode,
    confirmEndFreeTimer: () => page._confirmEndFreeTimer(),
    confirmInterruptCountdown: () => page._confirmInterruptCountdown(),
    warn: (msg, detail) => console.warn(msg, detail),
    getSessionId: () => page._timerState.sessionId,
    getSnapshotMode: () => page._confirmTimerSnapshot && page._confirmTimerSnapshot.mode,
    showToast: toast => wx.showToast(toast),
  }
}

function buildConfirmEndFreeTimerPageCapabilities(page, deps) {
  return {
    isActionLoading: () => page.data.actionLoading,
    getSessionId: () => page._timerState.sessionId,
    incrementConfirmActionSeq: () => { page._confirmActionSeq = (page._confirmActionSeq || 0) + 1 },
    setConfirmTimerSnapshot: v => { page._confirmTimerSnapshot = v },
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
    setData: data => page.setData(data),
    clearFreeTimerInterval: () => page._clearFreeTimerInterval(),
    completeFreeTimerSession: () => page._completeFreeTimerSession(),
  }
}

module.exports = {
  buildCancelEndConfirmPageCapabilities,
  buildConfirmEndFreeTimerPageCapabilities,
  buildConfirmEndTimerPageCapabilities,
  buildConfirmInterruptCountdownPageCapabilities,
  buildPauseCountdownEndConfirmPageCapabilities,
  buildShowCountdownInterruptConfirmPageCapabilities,
  buildShowEndFreeConfirmPageCapabilities,
}
