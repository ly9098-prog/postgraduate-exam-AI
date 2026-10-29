const {
  REVIEW_BATCH_SIZE_OPTIONS,
  normalizeReviewBatchSize,
} = require('./review-runner-support')
const { createOverviewVMController } = require('./overview-vm-controller')
const { createBatchSizeSheetController } = require('./batch-size-sheet-controller')
const { createOverviewLoadController } = require('./overview-load-controller')
const { createReviewDaySyncController } = require('./day-sync-controller')
const { createOverviewSyncController } = require('./overview-sync-controller')

function buildOverviewVMPageCapabilities(page, deps) {
  return {
      getBatchSizeOptions: () => REVIEW_BATCH_SIZE_OPTIONS,
      getDefaultBatchSize: () => 10,
      isUserBatchSizeSelected: () => page._userSelectedReviewBatchSize,
      getCurrentUserBatchSize: () => page.data.reviewBatchSize,
  }
}

function buildBatchSizeSheetPageCapabilities(page, deps) {
  return {
      getPhase: () => page.data.phase,
      isStarting: () => page.data.isStarting,
      isContinuing: () => page.data.isContinuing,
      getReviewBatchSize: () => page.data.reviewBatchSize,
      getPendingBatchSize: () => page.data.pendingBatchSize,
      getBatchSizeOptions: () => REVIEW_BATCH_SIZE_OPTIONS,
      normalizeBatchSize: v => normalizeReviewBatchSize(v),
      markUserSelected: () => { page._userSelectedReviewBatchSize = true },
      setData: patch => page.setData(patch),
  }
}

function buildOverviewLoadPageCapabilities(page, deps) {
  const { api } = deps
  return {
      nextRequestSeq: () => ++page._overviewRequestSeq,
      isRequestCurrent: seq => seq === page._overviewRequestSeq,
      isPageAlive: () => page._alive,
      isAutoStartPending: () => page._autoStartPending,
      setAutoStartPending: value => { page._autoStartPending = value },
      setOverviewLoading: value => { page._reviewSession.overviewLoading = value },
      getOverview: () => api.get('/review/today/overview'),
      buildOverviewVM: overview => page.buildReviewOverviewVM(overview),
      applyOverviewToSession: (overview, vm) => page._overviewSyncController().applyOverviewToSession(overview, vm),
      adjustVmForActiveSession: vm => page._overviewSyncController().adjustVmForActiveSession(vm),
      setData: (patch, callback) => page.setData(patch, callback),
      startReview: () => page.startTodayReview(),
      logError: (...args) => console.error(...args),
  }
}

function buildReviewDaySyncPageCapabilities(page, deps) {
  const { api } = deps
  return {
      isSameDay: () => page._overviewSyncController().isSameDay(),
      isPageAlive: () => page._alive,
      getOverview: () => api.get('/review/today/overview'),
      buildOverviewVM: overview => page.buildReviewOverviewVM(overview),
      applyOverviewWithDayReset: (overview, vm) => page._overviewSyncController().applyOverviewWithDayReset(overview, vm),
      setDateStr: () => page._setDateStr(),
      setData: patch => page.setData(patch),
      showSuccessToast: () => wx.showToast({ title: '日期已切换，已同步今日复习进度', icon: 'none' }),
      showFailureToast: () => wx.showToast({ title: '日期已切换，请联网同步后继续', icon: 'none' }),
      logError: (...args) => console.error(...args),
  }
}

function buildOverviewSyncPageCapabilities(page, deps) {
  return {
      getSession: () => page._reviewSession,
      getPhase: () => page.data.phase,
      getTodayDueCount: () => page.data.todayDueCount,
  }
}

module.exports = {
  buildOverviewVMPageCapabilities,
  buildBatchSizeSheetPageCapabilities,
  buildOverviewLoadPageCapabilities,
  buildReviewDaySyncPageCapabilities,
  buildOverviewSyncPageCapabilities,
}