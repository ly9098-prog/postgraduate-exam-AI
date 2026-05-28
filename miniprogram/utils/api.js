const config = require('../config')
const storage = require('./storage')
const { debugLog, isDebugMode, saveDebugSnapshot } = require('./debug')

const { KEYS } = storage

let _redirecting = false

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

function request(method, url, data = {}) {
  const traceId = _extractTraceId(data)
  const payload = _stripTraceId(data)
  return new Promise((resolve, reject) => {
    const token = storage.get(KEYS.TOKEN)
    const header = { 'Content-Type': 'application/json' }
    if (token) header['Authorization'] = `Bearer ${token}`
    if (traceId && isDebugMode()) header['X-Trace-Id'] = traceId

    wx.request({
      url: `${config.BASE_URL}${url}`,
      method,
      data: payload,
      header,
      timeout: 30000,
      success(res) {
        debugLog(traceId, 'API_RESPONSE', {
          method,
          url,
          statusCode: res.statusCode,
        })
        saveDebugSnapshot(traceId, 'api', {
          method,
          url,
          statusCode: res.statusCode,
          response: _summarizeResponseData(res.data),
        })
        if (res.statusCode === 401) {
          storage.remove(KEYS.TOKEN)
          storage.remove(KEYS.USER)
          if (!_redirecting) {
            _redirecting = true
            wx.redirectTo({ url: '/pages/login/login' })
          }
          return
        }
        if (res.statusCode >= 400) {
          reject({ code: res.statusCode, message: res.data?.detail || '请求失败' })
          return
        }
        resolve(res.data)
      },
      fail(err) {
        debugLog(traceId, 'API_ERROR', { method, url, message: err?.errMsg || '网络异常' })
        wx.showToast({ title: '网络异常', icon: 'none' })
        reject(err)
      },
    })
  })
}

module.exports = {
  get: (url, data) => request('GET', url, data),
  post: (url, data) => request('POST', url, data),
  put: (url, data) => request('PUT', url, data),
  del: (url) => request('DELETE', url),
}
