function buildLocalResult(options, submission, submitResult, questions) {
  const cacheCreatedAt = options.now()
  const cacheKey = options.buildCacheKey(cacheCreatedAt)
  return {
    cacheCreatedAt,
    cacheKey,
    payload: options.buildResultPayload({
      submission,
      submitResult,
      questions,
      traceId: options.getTraceId(),
      cacheKey,
      userId: options.getCurrentUserId(),
      createdAt: cacheCreatedAt,
    }),
  }
}

function storeResultCache(options, payload) {
  try {
    options.writeResultCache(payload)
    return true
  } catch (storageError) {
    options.logWarn('答题已提交成功，但本地结果缓存失败', storageError)
    return false
  }
}

module.exports = {
  buildLocalResult,
  storeResultCache,
}
