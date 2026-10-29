async function _checkAiDiagnosis(pageContext, { diagnosisCache }) {
if (pageContext._destroyed) return null
var stats = pageContext.data.stats || {}
var total = stats.total
if (!pageContext._aiStatsLoaded) {
return pageContext.data.aiDiagnosis || null
}
if (total === 0) {
if (pageContext.data.aiDiagnosis) {
var uid = pageContext._getUserId()
diagnosisCache.clear(uid)
pageContext.setData({
aiDiagnosis: null,
aiDiagnosisLoading: false,
aiDiagnosisRefreshing: false,
aiDiagnosisCacheTimeLabel: '',
aiDiagnosisCacheStale: false,
aiDiagnosisError: false,
aiInsightExpanded: false,
aiInsightHasDetails: false,
aiInsightWeakPoints: [],
aiInsightSuggestions: [],
})
} else {
pageContext.setData({ aiDiagnosisLoading: false })
}
return null
}
if (!pageContext.data.autoAiInsightEnabled) {
return pageContext.data.aiDiagnosis || null
}
return pageContext.ensureAiDiagnosis({ background: true, refreshOnChange: true })
}

function _delay(ms) {
return new Promise(resolve => setTimeout(resolve, ms))
}

async function _pollAiDiagnosis(pageContext, initial, requestId, { requestClient, timeoutMs }) {
let current = initial
for (let attempt = 0; attempt < 4 && pageContext._isAiDiagnosisPending(current); attempt++) {
await pageContext._delay(1200 + attempt * 350)
if (requestId !== pageContext._aiDiagnosisRequestId || !pageContext._alive) return null
current = await requestClient.get('/stats/ai-diagnosis', {}, { timeout: timeoutMs })
}
return current
}

async function ensureAiDiagnosis(pageContext, options, { diagnosisCache }) {
options = options || {}
if (pageContext._aiStatsLoaded) {
var total = (pageContext.data.stats || {}).total
if (total === 0) return null
}
if (pageContext._aiDiagnosisPromise) return pageContext._aiDiagnosisPromise
if (options.force) {
return pageContext._requestAiDiagnosis({ force: true })
}
var hasData = !!pageContext.data.aiDiagnosis
if (hasData && !options.background) {
return pageContext.data.aiDiagnosis
}
var needRefresh = false
var sourceChanged = false
if (!hasData) {
needRefresh = true
} else {
var cachedAt = pageContext._aiDiagnosisCachedAt
var isStale = pageContext.data.aiDiagnosisCacheStale || diagnosisCache.isExpired(cachedAt, pageContext.data.aiDiagnosis)
if (isStale) {
needRefresh = true
} else {
var currentSig = pageContext._buildAiDiagnosisSourceSignature()
var uid = pageContext._getUserId()
var cache = diagnosisCache.restore(uid)
if (cache.signature && cache.signature !== currentSig && (options.refreshOnChange || diagnosisCache.canRefresh(cachedAt))) {
needRefresh = true
sourceChanged = true
}
}
}
if (!needRefresh) {
return pageContext.data.aiDiagnosis
}
return pageContext._requestAiDiagnosis({ background: true, refresh: sourceChanged })
}

async function _requestAiDiagnosis(pageContext, opts) {
    opts = opts || {}
    var hasData = !!pageContext.data.aiDiagnosis
    var requestId = ++pageContext._aiDiagnosisRequestId
    pageContext.setData(hasData ? { aiDiagnosisRefreshing: true, aiDiagnosisError: false } : { aiDiagnosisLoading: true, aiDiagnosisError: false })
    pageContext._aiDiagnosisPromise = pageContext._executeAiDiagnosisRequest(opts, hasData, requestId)
    return pageContext._aiDiagnosisPromise
  }

async function _executeAiDiagnosisRequest(pageContext, opts, hasData, requestId) {
    try {
      var diagnosis = await pageContext._fetchAiDiagnosisData(opts, requestId)
      if (requestId !== pageContext._aiDiagnosisRequestId || !pageContext._alive) return pageContext.data.aiDiagnosis
      return pageContext._applyAiDiagnosisResult(diagnosis, hasData)
    } catch (e) {
      return pageContext._handleAiDiagnosisError(e, opts, hasData, requestId)
    } finally {
      pageContext._aiDiagnosisPromise = null
    }
  }

async function _fetchAiDiagnosisData(pageContext, opts, requestId, { requestClient, timeoutMs }) {
    var params = (opts.force || opts.refresh) ? { refresh: true } : {}
    var diagnosis = await requestClient.get('/stats/ai-diagnosis', params, { timeout: timeoutMs })
    if (pageContext._isAiDiagnosisPending(diagnosis)) {
      diagnosis = await pageContext._pollAiDiagnosis(diagnosis, requestId)
    }
    if (pageContext._isAiDiagnosisPending(diagnosis)) {
      throw new Error(String((diagnosis && (diagnosis.detail || diagnosis.message)) || 'AI 解析仍在生成，请稍后重试'))
    }
    return diagnosis
  }

function _applyAiDiagnosisResult(pageContext, diagnosis, hasData) {
    var normalized = pageContext._normalizeAiDiagnosis(diagnosis)
    var hasContent = pageContext._hasAiDiagnosisContent(normalized)
    if (hasContent) return pageContext._commitAiDiagnosisContent(normalized)
    if (hasData) {
      pageContext.setData({ aiDiagnosisLoading: false, aiDiagnosisRefreshing: false })
      return pageContext.data.aiDiagnosis
    }
    pageContext.setData({ aiDiagnosis: null, aiDiagnosisLoading: false, aiDiagnosisRefreshing: false, aiDiagnosisError: true })
    return null
  }

function _handleAiDiagnosisError(pageContext, e, opts, hasData, requestId, { getPlatform }) {
    console.error('加载 AI 诊断失败', e)
    if (requestId !== pageContext._aiDiagnosisRequestId || !pageContext._alive) return pageContext.data.aiDiagnosis
    if (hasData) {
      pageContext.setData({ aiDiagnosisLoading: false, aiDiagnosisRefreshing: false })
      if (opts.force) {
        getPlatform().showToast({ title: (e && typeof e.message === 'string' && e.message) || '更新失败，请稍后重试', icon: 'none' })
      }
      return pageContext.data.aiDiagnosis
    }
    pageContext.setData({ aiDiagnosis: null, aiDiagnosisLoading: false, aiDiagnosisRefreshing: false, aiDiagnosisError: true })
    return null
  }

module.exports = { _checkAiDiagnosis, _delay, _pollAiDiagnosis, ensureAiDiagnosis, _requestAiDiagnosis, _executeAiDiagnosisRequest, _fetchAiDiagnosisData, _applyAiDiagnosisResult, _handleAiDiagnosisError }
