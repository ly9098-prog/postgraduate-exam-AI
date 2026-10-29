function _getTrendAnimationController(page, dependencies) {
const { createTrendAnimationController, getDate, getSetTimeout } = dependencies
    if (!page._trendAnimationController) {
      page._trendAnimationController = createTrendAnimationController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getChartMode: () => page.data.chartMode,
        getTrendCtx: () => page._trendCtx,
        getTrendBarsRect: () => page._trendBarsRect,
        getTrendCanvasNode: () => page._trendCanvasNode,
        getBarAnimationToken: () => page._barAnimationToken,
        incrementBarAnimationToken: () => { page._barAnimationToken = (page._barAnimationToken || 0) + 1; return page._barAnimationToken },
        setBarRafId: id => { page._barRafId = id },
        markBarRenderedOnce: () => { page._barRenderedOnce = true },
        now: () => getDate().now(),
        setTimeout: getSetTimeout(),
        setData: patch => page.setData(patch),
        renderTrendBars: progress => page._renderTrendBars(progress),
      })
    }
    return page._trendAnimationController
  }

function _getChartModeController(page, dependencies) {
const { createChartModeController, getPlatform, getSetTimeout } = dependencies
    if (!page._chartModeController) {
      page._chartModeController = createChartModeController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getChartMode: () => page.data.chartMode,
        isBarMounted: () => !!page.data.barCanvasMounted,
        isBarRenderedOnce: () => !!page._barRenderedOnce,
        incrementBarAnimationToken: () => {
          page._barAnimationToken = (page._barAnimationToken || 0) + 1
        },
        setData: (patch, callback) => page.setData(patch, callback),
        hasNextTick: () => !!getPlatform().nextTick,
        nextTick: callback => getPlatform().nextTick(callback),
        setTimeout: getSetTimeout(),
        initCanvases: callback => page._initCanvases(callback),
        renderPie: (progress, includeLabels) => page._renderPieChart(progress, includeLabels),
        initTrendCanvas: callback => page._initTrendCanvas(callback),
        animateTrendOnly: () => page._animateTrendOnly(),
        renderTrendBars: progress => page._renderTrendBars(progress),
        isFirstMount: () => !page.data.barCanvasMounted,
      })
    }
    return page._chartModeController
  }

function _getDeferredHistoryController(page, dependencies) {
const { createDeferredHistoryController, getClearTimeout, getSetTimeout } = dependencies
    if (!page._deferredHistoryController) {
      page._deferredHistoryController = createDeferredHistoryController({
        getTimer: () => page._deferredHistoryTimer,
        setTimer: timer => { page._deferredHistoryTimer = timer },
        getPending: () => page._pendingHistoryCommit,
        setPending: value => { page._pendingHistoryCommit = value },
        clearTimeout: getClearTimeout(),
        setTimeout: getSetTimeout(),
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getRequestId: () => page._requestId,
        getDateRequestSeq: () => page._dateRequestSeq,
        getSelectedDate: () => page.data.selectedDate,
        formatSession: item => page._formatSession(item),
        setData: patch => page.setData(patch),
      })
    }
    return page._deferredHistoryController
  }

function _getDurationAnimationController(page, dependencies) {
const { createDurationAnimationController, getClearTimeout, getSetTimeout } = dependencies
    if (!page._durationAnimationController) {
      page._durationAnimationController = createDurationAnimationController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getToken: () => page._durationAnimationToken,
        incrementToken: () => { page._durationAnimationToken = (page._durationAnimationToken || 0) + 1 },
        getTimer: () => page._durationAnimationTimer,
        setTimer: timer => { page._durationAnimationTimer = timer },
        clearTimeout: getClearTimeout(),
        setTimeout: getSetTimeout(),
        getDisplaySessions: () => page.data._dispTodaySessions,
        setDisplayDurationSec: value => { page._displayTodayDurationSec = value },
        getDurationDisplayPatch: text => page._getTodayDurationDisplayPatch(text),
        setData: patch => page.setData(patch),
      })
    }
    return page._durationAnimationController
  }

function _getPieAnimationController(page, dependencies) {
const { createPieAnimationController, getDate, getSetTimeout } = dependencies
    if (!page._pieAnimationController) {
      page._pieAnimationController = createPieAnimationController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getPieCtx: () => page._pieCtx,
        getPieRect: () => page._pieRect,
        getPieCanvasNode: () => page._pieCanvasNode,
        getPieAnimationToken: () => page._pieAnimationToken,
        incrementPieAnimationToken: () => { page._pieAnimationToken = (page._pieAnimationToken || 0) + 1; return page._pieAnimationToken },
        incrementPieLabelToken: () => { page._pieLabelToken = (page._pieLabelToken || 0) + 1 },
        setPieDateRafId: id => { page._pieDateRafId = id },
        now: () => getDate().now(),
        setTimeout: getSetTimeout(),
        renderPie: (progress, includeLabels) => page._renderPieChart(progress, includeLabels),
        revealPieLabelsIncrementally: () => page._revealPieLabelsIncrementally(),
      })
    }
    return page._pieAnimationController
  }

function _getPieLabelRevealController(page, dependencies) {
const { createPieLabelRevealController, getSetTimeout } = dependencies
    if (!page._pieLabelRevealController) {
      page._pieLabelRevealController = createPieLabelRevealController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getPieCtx: () => page._pieCtx,
        getPieRect: () => page._pieRect,
        getPieCanvasNode: () => page._pieCanvasNode,
        getLabelLayout: () => page._pieRenderCache.labelLayout,
        getPieLabelToken: () => page._pieLabelToken,
        incrementPieLabelToken: () => { page._pieLabelToken = (page._pieLabelToken || 0) + 1; return page._pieLabelToken },
        setPieLabelRafId: id => { page._pieLabelRafId = id },
        getGeometry: rect => page._getPieGeometry(rect),
        setTimeout: getSetTimeout(),
        drawPieLabels: (ctx, geometry, layout, reveal, start, end) => page._drawPieLabels(ctx, geometry, layout, reveal, start, end),
      })
    }
    return page._pieLabelRevealController
  }

function _getStartAnimationsController(page, dependencies) {
const { createStartAnimationsController, getDate, getSetTimeout } = dependencies
    if (!page._startAnimationsController) {
      page._startAnimationsController = createStartAnimationsController({
        isAlive: () => page._alive,
        isVisible: () => page._isVisible,
        getRequestId: () => page._requestId,
        getChartMode: () => page.data.chartMode,
        getTodaySessions: () => page.data.todaySessions,
        getRawTodayDurationSec: () => page._rawTodayDur,
        getAnimActive: () => page._animActive,
        getFinalDrawn: () => page._finalDrawn,
        getPieCanvasNode: () => page._pieCanvasNode,
        setAnimActive: value => { page._animActive = value },
        setFinalDrawn: value => { page._finalDrawn = value },
        setDisplayDurationSec: value => { page._displayTodayDurationSec = value },
        setAnimTimer: timer => { page._animTimer = timer },
        setRafId: id => { page._rafId = id },
        incrementPieLabelToken: () => { page._pieLabelToken = (page._pieLabelToken || 0) + 1 },
        now: () => getDate().now(),
        setTimeout: getSetTimeout(),
        setData: patch => page.setData(patch),
        getDurationDisplayPatch: text => page._getTodayDurationDisplayPatch(text),
        formatMin: sec => page._fmtMin(sec),
        renderPie: (progress, includeLabels) => page._renderPieChart(progress, includeLabels),
        revealPieLabelsIncrementally: () => page._revealPieLabelsIncrementally(),
      })
    }
    return page._startAnimationsController
  }

module.exports = { _getTrendAnimationController, _getChartModeController, _getDeferredHistoryController, _getDurationAnimationController, _getPieAnimationController, _getPieLabelRevealController, _getStartAnimationsController }
