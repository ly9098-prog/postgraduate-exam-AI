// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { FREE_TIMER_MAX_MS, PHASE } = require('./pomodoro-page-support')
const { pomodoroTaskTypes } = require('../../../utils/storage')
const { formatElapsedSec } = require('./timer-math')

function buildPauseSessionPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    now: () => api.now(),
    setPendingSync: (action, sid, now) => page._setPendingPomodoroSync(action, sid, now),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    clearTimer: () => page._clearTimer(),
    setPauseStartTime: v => { page._timerState.pauseStartTime = v },
    setData: data => page.setData(data),
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'countdown pause snapshot'),
    retryPendingSync: () => page._retryPendingPomodoroSync(),
    showToast: toast => wx.showToast(toast),
  }
}

function buildResumeSessionPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionStartTime: () => page._timerState.sessionStartTime,
    warn: (msg, val) => console.warn(msg, val),
    resetToIdle: () => page._resetToIdle(),
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    now: () => api.now(),
    getPauseStartTime: () => page._timerState.pauseStartTime,
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    isDebugPreset: () => page.data.selectedPreset === 'debug',
    getWorkDurationMinutes: () => page.data.workDuration,
    setPendingSync: (action, sid, now) => page._setPendingPomodoroSync(action, sid, now),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'countdown resume adjustment'),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'countdown resume snapshot'),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    setData: data => page.setData(data),
    startTimer: (totalSec, opts) => page._startTimer(totalSec, opts),
    retryPendingSync: () => page._retryPendingPomodoroSync(),
    showToast: toast => wx.showToast(toast),
  }
}

function buildPauseFreeTimerPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    now: () => api.now(),
    setPendingSync: (action, sid, now) => page._setPendingPomodoroSync(action, sid, now),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    updateFreeElapsed: () => page._updateFreeElapsed(),
    clearFreeTimerInterval: () => page._clearFreeTimerInterval(),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    setData: data => page.setData(data),
    getElapsedSec: () => page._timerState.elapsedSec,
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'free pause snapshot'),
    retryPendingSync: () => page._retryPendingPomodoroSync(),
    showToast: toast => wx.showToast(toast),
  }
}

function buildResumeFreeTimerPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    isActionLoading: () => page.data.actionLoading,
    now: () => api.now(),
    getPauseStartTime: () => page._timerState.pauseStartTime,
    getTotalPausedMs: () => page._timerState.totalPausedMs || 0,
    setPendingSync: (action, sid, now) => page._setPendingPomodoroSync(action, sid, now),
    showPersistenceError: () => page._showPomodoroPersistenceError(),
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'free resume adjustment'),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'free resume snapshot'),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    setData: data => page.setData(data),
    startFreeTimerInterval: () => page._startFreeTimerInterval(),
    retryPendingSync: () => page._retryPendingPomodoroSync(),
    showToast: toast => wx.showToast(toast),
  }
}

function buildInterruptSessionPageCapabilities(page, deps) {
  return {
    getSessionId: () => page._timerState.sessionId,
    isFreeTimer: () => page.data.isFreeTimer,
    showEndFreeConfirm: () => page._showEndFreeConfirm(),
    showCountdownInterruptConfirm: () => page._showCountdownInterruptConfirm(),
  }
}

function buildEndSessionPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getSessionId: () => page._timerState.sessionId,
    clearTimer: () => page._clearTimer(),
    completeWithRetry: (sessionId, now) => page._completePomodoroWithRetry(sessionId, now),
    now: () => api.now(),
    consumeTerminalConflict: (sessionId, action) => page._consumePomodoroTerminalConflict(sessionId, action),
    handleTerminalConflict: (sessionId, conflict) => page._handlePomodoroTerminalConflict(sessionId, conflict),
    loadTodayStats: () => page.loadTodayStats(),
    resetToIdle: () => page._resetToIdle(),
  }
}

function buildResetToIdlePageCapabilities(page, deps) {
  return {
    clearFreeTimerInterval: () => page._clearFreeTimerInterval(),
    setConfirmTimerSnapshot: v => { page._confirmTimerSnapshot = v },
    invalidateCanvas: () => {
      page._canvasInitSeq = (page._canvasInitSeq || 0) + 1
      page._canvasReady = false
      page._canvasInitPending = false
      page._ctx = null
      page._pendingDraw = null
      page._lastDrawnProgress = undefined
      page._lastDrawnIsBreak = undefined
      page._ringCache = null
    },
    resetTimerState: () => { page._timerState = page._createTimerState() },
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
    getSelectedTaskType: () => pomodoroTaskTypes.getSelected(),
    taskTypeLabel: type => pomodoroTaskTypes.label(type),
    idlePhase: () => PHASE.IDLE,
    setData: data => page.setData(data),
    setCompletionBreakSec: v => { page._completionBreakSec = v },
    updateComputedFields: () => page._updateComputedFields(),
  }
}

function buildUpdateFreeElapsedPageCapabilities(page, deps) {
  return {
    isFreeTimer: () => page.data.isFreeTimer,
    showEndConfirm: () => page.data.showEndConfirm,
    isPaused: () => page.data.isPaused,
    getElapsedSec: () => page._timerState.elapsedSec,
    setData: data => page.setData(data),
    setFreeFriendlyText: v => { page._timerState.freeFriendlyText = v },
    getEffectiveFreeElapsedMs: () => page._getEffectiveFreeElapsedMs(),
    maxMs: () => FREE_TIMER_MAX_MS,
    setElapsedSec: v => { page._timerState.elapsedSec = v },
  }
}

function buildFreeTimerPageCapabilities(page, deps) {
  return {
    setTimeout: (fn, delay) => setTimeout(fn, delay),
    clearTimeout: timer => clearTimeout(timer),
    getElapsedMs: () => page._getEffectiveFreeElapsedMs(),
    isBlocked: () => page.data.isPaused || page.data.showEndConfirm,
    onTick: () => page._updateFreeElapsed(),
    shouldFinalize: () => page._checkFreeTimerLimitAndAutoEnd(),
  }
}

function buildFreeTimerLimitPageCapabilities(page, deps) {
  const { api } = deps
  return {
    finalizing: () => page._freeTimerFinalizing,
    setFinalizing: value => { page._freeTimerFinalizing = value },
    autoFinish: () => page._autoFinishFreeTimer(),
    isFreeTimer: () => page.data.isFreeTimer,
    isPaused: () => page.data.isPaused,
    getEffectiveFreeElapsedMs: () => page._getEffectiveFreeElapsedMs(),
    maxMs: FREE_TIMER_MAX_MS,
    clearFreeTimerInterval: () => page._clearFreeTimerInterval(),
    formatElapsedSec,
    setElapsedSec: value => { page._timerState.elapsedSec = value },
    setData: data => page.setData(data),
    showToast: toast => wx.showToast(toast),
    getSessionId: () => page._timerState.sessionId,
    now: () => api.now(),
    completeWithRetry: (sessionId, clientActionAt) =>
      page._completePomodoroWithRetry(sessionId, clientActionAt),
    consumeTerminalConflict: (sessionId, requestedAction) =>
      page._consumePomodoroTerminalConflict(sessionId, requestedAction),
    handleTerminalConflict: (sessionId, conflict) =>
      page._handlePomodoroTerminalConflict(sessionId, conflict),
    loadTodayStats: () => page.loadTodayStats(),
    resetToIdle: () => page._resetToIdle(),
  }
}

function buildFreeElapsedPageCapabilities(page, deps) {
  const { api } = deps
  return {
    now: () => api.now(),
    getSessionId: () => page._timerState.sessionId,
    getSessionStartTime: () => page._timerState.sessionStartTime,
    getTotalPausedMs: () => page._timerState.totalPausedMs,
    mergeLocalPauseAdjustment: (sessionId, totalPausedMs) =>
      page._mergeLocalPauseAdjustment(sessionId, totalPausedMs),
  }
}

function buildPomodoroPauseSyncPageCapabilities(page, deps) {
  return {
    setPendingPomodoroSync: (action, sessionId, clientActionAt) =>
      page._setPendingPomodoroSync(action, sessionId, clientActionAt),
    retryPendingPomodoroSync: () => page._retryPendingPomodoroSync(),
  }
}

module.exports = {
  buildEndSessionPageCapabilities,
  buildFreeElapsedPageCapabilities,
  buildFreeTimerLimitPageCapabilities,
  buildFreeTimerPageCapabilities,
  buildInterruptSessionPageCapabilities,
  buildPauseFreeTimerPageCapabilities,
  buildPauseSessionPageCapabilities,
  buildPomodoroPauseSyncPageCapabilities,
  buildResetToIdlePageCapabilities,
  buildResumeFreeTimerPageCapabilities,
  buildResumeSessionPageCapabilities,
  buildUpdateFreeElapsedPageCapabilities,
}
