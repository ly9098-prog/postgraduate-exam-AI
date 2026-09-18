
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
return questionType === 'multi_blank_choice' || questionType === 'multi_blank_multiple_choice'
}
function isMultiBlankMultipleType(questionType) {
return questionType === 'multi_blank_multiple_choice'
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
// 规范一个空的取值：逗号/顿号分隔的多个选项 key（多空多选），排序去重后用逗号连接。
// 单个 key 原样保留（支持多字符 key，如罗马数字 VII、Ⅲ）。
function normalizeSlotValue(raw) {
var keys = String(raw || '').split(/[，,、]/).map(function(k) { return k.trim().toUpperCase() }).filter(Boolean)
var seen = {}
var out = []
keys.forEach(function(k) {
if (!seen[k]) { seen[k] = true; out.push(k) }
})
return out.sort().join(',')
}
function normalizeBlankAnswer(answer, slotIds) {
if (!answer) return {}
if (typeof answer === 'object') return answer
var result = {}
var text = String(answer).trim()
// ①) Canonical "slot:value" pairs，value 可为逗号分隔的多个 key。
// 同一分段内，后续无冒号的片段归属上一个 slot（多 key 续写）：
//   "①:A,C;②:B" → {①:"A,C", ②:"B"}；"1:B,2:D" → {1:"B", 2:"D"}
var canonicalMatch = false
String(text).split(/[;；\n]+/).forEach(function(part) {
var currentSlot = null
part.split(/[，,、]/).forEach(function(seg) {
seg = seg.trim()
if (!seg) return
var m = seg.match(/^(.+?)\s*[:：=]\s*(.+)$/)
if (m) {
currentSlot = m[1].trim()
var value = normalizeSlotValue(m[2])
if (currentSlot && value) {
result[currentSlot] = result[currentSlot]
? normalizeSlotValue(result[currentSlot] + ',' + value)
: value
canonicalMatch = true
}
} else if (currentSlot) {
var extra = normalizeSlotValue(seg)
if (extra) {
result[currentSlot] = result[currentSlot]
? normalizeSlotValue(result[currentSlot] + ',' + extra)
: extra
canonicalMatch = true
}
}
})
})
if (canonicalMatch) return result
// ②) Circled compact: ①B、②D / ①AC、②D / ①A,C、②D（capture 到下一个槽位标记为止）
var slotMarker = '[①-⑳]|[（(]\\s*\\d+\\s*[）)]|第\\s*[\\d一二三四五六七八九十]+\\s*空'
var circledRe = new RegExp('[①-⑳]\\s*((?:(?!' + slotMarker + ')[^;；\\n])*)', 'g')
var circledPairs = text.match(circledRe)
if (circledPairs && circledPairs.length >= 1) {
circledPairs.forEach(function(pair) {
var m = pair.match(/^([①-⑳])\s*(.*)$/)
if (m) {
var value = normalizeSlotValue(m[2])
if (value) result[m[1]] = value
}
})
if (Object.keys(result).length > 0) return result
}
// ③) Parenthesized: (1)B、(2)D
var parenRe = new RegExp('[（(]\\s*(\\d+)\\s*[）)]\\s*((?:(?!' + slotMarker + ')[^;；\\n])*)', 'g')
var parenPairs = text.match(parenRe)
if (parenPairs && parenPairs.length >= 1) {
parenPairs.forEach(function(pair) {
var m = pair.match(/[（(]\s*(\d+)\s*[）)]\s*(.*)$/)
if (m) {
var value = normalizeSlotValue(m[2])
if (value) result[m[1]] = value
}
})
if (Object.keys(result).length > 0) return result
}
// ④) 第1空B，第2空D
var cnRe = new RegExp('第\\s*[\\d一二三四五六七八九十]+\\s*空\\s*[：:]?\\s*((?:(?!' + slotMarker + ')[^;；\\n])*)', 'g')
var cnPairs = text.match(cnRe)
if (cnPairs && cnPairs.length >= 1) {
cnPairs.forEach(function(pair) {
var m = pair.match(/第\s*(\d+|[\d一二三四五六七八九十]+)\s*空\s*[：:]?\s*(.*)$/)
if (m) {
var value = normalizeSlotValue(m[2])
if (value) result[m[1]] = value
}
})
if (Object.keys(result).length > 0) return result
}
// ⑤) Positional "B,D"（仅当提供了可信 slotIds 且数量匹配）
var trustedIds = Array.isArray(slotIds)
? slotIds.map(function(id) { return String(id || '').trim() }).filter(Boolean)
: []
if (trustedIds.length > 0 && text.indexOf(':') < 0 && text.indexOf('：') < 0) {
var positional = text.split(/[，,、\s]+/).map(function(v) { return v.trim().toUpperCase() }).filter(Boolean)
if (positional.length === 1 && trustedIds.length > 1) {
var compact = positional[0].match(/[A-H]/g) || []
if (compact.length === positional[0].length) positional = compact
}
if (positional.length === trustedIds.length && positional.every(function(v) { return normalizeSlotValue(v) !== '' })) {
trustedIds.forEach(function(id, index) { result[id] = normalizeSlotValue(positional[index]) })
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
if (id && value) parts.push(id + ':' + normalizeSlotValue(value))
})
return parts.join(';')
}
function slotKeySet(value) {
var set = {}
;String(value || '').toUpperCase().split(/[，,]/).forEach(function(key) {
var k = key.trim()
if (k) set[k] = true
})
return set
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
if (!user[k]) return false
if (isMultiBlankMultipleType(questionType)) {
// 多空多选：每空按 key 集合比较（双向相等，多余/缺失都判错）
var standardSet = slotKeySet(standard[k])
var userSet = slotKeySet(user[k])
var standardList = Object.keys(standardSet)
var userList = Object.keys(userSet)
if (standardList.length !== userList.length) return false
return standardList.every(function(key) { return userSet[key] })
}
return String(user[k]).toUpperCase() === String(standard[k]).toUpperCase()
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
isMultiBlankMultipleType: isMultiBlankMultipleType,
normalizeTrueFalseAnswer: normalizeTrueFalseAnswer,
normalizeBlankAnswer: normalizeBlankAnswer,
serializeBlankAnswer: serializeBlankAnswer,
isAnswerCorrect: isAnswerCorrect,
}
