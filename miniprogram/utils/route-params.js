/**
 * Route parameter decoding utilities.
 *
 * Safe wrappers for decodeURIComponent that never throw on malformed input.
 * Use these in onLoad instead of raw decodeURIComponent to prevent white
 * screens from corrupted share links or deep links.
 */

/**
 * Safely decode a URI component. Returns fallback (or the raw value) on error.
 *
 * Handles:
 *   - Malformed % sequences: "bad%", "%E4%B8" (truncated), "%%"
 *   - Double-encoded sequences: "100%25"
 *   - Already-decoded UTF-8 fragments: "%E9%AB%98" → valid
 *   - Non-string types: null, undefined, objects, numbers
 */
function safeDecodeURIComponent(value, fallback) {
  if (typeof value !== 'string') return arguments.length >= 2 ? fallback : ''
  try {
    return decodeURIComponent(value)
  } catch (_) {
    // URIError: malformed URI sequence — return raw value as fallback
    return arguments.length >= 2 ? fallback : value
  }
}

/**
 * Parse a value as a positive integer. Returns fallback on failure.
 *
 * Handles: null, undefined, NaN, Infinity, negative values, floats, non-numeric strings.
 */
function parsePositiveInt(value, fallback) {
  var n = parseInt(value, 10)
  if (isNaN(n) || n <= 0 || !isFinite(n)) return arguments.length >= 2 ? fallback : 0
  return n
}

/**
 * Parse a value as a string. Returns fallback on failure.
 *
 * Non-string inputs (null, undefined, objects, numbers) return the fallback.
 */
function parseStringParam(value, fallback) {
  if (typeof value === 'string') return value
  return arguments.length >= 2 ? fallback : ''
}

module.exports = {
  safeDecodeURIComponent: safeDecodeURIComponent,
  parsePositiveInt: parsePositiveInt,
  parseStringParam: parseStringParam,
}
