const {
  normalizeReviewQuestion,
  formatReviewElapsed,
} = require('./review-runner-support')
const { createReviewMasterController } = require('./master-controller')
const { createNextGroupController } = require('./next-group-controller')
const { createNextRetryGroupController } = require('./next-retry-group-controller')
const { createNextRemoteBatchController } = require('./next-remote-batch-controller')
const { createReviewTimerController } = require('./review-timer-controller')
const { createReviewStateWriter } = require('./review-active-state')

function buildReviewMasterPageCapabilities(page, deps) {
  const { api } = deps
  return {
      getData: () => page.data,
      getSession: () => page._reviewSession,
      setData: createReviewStateWriter(page),
      isPageAlive: () => page._alive,
      isMasterSubmitting: () => page.data.masterSubmitting,
      isSubmittingGroup: () => page.data.submittingGroup,
      isMasterUndoInFlight: () => page._masterUndoInFlight,
      getPendingMasterUndo: () => page._pendingMasterUndo,
      setPendingMasterUndo: value => { page._pendingMasterUndo = value },
      setMasterUndoInFlight: value => { page._masterUndoInFlight = value },
      getMasterUndoTimer: () => page._masterUndoTimer,
      setMasterUndoTimer: timer => { page._masterUndoTimer = timer },
      incrementMasteredCount: () => { page._masteredCount = (page._masteredCount || 0) + 1 },
      decrementMasteredCount: () => { page._masteredCount = Math.max(0, (page._masteredCount || 1) - 1) },
      syncReviewSessionDay: () => page._syncReviewSessionDayIfNeeded(),
      postMaster: scheduleId => api.post(`/review/${scheduleId}/master`),
      postUnmaster: scheduleId => api.post(`/review/${scheduleId}/unmaster`),
      refreshOverviewStatsSilently: () => page.refreshOverviewStatsSilently(),
      clearUndo: () => page._clearMasterUndo(),
      armUndoExpiry: ms => page._armMasterUndoExpiry(ms),
      clearReviewTimer: () => page._clearReviewTimer(),
      getTodayRemainingCount: () => page.data.todayRemainingCount,
      syncAnsweredFlags: () => page._syncAnsweredFlags(),
      showQuestion: index => page._showQuestion(index),
      startReviewTimer: () => page._startReviewTimer(),
      showToast: options => wx.showToast(options),
      logError: (message, error) => console.error(message, error),
      setTimeout,
      clearTimeout,
  }
}

function buildNextGroupPageCapabilities(page, deps) {
  return {
      getData: () => page.data,
      setData: (patch, callback) => page.setData(patch, callback),
      clearMasterUndo: () => page._clearMasterUndo(),
      clearResultDockFadeTimer: () => page._clearResultDockFadeTimer(),
      nextFlowSeq: () => ++page._flowRequestSeq,
      isPageAlive: () => page._alive,
      isFlowCurrent: seq => seq === page._flowRequestSeq,
      syncReviewSessionDay: () => page._syncReviewSessionDayIfNeeded(),
      getCurrentGroupIdx: () => page.data.currentGroupIdx,
      getTodayRemainingCount: () => page.data.todayRemainingCount,
      retryGroupController: page._nextRetryGroupController(),
      remoteBatchController: page._nextRemoteBatchController(),
      logError: (message, error) => console.error(message, error),
      showToast: options => wx.showToast(options),
      showResultDockAndRefreshTimer: () => page._showResultDockAndRefreshTimer(),
  }
}

function buildNextRetryGroupPageCapabilities(page, deps) {
  return {
      getGroups: () => page.data.groups,
      getSession: () => page._reviewSession,
      setData: createReviewStateWriter(page),
      syncAnsweredFlags: () => page._syncAnsweredFlags(),
      showQuestion: index => page._showQuestion(index),
      startReviewTimer: () => page._startReviewTimer(),
  }
}

function buildNextRemoteBatchPageCapabilities(page, deps) {
  const { api } = deps
  return {
      getBatchSize: () => page.data.reviewBatchSize,
      postNextBatch: payload => api.post('/review/today/next-batch', payload),
      isPageAlive: () => page._alive,
      isFlowCurrent: seq => seq === page._flowRequestSeq,
      normalizeQuestion: question => normalizeReviewQuestion(question),
      restoreDraft: questions => page._restoreReviewDraft(questions),
      getSession: () => page._reviewSession,
      setData: createReviewStateWriter(page),
      getCurrentBatchNo: () => page.data.currentBatchNo,
      getTotalBatchCount: () => page.data.totalBatchCount,
      getTodayDueCount: () => page.data.todayDueCount,
      getTodayCompletedCount: () => page.data.todayCompletedCount,
      getTodayRemainingCount: () => page.data.todayRemainingCount,
      syncAnsweredFlags: () => page._syncAnsweredFlags(),
      showQuestion: index => page._showQuestion(index),
      startReviewTimer: () => page._startReviewTimer(),
      showToast: options => wx.showToast(options),
      refreshOverviewStatsSilently: () => page.refreshOverviewStatsSilently(),
  }
}

function buildReviewTimerPageCapabilities(page, deps) {
  const { api, _reviewMonotonicNow, _reviewServerNow } = deps
  return {
      getSession: () => page._reviewSession,
      isPageAlive: () => page._alive,
      monotonicNow: () => _reviewMonotonicNow(),
      serverNow: () => _reviewServerNow(),
      getTimerId: () => page._timerInterval,
      setTimerId: id => { page._timerInterval = id },
      setInterval,
      clearInterval,
      setData: patch => page.setData(patch),
      formatElapsed: seconds => formatReviewElapsed(seconds),
      createRequestId: () => (typeof api.createRequestId === 'function' ? api.createRequestId() : undefined),
  }
}

module.exports = {
  buildReviewMasterPageCapabilities,
  buildNextGroupPageCapabilities,
  buildNextRetryGroupPageCapabilities,
  buildNextRemoteBatchPageCapabilities,
  buildReviewTimerPageCapabilities,
}
