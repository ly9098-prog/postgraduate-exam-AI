function createStartPracticeController(options) {
  return {
    start: startImpl.bind(null, options),
  }
}

async function startImpl(options) {
  if (options.isLoading() || options.isSubmitting()) return
  if (options.readPendingSubmission()) {
    await options.offerPendingSubmissionRecovery()
    if (options.readPendingSubmission()) return
  }
  if (!options.getSelectedSubjectId()) {
    options.openSubjectSheet()
    return
  }
  if (options.getSelectedMode() === 'sequential' && options.isSelectedSubjectHasChildren()) {
    options.showToast({ title: '顺序练习仅支持具体科目', icon: 'none' })
    return
  }
  const traceId = options.createTraceId()
  options.setSubmittedResultPayload(null)
  options.resetSession()
  options.setTraceId(traceId)
  options.setData({
    traceId,
    loading: true,
    renderCount: 0,
    started: true,
    currentIndex: 0,
    answeredCount: 0,
    results: [],
    submitted: false,
    wrongCount: 0,
    errorText: '',
    sequentialProgress: null,
    feedbackVisible: false,
    feedbackType: '',
    feedbackTitle: '',
    feedbackDetail: '',
    feedbackComboText: '',
  })
  options.setUnloadGuard(true)
  options.flushPendingRecentSubject()
  await options.loadQuestions()
}

module.exports = {
  createStartPracticeController,
}
