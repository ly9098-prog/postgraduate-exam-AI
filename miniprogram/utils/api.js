const config = require('../config')
const storage = require('./storage')
const { debugLog, isDebugMode, saveDebugSnapshot } = require('./debug')

const { KEYS } = storage

// ═══════════════════════════════════════════════
// 统一 API 错误对象
// 页面统一使用：error.code / error.message / error.detail
// ═══════════════════════════════════════════════
class ApiError extends Error {
  constructor(message, options = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code
    this.statusCode = options.statusCode
    this.detail = options.detail
    this.raw = options.raw
  }
}

let _refreshing = null
let _redirecting = false

// 主动续签阈值：token 过期前 1 小时即触发续签
// 避免因 24h 阈值适配短生命周期 token 时持续刷新
const PROACTIVE_REFRESH_SEC = 3600

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
      const d = new Date(value)
      if (!isNaN(d.getTime())) seconds = Math.floor(d.getTime() / 1000)
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
  if (data.detail) summary.error = String(data.detail).slice(0, 200)
  return summary
}

// Low-level request returning raw wx.request response (no 401 interception)
function _rawRequest(method, url, data, header, timeout) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${config.BASE_URL}${url}`,
      method,
      data,
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
async function _refreshToken() {
  const refreshToken = storage.get(KEYS.REFRESH_TOKEN)
  if (!refreshToken) {
    // No refresh token → must re-login at login page
    _clearAuthAndRedirect()
    throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401 })
  }

  const header = { 'Content-Type': 'application/json' }
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
  throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401 })
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
async function forceRefreshToken() {
  if (_refreshing) {
    try {
      return await _refreshing
    } catch (e) {
      throw e
    }
  }
  _refreshing = _refreshToken().finally(() => { _refreshing = null })
  return _refreshing
}

// 主动续签：检查 token 过期时间，即将过期时提前刷新
// 跳过无需 token 的端点（登录/注册），避免不必要的 wx.login 调用
function _skipProactiveRefresh(url) {
  return url === '/auth/login'
}

async function ensureValidToken() {
  const token = storage.get(KEYS.TOKEN)
  if (!token) return false

  const expiresAt = storage.get(KEYS.TOKEN_EXPIRES_AT)
  if (!expiresAt) return true  // 无过期信息，视为有效

  const timeToExpiry = expiresAt - Math.floor(Date.now() / 1000)
  if (timeToExpiry > PROACTIVE_REFRESH_SEC) return true  // 远未过期

  // Token 即将过期 → 主动续签（最多重试 1 次，应对冷启动网络延迟）
  for (let attempt = 0; attempt <= 1; attempt++) {
    if (!_refreshing) {
      _refreshing = _refreshToken().finally(() => { _refreshing = null })
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

function _buildHeader(traceId) {
  const token = storage.get(KEYS.TOKEN)
  const header = { 'Content-Type': 'application/json' }
  if (token) header['Authorization'] = `Bearer ${token}`
  if (traceId && isDebugMode()) header['X-Trace-Id'] = traceId
  return header
}

async function request(method, url, data = {}, options = {}) {
  const traceId = _extractTraceId(data)
  const payload = _stripTraceId(data)
  const timeout = options.timeout || 0

  // 主动续签：在发起请求前检查 token 是否需要刷新
  if (!_skipProactiveRefresh(url)) {
    const valid = await ensureValidToken()
    // ensureValidToken 两次重试后仍然失败 → 阻止本次请求
    // 注意：不检查 storage.get(KEYS.TOKEN)，因为 _refreshToken 失败时已调用
    // _clearAuthAndRedirect 清除了本地 token。即使 token 一开始就不存在，
    // 也应抛出错误避免发送无鉴权请求。
    if (!valid) {
      throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401 })
    }
  }

  const header = _buildHeader(traceId)

  // First attempt
  let res
  try {
    res = await _rawRequest(method, url, payload, header, timeout)
  } catch (err) {
    debugLog(traceId, 'API_ERROR', { method, url, message: err?.errMsg || '网络异常' })
    wx.showToast({ title: '网络异常', icon: 'none' })
    throw new ApiError(err?.errMsg || '网络异常', { code: 'NETWORK_ERROR', raw: err })
  }

  // Auto-refresh JWT on 401
  if (res.statusCode === 401) {
    debugLog(traceId, 'API_401_REFRESH', { method, url })

    let newToken
    try {
      newToken = await forceRefreshToken()
    } catch (_e) {
      // _refreshToken already clears auth and redirects to login
      throw new ApiError('登录已过期，请重新登录', { code: 'AUTH_REQUIRED', statusCode: 401 })
    }

    // Retry original request with new token
    header['Authorization'] = `Bearer ${newToken}`
    try {
      res = await _rawRequest(method, url, payload, header, timeout)
    } catch (err) {
      debugLog(traceId, 'API_ERROR', { method, url, message: err?.errMsg || '网络异常' })
      wx.showToast({ title: '网络异常', icon: 'none' })
      throw new ApiError(err?.errMsg || '网络异常', { code: 'NETWORK_ERROR', raw: err })
    }
  }

  debugLog(traceId, 'API_RESPONSE', { method, url, statusCode: res.statusCode })
  saveDebugSnapshot(traceId, 'api', {
    method,
    url,
    statusCode: res.statusCode,
    response: _summarizeResponseData(res.data),
  })

  if (res.statusCode >= 400) {
    throw new ApiError(res.data?.detail || '请求失败', {
      code: res.data?.code || res.statusCode,
      statusCode: res.statusCode,
      detail: res.data?.detail,
      raw: res.data,
    })
  }

  return res.data
}

module.exports = {
  get: (url, data, options) => request('GET', url, data, options),
  post: (url, data, options) => request('POST', url, data, options),
  put: (url, data, options) => request('PUT', url, data, options),
  del: (url, options) => request('DELETE', url, undefined, options),
  resetRedirecting,
  ensureValidToken,
  forceRefreshToken,
  request,
  ApiError,
  normalizeExpiresAt: _normalizeExpiresAt,
}
