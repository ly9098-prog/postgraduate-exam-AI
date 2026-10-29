// Page capability assembly for miniprogram/pages/pomodoro/pomodoro.js.
// Capability objects are frozen here; the page keeps lazy controller memoisation.

const { PHASE, PRESETS } = require('./pomodoro-page-support')
const { getChinaDayStartUtcMs, getChinaWallParts } = require('../../../utils/china-time')
const { CANVAS_INIT_MAX_RETRIES } = require('./canvas-layout')
const pomodoroTheme = require('./pomodoro-theme')

function buildCanvasInitPageCapabilities(page, deps) {
  return {
    canvasReady: () => page._canvasReady,
    getCtx: () => page._ctx,
    canvasInitPending: () => page._canvasInitPending,
    getCanvasInitSeq: () => page._canvasInitSeq,
    setCanvasInitSeq: value => { page._canvasInitSeq = value },
    setCanvasInitPending: value => { page._canvasInitPending = value },
    setCanvasReady: value => { page._canvasReady = value },
    setCtx: value => { page._ctx = value },
    setRingCache: value => { page._ringCache = value },
    ringCanvasPaintReady: () => page.data.ringCanvasPaintReady,
    setData: data => page.setData(data),
    setLastDrawnProgress: value => { page._lastDrawnProgress = value },
    setLastDrawnIsBreak: value => { page._lastDrawnIsBreak = value },
    setLastDrawnAt: value => { page._lastDrawnAt = value },
    maxRetries: () => CANVAS_INIT_MAX_RETRIES,
    nextTick: fn => wx.nextTick(fn),
    isPageVisible: () => page._pageVisible,
    createSelectorQuery: () => wx.createSelectorQuery().in(page),
    setTimeout: (fn, delay) => setTimeout(fn, delay),
    getWindowInfo: () => (wx.getWindowInfo ? wx.getWindowInfo() : {}),
    setDpr: value => { page._dpr = value },
    setCanvasSize: value => { page._canvasSize = value },
    getPendingDraw: () => page._pendingDraw,
    setPendingDraw: value => { page._pendingDraw = value },
    drawRing: (totalSec, isBreak) => page.drawRing(totalSec, isBreak),
  }
}

function buildDrawRingPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getCtx: () => page._ctx,
    setPendingDraw: value => { page._pendingDraw = value },
    isPageVisible: () => page._pageVisible,
    showEndConfirm: () => page.data.showEndConfirm,
    ringCanvasVisible: () => page.data.ringCanvasVisible,
    canvasInitPending: () => page._canvasInitPending,
    initCanvas: force => page._initCanvas(force),
    getProgress: () => page._timerState.progress,
    now: () => api.now(),
    getLastDrawnProgress: () => page._lastDrawnProgress,
    getLastDrawnIsBreak: () => page._lastDrawnIsBreak,
    getLastDrawnAt: () => page._lastDrawnAt,
    setLastDrawnProgress: v => { page._lastDrawnProgress = v },
    setLastDrawnIsBreak: v => { page._lastDrawnIsBreak = v },
    setLastDrawnAt: v => { page._lastDrawnAt = v },
    isFreeTimer: () => page.data.isFreeTimer,
    themeMode: () => page.data.themeMode,
    getRingCache: () => page._ringCache,
    setRingCache: v => { page._ringCache = v },
    buildRingCache: isBreak => page._buildRingCache(isBreak),
    ringCanvasPaintReady: () => page.data.ringCanvasPaintReady,
    setData: data => page.setData(data),
  }
}

function buildStatsPageCapabilities(page, deps) {
  const { api } = deps
  return {
    get: path => api.get(path),
    setTodayDurationSec: value => { page._timerState.todayDurationSec = value },
    setData: data => page.setData(data),
  }
}

function buildThemePageCapabilities(page, deps) {
  return {
    normalizeTheme: mode => pomodoroTheme.normalizeTheme(mode),
    getTheme: () => pomodoroTheme.getTheme(),
    setTheme: value => pomodoroTheme.setTheme(value),
    applyNativeTheme: value => pomodoroTheme.applyNativeTheme(value),
    getCurrentMode: () => page.data.themeMode,
    setData: (data, callback) => page.setData(data, callback),
    setTimeout: (callback, delay) => setTimeout(callback, delay),
    clearTimeout: id => clearTimeout(id),
    afterThemeApplied: () => {
      page._ringCache = null
      page._lastDrawnProgress = undefined
      page._lastDrawnIsBreak = undefined
      if ((page.data.phase === PHASE.RUNNING || page.data.phase === PHASE.BREAK) &&
          page.data.ringCanvasVisible && !page.data.showEndConfirm) {
        wx.nextTick(() => page.drawRing(page._getCurrentTotalSec(), page.data.phase === PHASE.BREAK))
      }
    },
  }
}

function buildFontSizePageCapabilities(page, deps) {
  return {
    getCurrentLevel: () => page.data.fontSizeLevel,
    setLevel: value => page.setData({ fontSizeLevel: value }),
    persist: value => wx.setStorageSync('pomodoro_font_size', value),
  }
}

function buildSubjectViewPageCapabilities(page, deps) {
  return {
    getSubjects: () => page.data.subjects,
  }
}

function buildPresetViewPageCapabilities(page, deps) {
  return {
    getPresets: () => PRESETS,
  }
}

function buildDateExamPageCapabilities(page, deps) {
  const { api } = deps
  return {
    now: () => api.now(),
    getChinaWallParts,
    getChinaDayStartUtcMs,
    utc: parts => Date.UTC(parts.year, parts.month, parts.day),
    getUtcDay: ms => new Date(ms).getUTCDay(),
  }
}

module.exports = {
  buildCanvasInitPageCapabilities,
  buildDateExamPageCapabilities,
  buildDrawRingPageCapabilities,
  buildFontSizePageCapabilities,
  buildPresetViewPageCapabilities,
  buildStatsPageCapabilities,
  buildSubjectViewPageCapabilities,
  buildThemePageCapabilities,
}
