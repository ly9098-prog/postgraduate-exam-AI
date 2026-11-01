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
  if (!page._alive) return false
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
  if (!enabled) {
    page._scheduleAiAvailabilityRetry(
      checking
        ? Math.max(
          1000,
          Number(value.retry_after_ms) || AVAILABILITY_CHECKING_RETRY_MS,
        )
        : Math.max(5000, Number(value.retry_after_ms) || AVAILABILITY_RETRY_MS),
    )
  }
  return enabled
}

function _availabilityCacheFresh(page) {
  return !!page._aiAvailability &&
    Date.now() - Number(page._aiAvailabilityCheckedAt || 0) < AVAILABILITY_CACHE_MS
}

async function _refreshAiAvailability(page, { requestClient, force } = {}) {
  const seq = ++page._aiAvailabilitySeq
  if (!force && _availabilityCacheFresh(page) && !page.data.aiAvailabilityChecking) {
    return page.data.aiAvailabilityEnabled
  }
  page._clearAiAvailabilityRetry()
  page.setData(_checkingState())
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

function _scheduleAiAvailabilityRetry(page, delay) {
  if (!page._alive || page._aiAvailabilityRetryTimer) return
  page._aiAvailabilityRetryTimer = setTimeout(() => {
    page._aiAvailabilityRetryTimer = null
    if (page._alive) page._refreshAiAvailability({ force: true, silent: true })
  }, Math.max(1000, Number(delay) || AVAILABILITY_RETRY_MS))
}

function _clearAiAvailabilityRetry(page) {
  if (!page._aiAvailabilityRetryTimer) return
  clearTimeout(page._aiAvailabilityRetryTimer)
  page._aiAvailabilityRetryTimer = null
}

function _initAiAvailabilityState(page) {
  page._aiAvailabilitySeq = 0
  page._aiAvailability = null
  page._aiAvailabilityCheckedAt = 0
  page._aiAvailabilityRetryTimer = null
}

function _clearAiAvailabilityState(page) {
  page._aiAvailabilitySeq = (page._aiAvailabilitySeq || 0) + 1
  page._aiAvailability = null
  page._aiAvailabilityCheckedAt = 0
  page._clearAiAvailabilityRetry()
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
}
