/**
 * Shared persistence keys for exam-runner local drafts.
 *
 * Keep all generations here so callers that terminate an attempt can remove
 * every compatible cache shape.  This prevents a cancelled/closed attempt from
 * being resurrected by an older client cache after the server has accepted the
 * terminal state.
 */
function normalizeAttemptId(attemptId) {
  const value = Number(attemptId)
  return Number.isInteger(value) && value > 0 ? value : 0
}

function cacheKey(attemptId) {
  const id = normalizeAttemptId(attemptId)
  return id ? `exam_attempt_pending_v3:${id}` : ''
}

function v2CacheKey(attemptId) {
  const id = normalizeAttemptId(attemptId)
  return id ? `exam_attempt_pending_v2:${id}` : ''
}

function legacyCacheKey(attemptId) {
  const id = normalizeAttemptId(attemptId)
  return id ? `exam_attempt_pending_v1:${id}` : ''
}

function pendingCacheKeys(attemptId) {
  const keys = [cacheKey(attemptId), v2CacheKey(attemptId), legacyCacheKey(attemptId)]
  return keys.filter(Boolean)
}

function clearPendingAttempt(attemptId) {
  const keys = pendingCacheKeys(attemptId)
  keys.forEach((key) => {
    try { wx.removeStorageSync(key) } catch (_) {}
  })
}

module.exports = {
  cacheKey,
  v2CacheKey,
  legacyCacheKey,
  pendingCacheKeys,
  clearPendingAttempt,
}
