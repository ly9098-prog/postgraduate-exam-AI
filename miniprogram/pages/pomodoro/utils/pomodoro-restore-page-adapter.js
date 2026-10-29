// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { FREE_TIMER_MAX_MS, PHASE, parseServerTime } = require('./pomodoro-page-support')
const { pomodoroTaskTypes } = require('../../../utils/storage')
const { computeCountdownRestore, computeFreeRestore, resolvePausedMs, resolveRestoredSubject } = require('./session-restore')
const { formatCountdownDisplay, formatElapsedSec } = require('./timer-math')

function buildCountdownSessionRestorePageCapabilities(page, deps) {
  const { api } = deps
  return {
    page,
    now: () => api.now(),
    parseServerTime,
    resolvePausedMs,
    computeCountdownRestore,
    resolveRestoredSubject,
    formatCountdownDisplay,
    runningPhase: PHASE.RUNNING,
    pomodoroTaskTypes,
    nextTick: callback => wx.nextTick(callback),
    vibrateLong: () => wx.vibrateLong(),
    showToast: payload => wx.showToast(payload),
  }
}

function buildFreeSessionRestorePageCapabilities(page, deps) {
  const { api } = deps
  return {
    page,
    now: () => api.now(),
    parseServerTime,
    resolvePausedMs,
    computeFreeRestore,
    resolveRestoredSubject,
    formatElapsedSec,
    maxMs: FREE_TIMER_MAX_MS,
    runningPhase: PHASE.RUNNING,
    pomodoroTaskTypes,
    nextTick: callback => wx.nextTick(callback),
  }
}

module.exports = {
  buildCountdownSessionRestorePageCapabilities,
  buildFreeSessionRestorePageCapabilities,
}
