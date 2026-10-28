function buildStatsCanvasInitPageCapabilities(page, dependencies) {
  const { wx } = dependencies
  return {
    isAlive: () => page._alive,
    getPage: () => page,
    createQuery: () => wx.createSelectorQuery(),
    getWindowInfo: () => (wx.getWindowInfo ? wx.getWindowInfo() : {}),
    pieSelector: () => '#pie-canvas',
    trendSelector: () => '#trend-bars-canvas',
    isPieReady: () => !!(page._pieCanvasNode && page._pieCtx && page._pieRect),
    isPiePending: () => !!page._canvasInitPending,
    setPiePending: value => { page._canvasInitPending = value },
    getPieCallbacks: () => page._canvasInitCallbacks,
    setPieCallbacks: value => { page._canvasInitCallbacks = value },
    addPieCallback: callback => page._canvasInitCallbacks.push(callback),
    commitPie: value => {
      page._pieCanvasNode = value.node
      page._pieCtx = value.ctx
      page._pieRect = value.rect
      page._pieDpr = value.dpr
    },
    isTrendMounted: () => !!page.data.barCanvasMounted,
    isTrendReady: () => !!(page._trendCanvasNode && page._trendCtx && page._trendBarsRect),
    isTrendPending: () => !!page._barInitPending,
    setTrendPending: value => { page._barInitPending = value },
    getTrendCallbacks: () => page._barInitCallbacks,
    setTrendCallbacks: value => { page._barInitCallbacks = value },
    addTrendCallback: callback => page._barInitCallbacks.push(callback),
    commitTrend: value => {
      page._trendCanvasNode = value.node
      page._trendCtx = value.ctx
      page._trendBarsRect = value.rect
    },
  }
}

module.exports = {
  buildStatsCanvasInitPageCapabilities,
}
