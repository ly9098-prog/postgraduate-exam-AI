/**
 * 番茄钟科目树本地缓存（24 小时）。
 *
 * 用途：避免每次进入番茄钟页面都请求 /practice/subjects。
 * 与后端 24h Redis 缓存互补：后端省数据库查询，本地省网络请求。
 *
 * 失败策略：任何读写/解析失败都当作“无缓存”，绝不因为缓存损坏阻塞页面。
 */

const SUBJECT_CACHE_KEY = 'pomodoro_subject_cache_v1'
const SUBJECT_CACHE_TTL_MS = 24 * 60 * 60 * 1000

function isCacheValid(entry, now) {
  if (!entry || !Array.isArray(entry.subjects)) return false
  const savedAt = Number(entry.savedAt)
  if (!Number.isFinite(savedAt) || savedAt <= 0) return false
  // 时钟回拨时 savedAt 可能大于 now；此时按未过期处理，避免频繁失效。
  if (now - savedAt > SUBJECT_CACHE_TTL_MS) return false
  return entry.subjects.length > 0
}

function readSubjectCache(now) {
  const current = Number.isFinite(now) ? now : Date.now()
  try {
    const entry = wx.getStorageSync(SUBJECT_CACHE_KEY)
    if (!isCacheValid(entry, current)) return null
    return entry.subjects
  } catch (e) {
    return null
  }
}

function writeSubjectCache(subjects) {
  if (!Array.isArray(subjects) || subjects.length === 0) return false
  try {
    wx.setStorageSync(SUBJECT_CACHE_KEY, {
      savedAt: Date.now(),
      subjects,
    })
    return true
  } catch (e) {
    return false
  }
}

function clearSubjectCache() {
  try {
    wx.removeStorageSync(SUBJECT_CACHE_KEY)
  } catch (e) {
    // best-effort
  }
}

module.exports = {
  SUBJECT_CACHE_KEY,
  SUBJECT_CACHE_TTL_MS,
  isCacheValid,
  readSubjectCache,
  writeSubjectCache,
  clearSubjectCache,
}
