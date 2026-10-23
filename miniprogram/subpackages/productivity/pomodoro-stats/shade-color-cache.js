const viewHelpers = require('./view-helpers')

/**
 * Tiny memoising wrapper around view-helpers.shadeColor.  The cache key is
 * `${hex}|${amount}` so repeated sector wall-shade lookups during a 980ms pie
 * animation do not recompute the same RGB values every frame.  The returned
 * object holds its own cache map so it never touches Page state; the page can
 * reset the cache by calling `reset()`.
 */
function createShadeColorCache(shadeFn = viewHelpers.shadeColor) {
  let cache = new Map()
  return {
    shade(hex, amount) {
      const key = hex + '|' + amount
      if (cache.has(key)) return cache.get(key)
      const value = shadeFn(hex, amount)
      cache.set(key, value)
      return value
    },
    reset() {
      cache = new Map()
    },
  }
}

module.exports = {
  createShadeColorCache,
}
