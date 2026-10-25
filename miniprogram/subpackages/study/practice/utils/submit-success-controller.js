function createSubmitSuccessController(options) {
  return {
    complete: completeImpl.bind(null, options),
  }
}

function completeImpl(options, submission, submitResult, questions) {
  submission.serverAccepted = true
  submission.retryBlocked = false
  const partialCount = (submission.partialQuestionIds || []).length
  const userId = options.getCurrentUserId()
  const cacheCreatedAt = options.now()
  const cacheKey = options.buildCacheKey(cacheCreatedAt)
  const localResultPayload = options.buildResultPayload({
    submission,
    submitResult,
    questions,
    traceId: options.getTraceId(),
    cacheKey,
    userId,
    createdAt: cacheCreatedAt,
  })
  const displaySkippedCount = localResultPayload.skipped
  options.setSubmittedResultPayload(localResultPayload)
  let resultCacheStored = false
  try {
    options.writeResultCache(localResultPayload)
    resultCacheStored = true
  } catch (storageError) {
    options.logWarn('答题已提交成功，但本地结果缓存失败', storageError)
  }
  const resultUrl = options.buildResultUrl({
    correct: localResultPayload.correct,
    wrong: localResultPayload.wrong,
    skipped: displaySkippedCount,
    partial: partialCount,
    total: localResultPayload.total,
    subjectId: localResultPayload.subject_id,
    subjectName: localResultPayload.subject_name || '',
    duration: localResultPayload.duration,
    cacheKey,
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
