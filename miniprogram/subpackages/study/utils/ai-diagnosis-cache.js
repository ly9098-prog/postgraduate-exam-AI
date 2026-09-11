
var storage = require('../../../utils/storage')
var chinaTime = require('../../../utils/china-time')
var CACHE_VERSION = 1
var CACHE_PREFIX = 'wrong_book_ai_diagnosis'
var CACHE_TTL = 6 * 60 * 60 * 1000
var FALLBACK_CACHE_TTL = 2 * 60 * 1000
var MIN_REFRESH_INTERVAL = 5 * 60 * 1000
function ttlFor(diagnosis) {
return diagnosis && diagnosis.generated === false ? FALLBACK_CACHE_TTL : CACHE_TTL
}
function isExpired(cachedAt, diagnosis) {
var timestamp = Number(cachedAt)
if (!timestamp || !isFinite(timestamp)) return true
return Date.now() >= timestamp + ttlFor(diagnosis)
}
function buildCacheKey(userId) {
if (!userId) return null
return CACHE_PREFIX + '_v' + CACHE_VERSION + '_' + userId
}
function buildSignature(stats, items) {
if (!stats) return ''
var first = items && items[0]
var parts = {
t: stats.total || 0,
u: stats.unmastered || 0,
i: first ? first.id || '' : '',
a: first ? (first.last_wrong_at || first.last_error_at || first.updated_at || '') : '',
}
return JSON.stringify(parts)
}
function restore(userId) {
var key = buildCacheKey(userId)
if (!key) return { status: 'miss', data: null, cachedAt: 0, signature: '' }
var raw
try { raw = storage.get(key) } catch (e) { raw = null }
if (!raw || typeof raw !== 'object') return { status: 'miss', data: null, cachedAt: 0, signature: '' }
if (raw.version !== CACHE_VERSION) {
try { storage.remove(key) } catch (_) {}
return { status: 'miss', data: null, cachedAt: 0, signature: '' }
}
if (raw.userKey && raw.userKey !== String(userId)) {
try { storage.remove(key) } catch (_) {}
return { status: 'miss', data: null, cachedAt: 0, signature: '' }
}
if (!raw.data || typeof raw.data !== 'object') {
try { storage.remove(key) } catch (_) {}
return { status: 'miss', data: null, cachedAt: 0, signature: '' }
}
var data = raw.data
var hasContent = !!(
(data.summary && String(data.summary).trim()) ||
(data.weak_points && data.weak_points.length > 0) ||
(data.strong_points && data.strong_points.length > 0) ||
(data.learning_suggestions && data.learning_suggestions.length > 0)
)
if (!hasContent) {
try { storage.remove(key) } catch (_) {}
return { status: 'miss', data: null, cachedAt: 0, signature: '' }
}
var now = Date.now()
var cachedAt = raw.cachedAt || 0
var expiresAt = raw.expiresAt || (cachedAt + ttlFor(data))
if (now < expiresAt) {
return { status: 'fresh', data: data, cachedAt: cachedAt, signature: raw.sourceSignature || '' }
}
return { status: 'stale', data: data, cachedAt: cachedAt, signature: raw.sourceSignature || '' }
}
function save(userId, diagnosis, signature) {
if (!userId) return
if (!diagnosis) return
var hasContent = !!(
(diagnosis.summary && String(diagnosis.summary).trim()) ||
(diagnosis.weak_points && diagnosis.weak_points.length > 0) ||
(diagnosis.strong_points && diagnosis.strong_points.length > 0) ||
(diagnosis.learning_suggestions && diagnosis.learning_suggestions.length > 0)
)
if (!hasContent) return
var key = buildCacheKey(userId)
if (!key) return
var now = Date.now()
var payload = {
version: CACHE_VERSION,
userKey: String(userId),
data: diagnosis,
cachedAt: now,
expiresAt: now + ttlFor(diagnosis),
sourceSignature: signature || '',
}
try { storage.set(key, payload) } catch (_) {}
}
function clear(userId) {
var key = buildCacheKey(userId)
if (key) {
try { storage.remove(key) } catch (_) {}
}
}
function canRefresh(cachedAt) {
if (!cachedAt) return true
return (Date.now() - cachedAt) >= MIN_REFRESH_INTERVAL
}
function formatCacheTime(timestamp) {
if (!timestamp) return ''
var ms = Number(timestamp)
if (!isFinite(ms)) return ''
var diff = Date.now() - ms
var minutes = Math.floor(diff / 60000)
if (minutes < 1) return '刚刚更新'
if (minutes < 60) return minutes + ' 分钟前更新'
var hours = Math.floor(minutes / 60)
if (hours < 6) return hours + ' 小时前更新'
var dayDiff = chinaTime.chinaCalendarDayDiff(ms, Date.now())
var timeText = chinaTime.formatChinaTimeHM(ms)
if (dayDiff === 0) return '今天 ' + timeText + ' 更新'
if (dayDiff === 1) return '昨天 ' + timeText + ' 更新'
return chinaTime.formatChinaMonthDayCn(ms) + '更新'
}
module.exports = {
CACHE_TTL: CACHE_TTL,
FALLBACK_CACHE_TTL: FALLBACK_CACHE_TTL,
MIN_REFRESH_INTERVAL: MIN_REFRESH_INTERVAL,
isExpired: isExpired,
buildCacheKey: buildCacheKey,
buildSignature: buildSignature,
restore: restore,
save: save,
clear: clear,
canRefresh: canRefresh,
formatCacheTime: formatCacheTime,
}
