function _resetAiLoadingState(page) {
page.setData({
aiLoading: false,
aiRegenerating: false,
aiSkeletonVisible: false,
aiInlineNotice: '',
})
}

function _syncWqCacheAi(page, wqId, normalized, generatedAt) {
if (!page._wqCache || !wqId || !normalized) return
const entry = page._wqCache[wqId]
if (!entry) return
const patch = { ai_analysis: normalized }
if (generatedAt !== undefined) patch.ai_analysis_generated_at = String(generatedAt || '')
entry.data = Object.assign({}, entry.data, patch)
}

async function _requestAiAnalysis(wqId, forceRegenerate, { postAnalysis, AI_REQUEST_TIMEOUT_MS }) {
return postAnalysis({
wrong_question_id: wqId,
force_regenerate: !!forceRegenerate,
}, {
timeout: AI_REQUEST_TIMEOUT_MS,
suppressNetworkToast: true,
})
}

async function _enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt, { postRecovery }) {
try {
const payload = {
wrong_question_id: wqId,
force_regenerate: !!forceRegenerate,
}
if (forceRegenerate) payload.baseline_generated_at = String(baselineGeneratedAt || '')
const result = await postRecovery(payload, {
timeout: 10000,
suppressNetworkToast: true,
})
return !!(result && result.queued)
} catch (e) {
console.warn('AI 恢复任务入队失败，将继续轮询原请求结果', e)
return false
}
}

function _analysisFailureState(model, result, { _fallbackMessage }) {
return {
aiErrorText: _fallbackMessage(
model,
result && result.error_code,
result && result.retryable
),
aiRetryable: !(result && result.retryable === false),
}
}

function onTapAiAnalysis(page, { showToast }) {
if (page.data.aiLoading || page.data.aiRegenerating) return
if (page.data.aiAvailabilityEnabled !== true) {
showToast({ title: page.data.aiAvailabilityMessage || 'AI 服务暂不可用', icon: 'none' })
if (page.data.aiAvailabilityStatus !== 'checking' && page._refreshAiAvailability) {
page._refreshAiAvailability({ force: true, silent: true })
}
return
}
const wqId = page._currentWqId || (page.data.wq && page.data.wq.id)
if (!wqId) {
showToast({ title: '缺少错题ID', icon: 'none' })
return
}
page.loadAiAnalysis(wqId)
}

module.exports = { _resetAiLoadingState, _syncWqCacheAi, _requestAiAnalysis, _enqueueAiRecovery, _analysisFailureState, onTapAiAnalysis }
