function buildDateCommitPageCapabilities(page) {
  return {
    isAlive: () => page._alive,
    isVisible: () => page._isVisible,
    getDateRequestSeq: () => page._dateRequestSeq,
    setRawTodayDuration: value => { page._rawTodayDur = value },
    setDaySubjectsRaw: subjects => { page._daySubjectsRaw = subjects },
    resetPieCache: () => page._resetPieCache(),
    setData: (patch, callback) => page.setData(patch, callback),
    animateSelectedDuration: (fromSec, toSec, fromSessions, toSessions) => {
      page._animateSelectedDuration(fromSec, toSec, fromSessions, toSessions)
    },
    getDistributionPeriod: () => page.data.distributionPeriod,
    loadDistributionForPeriod: (period, animate) => {
      page._loadDistributionForPeriod(period, animate)
    },
    getChartMode: () => page.data.chartMode,
    isPieReady: () => !!(page._pieCtx && page._pieRect),
    initCanvases: callback => page._initCanvases(callback),
    animatePieOnly: () => page._animatePieOnly(),
  }
}

module.exports = {
  buildDateCommitPageCapabilities,
}
