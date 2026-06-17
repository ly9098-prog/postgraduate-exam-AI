const config = require('../config')
const storage = require('./storage')
const { debugLog, isDebugMode, saveDebugSnapshot } = require('./debug')

const { KEYS } = storage

let _refreshing = null
let _redirecting = false

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

// Refresh JWT token: wx.login → POST /auth/login → store new token
async function _refreshToken() {
  const code = await _wxLogin()
  const header = { 'Content-Type': 'application/json' }
  const res = await _rawRequest('POST', '/auth/login', { code }, header)
  if (res.statusCode !== 200 || !res.data || !res.data.access_token) {
    throw new Error('刷新 token 失败')
  }
  storage.set(KEYS.TOKEN, res.data.access_token)
  if (res.data.user) {
    storage.set(KEYS.USER, res.data.user)
  }
  return res.data.access_token
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
}
