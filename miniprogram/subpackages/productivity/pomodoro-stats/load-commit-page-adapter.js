function buildLoadCommitPageCapabilities(page) {
  return {
    isAlive: () => page._alive,
    isVisible: () => page._isVisible,
    getRequestId: () => page._requestId,
    setDisplayTodayDurationSec: value => { page._displayTodayDurationSec = value },
    setDaySubjectsRaw: subjects => { page._daySubjectsRaw = subjects },
    setRawTodayDuration: value => { page._rawTodayDur = value },
    setRawWeekDuration: value => { page._rawWeekDur = value },
    setData: (patch, callback) => page.setData(patch, callback),
    queueDeferredHistory: (reqId, dateSeq, selectedDate, sessions, total) => {
      page._queueDeferredHistory(reqId, dateSeq, selectedDate, sessions, total)
    },
    isCumulativeCustomized: () => page._cumulativeCustomized,
    getCumulativeStartDate: () => page.data.cumulativeStartDate,
    refreshCumulativeSummary: (startDate, silent) => {
      page._refreshCumulativeSummary(startDate, silent)
    },
    getDistributionPeriod: () => page.data.distributionPeriod,
    loadDistributionForPeriod: (period, animate) => {
      page._loadDistributionForPeriod(period, animate)
    },
    getChartMode: () => page.data.chartMode,
    initCanvases: callback => page._initCanvases(callback),
    renderPie: (progress, includeLabels) => page._renderPieChart(progress, includeLabels),
    getPieCanvasNode: () => page._pieCanvasNode,
    setTimeout,
    startAnimations: reqId => page._startAnimations(reqId),
    isBarMounted: () => !!page.data.barCanvasMounted,
    initTrendCanvas: callback => page._initTrendCanvas(callback),
    renderTrendBars: progress => page._renderTrendBars(progress),
  }
}

module.exports = {
  buildLoadCommitPageCapabilities,
}
