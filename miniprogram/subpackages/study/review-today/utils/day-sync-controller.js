function createReviewDaySyncController(options) {
  return {
    syncIfNeeded: () => syncIfNeededImpl(options),
  }
}

async function syncIfNeededImpl(options) {
  if (options.isSameDay()) return true
  try {
    const overview = await options.getOverview()
    if (!options.isPageAlive()) return false
    const vm = options.buildOverviewVM(overview || {})
    options.applyOverviewWithDayReset(overview, vm)
    options.setDateStr()
    options.setData({ ...vm })
    options.showSuccessToast()
    return true
  } catch (error) {
    if (!options.isPageAlive()) return false
    options.logError('跨天同步复习进度失败', error)
    options.showFailureToast()
    return false
  }
}

module.exports = {
  createReviewDaySyncController,
}
