const config = require('../config')
const storage = require('./storage')
const { debugLog, isDebugMode, saveDebugSnapshot } = require('./debug')

const { KEYS } = storage

let _refreshing = null
let _redirecting = false

// 主动续签阈值：token 过期前 24 小时即触发续签
const PROACTIVE_REFRESH_SEC = 24 * 60 * 60

// 重置重定向锁，供登录成功后调用
function resetRedirecting() {
  _redirecting = false
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
function _rawRequest(method, url, data, header) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${config.BASE_URL}${url}`,
      method,
      data,
      header,
      timeout: 30000,
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

// Refresh JWT token: try refresh token first, fall back to wx.login
async function _refreshToken() {
  const refreshToken = storage.get(KEYS.REFRESH_TOKEN)
  if (refreshToken) {
    const header = { 'Content-Type': 'application/json' }
    const res = await _rawRequest('POST', '/auth/refresh', { refresh_token: refreshToken }, header)
    if (res.statusCode === 200 && res.data && res.data.access_token) {
      storage.set(KEYS.TOKEN, res.data.access_token)
      storage.set(KEYS.TOKEN_EXPIRES_AT, res.data.expires_at)
      storage.set(KEYS.REFRESH_TOKEN, res.data.refresh_token)
      if (res.data.user) {
        storage.set(KEYS.USER, res.data.user)
      }
      return res.data.access_token
    }
    // Refresh token invalid → clear it, fall through to wx.login
    storage.remove(KEYS.REFRESH_TOKEN)
  }

  // Fallback: full re-auth via wx.login
  const code = await _wxLogin()
  const header = { 'Content-Type': 'application/json' }
  const res = await _rawRequest('POST', '/auth/login', { code }, header)
  if (res.statusCode !== 200 || !res.data || !res.data.access_token) {
    throw new Error('刷新 token 失败')
  }
  storage.set(KEYS.TOKEN, res.data.access_token)
  storage.set(KEYS.TOKEN_EXPIRES_AT, res.data.expires_at)
  storage.set(KEYS.REFRESH_TOKEN, res.data.refresh_token)
  if (res.data.user) {
    storage.set(KEYS.USER, res.data.user)
  }
  return res.data.access_token
}

// 主动续签：检查 token 过期时间，即将过期时提前刷新
// 跳过无需 token 的端点（登录/注册），避免不必要的 wx.login 调用
function _skipProactiveRefresh(url) {
  return url === '/auth/login'
}

async function ensureValidToken() {
  const token = storage.get(KEYS.TOKEN)
  if (!token) {
    console.log('[AUTH_DIAG] ensureValidToken: token missing in storage')
    return false
  }

  const expiresAt = storage.get(KEYS.TOKEN_EXPIRES_AT)
  if (!expiresAt) {
    console.log('[AUTH_DIAG] ensureValidToken: no expires_at, treating as valid')
    return true  // 无过期信息，视为有效
  }

  const timeToExpiry = expiresAt - Math.floor(Date.now() / 1000)
  console.log('[AUTH_DIAG] ensureValidToken: timeToExpiry=' + timeToExpiry + 's')
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

async function request(method, url, data = {}) {
  const traceId = _extractTraceId(data)
  const payload = _stripTraceId(data)

  // 主动续签：在发起请求前检查 token 是否需要刷新
  if (!_skipProactiveRefresh(url)) {
    await ensureValidToken()
  }

  const header = _buildHeader(traceId)

  // First attempt
  let res
  try {
    res = await _rawRequest(method, url, payload, header)
  } catch (err) {
    debugLog(traceId, 'API_ERROR', { method, url, message: err?.errMsg || '网络异常' })
    wx.showToast({ title: '网络异常', icon: 'none' })
    throw err
  }

  // Auto-refresh JWT on 401
  if (res.statusCode === 401) {
    debugLog(traceId, 'API_401_REFRESH', { method, url })

    // Global refresh lock: only one refresh at a time
    if (!_refreshing) {
      _refreshing = _refreshToken().finally(() => { _refreshing = null })
    }

    let newToken
    try {
      newToken = await _refreshing
    } catch (_e) {
      // Refresh failed → clear auth, redirect to login
      storage.remove(KEYS.TOKEN)
      storage.remove(KEYS.TOKEN_EXPIRES_AT)
      storage.remove(KEYS.REFRESH_TOKEN)
      storage.remove(KEYS.USER)
      if (!_redirecting) {
        _redirecting = true
        wx.redirectTo({ url: '/pages/login/login' })
      }
      throw { code: 401, message: '登录已过期，请重新登录' }
    }

    // Retry original request with new token
    header['Authorization'] = `Bearer ${newToken}`
    try {
      res = await _rawRequest(method, url, payload, header)
    } catch (err) {
      debugLog(traceId, 'API_ERROR', { method, url, message: err?.errMsg || '网络异常' })
      wx.showToast({ title: '网络异常', icon: 'none' })
      throw err
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
    throw { code: res.statusCode, message: res.data?.detail || '请求失败' }
  }

  return res.data
}

module.exports = {
  get: (url, data) => request('GET', url, data),
  post: (url, data) => request('POST', url, data),
  put: (url, data) => request('PUT', url, data),
  del: (url) => request('DELETE', url),
  resetRedirecting,
  ensureValidToken,
}
