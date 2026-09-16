
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
function _hasQuotedAnalysisKey(str) {
if (typeof str !== 'string' || !str) return false
for (var i = 0; i < ALL_KNOWN_KEYS.length; i++) {
var escaped = ALL_KNOWN_KEYS[i].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
var re = new RegExp("[\"']" + escaped + "[\"']\\s*:", 'i')
if (re.test(str)) return true
}
return false
}
function _looksLikeJson(str) {
if (typeof str !== 'string' || !str) return false
var t = str.trim()
if (!t) return false
if (/^```(?:json|javascript|js)?/i.test(t)) return true
if (t.charAt(0) === '{' || t.charAt(0) === '[') return true
return _hasQuotedAnalysisKey(t)
}
function _hasDirectAnalysisField(obj) {
if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return false
for (var i = 0; i < ALL_KNOWN_KEYS.length; i++) {
var val = obj[ALL_KNOWN_KEYS[i]]
if (val !== undefined && val !== null && val !== '') return true
}
return false
}
function _isAnalysisShaped(obj) {
if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return false
if (_hasDirectAnalysisField(obj)) return true
for (var i = 0; i < WRAPPER_KEYS.length; i++) {
if (obj[WRAPPER_KEYS[i]] !== undefined && obj[WRAPPER_KEYS[i]] !== null) return true
}
return false
}
function _isTruncatedAnalysisJson(str) {
var raw = String(str || '').trim()
if (!raw) return false
var stripped = _stripFence(raw)
if (!stripped) return false
if (_safeParse(stripped) !== null) return false
if (!_hasQuotedAnalysisKey(stripped) && !_hasQuotedAnalysisKey(raw)) return false
var start = stripped.charAt(0)
return start === '{' || start === '[' || /^```(?:json|javascript|js)?/i.test(raw)
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
if (_hasDirectAnalysisField(obj)) return obj
for (var i = 0; i < WRAPPER_KEYS.length; i++) {
var val = obj[WRAPPER_KEYS[i]]
if (val === undefined || val === null) continue
if (typeof val === 'string') {
var parsed = _tryParseStructuredString(val)
if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
return _unwrapWrapper(parsed, depth + 1)
}
} else if (typeof val === 'object' && !Array.isArray(val)) {
return _unwrapWrapper(val, depth + 1)
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
if (parsed && _isAnalysisShaped(parsed)) return parsed
var parts = _splitTopLevelJson(stripped)
if (!parts.length) return null
var candidates = []
for (var i = 0; i < parts.length; i++) {
var item = _safeParse(parts[i])
if (item && _isAnalysisShaped(item)) candidates.push(item)
}
if (!candidates.length) return null
if (candidates.length === 1) return candidates[0]
return _pickBestObject(candidates) || candidates[0]
}
function _pickBestObject(arr) {
if (!arr || !arr.length) return null
var best = null
var bestScore = 0
for (var i = 0; i < arr.length; i++) {
var item = arr[i]
if (!item || typeof item !== 'object' || Array.isArray(item)) continue
var score = 0
if (item.mistake_diagnosis || item.error_analysis || item.diagnosis) score += 3
if (item.knowledge_patch || item.knowledge_weakness || item.knowledge) score += 2
if (item.review_task || item.suggestion || item.task) score += 2
if (item.mistakeDiagnosis) score += 2
if (item.knowledgePatch) score += 1
if (item.reviewTask) score += 1
if (score > bestScore) { bestScore = score; best = item }
}
return bestScore > 0 ? best : null
}
function _extractField(obj, keys) {
for (var i = 0; i < keys.length; i++) {
var val = obj[keys[i]]
if (val !== undefined && val !== null) return val
}
return ''
}
function _joinExtractedFields(obj) {
if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return ''
var parts = []
var diagnosis = _normalizeFieldValue(_extractField(obj, DIAGNOSIS_KEYS))
var knowledge = _normalizeFieldValue(_extractField(obj, KNOWLEDGE_KEYS))
var task = _normalizeFieldValue(_extractField(obj, TASK_KEYS))
if (diagnosis) parts.push(diagnosis)
if (knowledge) parts.push(knowledge)
if (task) parts.push(task)
return parts.join('\n')
}
function _formatErrorResult() {
return { mistake_diagnosis: '', knowledge_patch: '', review_task: '', formatError: true }
}
function _normalizeFieldValue(raw) {
if (raw === null || raw === undefined) return ''
if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
if (typeof raw === 'string') {
var trimmed = raw.trim()
if (!trimmed) return ''
var whole = _safeParse(_stripFence(trimmed))
if (Array.isArray(whole)) return _normalizeFieldValue(whole)
if (whole !== null && typeof whole === 'object') {
if (_hasDirectAnalysisField(whole)) {
var fromFields = _joinExtractedFields(whole)
if (fromFields) return fromFields
}
var extracted = _extractTextFromObject(whole)
if (extracted) return extracted
return trimmed
}
if (typeof whole === 'string' && whole.trim() && whole !== trimmed) {
return _normalizeFieldValue(whole)
}
if (_isTruncatedAnalysisJson(trimmed)) return ''
return trimmed
}
if (typeof raw === 'object') {
if (Array.isArray(raw)) {
var strs = []
for (var i = 0; i < raw.length; i++) {
var itemText = _normalizeFieldValue(raw[i])
if (itemText && strs.indexOf(itemText) === -1) strs.push(itemText)
}
return strs.join('\n')
}
if (_hasDirectAnalysisField(raw)) {
var fromObj = _joinExtractedFields(raw)
if (fromObj) return fromObj
}
var fromObject = _extractTextFromObject(raw)
if (fromObject) return fromObject
return ''
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
if (obj === null || obj === undefined) return ''
if (typeof obj !== 'object') return String(obj)
if (Array.isArray(obj)) {
var parts = []
for (var i = 0; i < obj.length; i++) {
var item = _extractTextFromObject(obj[i])
if (item && parts.indexOf(item) === -1) parts.push(item)
}
return parts.join('\n')
}
for (var i = 0; i < TEXT_SUB_KEYS.length; i++) {
var val = obj[TEXT_SUB_KEYS[i]]
if (val !== undefined && val !== null) {
if (typeof val === 'string') {
var t = val.trim()
if (t) return t
} else if (typeof val === 'object') {
var r = _extractTextFromObject(val)
if (r) return r
} else if (typeof val === 'number') {
return String(val)
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
function _collectArrayPayload(arr) {
var arrText = []
var arrayFormatError = false
for (var ai = 0; ai < arr.length; ai++) {
var item = arr[ai]
if (item && typeof item === 'object' && !Array.isArray(item)) {
var nestedObjResult = normalizeAiAnalysisPayload(item)
if (hasAiAnalysisContent(nestedObjResult)) return nestedObjResult
var nestedObjText = _extractTextFromObject(item)
if (nestedObjText && arrText.indexOf(nestedObjText) === -1) arrText.push(nestedObjText)
continue
}
if (typeof item === 'number' || typeof item === 'boolean') {
var scalar = String(item)
if (arrText.indexOf(scalar) === -1) arrText.push(scalar)
continue
}
if (typeof item !== 'string' || !item.trim()) continue
var arrayItem = item.trim()
var parsedItem = _safeParse(_stripFence(arrayItem))
if (typeof parsedItem === 'string' && parsedItem.trim()) {
arrayItem = parsedItem.trim()
parsedItem = _safeParse(_stripFence(arrayItem))
}
if (parsedItem && typeof parsedItem === 'object') {
var nestedParsed = normalizeAiAnalysisPayload(parsedItem)
if (hasAiAnalysisContent(nestedParsed)) return nestedParsed
var nestedParsedText = _extractTextFromObject(parsedItem)
if (nestedParsedText && arrText.indexOf(nestedParsedText) === -1) arrText.push(nestedParsedText)
continue
}
if (_isTruncatedAnalysisJson(arrayItem)) {
arrayFormatError = true
continue
}
if (arrText.indexOf(arrayItem) === -1) arrText.push(arrayItem)
}
if (arrText.length) return { mistake_diagnosis: arrText.join('\n'), knowledge_patch: '', review_task: '' }
return arrayFormatError ? _formatErrorResult() : EMPTY
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
if (typeof parsed === 'string' && parsed.trim() && parsed.trim() !== trimmed) {
return normalizeAiAnalysisPayload(parsed)
}
if (parsed && typeof parsed === 'object') {
obj = parsed
} else {
var parts = _splitTopLevelJson(unfenced)
var partObjects = []
for (var pi = 0; pi < parts.length; pi++) {
var p = _safeParse(parts[pi])
if (p && typeof p === 'object') partObjects.push(p)
}
var best = _pickBestObject(partObjects)
if (best) {
obj = best
} else {
if (_isTruncatedAnalysisJson(trimmed) || _isTruncatedAnalysisJson(unfenced)) {
return _formatErrorResult()
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
return _collectArrayPayload(obj)
}
}
obj = _unwrapWrapper(obj, 0)
if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return EMPTY
for (var eki = 0; eki < ALL_KNOWN_KEYS.length; eki++) {
var embeddedRaw = obj[ALL_KNOWN_KEYS[eki]]
var embeddedObj = null
if (typeof embeddedRaw === 'string') {
if (!_looksLikeJson(_stripFence(embeddedRaw)) && !_looksLikeJson(embeddedRaw)) continue
embeddedObj = _tryParseStructuredString(embeddedRaw)
} else if (embeddedRaw && typeof embeddedRaw === 'object' && !Array.isArray(embeddedRaw) && _hasDirectAnalysisField(embeddedRaw)) {
embeddedObj = embeddedRaw
} else {
continue
}
if (!embeddedObj || typeof embeddedObj !== 'object' || Array.isArray(embeddedObj) || embeddedObj === obj) continue
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
if (!_isEmptyResult(result)) return result
var fallbackText = _extractTextFromObject(obj)
if (fallbackText) {
result.mistake_diagnosis = fallbackText
return result
}
if (typeof input === 'string' && !_isTruncatedAnalysisJson(input) && !_isTruncatedAnalysisJson(_stripFence(input))) {
result.mistake_diagnosis = String(input).trim()
return result
}
result.formatError = true
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
