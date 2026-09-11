
var MAX_DEPTH = 6
var WRAPPER_KEYS = ['content', 'data', 'result', 'analysis', 'ai_analysis', 'payload']
var DIAGNOSIS_KEYS = [
'mistake_diagnosis', 'error_analysis', 'diagnosis',
'mistakeDiagnosis', 'mistakediagnosis', '错因诊断',
]
var KNOWLEDGE_KEYS = [
'knowledge_patch', 'knowledge_weakness', 'knowledge',
'knowledgePatch', 'knowledgepatch', '补漏重点',
]
var TASK_KEYS = [
'review_task', 'suggestion', 'task',
'reviewTask', 'reviewtask', 'reviewask', '复练任务',
]
var ALL_KNOWN_KEYS = []
.concat(DIAGNOSIS_KEYS)
.concat(KNOWLEDGE_KEYS)
.concat(TASK_KEYS)
var TEXT_SUB_KEYS = ['text', 'content', 'value', 'description']
function _safeParse(str) {
try { return JSON.parse(str) } catch (_) { return null }
}
function _looksLikeJson(str) {
if (typeof str !== 'string' || !str) return false
var t = str.trim()
if (!t) return false
if (/^```(?:json|javascript|js)?/i.test(t)) return true
if (t.charAt(0) === '{' || t.charAt(0) === '[') return true
for (var i = 0; i < ALL_KNOWN_KEYS.length; i++) {
var escaped = ALL_KNOWN_KEYS[i].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
var re = new RegExp("[\"']" + escaped + "[\"']\\s*:", 'i')
if (re.test(t)) return true
}
return false
}
function _stripFence(str) {
var value = String(str || '').trim()
var m = value.match(/```(?:json|javascript|js)?\s*\n?([\s\S]*?)\n?```/i)
if (m) return m[1].trim()
value = value.replace(/^```(?:json|javascript|js)?\s*/i, '')
value = value.replace(/\s*```$/, '')
return value.trim()
}
function _unwrapWrapper(obj, depth) {
if (depth >= MAX_DEPTH) return obj
if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return obj
for (var i = 0; i < WRAPPER_KEYS.length; i++) {
var val = obj[WRAPPER_KEYS[i]]
if (val !== undefined && val !== null) {
if (typeof val === 'string') {
var parsed = _tryParseStructuredString(val)
if (parsed && typeof parsed === 'object') return _unwrapWrapper(parsed, depth + 1)
} else if (typeof val === 'object' && !Array.isArray(val)) {
return _unwrapWrapper(val, depth + 1)
}
}
}
return obj
}
function _splitTopLevelJson(text) {
var results = []
var depth = 0
var braceDepth = 0
var bracketDepth = 0
var inString = false
var start = -1
var i = 0
for (i = 0; i < text.length; i++) {
var ch = text.charAt(i)
var prev = i > 0 ? text.charAt(i - 1) : ''
if (inString) {
if (ch === '"' && prev !== '\\') inString = false
continue
}
if (ch === '"') {
inString = true
continue
}
if (ch === '{') {
if (start === -1) start = i
braceDepth++
depth++
} else if (ch === '}') {
braceDepth--
depth--
if (depth === 0 && start !== -1) {
results.push(text.substring(start, i + 1))
start = -1
}
} else if (ch === '[') {
if (start === -1) start = i
bracketDepth++
depth++
} else if (ch === ']') {
bracketDepth--
depth--
if (depth === 0 && start !== -1) {
results.push(text.substring(start, i + 1))
start = -1
}
}
}
return results
}
function _tryParseStructuredString(value) {
if (typeof value !== 'string') return null
var stripped = _stripFence(value)
if (!stripped) return null
var parsed = _safeParse(stripped)
if (parsed && typeof parsed === 'object') return parsed
var parts = _splitTopLevelJson(stripped)
if (!parts.length) return null
var candidates = []
for (var i = 0; i < parts.length; i++) {
var item = _safeParse(parts[i])
if (item && typeof item === 'object') candidates.push(item)
}
if (!candidates.length) return null
if (candidates.length === 1) return candidates[0]
return _pickBestObject(candidates) || candidates[0]
}
function _pickBestObject(arr) {
if (!arr || !arr.length) return null
var best = null
var bestScore = -1
for (var i = 0; i < arr.length; i++) {
var item = arr[i]
if (!item || typeof item !== 'object') continue
var score = 0
if (item.mistake_diagnosis || item.error_analysis || item.diagnosis) score += 3
if (item.knowledge_patch || item.knowledge_weakness || item.knowledge) score += 2
if (item.review_task || item.suggestion || item.task) score += 2
if (item.mistakeDiagnosis) score += 2
if (item.knowledgePatch) score += 1
if (item.reviewTask) score += 1
if (score > bestScore) { bestScore = score; best = item }
}
return best
}
function _extractField(obj, keys) {
for (var i = 0; i < keys.length; i++) {
var val = obj[keys[i]]
if (val !== undefined && val !== null) return val
}
return ''
}
function _normalizeFieldValue(raw) {
if (raw === null || raw === undefined) return ''
if (typeof raw === 'number') return String(raw)
if (typeof raw === 'string') {
var trimmed = raw.trim()
if (!trimmed) return ''
var result = _tryParseStructuredString(trimmed)
if (result !== null && typeof result === 'object') {
return _extractTextFromObject(result)
}
if (_looksLikeJson(_stripFence(trimmed))) return ''
return trimmed
}
if (typeof raw === 'object') {
if (Array.isArray(raw)) {
var strs = []
for (var i = 0; i < raw.length; i++) {
var v = raw[i]
if (typeof v === 'string' && v.trim()) {
var clean = v.trim()
if (!_looksLikeJson(_stripFence(clean)) && strs.indexOf(clean) === -1) strs.push(clean)
} else if (typeof v === 'object' && v !== null) {
var t = _extractTextFromObject(v)
if (t && strs.indexOf(t) === -1) strs.push(t)
}
}
return strs.join('\n')
}
return _extractTextFromObject(raw)
}
return String(raw)
}
function _recursiveParseString(str, depth) {
if (depth >= MAX_DEPTH) return str
var trimmed = str.trim()
if (!trimmed) return str
if ((trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[')) {
var parsed = _safeParse(trimmed)
if (parsed && typeof parsed === 'object') return parsed
}
return str
}
function _extractTextFromObject(obj) {
if (!obj || typeof obj !== 'object') return String(obj || '')
for (var i = 0; i < TEXT_SUB_KEYS.length; i++) {
var val = obj[TEXT_SUB_KEYS[i]]
if (val !== undefined && val !== null) {
if (typeof val === 'string') {
var t = val.trim()
if (t) return t
} else if (typeof val === 'object') {
var r = _extractTextFromObject(val)
if (r) return r
}
}
}
return ''
}
function _isEmptyResult(result) {
return !(
(result.mistake_diagnosis && String(result.mistake_diagnosis).trim()) ||
(result.knowledge_patch && String(result.knowledge_patch).trim()) ||
(result.review_task && String(result.review_task).trim())
)
}
function normalizeAiAnalysisPayload(input) {
if (input === null || input === undefined) return EMPTY
if (typeof input === 'string' && !input.trim()) return EMPTY
if (typeof input === 'object' && !Array.isArray(input) && Object.keys(input).length === 0) return EMPTY
if (Array.isArray(input) && input.length === 0) return EMPTY
var obj = input
if (typeof obj === 'string') {
var trimmed = obj.trim()
var unfenced = _stripFence(trimmed)
var parsed = _safeParse(unfenced)
if (parsed && typeof parsed === 'object') {
obj = parsed
} else {
var parts = _splitTopLevelJson(unfenced)
if (parts.length > 0) {
var best = null
var bestScore = -1
for (var pi = 0; pi < parts.length; pi++) {
var p = _safeParse(parts[pi])
if (p && typeof p === 'object' && !Array.isArray(p)) {
var score = 0
if (p.mistake_diagnosis || p.error_analysis) score += 3
if (p.knowledge_patch || p.knowledge_weakness) score += 2
if (p.review_task || p.suggestion) score += 2
if (score > bestScore) { bestScore = score; best = p }
}
}
if (best) {
obj = best
} else {
if (_looksLikeJson(trimmed)) {
return { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
}
return { mistake_diagnosis: trimmed, knowledge_patch: '', review_task: '' }
}
} else {
if (_looksLikeJson(trimmed)) {
return { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
}
return { mistake_diagnosis: trimmed, knowledge_patch: '', review_task: '' }
}
}
}
if (Array.isArray(obj)) {
var bestObj = _pickBestObject(obj)
if (bestObj) {
obj = bestObj
} else {
var arrText = []
var arrayFormatError = false
for (var ai = 0; ai < obj.length; ai++) {
if (typeof obj[ai] === 'string' && obj[ai].trim()) {
var arrayItem = obj[ai].trim()
if (_looksLikeJson(_stripFence(arrayItem))) {
arrayFormatError = true
continue
}
if (arrText.indexOf(arrayItem) === -1) arrText.push(arrayItem)
}
}
if (arrText.length) return { mistake_diagnosis: arrText.join('\n'), knowledge_patch: '', review_task: '' }
return arrayFormatError
? { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
: EMPTY
}
}
obj = _unwrapWrapper(obj, 0)
if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return EMPTY
for (var eki = 0; eki < ALL_KNOWN_KEYS.length; eki++) {
var embeddedRaw = obj[ALL_KNOWN_KEYS[eki]]
if (typeof embeddedRaw !== 'string') continue
var embeddedClean = _stripFence(embeddedRaw)
if (!_looksLikeJson(embeddedClean)) continue
var embeddedObj = _tryParseStructuredString(embeddedRaw)
if (!embeddedObj || typeof embeddedObj !== 'object') continue
var embeddedResult = normalizeAiAnalysisPayload(embeddedObj)
if (hasAiAnalysisContent(embeddedResult)) return embeddedResult
}
var rawDiagnosis = _extractField(obj, DIAGNOSIS_KEYS)
var rawKnowledge = _extractField(obj, KNOWLEDGE_KEYS)
var rawTask = _extractField(obj, TASK_KEYS)
var diagnosis = _normalizeFieldValue(rawDiagnosis)
var knowledge = _normalizeFieldValue(rawKnowledge)
var task = _normalizeFieldValue(rawTask)
diagnosis = diagnosis.replace(/^错因诊断[：:]\s*/, '')
knowledge = knowledge.replace(/^补漏重点[：:]\s*/, '')
task = task.replace(/^复练任务[：:]\s*/, '')
var result = {
mistake_diagnosis: diagnosis,
knowledge_patch: knowledge,
review_task: task,
}
if (_isEmptyResult(result) && _looksLikeJson(JSON.stringify(input))) {
result.formatError = true
}
return result
}
var EMPTY = { mistake_diagnosis: '', knowledge_patch: '', review_task: '' }
function hasAiAnalysisContent(result) {
if (!result || typeof result !== 'object') return false
return !!(
(result.mistake_diagnosis && String(result.mistake_diagnosis).trim()) ||
(result.knowledge_patch && String(result.knowledge_patch).trim()) ||
(result.review_task && String(result.review_task).trim())
)
}
module.exports = {
normalizeAiAnalysisPayload: normalizeAiAnalysisPayload,
hasAiAnalysisContent: hasAiAnalysisContent,
}
