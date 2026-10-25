function createLoadCommitController(options) {
  const renderPieAfterCommit = context => renderPieAfterCommitImpl(options, context)
  return {
    commit: (viewState, context) => commitImpl(options, renderPieAfterCommit, viewState, context),
  }
}

function renderPieAfterCommitImpl(options, context) {
  options.initCanvases(() => {
    if (!options.isAlive() || !options.isVisible() || options.getChartMode() !== 'pie') return
    if (!context.willAnimate) {
      options.renderPie(1, true)
      return
    }
    options.renderPie(0, false)
    const node = options.getPieCanvasNode()
    const raf = node && node.requestAnimationFrame
      ? callback => node.requestAnimationFrame(callback)
      : callback => options.setTimeout(callback, 16)
    const animationRequestId = options.getRequestId()
    raf(() => raf(() => options.startAnimations(animationRequestId)))
  })
}

function commitImpl(options, renderPieAfterCommit, viewState, context) {
  options.setDisplayTodayDurationSec(context.willAnimate ? 0 : viewState.selectedDurationSec)
  options.setDaySubjectsRaw(viewState.subjectBreakdown)
  options.setRawTodayDuration(viewState.selectedDurationSec)
  options.setRawWeekDuration(context.weekDurationSec)
  options.setData(viewState.dataPatch, () =>
    commitCallback(options, renderPieAfterCommit, viewState, context)
  )
}

function commitCallback(options, renderPieAfterCommit, viewState, context) {
  if (!options.isAlive() || !options.isVisible() || context.reqId !== options.getRequestId()) return
  if (context.willAnimate) {
    options.queueDeferredHistory(
      context.reqId, context.dateSeq, context.effectiveDate, viewState.daySessions,
      context.historyTotal || (context.effectiveHistory && context.effectiveHistory.total) || 0
    )
  }
  const cumulativeStartDate = options.getCumulativeStartDate()
  if (options.isCumulativeCustomized() && cumulativeStartDate) {
    options.refreshCumulativeSummary(cumulativeStartDate, true)
  }
  if (!context.displayDaySubjects) {
    // Week/month/custom distributions follow the new daily anchor.
    options.loadDistributionForPeriod(options.getDistributionPeriod(), !context.willAnimate)
  } else if (options.isBarMounted()) {
    // This branch can only run after the user has explicitly mounted the bar.
    options.initTrendCanvas(() => options.renderTrendBars(1))
  } else if (options.getChartMode() === 'pie') {
    renderPieAfterCommit(context)
  }
}

module.exports = {
  createLoadCommitController,
}
