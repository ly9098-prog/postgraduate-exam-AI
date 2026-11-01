const { ApiError, getResponseHeader: _getResponseHeader, safeHttpMessage: _safeHttpMessage,
  extractErrorCode: _extractErrorCode, safeErrorMeta: _safeErrorMeta,
  summarizeResponseData: _summarizeResponseData } = require('./api-error')
const { generateCorrelationId: _generateCorrelationId,
  normalizeCorrelationId: _normalizeCorrelationId, extractTraceId: _extractTraceId,
  stripTraceId: _stripTraceId } = require('./api-correlation')
const { rawRequest: _rawRequest } = require('./api-transport')
const { updateServerClock: _updateServerClock } = require('./api-clock')
const { ensureValidToken, forceRefreshToken, buildHeader: _buildHeader,
  skipProactiveRefresh: _skipProactiveRefresh } = require('./api-auth')
const { debugLog, saveDebugSnapshot } = require('./debug')

async function _ensureRequestAuth(url, traceId) {
  if (_skipProactiveRefresh(url)) return
  const valid = await ensureValidToken(traceId)
  // ensureValidToken 两次重试后仍然失败 → 阻止本次请求
  // 注意：不检查 storage.get(KEYS.TOKEN)，因为 _refreshToken 失败时已调用
  // _clearAuthAndRedirect 清除了本地 token。即使 token 一开始就不存在，
  // 也应抛出错误避免发送无鉴权请求。
  if (!valid) {
    throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401, traceId })
  }
}

async function _attemptRequest(method, url, payload, header, timeout, traceId, requestId, options) {
  const requestStartedAt = Date.now()
  try {
    const res = await _rawRequest(method, url, payload, header, timeout)
    return { res, requestStartedAt, responseReceivedAt: Date.now(), requestId }
  } catch (err) {
    debugLog(traceId, 'API_ERROR', { method, url, requestId, message: err?.errMsg || '网络异常' })
    if (!options.suppressNetworkToast) wx.showToast({ title: '网络异常', icon: 'none' })
    throw new ApiError(_safeHttpMessage(0), { code: 'NETWORK_ERROR', statusCode: 0, traceId, requestId, raw: err })
  }
}

async function _retryAfterUnauthorized(context, requestId) {
  const { method, url, payload, header, timeout, traceId, options } = context
  debugLog(traceId, 'API_401_REFRESH', { method, url })

  let newToken
  try {
    newToken = await forceRefreshToken(traceId)
  } catch (_e) {
    // _refreshToken already clears auth and redirects to login
    throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401, traceId })
  }

  // Retry original request with new token under the same trace but a new HTTP request ID
  header['Authorization'] = `Bearer ${newToken}`
  const nextRequestId = _generateCorrelationId('req')
  header['X-Request-ID'] = nextRequestId
  return _attemptRequest(method, url, payload, header, timeout, traceId, nextRequestId, options)
}

function _finishRequest(context) {
  const { method, url, traceId, requestId, attempt } = context
  const res = attempt.res
  _updateServerClock(res, attempt.requestStartedAt, attempt.responseReceivedAt)

  const responseRequestId = _getResponseHeader(res.header, 'X-Request-ID') || requestId
  const responseTraceId = _getResponseHeader(res.header, 'X-Trace-ID') || traceId
  debugLog(responseTraceId, 'API_RESPONSE', {
    method,
    url,
    statusCode: res.statusCode,
    requestId: responseRequestId,
  })
  saveDebugSnapshot(responseTraceId, 'api', {
    method,
    url,
    statusCode: res.statusCode,
    requestId: responseRequestId,
    response: _summarizeResponseData(res.data),
  })

  if (res.statusCode >= 400) {
    // 后端响应只用于机器判断和调试快照；展示文案完全由前端按 HTTP 状态生成。
    const errorCode = _extractErrorCode(res.data, res.statusCode)
    const safeMeta = _safeErrorMeta(res.data, res.header)
    const availability = _safeAiAvailabilityDetail(res.data)
    throw new ApiError(_safeHttpMessage(res.statusCode), {
      code: errorCode,
      statusCode: res.statusCode,
      detail: availability ? { ...safeMeta, ...availability } : safeMeta,
      requestId: safeMeta && safeMeta.requestId,
      traceId: safeMeta && safeMeta.traceId,
      raw: undefined,
    })
  }

  return res.data
}

function _safeAiAvailabilityDetail(data) {
  const detail = data && data.detail
  if (!detail || typeof detail !== 'object' || detail.code !== 'ai_service_unavailable') {
    return null
  }
  const result = { code: 'ai_service_unavailable' }
  if (['checking', 'available', 'unavailable'].includes(detail.status)) {
    result.status = detail.status
  }
  if (typeof detail.enabled === 'boolean') result.enabled = detail.enabled
  if (typeof detail.reason === 'string' && /^[a-z][a-z0-9_]{1,63}$/.test(detail.reason)) {
    result.reason = detail.reason
  }
  if (typeof detail.message === 'string') result.message = detail.message.slice(0, 160)
  const retryAfter = Number(detail.retry_after_ms)
  if (Number.isFinite(retryAfter)) {
    result.retry_after_ms = Math.min(3600000, Math.max(1000, Math.trunc(retryAfter)))
  }
  return result
}

async function request(method, url, data = {}, options = {}) {
  const traceId = _normalizeCorrelationId(_extractTraceId(data), 'tr')
  const payload = _stripTraceId(data)
  const timeout = options.timeout || 0

  await _ensureRequestAuth(url, traceId)

  let requestId = _generateCorrelationId('req')
  const header = _buildHeader(traceId, requestId)
  let attempt = await _attemptRequest(method, url, payload, header, timeout, traceId, requestId, options)
  if (attempt.res.statusCode === 401) {
    attempt = await _retryAfterUnauthorized(
      { method, url, payload, header, timeout, traceId, options }, requestId)
    requestId = attempt.requestId
  }
  return _finishRequest({ method, url, traceId, requestId, attempt })
}

module.exports = { request }
