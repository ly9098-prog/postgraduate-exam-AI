function _getAiAutoSettingKey(pageContext, { settingPrefix }) {
const userId = pageContext._getUserId()
return userId ? settingPrefix + String(userId) : ''
}

function _restoreAiAutoSetting(pageContext, { storageClient }) {
const key = pageContext._getAiAutoSettingKey()
const enabled = key ? storageClient.get(key) === true : false
pageContext.setData({
autoAiInsightEnabled: enabled,
aiInsightText: pageContext.data.aiDiagnosis
? pageContext.data.aiInsightText
: pageContext._getAiInsightIdleText(enabled),
})
}

function toggleAiAutoAnalysis(pageContext, { storageClient, getPlatform }) {
const enabled = !pageContext.data.autoAiInsightEnabled
const key = pageContext._getAiAutoSettingKey()
if (key) storageClient.set(key, enabled)
if (pageContext._aiAutoSwitchTimer) clearTimeout(pageContext._aiAutoSwitchTimer)
pageContext.setData({
autoAiInsightEnabled: enabled,
aiAutoSwitchPulse: true,
aiInsightText: pageContext.data.aiDiagnosis
? pageContext.data.aiInsightText
: pageContext._getAiInsightIdleText(enabled),
})
pageContext._aiAutoSwitchTimer = setTimeout(() => {
if (pageContext._alive) pageContext.setData({ aiAutoSwitchPulse: false })
pageContext._aiAutoSwitchTimer = null
}, 420)
if (!enabled) {
if (pageContext.data.aiDiagnosisLoading || pageContext.data.aiDiagnosisRefreshing) {
pageContext._aiDiagnosisRequestId++
pageContext.setData({ aiDiagnosisLoading: false, aiDiagnosisRefreshing: false, aiDiagnosisError: false })
}
getPlatform().showToast({ title: '已切换为手动分析', icon: 'none' })
return
}
getPlatform().showToast({ title: '已开启自动分析', icon: 'none' })
if (pageContext._aiStatsLoaded && Number((pageContext.data.stats || {}).total) > 0) {
const startAutoAnalysis = () => {
if (pageContext._alive && pageContext.data.autoAiInsightEnabled) {
pageContext.ensureAiDiagnosis({ background: true, refreshOnChange: true })
}
}
if (pageContext._aiDiagnosisPromise) pageContext._aiDiagnosisPromise.finally(startAutoAnalysis)
else startAutoAnalysis()
}
}

function _restoreAiDiagnosisFromCache(pageContext, { diagnosisCache }) {
var user = pageContext._getUser()
var userId = user && (user.id || user.user_id || user.openid || '')
var cache = diagnosisCache.restore(userId)
if (cache.status !== 'miss' && pageContext._hasAiDiagnosisContent(cache.data)) {
pageContext._aiDiagnosisCachedAt = cache.cachedAt
const normalized = pageContext._normalizeAiDiagnosis(cache.data)
const detailState = pageContext._buildAiInsightDetails(normalized)
pageContext.setData({
aiDiagnosis: normalized,
aiDiagnosisCacheTimeLabel: diagnosisCache.formatCacheTime(cache.cachedAt),
aiDiagnosisCacheStale: cache.status === 'stale',
aiDiagnosisError: false,
aiDiagnosisLoading: false,
aiDiagnosisRefreshing: false,
aiInsightText: pageContext._oneLineInsight(cache.data.summary) || pageContext.data.aiInsightText,
...detailState,
})
}
}

function _getUser({ storageClient }) {
try { return storageClient.get(storageClient.KEYS.USER) } catch (_) { return null }
}

function _getUserId(pageContext) {
var user = pageContext._getUser()
return user && (user.id || user.user_id || user.openid || '')
}

function _buildAiDiagnosisSourceSignature(pageContext, { diagnosisCache }) {
var stats = pageContext.data.stats || {}
var list = pageContext.data.list || []
var firstItem = list[0] || {}
return diagnosisCache.buildSignature(stats, list)
}

function _commitAiDiagnosisContent(pageContext, normalized, { diagnosisCache }) {
    var sig = pageContext._buildAiDiagnosisSourceSignature()
    var uid = pageContext._getUserId()
    var now = Date.now()
    pageContext._aiDiagnosisCachedAt = now
    diagnosisCache.save(uid, normalized, sig)
    var detailState = pageContext._buildAiInsightDetails(normalized)
    pageContext.setData({
      aiDiagnosis: normalized, aiDiagnosisLoading: false, aiDiagnosisRefreshing: false,
      aiDiagnosisCacheTimeLabel: diagnosisCache.formatCacheTime(now), aiDiagnosisCacheStale: false,
      aiDiagnosisError: false,
      aiInsightText: pageContext._oneLineInsight(normalized.summary) || pageContext.data.aiInsightText,
      ...detailState,
    })
    return normalized
  }

module.exports = { _getAiAutoSettingKey, _restoreAiAutoSetting, toggleAiAutoAnalysis, _restoreAiDiagnosisFromCache, _getUser, _getUserId, _buildAiDiagnosisSourceSignature, _commitAiDiagnosisContent }
