function createNextGroupController(options) {
  const retryGroupController = options.retryGroupController
  const remoteBatchController = options.remoteBatchController

  return {
    async next() {
      options.clearMasterUndo()
      options.clearResultDockFadeTimer()
      if (options.getData().resultTransitioning) return { status: 'busy' }

      const flowSeq = options.nextFlowSeq()
      options.setData({ resultTransitioning: true })
      if (!await options.syncReviewSessionDay()) {
        if (options.isPageAlive() && options.isFlowCurrent(flowSeq)) {
          options.setData({ resultTransitioning: false })
        }
        return { status: 'sync-failed' }
      }

      const nextGroupIdx = options.getCurrentGroupIdx() + 1
      if (retryGroupController.enter(nextGroupIdx)) return { status: 'retry-group' }

      if (options.getTodayRemainingCount() > 0) {
        try {
          const remoteBatch = await remoteBatchController.next(flowSeq)
          if (remoteBatch.status !== 'complete') return { status: remoteBatch.status }
        } catch (error) {
          if (!options.isPageAlive() || !options.isFlowCurrent(flowSeq)) return { status: 'dead' }
          options.logError('获取下一组失败', error)
          options.showToast({ title: '获取下一组失败', icon: 'none' })
          options.setData({ resultTransitioning: false })
          return { status: 'error' }
        }
      }

      options.setData({
        todayRemainingCount: 0,
        resultTransitioning: false,
        resultDockVisible: true,
      }, options.showResultDockAndRefreshTimer)
      return { status: 'complete' }
    },
  }
}

module.exports = {
  createNextGroupController,
}
