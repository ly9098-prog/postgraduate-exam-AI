function createSubmitSuccessController(options) {
  return {
    complete: completeImpl.bind(null, options),
  }
}

function completeImpl(options, submission, submitResult, questions) {
  submission.serverAccepted = true
  submission.retryBlocked = false
  const partialCount = (submission.partialQuestionIds || []).length
  const localResult = buildLocalResult(options, submission, submitResult, questions)
  const localResultPayload = localResult.payload
  const displaySkippedCount = localResultPayload.skipped
  options.setSubmittedResultPayload(localResultPayload)
  const resultCacheStored = storeResultCache(options, localResultPayload)
  const resultUrl = options.buildResultUrl({
    correct: localResultPayload.correct,
    wrong: localResultPayload.wrong,
    skipped: displaySkippedCount,
    partial: partialCount,
    total: localResultPayload.total,
    subjectId: localResultPayload.subject_id,
    subjectName: localResultPayload.subject_name || '',
    duration: localResultPayload.duration,
    cacheKey: localResult.cacheKey,
    requestId: submission.requestId || '',
    resultCacheStored,
    source: options.getLaunchSource(),
    returnTo: options.getLaunchReturnTo(),
  })
  submission.keepPendingUntilResult = !resultCacheStored
  options.setPendingResultUrl(resultUrl)
  submission.pendingPersisted = options.persistPendingSubmission(
    submission,
    'submitted',
    resultUrl
  ) || submission.pendingPersisted
  options.setUnloadGuard(false)
  options.setData({ submitting: false, submitted: true })
  options.openSubmittedResult(resultUrl, submission)
}

module.exports = {
  createSubmitSuccessController,
}
const {
  buildLocalResult,
  storeResultCache,
} = require('./submit-success-state')
