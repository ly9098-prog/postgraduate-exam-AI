function _isCurrentAiRequest(page, requestId, wqId) {
return requestId === page._aiRequestId &&
page._alive &&
page.data.wq &&
String(page.data.wq.id) === String(wqId)
}

async function _pollPersistedAiAnalysis(page, wqId, requestId, options, { AI_CACHE_POLL_ATTEMPTS, _sleep, _aiPollDelayMs, fetchStatus, _normalizeAiPayload, _hasAiContent }) {
const pollOptions = options || {}
const baselineGeneratedAt = String(pollOptions.baselineGeneratedAt || '')
const requireNewGeneration = !!pollOptions.requireNewGeneration
for (var attempt = 0; attempt < AI_CACHE_POLL_ATTEMPTS; attempt++) {
if (!page._isCurrentAiRequest(requestId, wqId)) return null
if (attempt > 0) await _sleep(_aiPollDelayMs(attempt))
if (!page._isCurrentAiRequest(requestId, wqId)) return null
try {
const status = await fetchStatus(wqId)
if (!page._isCurrentAiRequest(requestId, wqId)) return null
if (!status || !status.ready) continue
const generatedAt = String(status.generated_at || '')
if (requireNewGeneration && generatedAt === baselineGeneratedAt) continue
const normalized = _normalizeAiPayload(status.content)
if (_hasAiContent(normalized)) {
const latestWq = Object.assign({}, page.data.wq || {}, {
ai_analysis: normalized,
ai_analysis_status: 'ready',
ai_analysis_generated_at: generatedAt,
})
return { normalized, latestWq, generatedAt }
}
} catch (_) {
}
}
return null
}

function _applyRecoveredAiResult(page, recovered, options, { _generationMarker, _normalizeAiResult }) {
if (!recovered) return false
const applyOptions = options || {}
page._resetAiLoadingState()
page._aiResult = recovered.normalized
page._aiGenerationMarker = String(recovered.generatedAt || _generationMarker(recovered.latestWq) || '')
if (recovered.latestWq) {
page._syncWqCacheAi(
recovered.latestWq.id,
recovered.normalized,
page._aiGenerationMarker
)
}
const latestWq = recovered.latestWq || page.data.wq
page.setData({
wq: latestWq,
aiCards: _normalizeAiResult(recovered.normalized),
aiFallback: false,
aiFromCache: !applyOptions.fromRegeneration,
aiFromQuestionAnalysis: false,
aiErrorText: '',
aiRetryable: true,
aiInlineNotice: '',
})
return true
}

module.exports = { _isCurrentAiRequest, _pollPersistedAiAnalysis, _applyRecoveredAiResult }
