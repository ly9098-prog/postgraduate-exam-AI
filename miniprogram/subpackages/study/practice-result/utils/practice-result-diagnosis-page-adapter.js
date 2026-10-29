// Page capability assembly for miniprogram/subpackages/study/practice-result/index.js.
// Assemble live page ports here; the page keeps lazy controller memoisation.

const errorDiagnosis = require('../../utils/error-diagnosis')

function buildBatchDiagnosisPageCapabilities(page, deps) {
  const { api } = deps
  return {
    getBatchDiagnosisSaving: () => page.data.batchDiagnosisSaving,
    getBatchSelectedMap: () => page.data.batchSelectedMap,
    getWrongReviewItems: () => page.data.wrongReviewItems,
    getReviewItems: () => page.data.reviewItems,
    getFilteredReviewItems: () => page.data.filteredReviewItems,
    isPageAlive: () => page._pageAlive,
    setData: patch => page.setData(patch),
    showToast: options => wx.showToast(options),
    getQuickTypes: () => errorDiagnosis.QUICK_TYPES,
    showOptions: opts => page._showAppOptions(opts),
    incrementDiagnosisRefreshSeq: () => { page._diagnosisRefreshSeq = (page._diagnosisRefreshSeq || 0) + 1 },
    putDiagnosis: (wqId, payload) => api.put(`/wrong-questions/${wqId}/diagnosis`, payload),
    normalizeDiagnosis: raw => errorDiagnosis.normalizeDiagnosis(raw),
  }
}

module.exports = {
  buildBatchDiagnosisPageCapabilities,
}
