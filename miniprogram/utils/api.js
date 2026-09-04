const config = require('../config')
const storage = require('./storage')
const { debugLog, saveDebugSnapshot } = require('./debug')
const { parseServerUtc } = require('./china-time')

const { KEYS } = storage

// ═══════════════════════════════════════════════
// 统一 API 错误对象
// 页面统一使用：error.code / error.statusCode / error.message。
// error.message 只允许前端安全文案，禁止直接透传后端 detail/error.message。
// ═══════════════════════════════════════════════
class ApiError extends Error {
  constructor(message, options = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code
    this.statusCode = options.statusCode
    this.detail = options.detail
    this.raw = options.raw
    this.requestId = options.requestId || (options.detail && options.detail.requestId)
    this.traceId = options.traceId || (options.detail && options.detail.traceId)
  }
}

let _refreshing = null
let _redirecting = false
let _serverClockOffsetMs = 0
let _serverClockSynced = false
let _serverClockSampleAtMs = 0
let _serverClockBestRttMs = Infinity
let _serverClockSourceRank = 0

function _updateServerClock(res, requestStartedAt, responseReceivedAt) {
  if (!res) return
  let serverMs = NaN
  let sourceRank = 0
  if (res.data && typeof res.data === 'object' && res.data.server_now) {
    serverMs = parseServerUtc(res.data.server_now)
    if (Number.isFinite(serverMs)) sourceRank = 2
  }
  if (!Number.isFinite(serverMs)) {
    const dateHeader = _getResponseHeader(res.header, 'Date')
    if (dateHeader) serverMs = Date.parse(dateHeader)
    if (Number.isFinite(serverMs)) sourceRank = 1
  }
  if (!Number.isFinite(serverMs)) return

  const receivedAt = Number.isFinite(responseReceivedAt) ? responseReceivedAt : Date.now()
  const startedAt = Number.isFinite(requestStartedAt) ? requestStartedAt : receivedAt
  const rttMs = Math.max(0, receivedAt - startedAt)
  const clientMidpointMs = startedAt + rttMs / 2
  const candidateOffsetMs = serverMs - clientMidpointMs
  const sampleExpired = !_serverClockSampleAtMs || receivedAt - _serverClockSampleAtMs > 10 * 60 * 1000
  const sourceImproved = sourceRank > _serverClockSourceRank
  const rttImproved = sourceRank === _serverClockSourceRank && rttMs <= _serverClockBestRttMs + 50

  // Prefer explicit server_now and low-RTT samples. Periodically accept a fresh
  // sample even when RTT is worse so a device clock adjustment can self-heal.
  if (!_serverClockSynced || sampleExpired || sourceImproved || rttImproved) {
    _serverClockOffsetMs = candidateOffsetMs
    _serverClockSynced = true
    _serverClockSampleAtMs = receivedAt
    _serverClockBestRttMs = rttMs
    _serverClockSourceRank = sourceRank
  }
}

function now() {
  return Date.now() + (_serverClockSynced ? _serverClockOffsetMs : 0)
}

// 主动续签阈值：token 过期前 1 小时即触发续签
// 避免因 24h 阈值适配短生命周期 token 时持续刷新
const PROACTIVE_REFRESH_SEC = 3600

function _generateCorrelationId(prefix) {
  const random = Math.random().toString(36).slice(2, 12)
  return `${prefix}_${Date.now().toString(36)}${random}`.slice(0, 64)
}

function _normalizeCorrelationId(value, prefix) {
  const text = typeof value === 'string' ? value.trim() : ''
  if (/^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(text)) return text
  return _generateCorrelationId(prefix)
}

function _getResponseHeader(headers, name) {
  if (!headers || typeof headers !== 'object') return undefined
  const target = String(name).toLowerCase()
  const key = Object.keys(headers).find(k => String(k).toLowerCase() === target)
  const value = key ? headers[key] : undefined
  return typeof value === 'string' && value.length <= 64 ? value : undefined
}

function _safeHttpMessage(statusCode) {
  switch (Number(statusCode) || 0) {
    case 0: return '网络连接失败，请检查网络后重试'
    case 400: return '请求参数有误，请检查后重试'
    case 401: return '登录状态已失效，请重新登录'
    case 403: return '没有权限执行此操作'
    case 404: return '请求的资源不存在'
    case 405: return '请求方式不支持'
    case 409: return '当前数据状态已变化，请刷新后重试'
    case 413: return '上传内容过大，请调整后重试'
    case 415: return '不支持的内容类型'
    case 422: return '提交内容校验未通过，请检查后重试'
    case 429: return '请求过于频繁，请稍后重试'
    case 502:
    case 503: return '服务暂时不可用，请稍后重试'
    case 504: return '服务响应超时，请稍后重试'
    default:
      if (Number(statusCode) >= 500) return '服务器内部错误，请稍后重试'
      return '请求失败，请稍后重试'
  }
}

function _extractErrorCode(data, statusCode) {
  if (data && typeof data === 'object') {
    if (data.error && typeof data.error === 'object' && typeof data.error.code === 'string') {
      return data.error.code
    }
    if (typeof data.code === 'string') return data.code
    if (data.detail && typeof data.detail === 'object' && typeof data.detail.error_code === 'string') {
      return data.detail.error_code
    }
    if (typeof data.detail === 'string' && /^[A-Z][A-Z0-9_]{2,63}$/.test(data.detail)) {
      return data.detail
    }
  }
  return Number(statusCode) || 'HTTP_ERROR'
}

function _safeErrorMeta(data, responseHeaders) {
  const meta = {}
  if (data && typeof data === 'object' && data.error && typeof data.error === 'object') {
    if (typeof data.error.request_id === 'string') meta.requestId = data.error.request_id
    if (typeof data.error.trace_id === 'string') meta.traceId = data.error.trace_id
    if (data.error.retryable === true) meta.retryable = true
  }
  const headerRequestId = _getResponseHeader(responseHeaders, 'X-Request-ID')
  const headerTraceId = _getResponseHeader(responseHeaders, 'X-Trace-ID')
  if (!meta.requestId && headerRequestId) meta.requestId = headerRequestId
  if (!meta.traceId && headerTraceId) meta.traceId = headerTraceId
  return Object.keys(meta).length ? meta : undefined
}

// 重置重定向锁，供登录成功后调用
function resetRedirecting() {
  _redirecting = false
}

/** 标准化 expires_at 为 Unix 秒。支持：Unix 秒、Unix 毫秒、ISO 日期字符串 */
function _normalizeExpiresAt(value) {
  if (value == null) return null
  let seconds
  if (typeof value === 'number') {
    seconds = value
  } else if (typeof value === 'string') {
    const parsed = Number(value)
    if (!isNaN(parsed)) {
      seconds = parsed
    } else {
      const ms = parseServerUtc(value)
      if (!isNaN(ms)) seconds = Math.floor(ms / 1000)
      else return null
    }
  } else {
    return null
  }
  // 检测毫秒级时间戳（> 1e12）
  if (seconds > 1e12) seconds = Math.floor(seconds / 1000)
  return seconds
}

function _extractTraceId(data) {
  if (data && typeof data === 'object' && data._traceId) {
    return data._traceId
  }
  return ''
}

function _stripTraceId(data) {
  if (!data || typeof data !== 'object' || !data._traceId) return data
  const { _traceId, ...rest } = data
  return rest
}

function _summarizeResponseData(data) {
  if (!data || typeof data !== 'object') return { type: typeof data }
  const summary = {}
  if (data.trace_id) summary.trace_id = data.trace_id
  if (typeof data.total === 'number') summary.total = data.total
  if (Array.isArray(data.questions)) {
    summary.questionIds = data.questions.map(q => q && q.id).filter(id => id !== undefined)
    summary.question_count = data.questions.length
  }
  if (Array.isArray(data.results)) summary.result_count = data.results.length
  if (typeof data.total_correct === 'number') summary.total_correct = data.total_correct
  if (typeof data.total_wrong === 'number') summary.total_wrong = data.total_wrong
  const errorCode = _extractErrorCode(data, 0)
  if (typeof errorCode === 'string' && errorCode !== 'HTTP_ERROR') summary.errorCode = errorCode
  return summary
}

// Low-level request returning raw wx.request response (no 401 interception)
function _rawRequest(method, url, data, header, timeout) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${config.BASE_URL}${url}`,
      method,
      data: data,
      header,
      timeout: timeout || 30000,
      success: resolve,
      fail: reject,
    })
  })
}

function _rawUploadFile(url, filePath, name, formData, header, timeout) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${config.BASE_URL}${url}`,
      filePath,
      name: name || 'file',
      formData: formData || {},
      header,
      timeout: timeout || 30000,
      success: resolve,
      fail: reject,
    })
  })
}

// wx.login promise wrapper
function _wxLogin() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (res) => {
        if (res.code) resolve(res.code)
        else reject(new Error('wx.login 获取 code 失败'))
      },
      fail: reject,
    })
  })
}

// Refresh JWT token: only try refresh token, never auto-wx.login
// wx.login must only happen in login.js after user consent
async function _refreshToken(traceId = '') {
  const refreshToken = storage.get(KEYS.REFRESH_TOKEN)
  if (!refreshToken) {
    // No refresh token → must re-login at login page
    _clearAuthAndRedirect()
    throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401, traceId })
  }

  const header = {
    'Content-Type': 'application/json',
    'X-Trace-ID': _normalizeCorrelationId(traceId, 'tr'),
    'X-Request-ID': _generateCorrelationId('req'),
  }
  const res = await _rawRequest('POST', '/auth/refresh', { refresh_token: refreshToken }, header)
  if (res.statusCode === 200 && res.data && res.data.access_token) {
    try {
      storage.setStrict(KEYS.TOKEN, res.data.access_token)
      storage.setStrict(KEYS.TOKEN_EXPIRES_AT, _normalizeExpiresAt(res.data.expires_at))
      storage.setStrict(KEYS.REFRESH_TOKEN, res.data.refresh_token || refreshToken)
      if (res.data.user) {
        storage.setStrict(KEYS.USER, res.data.user)
      }
    } catch (e) {
      throw new ApiError('写入认证信息失败', { code: 'STORAGE_ERROR' })
    }
    return res.data.access_token
  }

  // Refresh token invalid → clear auth, redirect to login
  _clearAuthAndRedirect()
  throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401, traceId })
}

function _clearAuthAndRedirect() {
  // 自动失效场景不清除协议同意记录，避免用户在登录页被强制重新同意
  storage.clearSession({ preservePrivacyAcceptance: true, includeDebugSnapshots: true })
  if (!_redirecting) {
    _redirecting = true
    wx.reLaunch({ url: '/pages/login/login' })
  }
}

// Force refresh token: always makes an API call, ignores local expiry
// Used by file-request.js when server returns 401 on a valid-looking token
async function forceRefreshToken(traceId = '') {
  if (_refreshing) {
    try {
      return await _refreshing
    } catch (e) {
      throw e
    }
  }
  _refreshing = _refreshToken(traceId).finally(() => { _refreshing = null })
  return _refreshing
}

// 主动续签：检查 token 过期时间，即将过期时提前刷新
// 跳过无需 token 的端点（登录/注册），避免不必要的 wx.login 调用
function _skipProactiveRefresh(url) {
  return url === '/auth/login'
}

async function ensureValidToken(traceId = '') {
  const token = storage.get(KEYS.TOKEN)
  if (!token) return false

  const expiresAt = storage.get(KEYS.TOKEN_EXPIRES_AT)
  if (!expiresAt) return true  // 无过期信息，视为有效

  const timeToExpiry = expiresAt - Math.floor(Date.now() / 1000)
  if (timeToExpiry > PROACTIVE_REFRESH_SEC) return true  // 远未过期

  // Token 即将过期 → 主动续签（最多重试 1 次，应对冷启动网络延迟）
  for (let attempt = 0; attempt <= 1; attempt++) {
    if (!_refreshing) {
      _refreshing = _refreshToken(traceId).finally(() => { _refreshing = null })
    }
    try {
      await _refreshing
      return true
    } catch {
      if (attempt === 0) {
        await new Promise(r => setTimeout(r, 1500))
        continue
      }
      return false
    }
  }
  return false
}

function _buildHeader(traceId, requestId) {
  const token = storage.get(KEYS.TOKEN)
  const header = { 'Content-Type': 'application/json' }
  if (token) header['Authorization'] = `Bearer ${token}`
  header['X-Trace-ID'] = traceId
  header['X-Request-ID'] = requestId
  return header
}

async function request(method, url, data = {}, options = {}) {
  const traceId = _normalizeCorrelationId(_extractTraceId(data), 'tr')
  const payload = _stripTraceId(data)
  const timeout = options.timeout || 0

  // 主动续签：在发起请求前检查 token 是否需要刷新
  if (!_skipProactiveRefresh(url)) {
    const valid = await ensureValidToken(traceId)
    // ensureValidToken 两次重试后仍然失败 → 阻止本次请求
    // 注意：不检查 storage.get(KEYS.TOKEN)，因为 _refreshToken 失败时已调用
    // _clearAuthAndRedirect 清除了本地 token。即使 token 一开始就不存在，
    // 也应抛出错误避免发送无鉴权请求。
    if (!valid) {
      throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401, traceId })
    }
  }

  let requestId = _generateCorrelationId('req')
  const header = _buildHeader(traceId, requestId)

  // First attempt
  let res
  let requestStartedAt = Date.now()
  let responseReceivedAt = requestStartedAt
  try {
    res = await _rawRequest(method, url, payload, header, timeout)
    responseReceivedAt = Date.now()
  } catch (err) {
    debugLog(traceId, 'API_ERROR', { method, url, requestId, message: err?.errMsg || '网络异常' })
    if (!options.suppressNetworkToast) wx.showToast({ title: '网络异常', icon: 'none' })
    throw new ApiError(_safeHttpMessage(0), { code: 'NETWORK_ERROR', statusCode: 0, traceId, requestId, raw: err })
  }

  // Auto-refresh JWT on 401
  if (res.statusCode === 401) {
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
    requestId = _generateCorrelationId('req')
    header['X-Request-ID'] = requestId
    requestStartedAt = Date.now()
    try {
      res = await _rawRequest(method, url, payload, header, timeout)
      responseReceivedAt = Date.now()
    } catch (err) {
      debugLog(traceId, 'API_ERROR', { method, url, requestId, message: err?.errMsg || '网络异常' })
      if (!options.suppressNetworkToast) wx.showToast({ title: '网络异常', icon: 'none' })
      throw new ApiError(_safeHttpMessage(0), { code: 'NETWORK_ERROR', statusCode: 0, traceId, requestId, raw: err })
    }
  }

  _updateServerClock(res, requestStartedAt, responseReceivedAt)

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
    throw new ApiError(_safeHttpMessage(res.statusCode), {
      code: errorCode,
      statusCode: res.statusCode,
      detail: safeMeta,
      requestId: safeMeta && safeMeta.requestId,
      traceId: safeMeta && safeMeta.traceId,
      raw: undefined,
    })
  }

  return res.data
}

function _parseUploadResponseData(raw) {
  if (raw == null || raw === '') return {}
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch (_) {
    return {}
  }
}

/**
 * Authenticated multipart upload with the same JWT refresh behaviour as request().
 * wx.uploadFile manages the multipart Content-Type boundary, so it must not reuse
 * the JSON Content-Type header from normal API requests.
 */
async function uploadFile(url, filePath, options = {}) {
  const traceId = _normalizeCorrelationId(options.traceId, 'tr')
  const valid = await ensureValidToken(traceId)
  if (!valid) {
    throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401, traceId })
  }

  const buildUploadHeader = (token, requestId) => {
    const header = {
      'X-Trace-ID': traceId,
      'X-Request-ID': requestId,
    }
    if (token) header.Authorization = `Bearer ${token}`
    return header
  }

  let requestId = _generateCorrelationId('req')
  let token = storage.get(KEYS.TOKEN)
  let res
  try {
    res = await _rawUploadFile(
      url,
      filePath,
      options.name || 'file',
      options.formData || {},
      buildUploadHeader(token, requestId),
      options.timeout
    )
  } catch (err) {
    throw new ApiError(_safeHttpMessage(0), {
      code: 'NETWORK_ERROR',
      statusCode: 0,
      traceId,
      requestId,
      raw: err,
    })
  }

  if (res.statusCode === 401) {
    token = await forceRefreshToken(traceId)
    requestId = _generateCorrelationId('req')
    try {
      res = await _rawUploadFile(
        url,
        filePath,
        options.name || 'file',
        options.formData || {},
        buildUploadHeader(token, requestId),
        options.timeout
      )
    } catch (err) {
      throw new ApiError(_safeHttpMessage(0), {
        code: 'NETWORK_ERROR',
        statusCode: 0,
        traceId,
        requestId,
        raw: err,
      })
    }
  }

  const data = _parseUploadResponseData(res.data)
  if (res.statusCode >= 400) {
    const safeMeta = _safeErrorMeta(data, res.header)
    throw new ApiError(_safeHttpMessage(res.statusCode), {
      code: _extractErrorCode(data, res.statusCode),
      statusCode: res.statusCode,
      detail: safeMeta,
      requestId: (safeMeta && safeMeta.requestId) || requestId,
      traceId: (safeMeta && safeMeta.traceId) || traceId,
    })
  }

  return data
}

module.exports = {
  get: (url, data, options) => request('GET', url, data, options),
  post: (url, data, options) => request('POST', url, data, options),
  put: (url, data, options) => request('PUT', url, data, options),
  del: (url, options) => request('DELETE', url, undefined, options),
  resetRedirecting,
  ensureValidToken,
  forceRefreshToken,
  uploadFile,
  request,
  ApiError,
  getErrorMessage: (error) => error instanceof ApiError ? error.message : '请求失败，请稍后重试',
  normalizeExpiresAt: _normalizeExpiresAt,
  createTraceId: () => _generateCorrelationId('tr'),
  createRequestId: () => _generateCorrelationId('req'),
  createClientStartId: () => _generateCorrelationId('pstart'),
  now,
}
