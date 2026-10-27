function _generateCorrelationId(prefix) {
  const random = Math.random().toString(36).slice(2, 12)
  return `${prefix}_${Date.now().toString(36)}${random}`.slice(0, 64)
}

function _normalizeCorrelationId(value, prefix) {
  const text = typeof value === 'string' ? value.trim() : ''
  if (/^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(text)) return text
  return _generateCorrelationId(prefix)
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

module.exports = {
  generateCorrelationId: _generateCorrelationId,
  normalizeCorrelationId: _normalizeCorrelationId,
  extractTraceId: _extractTraceId,
  stripTraceId: _stripTraceId,
}
