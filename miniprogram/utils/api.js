const { ApiError } = require('./api-error')
const { resetRedirecting, ensureValidToken, forceRefreshToken,
  normalizeExpiresAt: _normalizeExpiresAt } = require('./api-auth')
const { generateCorrelationId: _generateCorrelationId } = require('./api-correlation')
const { now } = require('./api-clock')
const { request } = require('./api-request')
const { uploadFile } = require('./api-upload')

// ═══════════════════════════════════════════════
// 统一 API 错误对象
// 页面统一使用：error.code / error.statusCode / error.message。
// error.message 只允许前端安全文案，禁止直接透传后端 detail/error.message。
// ═══════════════════════════════════════════════
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
