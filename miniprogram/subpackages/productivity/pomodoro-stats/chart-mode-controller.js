function createChartModeController(options) {
  const schedule = callback => {
    if (options.hasNextTick()) options.nextTick(callback)
    else options.setTimeout(callback, 0)
  }

  const drawPie = () => {
    if (!options.isAlive() || !options.isVisible() || options.getChartMode() !== 'pie') return
    options.initCanvases(() => options.renderPie(1, true))
  }

  const drawBar = () => {
    if (!options.isAlive() || !options.isVisible() || options.getChartMode() !== 'bar') return
    options.initTrendCanvas(() => {
      if (!options.isAlive() || !options.isVisible() || options.getChartMode() !== 'bar') return
      if (options.isFirstMount() || !options.isBarRenderedOnce()) options.animateTrendOnly()
      else options.renderTrendBars(1)
    })
  }

  return {
    toggle() {
      if (options.getChartMode() === 'bar') {
        options.incrementBarAnimationToken()
        options.setData({ chartMode: 'pie', barRendering: false }, () => schedule(drawPie))
        return
      }

      const firstMount = !options.isBarMounted()
      options.setData({
        chartMode: 'bar',
        barCanvasMounted: true,
        barRendering: firstMount || !options.isBarRenderedOnce(),
        selectedSubjectDetail: null,
        _selectedSubject: null,
      }, () => schedule(() => drawBar(firstMount)))
    },
  }
}

module.exports = {
  createChartModeController,
}
