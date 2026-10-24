/**
 * Pure helpers for practice result cache validation,
 * extracted from practice-result/index.js.
 */

/**
 * Validate that a cached payload's request_id matches the expected one.
 * Returns true if no expected ID is provided (back-compat).
 */
function isPayloadRequestValid(value, expectedRequestId) {
  if (!value || typeof value !== 'object') return false
  var source = value.data && typeof value.data === 'object' ? value.data : value
  var expected = String(expectedRequestId || '').trim()
  if (!expected) return true
  var actual = String(
    source.request_id || source.requestId || value.request_id || value.requestId || ''
  ).trim()
  return !!actual && actual === expected
}

/**
 * Extract createdAt from a cache key pattern `pr_<timestamp>_<random>`.
 */
function extractCreatedAtFromCacheKey(cacheKey) {
  if (!cacheKey) return 0
  var match = /^pr_(\d+)_/.exec(String(cacheKey))
  if (match) return Number(match[1]) || 0
  return 0
}

module.exports = { isPayloadRequestValid, extractCreatedAtFromCacheKey }
