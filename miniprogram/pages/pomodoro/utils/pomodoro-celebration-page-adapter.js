// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { MOTTOES } = require('./pomodoro-page-support')
const { pomodoroTaskTypes } = require('../../../utils/storage')
const { resolveBreakSec } = require('./celebration-dismiss')
const { buildCompletionCelebration } = require('./completion-celebration')

function buildCompletionCelebrationPageCapabilities(page, deps) {
  return {
    buildCompletionCelebration,
    data: () => page.data,
    mottoes: MOTTOES,
    nextCelebrationType: () => page._nextCelebrationType(),
    recordSession: (session, taskType) => pomodoroTaskTypes.recordSession(session, taskType),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    setStorage: (key, value, context) => page._safeSetPomodoroStorage(key, value, context),
    clearConfirmSnapshot: () => { page._confirmTimerSnapshot = null },
    timer: () => page._timerState,
    setCompletionBreakSec: value => { page._completionBreakSec = value },
    invalidateCanvas: () => {
      page._canvasInitSeq = (page._canvasInitSeq || 0) + 1
      page._canvasInitPending = false
      page._canvasReady = false
      page._ctx = null
      page._ringCache = null
      page._pendingDraw = null
    },
    setData: data => page.setData(data),
  }
}

function buildWorkCompletePageCapabilities(page, deps) {
  const { api } = deps
  return {
    timer: () => page._timerState,
    resetIdle: () => page._resetToIdle(),
    now: () => api.now(),
    clearTimer: () => page._clearTimer(),
    vibrateLong: () => wx.vibrateLong(),
    completeWithRetry: (sessionId, completedAt) => page._completePomodoroWithRetry(sessionId, completedAt),
    consumeTerminalConflict: (sessionId, action) => page._consumePomodoroTerminalConflict(sessionId, action),
    handleTerminalConflict: (sessionId, conflict) => page._handlePomodoroTerminalConflict(sessionId, conflict),
    loadStats: () => page.loadTodayStats(),
    showToast: toast => wx.showToast(toast),
    showCompletionCelebration: sessionId => page._showCompletionCelebration(sessionId),
  }
}

function buildCelebrationDismissPageCapabilities(page, deps) {
  return {
    getStorage: (key, context) => page._safeGetPomodoroStorage(key, context),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    resolveBreakSec,
    getCompletionBreakSec: () => page._completionBreakSec,
    setCompletionBreakSec: value => { page._completionBreakSec = value },
    view: () => page.data,
    setData: data => page.setData(data),
    persistenceError: () => page._showPomodoroPersistenceError(),
    startBreak: breakSec => page._startBreak(breakSec),
    resetIdle: () => page._resetToIdle(),
  }
}

function buildBreakRestorePageCapabilities(page, deps) {
  const { api } = deps
  return {
    getStorageSync: key => wx.getStorageSync(key),
    now: () => api.now(),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    resetIdle: () => page._resetToIdle(),
    startBreak: (totalSec, breakOptions) => page._startBreak(totalSec, breakOptions),
  }
}

function buildCelebrationTypePageCapabilities(page, deps) {
  return {
    getIndex: () => wx.getStorageSync('pomodoro_anim_idx'),
    setIndex: value => wx.setStorageSync('pomodoro_anim_idx', value),
  }
}

module.exports = {
  buildBreakRestorePageCapabilities,
  buildCelebrationDismissPageCapabilities,
  buildCelebrationTypePageCapabilities,
  buildCompletionCelebrationPageCapabilities,
  buildWorkCompletePageCapabilities,
}
