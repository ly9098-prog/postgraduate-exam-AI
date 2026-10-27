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

function _parseUploadResponseData(raw) {
  if (raw == null || raw === '') return {}
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch (_) {
    return {}
  }
}

module.exports = {
  ApiError,
  getResponseHeader: _getResponseHeader,
  safeHttpMessage: _safeHttpMessage,
  extractErrorCode: _extractErrorCode,
  safeErrorMeta: _safeErrorMeta,
  summarizeResponseData: _summarizeResponseData,
  parseUploadResponseData: _parseUploadResponseData,
}
