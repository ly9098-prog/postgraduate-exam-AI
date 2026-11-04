const {
  KF,
  reviewFailureNeedsRefresh,
} = require('./review-runner-support')
const adapter = require('../../utils/question-runner-adapter')
const { createGroupSubmitFlowController } = require('./group-submit-flow-controller')
const { createGroupSubmitEntryController } = require('./submit-entry-controller')
const { createGroupSubmitConfirmController } = require('./submit-confirm-controller')
const { createGroupSubmitRequestController } = require('./submit-request-controller')
const { createGroupSubmitResultController } = require('./submit-result-controller')
const { createResultDockController } = require('./result-dock-controller')
const { createReviewStateWriter } = require('./review-active-state')

function buildGroupSubmitFlowPageCapabilities(page, deps) {
  return {
      getGroupQuestions: () => page.data.groupQuestions,
      confirm: groupQuestions => page._groupSubmitEntryController().confirm(groupQuestions),
      begin: groupQuestions => page._groupSubmitEntryController().begin(groupQuestions),
      request: input => page._groupSubmitRequestController().submit(input),
      isQuestionAnswered: (q, a) => adapter.isQuestionAnswered(q, a, KF),
      getRequestId: q => page._getReviewRequestId(q),
      buildTimingSession: () => page._buildReviewTimingSession(),
      enrichForResult: q => page._enrichForResult(q),
      failureNeedsRefresh: reviewFailureNeedsRefresh,
      applyResult: input => page._groupSubmitResultController().apply(input),
      isPageAlive: () => page._alive,
      logError: (...args) => console.error(...args),
      showResultFailureToast: () => wx.showToast({ title: '提交失败，请重试', icon: 'none' }),
      setSubmitting: value => page.setData({ submittingGroup: value }),
  }
}

function buildGroupSubmitEntryPageCapabilities(page, deps) {
  return {
      getData: () => page.data,
      getSession: () => page._reviewSession,
      isConfirmPending: () => page._submitConfirmPending,
      isMasterUndoInFlight: () => page._masterUndoInFlight,
      isPageAlive: () => page._alive,
      computeAnsweredCount: (questions, answers) => adapter.computeAnsweredCount(questions, answers, KF),
      confirmController: page._groupSubmitConfirmController || (
        page._groupSubmitConfirmController = createGroupSubmitConfirmController({
          getConfirm: () => page.selectComponent('#submitConfirm'),
          setPending: value => { page._submitConfirmPending = value },
          isPageAlive: () => page._alive,
          getPhase: () => page.data.phase,
          findUnansweredIndex: () => page.data.groupQuestions.findIndex(q => !adapter.isQuestionAnswered(q, page._reviewSession.answers, KF)),
          showQuestion: index => page._showQuestion(index),
        })
      ),
      showToast: options => wx.showToast(options),
      clearMasterUndo: () => page._clearMasterUndo(),
      setSubmitting: value => page.setData({ submittingGroup: value }),
      syncReviewSessionDay: () => page._syncReviewSessionDayIfNeeded(),
  }
}

function buildGroupSubmitRequestPageCapabilities(page, deps) {
  const { api } = deps
  return {
      postGrade: payload => api.post('/review/grade-batch', payload),
      showToast: options => wx.showToast(options),
      setSubmitting: value => page.setData({ submittingGroup: value }),
      isPageAlive: () => page._alive,
  }
}

function buildGroupSubmitResultPageCapabilities(page, deps) {
  return {
      getGroups: () => page.data.groups,
      getSession: () => page._reviewSession,
      getTodayDueCount: () => page.data.todayDueCount,
      getTodayCompletedCount: () => page.data.todayCompletedCount,
      getCurrentGroupIdx: () => page.data.currentGroupIdx,
      clearSubmittedDraft: (questions, results) => page._clearSubmittedReviewDraft(questions, results),
      showToast: options => wx.showToast(options),
      pauseTimer: () => page._pauseReviewTimer(),
      setData: createReviewStateWriter(page),
      showResultDockAndRefreshTimer: () => page._showResultDockAndRefreshTimer(),
  }
}

function buildResultDockPageCapabilities(page, deps) {
  return {
      getPhase: () => page.data.phase,
      getTodayRemainingCount: () => page.data.todayRemainingCount,
      getResultDockVisible: () => page.data.resultDockVisible,
      setData: patch => page.setData(patch),
      clearFadeTimer: () => page._clearResultDockFadeTimer(),
      setFadeTimer: timer => { page._resultDockFadeTimer = timer },
      setTimeout,
      clearTimeout,
      isPageAlive: () => page._alive,
      getFadeDelay: () => 5000,
  }
}

module.exports = {
  buildGroupSubmitFlowPageCapabilities,
  buildGroupSubmitEntryPageCapabilities,
  buildGroupSubmitRequestPageCapabilities,
  buildGroupSubmitResultPageCapabilities,
  buildResultDockPageCapabilities,
}
