function createExamPendingCacheController(options) {
  return {
    load: loadImpl.bind(null, options),
    persist: persistImpl.bind(null, options),
    clear: clearImpl.bind(null, options),
  }
}

function loadImpl(options, attemptId) {
  try {
    let raw = options.readStorage(options.cacheKey(attemptId))
    let savedAt = 0
    let items = null
    let submitPending = false

    if (raw && typeof raw === 'object' && raw.items && typeof raw.items === 'object') {
      savedAt = Number(raw.saved_at || 0)
      items = options.sanitizePendingItems(raw.items)
      submitPending = raw.submit_pending === true
    } else {
      const v2 = options.readStorage(options.v2CacheKey(attemptId))
      const v1 = options.readStorage(options.legacyCacheKey(attemptId))
      const legacy = v2 && typeof v2 === 'object' ? v2 : (v1 && typeof v1 === 'object' ? v1 : null)
      if (legacy) {
        savedAt = Number(legacy.saved_at || 0)
        items = options.sanitizePendingItems(
          legacy.items && typeof legacy.items === 'object' ? legacy.items : legacy
        )
        submitPending = legacy.submit_pending === true
      }
    }

    if (!items) return Object.create(null)
    const ttl = submitPending ? options.getSubmitPendingTtlMs() : options.getDraftTtlMs()
    const now = options.now()
    if (savedAt > 0 && now - savedAt > ttl) {
      clearImpl(options, attemptId)
      return Object.create(null)
    }
    options.setRetainPendingForSubmit(submitPending)

    try {
      options.writeStorage(options.cacheKey(attemptId), {
        schema_version: options.getSchemaVersion(),
        saved_at: savedAt || now,
        submit_pending: submitPending,
        items,
      })
      options.removeStorage(options.v2CacheKey(attemptId))
      options.removeStorage(options.legacyCacheKey(attemptId))
    } catch (_) {}
    return items
  } catch (_) {
    return Object.create(null)
  }
}

function persistImpl(options, pending, attemptId, retainPendingForSubmit) {
  try {
    const keys = Object.keys(pending || {}).filter(options.isPendingItemKey)
    if (keys.length) {
      const items = Object.create(null)
      keys.forEach((key) => { items[key] = Object.assign({}, pending[key]) })
      options.writeStorage(options.cacheKey(attemptId), {
        schema_version: options.getSchemaVersion(),
        saved_at: options.now(),
        submit_pending: !!retainPendingForSubmit,
        items,
      })
    } else {
      clearImpl(options, attemptId)
    }
  } catch (_) {}
}

function clearImpl(options, attemptId) {
  try {
    options.clearPendingAttempt(attemptId)
  } catch (_) {}
}

module.exports = {
  createExamPendingCacheController,
}
