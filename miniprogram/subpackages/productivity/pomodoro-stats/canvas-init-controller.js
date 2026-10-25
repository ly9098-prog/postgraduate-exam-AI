function createStatsCanvasInitController(options) {
  const finishPie = makeFinish(options.setPiePending, options.getPieCallbacks, options.setPieCallbacks)
  const finishTrend = makeFinish(options.setTrendPending, options.getTrendCallbacks, options.setTrendCallbacks)
  return {
    initPie: initPieImpl.bind(null, options, finishPie),
    initTrend: initTrendImpl.bind(null, options, finishTrend),
  }
}

function makeFinish(clearPending, takeCallbacks, setCallbacks) {
  return () => {
    clearPending(false)
    const callbacks = takeCallbacks().slice()
    setCallbacks([])
    callbacks.forEach(callback => callback())
  }
}

function queryCanvas(options, selector, finish, commit) {
  options.createQuery().in(options.getPage())
    .select(selector)
    .fields({ node: true, size: true })
    .exec(result => {
      const info = result && result[0]
      if (!options.isAlive() || !info || !info.node) {
        finish()
        return
      }
      const node = info.node
      const ctx = node.getContext('2d')
      const width = info.width
      const height = info.height
      // Hidden canvases can report a zero-sized node; don't cache that layout.
      if (!width || !height) {
        finish()
        return
      }
      const windowInfo = options.getWindowInfo() || {}
      const dpr = windowInfo.pixelRatio || 2
      node.width = Math.round(width * dpr)
      node.height = Math.round(height * dpr)
      ctx.scale(dpr, dpr)
      commit({ node, ctx, rect: { width, height }, dpr })
      finish()
    })
}

function initPieImpl(options, finishPie, callback) {
  const done = typeof callback === 'function' ? callback : () => {}
  if (options.isPieReady()) { done(); return }
  if (options.isPiePending()) { options.addPieCallback(done); return }
  options.setPiePending(true)
  options.setPieCallbacks([done])
  queryCanvas(options, options.pieSelector(), finishPie, options.commitPie)
}

function initTrendImpl(options, finishTrend, callback) {
  const done = typeof callback === 'function' ? callback : () => {}
  if (!options.isTrendMounted()) { done(); return }
  if (options.isTrendReady()) { done(); return }
  if (options.isTrendPending()) { options.addTrendCallback(done); return }
  options.setTrendPending(true)
  options.setTrendCallbacks([done])
  queryCanvas(options, options.trendSelector(), finishTrend, options.commitTrend)
}

module.exports = {
  createStatsCanvasInitController,
}
