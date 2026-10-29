// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { FREE_TIMER_MAX_MS, PHASE, POMODORO_PAUSE_TOGGLE_COOLDOWN_MS, parseServerTime } = require('./pomodoro-page-support')
const { pomodoroTaskTypes } = require('../../../utils/storage')
const { readSubjectCache, writeSubjectCache } = require('./subject-cache')
const { buildSubjectChoices } = require('./subject-options')
const { filter408SubjectTree } = require('./subject-scope')
const { formatElapsedSec } = require('./timer-math')

function buildSubjectLoadPageCapabilities(page, deps) {
  const { api } = deps
  return {
    readSubjectCache,
    fetchSubjects: () => api.get('/practice/subjects'),
    filterSubjectTree: filter408SubjectTree,
    buildSubjectChoices,
    writeSubjectCache,
    applySubjects: flat => page._applySubjects(flat),
    setSubjectsState: patch => page.setData(patch),
    logError: (message, error) => console.error(message, error),
  }
}

function buildStartSessionPageCapabilities(page, deps) {
  return {
    page,
    phases: PHASE,
    ceremonyDelayMs: 2500,
    debugCeremonyDelayMs: 1000,
    wait: ms => new Promise(resolve => setTimeout(resolve, ms)),
    showToast: payload => wx.showToast(payload),
    pomodoroTaskTypes,
  }
}

function buildFreeTimerBeginPageCapabilities(page, deps) {
  const { api } = deps
  return {
    parseServerTime,
    now: () => api.now(),
    maxMs: FREE_TIMER_MAX_MS,
    formatElapsedSec,
    clearTimer: () => page._clearTimer(),
    timer: () => page._timerState,
    runningPhase: PHASE.RUNNING,
    setData: data => page.setData(data),
    updateComputedFields: () => page._updateComputedFields(),
    autoFinishFreeTimer: () => page._autoFinishFreeTimer(),
    startFreeTimerInterval: () => page._startFreeTimerInterval(),
    nextTick: callback => wx.nextTick(callback),
    initCanvas: force => page._initCanvas(force),
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
  }
}

function buildBeginCountdownPageCapabilities(page, deps) {
  const { api } = deps
  return {
    parseServerTime,
    isDebugPreset: () => page.data.selectedPreset === 'debug',
    getWorkDurationMinutes: () => page.data.workDuration,
    now: () => api.now(),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    runningPhase: () => PHASE.RUNNING,
    setData: data => page.setData(data),
    updateComputedFields: () => page._updateComputedFields(),
    onWorkComplete: () => page._onWorkComplete(),
    startTimer: (totalSec, opts) => page._startTimer(totalSec, opts),
  }
}

function buildPauseTogglePageCapabilities(page, deps) {
  return {
    cooldownMs: POMODORO_PAUSE_TOGGLE_COOLDOWN_MS,
    setTimeout: (callback, delay) => setTimeout(callback, delay),
    clearTimeout: id => clearTimeout(id),
    phase: () => page.data.phase,
    runningPhase: PHASE.RUNNING,
    sessionId: () => page._timerState.sessionId,
    actionLoading: () => page.data.actionLoading,
    showEndConfirm: () => page.data.showEndConfirm,
    isFreeTimer: () => page.data.isFreeTimer,
    isPaused: () => page.data.isPaused,
    pauseFree: () => page._pauseFreeTimer(),
    resumeFree: () => page._resumeFreeTimer(),
    pauseCountdown: () => page._pauseSession(),
    resumeCountdown: () => page._resumeSession(),
  }
}

function buildStartTimerPageCapabilities(page, deps) {
  const { api } = deps
  return {
    clearTimer: () => page._clearTimer(),
    initCanvas: force => page._initCanvas(force),
    setTimeout: (fn, delay) => setTimeout(fn, delay),
    clearTimeout: timer => clearTimeout(timer),
    clearInterval: timer => clearInterval(timer),
    setTimerController: controller => { page._timerController = controller },
    getRemainingSec: () => page._timerState.remainingSec,
    formatCountdownDisplay: sec => page._formatCountdownDisplay(sec),
    now: () => api.now(),
    setCountdownTotalSec: value => { page._countdownTotalSec = value },
    setCountdownEndAt: value => { page._countdownEndAt = value },
    setTimerFields: patch => Object.assign(page._timerState, patch),
    setData: data => page.setData(data),
    isPaused: () => page.data.isPaused,
    showEndConfirm: () => page.data.showEndConfirm,
    getCountdownEndAt: () => page._countdownEndAt,
    getProgress: () => page._timerState.progress,
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
    isBreakPhase: () => page.data.phase === 'break',
    onWorkComplete: () => page._onWorkComplete(),
  }
}

function buildStartBreakPageCapabilities(page, deps) {
  const { api } = deps
  return {
    now: () => api.now(),
    safeSetStorage: (key, value) => page._safeSetPomodoroStorage(key, value, 'break snapshot'),
    safeRemoveStorage: key => page._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
    setTimerFields: patch => Object.assign(page._timerState, patch),
    formatCountdownDisplay: sec => page._formatCountdownDisplay(sec),
    breakPhase: () => PHASE.BREAK,
    setData: data => page.setData(data),
    clearTimer: () => page._clearTimer(),
    initCanvas: force => page._initCanvas(force),
    setCountdownTotalSec: value => { page._countdownTotalSec = value },
    setCountdownEndAt: value => { page._countdownEndAt = value },
    getCountdownEndAt: () => page._countdownEndAt,
    getRemainingSec: () => page._timerState.remainingSec,
    getProgress: () => page._timerState.progress,
    drawRing: (total, isBreak) => page.drawRing(total, isBreak),
    resetToIdle: () => page._resetToIdle(),
    getTimerController: () => page._timerController,
    setTimerController: controller => { page._timerController = controller },
    setTimeout: (fn, delay) => setTimeout(fn, delay),
    clearTimeout: timer => clearTimeout(timer),
    clearInterval: timer => clearInterval(timer),
  }
}

function buildSkipBreakPageCapabilities(page, deps) {
  return {
    clearTimer: () => page._clearTimer(),
    removeStorage: (key, context) => page._safeRemovePomodoroStorage(key, context),
    resetIdle: () => page._resetToIdle(),
  }
}

module.exports = {
  buildBeginCountdownPageCapabilities,
  buildFreeTimerBeginPageCapabilities,
  buildPauseTogglePageCapabilities,
  buildSkipBreakPageCapabilities,
  buildStartBreakPageCapabilities,
  buildStartSessionPageCapabilities,
  buildStartTimerPageCapabilities,
  buildSubjectLoadPageCapabilities,
}
