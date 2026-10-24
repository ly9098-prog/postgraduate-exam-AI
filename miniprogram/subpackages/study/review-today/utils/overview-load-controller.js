function createOverviewLoadController(options) {
  return {
    load: () => loadImpl(options),
    refreshSilently: () => refreshSilentlyImpl(options),
  }
}

async function loadImpl(options) {
  const requestSeq = options.nextRequestSeq()
  options.setOverviewLoading(true)
  options.setData({ phase: 'loading', isStarting: false, isContinuing: false })
  try {
    const overview = await options.getOverview()
    if (!options.isPageAlive() || !options.isRequestCurrent(requestSeq)) return
    const vm = options.buildOverviewVM(overview)
    options.applyOverviewToSession(overview, vm)
    const targetPhase = vm.todayRemainingCount > 0 ? 'overview' : 'empty'
    const shouldAutoStart = options.isAutoStartPending() && targetPhase === 'overview'
    if (targetPhase === 'empty') options.setAutoStartPending(false)
    options.setOverviewLoading(false)
    options.setData({
      ...vm,
      phase: targetPhase,
    }, () => {
      if (shouldAutoStart && options.isPageAlive() && options.isRequestCurrent(requestSeq)) {
        options.setAutoStartPending(false)
        options.startReview()
      }
    })
  } catch (error) {
    if (!options.isPageAlive() || !options.isRequestCurrent(requestSeq)) return
    options.logError('加载复习概览失败', error)
    options.setOverviewLoading(false)
    options.setData({
      phase: 'error',
      errorText: '复习计划加载失败，请稍后重试',
    })
  }
}

async function refreshSilentlyImpl(options) {
  const requestSeq = options.nextRequestSeq()
  try {
    const overview = await options.getOverview()
    if (!options.isPageAlive() || !options.isRequestCurrent(requestSeq)) return
    const vm = options.buildOverviewVM(overview)
    options.applyOverviewToSession(overview, vm)
    options.adjustVmForActiveSession(vm)
    options.setData({ ...vm })
  } catch (error) {
    if (!options.isPageAlive() || !options.isRequestCurrent(requestSeq)) return
    options.logError('刷新复习概览失败', error)
  }
}

module.exports = {
  createOverviewLoadController,
}
