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
const patch = { ai_analysis: normalized, ai_analysis_status: 'ready' }
if (generatedAt !== undefined) patch.ai_analysis_generated_at = String(generatedAt || '')
entry.data = Object.assign({}, entry.data, patch)
}

async function _requestAiAnalysis(wqId, forceRegenerate, { postAnalysis, AI_REQUEST_TIMEOUT_MS, applyAvailability, waitForAvailability, isCurrent }) {
const request = () => postAnalysis({
wrong_question_id: wqId,
force_regenerate: !!forceRegenerate,
}, {
timeout: AI_REQUEST_TIMEOUT_MS,
suppressNetworkToast: true,
})
const result = await request()
if (result && result.error_code === 'ai_service_unavailable' && result.availability &&
  result.availability.status === 'checking' && waitForAvailability && isCurrent()) {
applyAvailability(result.availability)
return await waitForAvailability(request) || result
}
return result
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
const value = result || {}
const detail = value.detail || (value.raw && value.raw.data && value.raw.data.detail) || {}
const code = value.error_code || detail.error_code || detail.code || value.code
const availability = value.availability || detail.availability ||
  (detail.status === 'unavailable' || detail.status === 'checking' ? detail : null)
const status = Number(value.statusCode) || 0
const messages = {
401: '登录状态已失效，可返回首页重新登录',
403: '当前暂不能生成这道题的复盘，可先查看参考答案',
404: '这道错题已不存在，请返回错题本',
409: '题目信息已更新，请返回错题本重新进入',
422: '题目信息暂无法用于复盘，可先查看参考答案',
429: 'AI 服务当前繁忙，请稍后重试',
}
return {
aiErrorText: availability
  ? _fallbackMessage('', 'availability_' + availability.reason)
  : messages[status] || _fallbackMessage(model, code, value.retryable),
aiRetryable: availability ? true
  : ![401, 403, 404, 409, 422].includes(status) && value.retryable !== false,
}
}

function onTapAiAnalysis(page, { showToast, runWhenAvailable }) {
if (page.data.aiLoading || page.data.aiRegenerating) return
if (page.data.aiAvailabilityStatus === 'checking' && page.data.aiAvailabilityEnabled !== true) {
const wqId = page._currentWqId || (page.data.wq && page.data.wq.id)
if (wqId) return runWhenAvailable(wqId, () => page.loadAiAnalysis(wqId))
return
}
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
