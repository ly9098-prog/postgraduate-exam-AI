const config = require('../config')

const SENSITIVE_KEYS = ['token', 'authorization', 'secret', 'password', 'openid']
const MAX_STRING_LENGTH = 500
const MAX_ARRAY_ITEMS = 20
const MAX_OBJECT_KEYS = 40
const MAX_DEPTH = 4
const MAX_SNAPSHOT_SIZE = 20000

function _isSensitiveKey(key) {
  const lower = String(key || '').toLowerCase()
  return SENSITIVE_KEYS.some(word => lower.indexOf(word) >= 0)
}

function _sanitizeDebugValue(value, depth = 0) {
  if (depth >= MAX_DEPTH) return '[truncated:depth]'
  if (Array.isArray(value)) {
    const items = value.slice(0, MAX_ARRAY_ITEMS).map(item => _sanitizeDebugValue(item, depth + 1))
    if (value.length > MAX_ARRAY_ITEMS) items.push({ _truncated_items: value.length - MAX_ARRAY_ITEMS })
    return items
  }
  if (value && typeof value === 'object') {
    const out = {}
    const keys = Object.keys(value)
    keys.slice(0, MAX_OBJECT_KEYS).forEach((key) => {
      out[key] = _isSensitiveKey(key) ? '[redacted]' : _sanitizeDebugValue(value[key], depth + 1)
    })
    if (keys.length > MAX_OBJECT_KEYS) out._truncated_keys = keys.length - MAX_OBJECT_KEYS
    return out
  }
  if (typeof value === 'string' && value.length > MAX_STRING_LENGTH) {
    return value.slice(0, MAX_STRING_LENGTH) + `...[truncated:${value.length - MAX_STRING_LENGTH}]`
  }
  return value
}

function _trimSnapshotPayload(payload) {
  let text = JSON.stringify(payload)
  if (!text || text.length <= MAX_SNAPSHOT_SIZE) return payload
  return {
    traceId: payload.traceId,
    stage: payload.stage,
    savedAt: payload.savedAt,
    data: {
      _truncated: true,
      summary: _sanitizeDebugValue(payload.data, 1),
    },
  }
}

function isDebugMode() {
  return !!config.DEBUG_MODE
}

function createTraceId() {
  if (!isDebugMode()) return ''
  const now = new Date()
  const yyyy = now.getFullYear()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  const random = Math.random().toString(16).slice(2, 8).padEnd(6, '0')
  return `TRACE_${yyyy}${mm}${dd}_${random}`
}

function shouldDebugQuestion(questionId) {
  if (!isDebugMode()) return false
  const target = config.DEBUG_QUESTION_ID
  if (target === undefined || target === null || target === '') return true
  return String(questionId) === String(target)
}

function debugLog(traceId, stage, data = {}) {
  if (!isDebugMode()) return
  const id = traceId || 'NO_TRACE'
  console.log(`[TRACE:${id}][${stage}]`, data)
}

function saveDebugSnapshot(traceId, stage, data = {}) {
  if (!isDebugMode() || !traceId || typeof wx === 'undefined') return
  const key = `debug_snapshot:${traceId}:${stage}:${Date.now()}`
  try {
    const payload = _trimSnapshotPayload({
      traceId,
      stage,
      savedAt: new Date().toISOString(),
      data: _sanitizeDebugValue(data),
    })
    wx.setStorageSync(key, payload)
  } catch (e) {
    debugLog(traceId, 'SNAPSHOT_ERROR', { stage, message: e && e.message })
  }
}

module.exports = {
  createTraceId,
  debugLog,
  isDebugMode,
  saveDebugSnapshot,
  shouldDebugQuestion,
}
