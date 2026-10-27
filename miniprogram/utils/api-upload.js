const storage = require('./storage')
const { ApiError, safeHttpMessage: _safeHttpMessage,
  parseUploadResponseData: _parseUploadResponseData, extractErrorCode: _extractErrorCode,
  safeErrorMeta: _safeErrorMeta } = require('./api-error')
const { generateCorrelationId: _generateCorrelationId,
  normalizeCorrelationId: _normalizeCorrelationId } = require('./api-correlation')
const { rawUploadFile: _rawUploadFile } = require('./api-transport')
const { ensureValidToken, forceRefreshToken } = require('./api-auth')

const { KEYS } = storage

function _buildUploadHeader(traceId, token, requestId) {
  const header = {
    'X-Trace-ID': traceId,
    'X-Request-ID': requestId,
  }
  if (token) header.Authorization = `Bearer ${token}`
  return header
}

async function _attemptUpload(context) {
  const { url, filePath, options, traceId, token, requestId } = context
  try {
    return await _rawUploadFile(
      url,
      filePath,
      options.name || 'file',
      options.formData || {},
      _buildUploadHeader(traceId, token, requestId),
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

function _finishUpload(context) {
  const { res, traceId, requestId } = context
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

  let requestId = _generateCorrelationId('req')
  let token = storage.get(KEYS.TOKEN)
  let res = await _attemptUpload({ url, filePath, options, traceId, token, requestId })

  if (res.statusCode === 401) {
    token = await forceRefreshToken(traceId)
    requestId = _generateCorrelationId('req')
    res = await _attemptUpload({ url, filePath, options, traceId, token, requestId })
  }

  return _finishUpload({ res, traceId, requestId })
}

module.exports = { uploadFile }
