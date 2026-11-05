const AVAILABILITY_TIMEOUT_MS = 5000
const AVAILABILITY_CHECKING_RETRY_MS = 2000
const AVAILABILITY_RETRY_MS = 5000
const AVAILABILITY_CACHE_MS = 30000

function _checkingState() {
  return {
    aiAvailabilityChecking: true,
    aiAvailabilityEnabled: false,
    aiAvailabilityStatus: 'checking',
    aiAvailabilityReason: 'checking',
    aiAvailabilityMessage: '正在检查 AI 服务',
  }
}

function _applyAvailability(page, state) {
  if (!page._alive || page._aiAvailabilityPaused) return false
  page._aiAvailabilitySeq = (page._aiAvailabilitySeq || 0) + 1
  _clearAiAvailabilityRetry(page)
  const value = state && typeof state === 'object' ? state : {}
  const enabled = value.enabled === true
  const checking = value.status === 'checking'
  const reason = String(value.reason || (checking ? 'checking' : 'transient'))
  const message = enabled ? '' : String(value.message || (checking
    ? '正在检查 AI 服务'
    : 'AI 服务暂时不可用，请稍后重试'))
  page._aiAvailability = value
  page._aiAvailabilityCheckedAt = Date.now()
  page.setData({
    aiAvailabilityChecking: checking,
    aiAvailabilityEnabled: enabled,
    aiAvailabilityStatus: enabled ? 'available' : String(value.status || 'unavailable'),
    aiAvailabilityReason: reason,
    aiAvailabilityMessage: message,
  })
  _resumeAvailabilityRetry(page)
  return enabled
}

function _resumeAvailabilityRetry(page) {
  if (page.data.aiAvailabilityEnabled || page._aiAvailabilityIntent) return
  const state = page._aiAvailability || {}
  const checking = state.status === 'checking'
  const minimum = checking ? 1000 : AVAILABILITY_RETRY_MS
  const fallback = checking ? AVAILABILITY_CHECKING_RETRY_MS : AVAILABILITY_RETRY_MS
  const delay = Math.max(minimum, Number(state.retry_after_ms) || fallback)
  const elapsed = Math.max(0, Date.now() - Number(page._aiAvailabilityCheckedAt || 0))
  page._scheduleAiAvailabilityRetry(Math.max(1000, delay - elapsed))
}

function _availabilityCacheFresh(page) {
  return !!page._aiAvailability &&
    Date.now() - Number(page._aiAvailabilityCheckedAt || 0) < AVAILABILITY_CACHE_MS
}

async function _refreshAiAvailability(page, { requestClient, force, silent } = {}) {
  if (!page._alive || page._aiAvailabilityPaused) return false
  if (!force && _availabilityCacheFresh(page) && !page.data.aiAvailabilityChecking) {
    _resumeAvailabilityRetry(page)
    return page.data.aiAvailabilityEnabled
  }
  const seq = page._aiAvailabilitySeq = (page._aiAvailabilitySeq || 0) + 1
  page._clearAiAvailabilityRetry()
  if (!silent || (!page._aiAvailability && !page.data.aiAvailabilityEnabled)) page.setData(_checkingState())
  let timer = null
  try {
    const request = requestClient.get('/ai/error-analysis/availability', {}, {
      timeout: AVAILABILITY_TIMEOUT_MS,
      suppressNetworkToast: true,
    })
    const timeout = new Promise(resolve => {
      timer = setTimeout(() => resolve(null), AVAILABILITY_TIMEOUT_MS)
    })
    const state = await Promise.race([request, timeout])
    if (timer) clearTimeout(timer)
    if (!page._alive || seq !== page._aiAvailabilitySeq) return false
    if (!state) {
      page._aiAvailabilityCheckedAt = Date.now()
      page.setData({
        aiAvailabilityChecking: false,
        aiAvailabilityEnabled: false,
        aiAvailabilityStatus: 'unavailable',
        aiAvailabilityReason: 'checking',
        aiAvailabilityMessage: 'AI 服务仍在检查，完成后将自动更新',
      })
      page._scheduleAiAvailabilityRetry(AVAILABILITY_RETRY_MS)
      return false
    }
    return _applyAvailability(page, state)
  } catch (_) {
    if (timer) clearTimeout(timer)
    if (!page._alive || seq !== page._aiAvailabilitySeq) return false
    page.setData({
      aiAvailabilityChecking: false,
      aiAvailabilityEnabled: false,
      aiAvailabilityStatus: 'unavailable',
      aiAvailabilityReason: 'status_unavailable',
      aiAvailabilityMessage: '暂时无法检查 AI 服务，请稍后重试',
    })
    page._scheduleAiAvailabilityRetry(AVAILABILITY_RETRY_MS)
    return false
  }
}

async function runWhenAvailable(page, wqId, action) {
  if (page._aiAvailabilityPaused) return
  if (page.data.aiAvailabilityEnabled) return action()
  if (page._aiAvailabilityIntent || page.data.aiAvailabilityStatus !== 'checking') return
  const intent = { wqId, requestId: page._aiRequestId }
  const deadline = Date.now() + 65000
  page._aiAvailabilityIntent = intent
  page.setData({ aiAvailabilityPending: true })
  const isCurrent = () => page._alive && page._aiAvailabilityIntent === intent &&
    page._aiRequestId === intent.requestId &&
    Number(page._currentWqId || (page.data.wq && page.data.wq.id)) === Number(wqId)
  try {
    for (let attempt = 0; attempt < 32 && isCurrent() && Date.now() < deadline; attempt++) {
      const enabled = await page._refreshAiAvailability({ force: true, silent: true })
      if (!isCurrent()) return
      if (enabled) {
        page._aiAvailabilityIntent = null
        page.setData({ aiAvailabilityPending: false })
        return action()
      }
      if (page.data.aiAvailabilityStatus !== 'checking') return
      await new Promise(resolve => setTimeout(resolve, AVAILABILITY_CHECKING_RETRY_MS))
    }
  } finally {
    if (page._aiAvailabilityIntent === intent) {
      page._aiAvailabilityIntent = null
      if (page._alive) {
        page.setData({ aiAvailabilityPending: false })
        if (!page.data.aiAvailabilityEnabled) page._scheduleAiAvailabilityRetry(
          Number((page._aiAvailability || {}).retry_after_ms) || AVAILABILITY_RETRY_MS)
      }
    }
  }
}

function _scheduleAiAvailabilityRetry(page, delay) {
  if (!page._alive || page._aiAvailabilityPaused || page._aiAvailabilityRetryTimer) return
  page._aiAvailabilityRetryTimer = setTimeout(() => {
    page._aiAvailabilityRetryTimer = null
    if (page._alive && !page._aiAvailabilityPaused) page._refreshAiAvailability({ force: true, silent: true })
  }, Math.max(1000, Number(delay) || AVAILABILITY_RETRY_MS))
}

function _clearAiAvailabilityRetry(page) {
  if (!page._aiAvailabilityRetryTimer) return
  clearTimeout(page._aiAvailabilityRetryTimer)
  page._aiAvailabilityRetryTimer = null
}

function _initAiAvailabilityState(page) {
  page._aiAvailabilityPaused = false
  page._aiAvailabilityIntent = null
  page._aiAvailabilitySeq = 0
  page._aiAvailability = null
  page._aiAvailabilityCheckedAt = 0
  page._aiAvailabilityRetryTimer = null
}

function _clearAiAvailabilityState(page) {
  pauseAvailability(page)
  page._aiAvailability = null
  page._aiAvailabilityCheckedAt = 0
}

function pauseAvailability(page) {
  page._aiAvailabilityPaused = true
  page._aiAvailabilitySeq = (page._aiAvailabilitySeq || 0) + 1
  page._aiAvailabilityIntent = null
  page._clearAiAvailabilityRetry()
  if (page._alive && page.data.aiAvailabilityPending) page.setData({ aiAvailabilityPending: false })
}

function resumeAvailability(page) {
  page._aiAvailabilityPaused = false
  if (page._alive && page.data.wq) return page._refreshAiAvailability({ silent: true })
}

function _availabilityFromError(error) {
  const detail = error && (error.detail || (error.raw && error.raw.data))
  if (!detail || detail.code !== 'ai_service_unavailable') return null
  return {
    status: detail.status || 'unavailable',
    enabled: detail.enabled === true,
    reason: detail.reason || 'transient',
    message: detail.message || 'AI 服务暂时不可用，请稍后重试',
    retry_after_ms: Number(detail.retry_after_ms) || AVAILABILITY_RETRY_MS,
  }
}

module.exports = {
  AVAILABILITY_TIMEOUT_MS,
  AVAILABILITY_CHECKING_RETRY_MS,
  AVAILABILITY_RETRY_MS,
  AVAILABILITY_CACHE_MS,
  _checkingState,
  _applyAvailability,
  _availabilityCacheFresh,
  _refreshAiAvailability,
  _scheduleAiAvailabilityRetry,
  _clearAiAvailabilityRetry,
  _initAiAvailabilityState,
  _clearAiAvailabilityState,
  _availabilityFromError,
  runWhenAvailable,
  pauseAvailability,
  resumeAvailability,
}
