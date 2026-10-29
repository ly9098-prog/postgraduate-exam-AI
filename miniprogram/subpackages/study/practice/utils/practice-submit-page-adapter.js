function _pendingSubmissionController(page, dependencies) {
const { PRACTICE_PENDING_SUBMISSION_TTL_MS, createPendingSubmissionController, getConsole, getDate, getPlatform } = dependencies
return page._pendingSubmission || (
page._pendingSubmission = createPendingSubmissionController({
getStorageKey: () => page._pendingSubmissionStorageKey(),
readStorage: key => getPlatform().getStorageSync(key),
writeStorage: (key, value) => getPlatform().setStorageSync(key, value),
removeStorage: key => getPlatform().removeStorageSync(key),
now: () => getDate().now(),
getTtlMs: () => PRACTICE_PENDING_SUBMISSION_TTL_MS,
isPageAlive: () => page._pageAlive,
showConfirm: options => page._showSubmitConfirm(options),
logWarn: (...args) => getConsole().warn(...args),
restoreSubmittedSnapshot: (submission, resultUrl) => {
page._practiceSession.submissionSnapshot = submission
page._practiceSession.requestId = submission.requestId || ''
page._pendingResultUrl = resultUrl
page.setData({ submitted: true, submitting: false })
page._setPracticeUnloadGuard(false)
page._openSubmittedResult(resultUrl, submission)
},
resumePendingSubmission: async submission => {
page._resetSession()
page._practiceSession.submissionSnapshot = submission
page._practiceSession.requestId = submission.requestId || ''
page._practiceSession.traceId = submission.traceId || ''
page.setData({ started: true, submitted: false, submitting: false })
page._setPracticeUnloadGuard(true, '交卷仍在确认中。')
await page.doSubmit(true)
if (!page.data.submitted && page._pageAlive) {
page._setPracticeUnloadGuard(false)
page.setData({ started: false })
return false
}
return true
},
})
)
}

function _submittedResultController(page, dependencies) {
const { createSubmittedResultController, getConsole, getPlatform } = dependencies
  return page._submittedResultControllerInstance || (
    page._submittedResultControllerInstance = createSubmittedResultController({
      isPageAlive: () => page._pageAlive,
      getSubmittedResultPayload: () => page._submittedResultPayload,
      writeResultCache: payload => getPlatform().setStorageSync('lastPracticeResult', payload),
      logWarn: (...args) => getConsole().warn(...args),
      logError: (...args) => getConsole().error(...args),
      showConfirm: options => page._showSubmitConfirm(options),
      getSession: () => page._practiceSession,
      setPendingResultUrl: value => { page._pendingResultUrl = value },
      setData: patch => page.setData(patch),
      setUnloadGuard: enabled => page._setPracticeUnloadGuard(enabled),
      redirectTo: options => getPlatform().redirectTo(options),
    })
  )
}

function _submitFlowController(page, dependencies) {
const { api, buildSubmitPayload, createSubmitFlowController } = dependencies
return page._submitFlowControllerInstance || (
page._submitFlowControllerInstance = createSubmitFlowController({
isSubmitting: () => page.data.submitting,
getSubmissionSnapshot: () => page._practiceSession.submissionSnapshot,
isSubmitted: () => page.data.submitted,
getPendingResultUrl: () => page._pendingResultUrl,
openSubmittedResult: (resultUrl, submission) => page._openSubmittedResult(resultUrl, submission),
showConfirm: options => page._showSubmitConfirm(options),
getQuestions: () => page.data.questions || [],
prepareSubmission: skipConfirm => page._submitEntryController().prepare(skipConfirm),
clearTimer: () => page._clearTimer(),
persistPendingSubmission: (submission, status, resultUrl) => page._persistPendingSubmission(submission, status, resultUrl),
setData: patch => page.setData(patch),
buildSubmitPayload,
getTraceId: () => page._practiceSession.traceId,
requestSubmit: payload => api.post('/practice/batch-submit', payload),
isPageAlive: () => page._pageAlive,
handleSubmitError: (submission, error) => page._submitErrorController().handle(submission, error),
completeSubmit: (submission, submitResult, questions) => page._submitSuccessController().complete(submission, submitResult, questions),
})
)
}

function _submitSuccessController(page, dependencies) {
const { buildLightQuestions, buildPracticeResultUrl, buildStoredResults, buildSubmitResultPayload, computeDisplaySkippedCount, createSubmitSuccessController, getConsole, getDate, getMath, getPlatform } = dependencies
return page._submitSuccessControllerInstance || (
page._submitSuccessControllerInstance = createSubmitSuccessController({
getCurrentUserId: () => page._getCurrentUserId(),
now: () => getDate().now(),
buildCacheKey: createdAt => 'pr_' + createdAt + '_' + getMath().random().toString(36).slice(2, 8),
getTraceId: () => page._practiceSession.traceId,
buildResultPayload: options => buildSubmitResultPayload({
...options,
buildStoredResults,
buildLightQuestions,
computeDisplaySkippedCount,
}),
setSubmittedResultPayload: payload => { page._submittedResultPayload = payload },
writeResultCache: payload => getPlatform().setStorageSync('lastPracticeResult', payload),
logWarn: (...args) => getConsole().warn(...args),
buildResultUrl: options => buildPracticeResultUrl(options),
getLaunchSource: () => page._launchSource || '',
getLaunchReturnTo: () => page._launchReturnTo || '',
setPendingResultUrl: value => { page._pendingResultUrl = value },
persistPendingSubmission: (submission, status, resultUrl) => page._persistPendingSubmission(submission, status, resultUrl),
setUnloadGuard: enabled => page._setPracticeUnloadGuard(enabled),
setData: patch => page.setData(patch),
openSubmittedResult: (resultUrl, submission) => page._openSubmittedResult(resultUrl, submission),
})
)
}

function _submitErrorController(page, dependencies) {
const { createSubmitErrorController, getConsole, isDeterministicReject, resolveRejectMessage } = dependencies
return page._submitError || (
page._submitError = createSubmitErrorController({
isPageAlive: () => page._pageAlive,
logError: (...args) => getConsole().error(...args),
pauseQuestionTiming: () => { page._practiceSession.currentQuestionStartedMonoMs = 0 },
setData: patch => page.setData(patch),
isDeterministicReject,
persistPendingSubmission: (submission, status, resultUrl) => page._persistPendingSubmission(submission, status, resultUrl),
setUnloadGuard: (enabled, message) => page._setPracticeUnloadGuard(enabled, message),
resolveRejectMessage,
showConfirm: options => page._showSubmitConfirm(options),
})
)
}

function _submitEntryController(page, dependencies) {
const { adapter, api, buildRecoveryQuestions, buildSubmissionSnapshot, buildSubmitAnswers, buildSubmitSession, classifyAnswers, createSubmitEntryController, getDate, getMath, getPlatform, monotonicNow } = dependencies
return page._submitEntry || (
page._submitEntry = createSubmitEntryController({
getQuestions: () => page.data.questions || [],
getSelectedSubjectId: () => page.data.selectedSubjectId,
getSelectedSubjectName: () => page.data.selectedSubjectName,
getAnswerMap: () => page._practiceSession.answerMap,
getActiveStartedMonoMs: () => page._practiceSession.activeStartedMonoMs,
getComboCount: () => page._practiceSession.comboCount,
buildAnsweredFlags: adapter.buildAnsweredFlags,
classifyAnswers,
isMultiBlank: adapter.isMultiBlankChoice,
showToast: options => getPlatform().showToast(options),
showPausedConfirm: options => page._showSubmitConfirmPaused(options),
showConfirm: options => page._showSubmitConfirm(options),
clearTimer: () => page._clearTimer(),
settleQuestionTime: pause => page._settleQuestionTime(pause),
monotonicNow,
now: () => api.now(),
getBackgroundMs: () => page._practiceSession.backgroundMs,
getRequestId: () => page._practiceSession.requestId,
buildRequestId: () => 'req_' + getDate().now() + '_' + getMath().random().toString(36).slice(2, 8),
setRequestId: requestId => { page._practiceSession.requestId = requestId },
buildSubmitAnswers,
getQuestionTimeMap: () => page._practiceSession.questionTimeMap,
getRecommendationRequestId: () => page._practiceSession.recommendationRequestId,
buildSubmitSession,
getBatchMode: () => page._practiceSession.batchMode,
getSelectedMode: () => page.data.selectedMode,
getStartedAtMs: () => page._practiceSession.startedAtMs,
buildRecoveryQuestions,
getBatchToken: () => page._practiceSession.batchToken,
buildSubmissionSnapshot,
getTraceId: () => page._practiceSession.traceId,
getKnowledgeScope: () => page._practiceSession.knowledgeScope,
setSubmissionSnapshot: submission => { page._practiceSession.submissionSnapshot = submission },
persistPendingSubmission: (submission, status, resultUrl) => page._persistPendingSubmission(submission, status, resultUrl),
setUnloadGuard: (enabled, message) => page._setPracticeUnloadGuard(enabled, message),
})
)
}

module.exports = { _pendingSubmissionController, _submittedResultController, _submitFlowController, _submitSuccessController, _submitErrorController, _submitEntryController }
