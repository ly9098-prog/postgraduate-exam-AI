const {
  KF,
  normalizeReviewQuestion,
} = require('./review-runner-support')
const adapter = require('../../utils/question-runner-adapter')
const { createReviewSessionController } = require('./review-session-controller')
const { createStartBatchController } = require('./start-batch-controller')
const { createNavBackController } = require('./nav-back-controller')
const { createReviewSelfHealController } = require('./self-heal-controller')
const { createReviewStateWriter, createReviewActivityClearer } = require('./review-active-state')

function buildReviewSessionPageCapabilities(page, deps) {
  return {
      getSession: () => page._reviewSession,
      setData: patch => page.setData(patch),
  }
}

function buildStartBatchPageCapabilities(page, deps) {
  const { api } = deps
  return {
      getTodayRemainingCount: () => page.data.todayRemainingCount,
      isStarting: () => page.data.isStarting,
      isContinuing: () => page.data.isContinuing,
      nextFlowSeq: () => ++page._flowRequestSeq,
      getCurrentFlowSeq: () => page._flowRequestSeq,
      isFlowCurrent: seq => seq === page._flowRequestSeq,
      isPageAlive: () => page._alive,
      setData: createReviewStateWriter(page),
      getBatchSize: () => page.data.reviewBatchSize,
      postNextBatch: payload => api.post('/review/today/next-batch', payload),
      loadOverview: () => page.loadTodayReviewOverview(),
      normalizeQuestion: question => normalizeReviewQuestion(question),
      restoreDraft: questions => page._restoreReviewDraft(questions),
      getSession: () => page._reviewSession,
      getData: () => page.data,
      enrichQuestion: question => page._enrichQuestion(question),
      buildOptionList: (question, answers) => adapter.buildOptionList(question, answers, KF),
      getBlankOptionGroups: question => adapter.getBlankOptionGroups(question),
      enrichBlankOptionGroups: (groups, answer) => adapter.enrichBlankOptionGroups(groups, answer),
      computeAnsweredCount: (questions, answers) => adapter.computeAnsweredCount(questions, answers, KF),
      getTotalBatchCount: () => page.data.totalBatchCount,
      checkSetDataSize: data => page._checkSetDataSize(data),
      syncAnsweredFlags: () => page._syncAnsweredFlags(),
      updateRunnerFields: () => page._updateRunnerFields(),
      checkRenderInvariant: renderModel => page._checkRenderInvariant(renderModel),
      recordRenderTrace: trace => page._recordRenderTrace(trace),
      startReviewTimer: () => page._startReviewTimer(),
      showToast: options => wx.showToast(options),
      logError: (...args) => console.error(...args),
  }
}

function buildNavBackPageCapabilities(page, deps) {
  return {
      getPhase: () => page.data.phase,
      setData: patch => page.setData(patch),
      clearMasterUndo: () => page._clearMasterUndo(),
      clearReviewTimer: () => page._clearReviewTimer(),
      clearReviewActivity: createReviewActivityClearer(),
      getCurrentPages: () => getCurrentPages(),
      navigateBack: () => wx.navigateBack(),
      reLaunch: options => wx.reLaunch(options),
  }
}

function buildReviewSelfHealPageCapabilities(page, deps) {
  return {
      setSafeModeActive: v => { page._reviewSession.safeModeActive = v },
      getCurrentQuestion: () => page.data.currentQuestion,
      getCurrentIndex: () => page.data.currentIndex,
      getGroupQuestions: () => page.data.groupQuestions,
      enrichQuestion: q => page._enrichQuestion(q),
      setData: patch => page.setData(patch),
      showQuestion: idx => page._showQuestion(idx),
  }
}

module.exports = {
  buildReviewSessionPageCapabilities,
  buildStartBatchPageCapabilities,
  buildNavBackPageCapabilities,
  buildReviewSelfHealPageCapabilities,
}
