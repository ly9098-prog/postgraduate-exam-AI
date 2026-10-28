const examAttemptCache = require('./exam-attempt-cache')
const api = require('../../../utils/api')

const EXAM_CACHE_SCHEMA_VERSION = 3
// 本地草稿保留时长：离开作答页后 60 分钟内可恢复，超时进入重新作答状态。
const EXAM_DRAFT_TTL_MS = 60 * 60 * 1000
// 到时后如果因为断网尚未完成交卷，pending 答案需要比普通草稿保留更久。
// 只有服务端确认终态后才主动清理；7 天上限用于防止异常缓存永久占用空间。
const EXAM_SUBMIT_PENDING_TTL_MS = 7 * 24 * 60 * 60 * 1000
const { cacheKey, v2CacheKey, legacyCacheKey } = examAttemptCache

function isPendingItemKey(value) { return /^\d+$/.test(String(value || '')) }

function sanitizePendingItems(raw) {
  const source = raw && typeof raw === 'object' ? raw : {}
  const result = Object.create(null)
  Object.keys(source).forEach((key) => {
    if (!isPendingItemKey(key)) return
    const value = source[key]
    if (!value || typeof value !== 'object') return
    result[String(Number(key))] = {
      selected_answer: String(value.selected_answer || '').trim().toUpperCase() || null,
      marked_for_review: !!value.marked_for_review,
      used_time: Math.min(6 * 60 * 60, Math.max(0, Number(value.used_time || 0))),
    }
  })
  return result
}

function buildExamPendingCachePageCapabilities(page) {
  return {
    readStorage: key => wx.getStorageSync(key),
    writeStorage: (key, value) => wx.setStorageSync(key, value),
    removeStorage: key => wx.removeStorageSync(key),
    cacheKey,
    v2CacheKey,
    legacyCacheKey,
    clearPendingAttempt: attemptId => examAttemptCache.clearPendingAttempt(attemptId),
    now: () => api.now(),
    sanitizePendingItems,
    isPendingItemKey,
    getSchemaVersion: () => EXAM_CACHE_SCHEMA_VERSION,
    getDraftTtlMs: () => EXAM_DRAFT_TTL_MS,
    getSubmitPendingTtlMs: () => EXAM_SUBMIT_PENDING_TTL_MS,
    setRetainPendingForSubmit: value => { page._retainPendingForSubmit = value },
  }
}

module.exports = {
  buildExamPendingCachePageCapabilities,
  isPendingItemKey,
}
