const storage = require('./storage')
const { parseServerUtc } = require('./china-time')
const { generateCorrelationId: _generateCorrelationId,
  normalizeCorrelationId: _normalizeCorrelationId } = require('./api-correlation')
const { rawRequest: _rawRequest } = require('./api-transport')
const { ApiError } = require('./api-error')

const { KEYS } = storage

let _refreshing = null
let _redirecting = false

// 主动续签阈值：token 过期前 1 小时即触发续签
// 避免因 24h 阈值适配短生命周期 token 时持续刷新
const PROACTIVE_REFRESH_SEC = 3600

function resetRedirecting() {
  _redirecting = false
}

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

module.exports = {
  PROACTIVE_REFRESH_SEC,
  resetRedirecting,
  normalizeExpiresAt: _normalizeExpiresAt,
  forceRefreshToken,
  ensureValidToken,
  buildHeader: _buildHeader,
  clearAuthAndRedirect: _clearAuthAndRedirect,
  skipProactiveRefresh: _skipProactiveRefresh,
}
