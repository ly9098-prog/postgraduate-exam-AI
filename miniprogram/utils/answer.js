/**
 * Answer normalization and comparison utilities.
 * Single source of truth for all answer-related operations.
 */

/**
 * Normalize a choice answer (multi/single choice) into a sorted array.
 * Supports: "A,C", "C,A", "AC", "A C", "A；C", "A，C", "a,c"
 */
function normalizeChoiceAnswer(answer) {
  if (!answer) return []
  var str = String(answer).toUpperCase().trim()
  // Try comma/semicolon/Chinese-comma split first
  var parts = str.split(/[;,；，\s]+/).map(function(p) { return p.trim() }).filter(Boolean)
  if (parts.length <= 1) {
    // No delimiter found — try splitting by adjacent letters (e.g. "AC" -> ["A","C"])
    parts = []
    for (var i = 0; i < str.length; i++) {
      var ch = str[i]
      if (ch >= 'A' && ch <= 'Z') parts.push(ch)
    }
  }
  // Filter to single letters only, deduplicate, sort
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

/**
 * Serialize a choice answer array to stable string format.
 */
function serializeChoiceAnswer(answer) {
  return normalizeChoiceAnswer(answer).join(',')
}

/**
 * Normalize answer into a Set for quick lookup.
 */
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

/**
 * Normalize blank answer from serialized string to {slotId: value} map.
 */
function normalizeBlankAnswer(answer) {
  if (!answer) return {}
  if (typeof answer === 'object') return answer
  var result = {}
  String(answer).split(/[;；,，\n]+/).forEach(function(part) {
    var m = part.trim().match(/^(.+?)\s*[:：=]\s*([A-Za-z])$/)
    if (m) result[m[1].trim()] = m[2].trim().toUpperCase()
  })
  return result
}

/**
 * Serialize blank answers map to stable string.
 */
function serializeBlankAnswer(groups, blankAnswers) {
  var parts = []
  ;(groups || []).forEach(function(group) {
    var id = String((group && group.id) || '').trim()
    var value = blankAnswers && blankAnswers[id]
    if (id && value) parts.push(id + ':' + String(value).trim().toUpperCase())
  })
  return parts.join(';')
}

/**
 * Check if user answer is correct based on question type.
 * For multiple_choice: normalizes both to sorted set before comparison.
 * For single_choice/true_false: case-insensitive, whitespace-trimmed comparison.
 * For multi_blank_choice: slot-by-slot comparison.
 */
function isAnswerCorrect(userAnswer, correctAnswer, questionType) {
  if (!userAnswer || !correctAnswer) return null
  if (isMultiBlankType(questionType)) {
    var user = normalizeBlankAnswer(userAnswer)
    var standard = normalizeBlankAnswer(correctAnswer)
    var userKeys = Object.keys(user)
    var standardKeys = Object.keys(standard)
    if (standardKeys.length === 0) return null
    return standardKeys.every(function(k) {
      return user[k] && String(user[k]).toUpperCase() === String(standard[k]).toUpperCase()
    })
  }
  if (isMultipleChoiceType(questionType)) {
    return serializeChoiceAnswer(userAnswer) === serializeChoiceAnswer(correctAnswer)
  }
  // single_choice / true_false / judgement
  return String(userAnswer).trim().toUpperCase() === String(correctAnswer).trim().toUpperCase()
}

module.exports = {
  normalizeChoiceAnswer: normalizeChoiceAnswer,
  serializeChoiceAnswer: serializeChoiceAnswer,
  normalizeAnswerSet: normalizeAnswerSet,
  isMultipleChoiceType: isMultipleChoiceType,
  isTrueFalseType: isTrueFalseType,
  isMultiBlankType: isMultiBlankType,
  normalizeBlankAnswer: normalizeBlankAnswer,
  serializeBlankAnswer: serializeBlankAnswer,
  isAnswerCorrect: isAnswerCorrect,
}
