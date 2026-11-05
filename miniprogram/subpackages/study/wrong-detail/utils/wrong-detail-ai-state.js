function _aiPollDelayMs(attempt) {
if (attempt <= 5) return 2000
if (attempt <= 15) return 3000
return 5000
}

function _isTimeoutError(err) {
const message = [
err && err.message,
err && err.raw && err.raw.errMsg,
].filter(Boolean).join(' ').toLowerCase()
return message.includes('timeout') || message.includes('timed out')
}

function _shouldRecoverAiRequest(err) {
const statusCode = Number(err && err.statusCode)
return statusCode === 408 || statusCode === 502 || statusCode === 504 ||
(statusCode === 0 && !!(err && (err.name === 'ApiError' || err.code === 'NETWORK_ERROR'))) ||
((!Number.isFinite(statusCode) || statusCode === 0) && _isTimeoutError(err))
}

function _generationMarker(wq) {
return String((wq && wq.ai_analysis_generated_at) || '')
}

function _fallbackMessage(model, errorCode, retryable) {
if (errorCode === 'ai_service_unavailable') return 'AI 服务暂时不可用，请稍后重试'
if (errorCode === 'availability_checking') return '正在确认 AI 服务状态，恢复后可重试'
if (errorCode === 'availability_quota' || errorCode === 'ai_provider_quota_exceeded') return 'AI 服务额度暂不足，恢复后可重试'
if (errorCode === 'availability_user_quota') return '今日 AI 使用额度已用尽，可先查看参考答案'
if (errorCode === 'availability_configuration' || errorCode === 'ai_provider_auth_failed') return 'AI 服务连接异常，待服务恢复后可重试'
if (errorCode === 'availability_unconfigured' || errorCode === 'ai_model_unconfigured') return 'AI 复盘服务暂未就绪，可先查看参考答案'
if (errorCode === 'ai_provider_rate_limited') return 'AI 服务当前繁忙，请稍后重试'
if (errorCode === 'ai_provider_timeout') return 'AI 分析生成超时，请稍后重试'
if (errorCode === 'ai_provider_transient') return 'AI 服务暂时不可用，请稍后重试'
if (errorCode === 'ai_response_parse_failed') return 'AI 返回格式异常，请重新生成'
if (model === 'timeout') return 'AI 分析生成超时，请稍后重试'
if (model === 'parse_failed') return 'AI 返回格式异常，请重新生成'
if (model === 'vision_input_missing') return '题目图片缺失或无法读取，AI 解析失败'
if (model === 'vision_unavailable') return '暂时无法分析题目图片，可先查看参考答案'
if (model === 'vision_parse_failed') return 'AI 未能正确读取题目图片，解析失败，请稍后重试'
if (retryable === false) return '这道题暂时无法生成复盘，可先查看参考答案'
return 'AI 服务暂时不可用，请稍后重试'
}

function _isWqMastered(wq) {
if (!wq) return false
return wq.is_mastered === true ||
wq.mastered === true ||
wq.review_status === 'mastered' ||
wq.status === 'mastered'
}

function _normalizeAiResult(content, _buildAiRichText) {
const diagnosis = content.mistake_diagnosis || content.error_analysis || ''
const knowledge = content.knowledge_patch || content.knowledge_weakness || ''
const task = content.review_task || content.suggestion || ''
return {
mistakeDiagnosis: _buildAiRichText(String(diagnosis).replace(/^错因诊断[：:]\s*/, '')),
knowledgePatch: _buildAiRichText(String(knowledge).replace(/^补漏重点[：:]\s*/, '')),
reviewTask: _buildAiRichText(String(task).replace(/^复练任务[：:]\s*/, '')),
formatError: !!(content && content.formatError),
}
}

function _hasStoredAnalysisValue(raw, normalizeAiAnalysisPayload, hasAiAnalysisContent) {
if (raw === null || raw === undefined) return false
if (typeof raw === 'string') {
const t = raw.trim()
if (!t) return false
if (/^(null|true|false|undefined|\[\]|\{\}|-?\d+(?:\.\d+)?)$/i.test(t)) return false
return true
}
if (Array.isArray(raw)) return raw.length > 0
if (typeof raw === 'object') {
if (Object.keys(raw).length === 0) return false
return hasAiAnalysisContent(normalizeAiAnalysisPayload(raw))
}
return true
}

function _resolvePreferredAnalysis(wq, _hasStoredAnalysisValue, _normalizeAiPayload) {
if (!wq) return null
if ((!wq.ai_analysis_status || wq.ai_analysis_status === 'ready') && _hasStoredAnalysisValue(wq.ai_analysis)) {
return {
normalized: _normalizeAiPayload(wq.ai_analysis),
source: 'ai',
}
}
if (_hasStoredAnalysisValue(wq.analysis)) {
return {
normalized: _normalizeAiPayload(wq.analysis),
source: 'question',
}
}
return null
}

module.exports = { _aiPollDelayMs, _isTimeoutError, _shouldRecoverAiRequest, _generationMarker, _fallbackMessage, _isWqMastered, _normalizeAiResult, _hasStoredAnalysisValue, _resolvePreferredAnalysis }
