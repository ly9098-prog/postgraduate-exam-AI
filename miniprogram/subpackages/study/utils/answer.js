
function normalizeChoiceAnswer(answer) {
if (!answer) return []
var str = String(answer).toUpperCase().trim()
var parts = str.split(/[;,；，\s]+/).map(function(p) { return p.trim() }).filter(Boolean)
if (parts.length <= 1) {
parts = []
for (var i = 0; i < str.length; i++) {
var ch = str[i]
if (ch >= 'A' && ch <= 'Z') parts.push(ch)
}
}
var seen = {}
return parts.filter(function(p) {
if (p.length === 1 && p >= 'A' && p <= 'Z') {
if (seen[p]) return false
seen[p] = true
return true
}
return false
}).sort()
}
function serializeChoiceAnswer(answer) {
return normalizeChoiceAnswer(answer).join(',')
}
function normalizeAnswerSet(answer) {
var arr = normalizeChoiceAnswer(answer)
var set = {}
for (var i = 0; i < arr.length; i++) set[arr[i]] = true
return set
}
function isMultipleChoiceType(questionType) {
return questionType === 'multiple_choice'
}
function isTrueFalseType(questionType) {
return questionType === 'true_false' || questionType === 'judgement'
}
function isMultiBlankType(questionType) {
return questionType === 'multi_blank_choice'
}
function normalizeTrueFalseAnswer(answer) {
if (answer === undefined || answer === null) return ''
var value = String(answer).trim().toLowerCase()
var truthy = { a: true, 'true': true, '对': true, '是': true, '正确': true, t: true, yes: true, '1': true }
var falsy = { b: true, 'false': true, '错': true, '否': true, '错误': true, f: true, no: true, '0': true }
if (Object.prototype.hasOwnProperty.call(truthy, value)) return 'A'
if (Object.prototype.hasOwnProperty.call(falsy, value)) return 'B'
return value.toUpperCase()
}
function normalizeBlankAnswer(answer, slotIds) {
if (!answer) return {}
if (typeof answer === 'object') return answer
var result = {}
var text = String(answer).trim()
var canonicalMatch = false
String(text).split(/[;；,，、\n]+/).forEach(function(part) {
var m = part.trim().match(/^(.+?)\s*[:：=]\s*(.+)$/)
if (m) {
result[m[1].trim()] = m[2].trim().toUpperCase()
canonicalMatch = true
}
})
if (canonicalMatch) return result
var circledPairs = text.match(/[①-⑳]\s*[A-Za-z]/g)
if (circledPairs && circledPairs.length >= 1) {
circledPairs.forEach(function(pair) {
var m = pair.match(/^([①-⑳])\s*([A-Za-z])$/)
if (m) result[m[1]] = m[2].toUpperCase()
})
if (Object.keys(result).length > 0) return result
}
var parenPairs = text.match(/[（(]\s*\d+\s*[）)]\s*[A-Za-z]/g)
if (parenPairs && parenPairs.length >= 1) {
parenPairs.forEach(function(pair) {
var m = pair.match(/[（(]\s*(\d+)\s*[）)]\s*([A-Za-z])/)
if (m) result[m[1]] = m[2].toUpperCase()
})
if (Object.keys(result).length > 0) return result
}
var cnPairs = text.match(/第\s*[\d一二三四五六七八九十]+\s*空\s*[：:]?\s*[A-Za-z]/g)
if (cnPairs && cnPairs.length >= 1) {
cnPairs.forEach(function(pair) {
var m = pair.match(/第\s*(\d+|[\d一二三四五六七八九十]+)\s*空\s*[：:]?\s*([A-Za-z])/)
if (m) result[m[1]] = m[2].toUpperCase()
})
if (Object.keys(result).length > 0) return result
}
var trustedIds = Array.isArray(slotIds)
? slotIds.map(function(id) { return String(id || '').trim() }).filter(Boolean)
: []
if (trustedIds.length > 0 && text.indexOf(':') < 0 && text.indexOf('：') < 0) {
var positional = text.split(/[，,、\s]+/).map(function(v) { return v.trim().toUpperCase() }).filter(Boolean)
if (positional.length === 1 && trustedIds.length > 1) {
var compact = positional[0].match(/[A-H]/g) || []
if (compact.length === positional[0].length) positional = compact
}
if (positional.length === trustedIds.length && positional.every(function(v) { return /^[A-H]$/.test(v) })) {
trustedIds.forEach(function(id, index) { result[id] = positional[index] })
return result
}
}
return result
}
function serializeBlankAnswer(groups, blankAnswers) {
var parts = []
;(groups || []).forEach(function(group) {
var id = String((group && group.id) || '').trim()
var value = blankAnswers && blankAnswers[id]
if (id && value) parts.push(id + ':' + String(value).trim().toUpperCase())
})
return parts.join(';')
}
function isAnswerCorrect(userAnswer, correctAnswer, questionType, slotIds) {
if (!userAnswer || !correctAnswer) return null
if (isMultiBlankType(questionType)) {
var user = normalizeBlankAnswer(userAnswer, slotIds)
var standard = normalizeBlankAnswer(correctAnswer, slotIds)
var userKeys = Object.keys(user)
var standardKeys = Object.keys(standard)
if (standardKeys.length === 0) return null
var allStandardMatch = standardKeys.every(function(k) {
return user[k] && String(user[k]).toUpperCase() === String(standard[k]).toUpperCase()
})
if (!allStandardMatch) return false
return userKeys.every(function(k) {
return standardKeys.indexOf(k) >= 0
})
}
if (isTrueFalseType(questionType)) {
return normalizeTrueFalseAnswer(userAnswer) === normalizeTrueFalseAnswer(correctAnswer)
}
if (isMultipleChoiceType(questionType)) {
return serializeChoiceAnswer(userAnswer) === serializeChoiceAnswer(correctAnswer)
}
return String(userAnswer).trim().toUpperCase() === String(correctAnswer).trim().toUpperCase()
}
module.exports = {
normalizeChoiceAnswer: normalizeChoiceAnswer,
serializeChoiceAnswer: serializeChoiceAnswer,
normalizeAnswerSet: normalizeAnswerSet,
isMultipleChoiceType: isMultipleChoiceType,
isTrueFalseType: isTrueFalseType,
isMultiBlankType: isMultiBlankType,
normalizeTrueFalseAnswer: normalizeTrueFalseAnswer,
normalizeBlankAnswer: normalizeBlankAnswer,
serializeBlankAnswer: serializeBlankAnswer,
isAnswerCorrect: isAnswerCorrect,
}
