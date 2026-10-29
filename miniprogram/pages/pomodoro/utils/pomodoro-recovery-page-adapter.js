// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { FREE_TIMER_MAX_MS, PHASE, POMODORO_TERMINAL_CONFLICT_KEY, POMODORO_UNKNOWN_START_KEY, parseServerTime } = require('./pomodoro-page-support')
const { pomodoroTaskTypes } = require('../../../utils/storage')
const { canReconcilePendingSync, decidePendingSyncReconciliation } = require('./sync-reconciliation')
const { handleTerminalConflict } = require('./terminal-conflict-handler')
const conflictState = require('./terminal-conflict-state')
const { formatElapsedSec } = require('./timer-math')
const { buildUnknownStartAttempt, buildUnknownStartPayload, matchesUnknownStartAttempt, startCancellationAt } = require('./unknown-start-helpers')

function buildSyncRetryPageCapabilities(page, deps) {
  return {
    setTimeout: (fn, delay) => setTimeout(fn, delay),
    clearTimeout: timer => clearTimeout(timer),
    isVisible: () => page._pageVisible,
    hasPending: () => !!page._getPendingPomodoroSync(),
    retry: () => page._retryPendingPomodoroSync(),
    warn: (message, error) => console.warn(message, error),
    consumeConflict: () => page._consumeAnyPomodoroTerminalConflict(),
    handleConflict: (sessionId, conflict) => page._handlePomodoroTerminalConflict(sessionId, conflict),
    loadStats: () => page.loadTodayStats(),
    canListen: () => typeof wx.onNetworkStatusChange === 'function' &&
      typeof wx.offNetworkStatusChange === 'function',
    onNetworkStatusChange: handler => wx.onNetworkStatusChange(handler),
    offNetworkStatusChange: handler => {
      if (typeof wx.offNetworkStatusChange === 'function') wx.offNetworkStatusChange(handler)
    },
  }
}

function buildUnknownStartPageCapabilities(page, deps) {
  const { api } = deps
  return {
    page,
    storageKey: POMODORO_UNKNOWN_START_KEY,
    post: (path, payload) => api.post(path, payload),
    createClientStartId: () => api.createClientStartId(),
    now: () => api.now(),
    parseServerTime,
    buildAttempt: buildUnknownStartAttempt,
    buildPayload: buildUnknownStartPayload,
    matches: matchesUnknownStartAttempt,
    startCancellationAt,
    recordSession: (session, taskType) => pomodoroTaskTypes.recordSession(session, taskType),
    reconcile: attempt => page._reconcileUnknownStartAttempt(attempt),
  }
}

function buildResumeErrorPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getActive: path => api.get(path),
    parseServerTime,
    showToast: toast => wx.showToast(toast),
    resetIdle: () => page._resetToIdle(),
    timer: () => page._timerState,
    isFreeTimer: () => page.data.isFreeTimer,
    mergeLocalPauseAdjustment: (sessionId, serverPausedMs) =>
      page._mergeLocalPauseAdjustment(sessionId, serverPausedMs),
    getEffectiveFreeElapsedMs: () => page._getEffectiveFreeElapsedMs(),
    formatElapsedSec,
    setData: data => page.setData(data),
    startFreeTimerInterval: () => page._startFreeTimerInterval(),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    now: () => api.now(),
    getCurrentTotalSec: () => page._getCurrentTotalSec(),
    startTimer: totalSec => page._startTimer(totalSec),
  }
}

function buildPendingSyncQueuePageCapabilities(page, deps) {
  const { api } = deps
  return {
    storage: {
      read: (key, context) => page._safeGetPomodoroStorage(key, context),
      write: (key, value, context) => page._safeSetPomodoroStorage(key, value, context),
      remove: (key, context) => page._safeRemovePomodoroStorage(key, context),
    },
    now: () => api.now(),
  }
}

function buildPomodoroSessionActionDropperPageCapabilities(page, deps) {
  return {
    getPendingPomodoroSyncQueue: () => page._getPendingPomodoroSyncQueue(),
    writePendingPomodoroSyncQueue: queue => page._writePendingPomodoroSyncQueue(queue),
    safeGetPomodoroStorage: (key, context) => page._safeGetPomodoroStorage(key, context),
    safeRemovePomodoroStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
  }
}

function buildTerminalConflictPageCapabilities(page, deps) {
  const { api } = deps
  return {
    storageKey: POMODORO_TERMINAL_CONFLICT_KEY,
    getStorage: (key, context) => page._safeGetPomodoroStorage(key, context),
    setStorage: (key, value, context) => page._safeSetPomodoroStorage(key, value, context),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    now: () => api.now(),
    createConflict: conflictState.createTerminalConflict,
    isValidConflict: conflictState.isValidTerminalConflict,
    matchesConflict: conflictState.matchesTerminalConflict,
    isStorageConflict: value => conflictState.isStorageConflict(value),
    handleTerminalConflict,
    dropSessionActions: sessionId => page._dropPendingPomodoroSessionActions(sessionId),
    persistenceError: () => page._showPomodoroPersistenceError(),
    getCompletionBreakSec: () => page._completionBreakSec,
    setCompletionBreakSec: value => { page._completionBreakSec = value },
    clearTimer: () => page._clearTimer(),
    setData: data => page.setData(data),
    resetIdle: () => page._resetToIdle(),
    showToast: toast => wx.showToast(toast),
    loadStats: () => page.loadTodayStats(),
  }
}

function buildPendingSyncPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getQueue: () => page._getPendingPomodoroSyncQueue(),
    clearPending: expected => page._clearPendingPomodoroSync(expected),
    updatePending: (expected, patch) => page._updatePendingPomodoroSync(expected, patch),
    enqueue: (action, sessionId, clientActionAt) => (
      page._setPendingPomodoroSync(action, sessionId, clientActionAt)
    ),
    hasPending: (sessionId, action) => page._hasPendingPomodoroAction(sessionId, action),
    canReconcile: error => canReconcilePendingSync(error),
    decideReconciliation: (pending, error, active) => (
      decidePendingSyncReconciliation(pending, error, active)
    ),
    formatClientActionAt: timestamp => {
      try {
        return new Date(timestamp).toISOString()
      } catch (_) {
        return null
      }
    },
    post: (path, body) => api.post(path, body),
    getActive: () => api.get('/pomodoro/active'),
    now: () => api.now(),
    isVisible: () => page._pageVisible,
    restoreSession: active => page._restoreSession(active),
    maybeClearAdjustment: sessionId => page._maybeClearLocalPauseAdjustment(sessionId),
    dropSessionActions: sessionId => page._dropPendingPomodoroSessionActions(sessionId),
    getStorage: (key, context) => page._safeGetPomodoroStorage(key, context),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    setCompletionBreakSec: value => { page._completionBreakSec = value },
    setData: data => page.setData(data),
    recordTerminalConflict: (sessionId, action, status) => (
      page._recordPomodoroTerminalConflict(sessionId, action, status)
    ),
    readConflict: () => page._readPomodoroTerminalConflict(),
    isStorageConflict: value => page._isPomodoroStorageError(value),
    clearRetryTimer: reset => page._clearPendingPomodoroSyncRetryTimer(reset),
    scheduleRetry: error => page._schedulePendingPomodoroSyncRetry(error),
    persistenceError: () => page._showPomodoroPersistenceError(),
    logError: (...args) => console.error(...args),
  }
}

function buildActiveSyncPageCapabilities(page, deps) {
  const { api } = deps
  return {
    now: () => api.now(),
    view: () => page.data,
    timer: () => page._timerState,
    runningPhase: PHASE.RUNNING,
    parseServerTime,
    setData: data => page.setData(data),
    updateComputedFields: () => page._updateComputedFields(),
    mergeLocalPauseAdjustment: (sessionId, serverPausedMs, failClosed) =>
      page._mergeLocalPauseAdjustment(sessionId, serverPausedMs, failClosed),
    persistenceError: () => page._showPomodoroPersistenceError(),
    canvasReady: () => !!page._canvasReady,
    ctx: () => page._ctx,
    nextTick: callback => wx.nextTick(callback),
    isPageVisible: () => page._pageVisible,
    initCanvas: force => page._initCanvas(force),
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
    maxMs: FREE_TIMER_MAX_MS,
    formatElapsedSec,
    autoFinishFreeTimer: () => page._autoFinishFreeTimer(),
    startFreeTimerInterval: () => page._startFreeTimerInterval(),
    clearTimer: () => page._clearTimer(),
    onWorkComplete: () => page._onWorkComplete(),
    startTimer: (totalSec, timerOptions) => page._startTimer(totalSec, timerOptions),
  }
}

function buildPomodoroActiveSessionReconcilerPageCapabilities(page, deps) {
  const { api } = deps
  return {
    safeGetPomodoroStorage: (key, context) => page._safeGetPomodoroStorage(key, context),
    buildCachedActiveSession: local => page._buildCachedActiveSession(local),
    getActive: path => api.get(path),
    safeRemovePomodoroStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    hasPendingPomodoroAction: (sessionId, actions) => page._hasPendingPomodoroAction(sessionId, actions),
    clearLocalPauseAdjustment: sessionId => page._clearLocalPauseAdjustment(sessionId),
  }
}

function buildPomodoroRunningStateMigratorPageCapabilities(page, deps) {
  return {
    safeGetPomodoroStorage: (key, context) => page._safeGetPomodoroStorage(key, context),
    safeSetPomodoroStorage: (key, value, context) => page._safeSetPomodoroStorage(key, value, context),
    safeRemovePomodoroStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
  }
}

module.exports = {
  buildActiveSyncPageCapabilities,
  buildPendingSyncPageCapabilities,
  buildPendingSyncQueuePageCapabilities,
  buildPomodoroActiveSessionReconcilerPageCapabilities,
  buildPomodoroRunningStateMigratorPageCapabilities,
  buildPomodoroSessionActionDropperPageCapabilities,
  buildResumeErrorPageCapabilities,
  buildSyncRetryPageCapabilities,
  buildTerminalConflictPageCapabilities,
  buildUnknownStartPageCapabilities,
}
