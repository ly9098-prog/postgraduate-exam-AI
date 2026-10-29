const { KF } = require('./review-runner-support')
const { isTrueFalseType } = require('../../utils/answer')
const { createAnswerInteractionController } = require('./answer-interaction-controller')
const { createQuestionDisplayController } = require('./question-display-controller')
const { createQuestionEnrichmentController } = require('./question-enrichment-controller')
const { createRenderSafetyController } = require('./render-safety-controller')

function buildAnswerInteractionPageCapabilities(page, deps) {
  return {
      isSubmitting: () => page.data.submittingGroup,
      getCurrentQuestion: () => page.data.currentQuestion,
      getAnswers: () => page._reviewSession.answers,
      setAnswers: answers => { page._reviewSession.answers = answers },
      getGroupQuestions: () => page.data.groupQuestions,
      getKeyField: () => KF,
      setData: patch => page.setData(patch),
      persistDraft: () => page._persistReviewDraft(),
      syncAnsweredFlags: () => page._syncAnsweredFlags(),
      updateRunnerFields: () => page._updateRunnerFields(),
      buildRunnerSubtitle: () => '第 ' + (page.data.currentBatchNo || page.data.currentGroupIdx + 1) + ' / ' + (page.data.totalBatchCount || 1) + ' 组',
  }
}

function buildQuestionDisplayPageCapabilities(page, deps) {
  return {
      getGroupQuestions: () => page.data.groupQuestions,
      getAnswers: () => page._reviewSession.answers,
      setOptionKeys: keys => { page._reviewSession.optionKeys = keys },
      getKeyField: () => KF,
      getAnsweredCount: () => page.data._answeredCount,
      getCurrentQuestion: () => page.data.currentQuestion,
      enrichQuestion: q => page._enrichQuestion(q),
      setData: patch => page.setData(patch),
      checkSetDataSize: data => page._checkSetDataSize(data),
      checkRenderInvariant: model => page._checkRenderInvariant(model),
      recordRenderTrace: trace => page._recordRenderTrace(trace),
      buildRunnerSubtitle: () => '第 ' + (page.data.currentBatchNo || page.data.currentGroupIdx + 1) + ' / ' + (page.data.totalBatchCount || 1) + ' 组',
  }
}

function buildQuestionEnrichmentPageCapabilities(page, deps) {
  const { config } = deps
  return {
      isDev: () => config.DEV,
      isSafeModeActive: () => page._reviewSession.safeModeActive,
      isTrueFalse: t => isTrueFalseType(t),
      subjectLabel: (name, code) => page.subjectLabel(name, code),
  }
}

function buildRenderSafetyPageCapabilities(page, deps) {
  const { config } = deps
  return {
      isSafeModeActive: () => page._reviewSession.safeModeActive,
      enterSafeMode: () => page._enterSafeMode(),
      getRenderTraces: () => page._reviewSession.renderTraces,
      setRenderTraces: traces => { page._reviewSession.renderTraces = traces },
      isDev: () => config.DEV,
  }
}

module.exports = {
  buildAnswerInteractionPageCapabilities,
  buildQuestionDisplayPageCapabilities,
  buildQuestionEnrichmentPageCapabilities,
  buildRenderSafetyPageCapabilities,
}