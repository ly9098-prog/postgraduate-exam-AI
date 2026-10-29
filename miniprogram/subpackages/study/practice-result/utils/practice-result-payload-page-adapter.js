// Page capability assembly for miniprogram/subpackages/study/practice-result/index.js.
// Assemble live page ports here; the page keeps lazy controller memoisation.

const { resolveResultCounts } = require('./result-counts')
const {
  normalizePercent,
  formatDuration,
  getQuestionListHeightRpx,
  buildErrorDonutGradient,
} = require('./format-helpers')
const { normalizeGrowthProfile } = require('./growth-helpers')

function buildPracticePayloadPageState(page) {
  return {
    incrementDiagnosisRefreshSeq: () => { page._diagnosisRefreshSeq = (page._diagnosisRefreshSeq || 0) + 1 },
    setSessionPayload: source => { page._sessionPayload = source },
    isPageAlive: () => page._pageAlive,
    isResultVisible: () => page._resultVisible,
    setData: patch => page.setData(patch),
    refreshWrongDiagnoses: () => page.refreshWrongDiagnoses(),
  }
}

function buildPracticePayloadPageCapabilities(page, deps) {
  const { knowledgePracticeSync, buildErrorDonutSvg } = deps
  return {
    buildReviewItem: (q, r, a, i) => page.buildReviewItem(q, r, a, i),
    normalizeReviewItem: (item, index) => page.normalizeReviewItem(item, index),
    resolveResultCounts: (source, reviewItems) => resolveResultCounts(source, reviewItems),
    normalizePercent,
    formatDuration,
    getQuestionListHeightRpx,
    buildErrorDonutGradient,
    buildErrorDonutSvg,
    normalizeGrowthProfile,
    buildLocalErrorDistribution: items => page.buildLocalErrorDistribution(items),
    getResultTip: (acc, wrong, skipped, partial, total) =>
      page.getResultTip(acc, wrong, skipped, partial, total),
    getLaunchKnowledgePointId: () => page._launchKnowledgePointId,
    getLaunchSource: () => page._launchSource,
    getLaunchSubjectId: () => page._launchSubjectId,
    getPracticeRequestId: () => page._practiceRequestId,
    recordKnowledgePractice: data => knowledgePracticeSync.record(data),
    consumeKnowledgeBaseline: (subjectId, kpId) =>
      knowledgePracticeSync.consumeBaseline(subjectId, kpId),
  }
}

module.exports = {
  buildPracticePayloadPageState,
  buildPracticePayloadPageCapabilities,
}
