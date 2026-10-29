function _getCancelWorkController(page, dependencies) {
const { createCancelWorkController, getClearTimeout } = dependencies
    if (!page._cancelWorkController) {
      page._cancelWorkController = createCancelWorkController({
        clearDynamicRefresh: () => page._clearDynamicRefresh(),
        cancelDurationAnimation: resetState => page._cancelDurationAnimation(resetState),
        cancelDeferredHistory: clearPending => page._cancelDeferredHistory(clearPending),
        setAnimActive: value => { page._animActive = value },
        setFinalDrawn: value => { page._finalDrawn = value },
        incrementRequestId: () => { page._requestId++ },
        getMainRafId: () => page._rafId,
        getPieDateRafId: () => page._pieDateRafId,
        getPieLabelRafId: () => page._pieLabelRafId,
        getBarRafId: () => page._barRafId,
        getPieCanvasNode: () => page._pieCanvasNode,
        getTrendCanvasNode: () => page._trendCanvasNode,
        cancelFrame: (id, node) => {
          if (id && node && node.cancelAnimationFrame) node.cancelAnimationFrame(id)
        },
        setMainRafId: id => { page._rafId = id },
        setPieDateRafId: id => { page._pieDateRafId = id },
        setPieLabelRafId: id => { page._pieLabelRafId = id },
        setBarRafId: id => { page._barRafId = id },
        incrementPieAnimationToken: () => { page._pieAnimationToken = (page._pieAnimationToken || 0) + 1 },
        incrementPieLabelToken: () => { page._pieLabelToken = (page._pieLabelToken || 0) + 1 },
        incrementBarAnimationToken: () => { page._barAnimationToken = (page._barAnimationToken || 0) + 1 },
        clearAnimTimer: () => {
          if (page._animTimer) {
            getClearTimeout()(page._animTimer)
            page._animTimer = null
          }
        },
      })
    }
    return page._cancelWorkController
  }

function _getStatsCanvasInitController(page, dependencies) {
const { buildStatsCanvasInitPageCapabilities, createStatsCanvasInitController, getPlatform } = dependencies
    if (!page._statsCanvasInitController) {
      page._statsCanvasInitController = createStatsCanvasInitController(
        buildStatsCanvasInitPageCapabilities(page, { wx: getPlatform() })
      )
    }
    return page._statsCanvasInitController
  }

function _getPieTapController(page, dependencies) {
const { createPieTapController, getPlatform, getSetTimeout } = dependencies
    if (!page._pieTapController) {
      page._pieTapController = createPieTapController({
        isAlive: () => page._alive,
        hasDistributionData: () => page.data.distributionHasData,
        getSubjects: () => page.data.subjects,
        getSelectedSubjectDetail: () => page.data.selectedSubjectDetail,
        getGeometry: rect => page._getPieGeometry(rect),
        createSelectorQuery: () => getPlatform().createSelectorQuery().in(page),
        setData: (patch, callback) => page.setData(patch, callback),
        renderPie: progress => page._renderPieChart(progress),
        setTimeout: getSetTimeout(),
      })
    }
    return page._pieTapController
  }

function _getCloseDetailController(page, dependencies) {
const { createCloseDetailController } = dependencies
    if (!page._closeDetailController) {
      page._closeDetailController = createCloseDetailController({
        isAlive: () => page._alive,
        setData: (patch, callback) => page.setData(patch, callback),
        renderPie: progress => page._renderPieChart(progress),
      })
    }
    return page._closeDetailController
  }

function _renderPieChart(page, progress, includeLabels = true, dependencies) {
const { buildPieRenderCapabilities, pieRenderer } = dependencies
    pieRenderer.renderPieChart({
      ...buildPieRenderCapabilities({
        getCtx: () => page._pieCtx,
        getRect: () => page._pieRect,
        getSubjects: () => page.data.subjects,
        getThemeMode: () => page.data.themeMode,
        getDpr: () => page._pieDpr,
        getSelectedSubject: () => page.data._selectedSubject,
        getCache: () => page._pieRenderCache,
        getPalette: () => page._getCanvasPalette(),
        getShade: () => (hex, amount) => page._shadeColorCached(hex, amount),
      }),
      progress,
      includeLabels,
    })
  }

function _renderTrendBars(page, progress, dependencies) {
const { trendChart } = dependencies
    trendChart.renderTrendBars(page._trendCtx, {
      trends: page.data.trends,
      rect: page._trendBarsRect,
      progress,
      themeMode: page.data.themeMode,
      palette: page._getCanvasPalette(),
    })
  }

function _resetPieCache(page) {
    page._pieRenderCache = { sectors: null, wallSteps: null, labelLayout: null }
    if (page._shadeColorCache) page._shadeColorCache.reset()
  }

module.exports = { _getCancelWorkController, _getStatsCanvasInitController, _getPieTapController, _getCloseDetailController, _renderPieChart, _renderTrendBars, _resetPieCache }
