function _getAiInsightIdleText(enabled) {
return enabled
? '自动分析已开启，进入错题本时会生成最新洞察'
: '自动分析已关闭，点击生成获取 AI 洞察'
}

function _normalizeAiDiagnosis(raw) {
if (!raw) return null
var copy = JSON.parse(JSON.stringify(raw))
var diagnosisListKeys = ['weak_points', 'strong_points', 'learning_suggestions']
for (var listKeyIndex = 0; listKeyIndex < diagnosisListKeys.length; listKeyIndex++) {
var listKey = diagnosisListKeys[listKeyIndex]
if (!Array.isArray(copy[listKey])) copy[listKey] = []
}
var diagnosisPointKeys = ['weak_points', 'strong_points']
for (var diagnosisKeyIndex = 0; diagnosisKeyIndex < diagnosisPointKeys.length; diagnosisKeyIndex++) {
var key = diagnosisPointKeys[diagnosisKeyIndex]
copy[key] = copy[key].map(function(item) {
if (!item || typeof item !== 'object') return null
var acc = item.accuracy
if (typeof acc !== 'number') acc = 0
if (acc > 1) acc = Math.min(acc, 100)
var pct = acc <= 1 ? Math.round(acc * 100) : Math.round(acc)
pct = Math.max(0, Math.min(100, pct))
return {
knowledge_point: String(item.knowledge_point || ''),
accuracy: acc,
_accuracyPercent: pct,
suggestion: String(item.suggestion || ''),
}
}).filter(function(item) { return item && item.knowledge_point })
}
copy.learning_suggestions = copy.learning_suggestions.filter(function(s) { return s && String(s).trim() })
return copy
}

function _hasAiDiagnosisContent(pageContext, value) {
if (!value || typeof value !== 'object') return false
const normalized = pageContext._normalizeAiDiagnosis(value)
return !!(
(normalized.summary && String(normalized.summary).trim()) ||
(normalized.weak_points && normalized.weak_points.length) ||
(normalized.strong_points && normalized.strong_points.length) ||
(normalized.learning_suggestions && normalized.learning_suggestions.length)
)
}

function _isAiDiagnosisPending(value) {
if (!value || typeof value !== 'object') return false
const status = String(value.status || value.state || value.generation_status || '').toLowerCase()
const message = String(value.message || value.detail || value.summary || '').toLowerCase()
const pendingText = /正在生成|生成中|处理中|排队中|generating|processing|queued/.test(message)
return ['pending', 'processing', 'generating', 'queued', 'running'].includes(status) || value.generating === true || pendingText
}

function _buildAiInsightDetails(diagnosis) {
const data = diagnosis || {}
const weakPoints = (Array.isArray(data.weak_points) ? data.weak_points : [])
.slice(0, 3)
.map(item => ({
name: String((item && item.knowledge_point) || '待识别薄弱点'),
accuracyPercent: Number(
item && typeof item._accuracyPercent === 'number'
? item._accuracyPercent
: Math.round(Math.max(0, Math.min(1, Number((item && item.accuracy) || 0))) * 100)
),
suggestion: String((item && item.suggestion) || ''),
}))
const suggestions = (Array.isArray(data.learning_suggestions) ? data.learning_suggestions : [])
.map(item => String(item || '').trim())
.filter(Boolean)
.slice(0, 3)
return {
aiInsightWeakPoints: weakPoints,
aiInsightSuggestions: suggestions,
aiInsightHasDetails: weakPoints.length > 0 || suggestions.length > 0,
}
}

module.exports = { _getAiInsightIdleText, _normalizeAiDiagnosis, _hasAiDiagnosisContent, _isAiDiagnosisPending, _buildAiInsightDetails }
