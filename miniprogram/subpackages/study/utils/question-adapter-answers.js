var { answerLib } = require('./question-adapter-dependencies')
var { _groupId, getQuestionOptions, getBlankOptionGroups } = require('./question-adapter-groups')

function normalizeBlankAnswer(answer, slotIds) {
  var parsed = answerLib.normalizeBlankAnswer(answer, slotIds)
  if (!parsed || typeof parsed !== 'object') return {}
  var normalized = {}
  Object.keys(parsed).forEach(function (key) {
    var id = String(key == null ? '' : key).trim()
    if (!id) return
    normalized[id] = String(parsed[key] == null ? '' : parsed[key]).trim().toUpperCase()
  })
  return normalized
}

function serializeBlankAnswer(groups, blankAnswers) {
  var normalizedGroups = (groups || []).map(function (group, index) {
    return Object.assign({}, group, { id: _groupId(group, String(index + 1)) })
  })
  return answerLib.serializeBlankAnswer(normalizedGroups, normalizeBlankAnswer(blankAnswers))
}

function isMultiBlankChoice(q) {
  return q && (q.question_type === 'multi_blank_choice' || q.question_type === 'multi_blank_multiple_choice' || getBlankOptionGroups(q).length > 0)
}

function isMultiBlankMultipleChoice(q) {
  return q && q.question_type === 'multi_blank_multiple_choice'
}

function _slotValueHas(value, key) {
  if (!value) return false
  return String(value).toUpperCase().split(',').indexOf(String(key).toUpperCase()) >= 0
}

function isQuestionAnswered(q, answerMap, keyField) {
  keyField = keyField || 'id'
  var answer = (answerMap || {})[String(q[keyField])] || ''
  if (isMultiBlankChoice(q)) {
    var groups = getBlankOptionGroups(q)
    if (!groups.length) return !!answer
    var blankAnswers = normalizeBlankAnswer(answer)
    return groups.every(function (group) {
      var value = blankAnswers[String((group && group.id) || '').trim()]
      return !!value && String(value).split(',').some(function (k) { return !!k.trim() })
    })
  }
  return !!answer
}

function buildAnsweredFlags(questions, answerMap, keyField) {
  keyField = keyField || 'id'
  var flags = {}
    ; (questions || []).forEach(function (q) {
      flags[String(q[keyField])] = isQuestionAnswered(q, answerMap, keyField)
    })
  return flags
}

function countAnswered(flags) {
  return Object.keys(flags || {}).filter(function (id) { return flags[id] }).length
}

function applyAnsweredFlags(questions, flags, keyField) {
  keyField = keyField || 'id'
  return (questions || []).map(function (q) {
    return Object.assign({}, q, { _answered: !!(flags || {})[String(q[keyField])] })
  })
}

function computeAnsweredCount(questions, answerMap, keyField) {
  keyField = keyField || 'id'
  return (questions || []).filter(function (q) {
    return isQuestionAnswered(q, answerMap, keyField)
  }).length
}

function getCorrectAnswer(q) {
  if (!q) return ''
  return q.answer || q.correct_answer || q.standard_answer || q.right_answer || ''
}

function isAnswerCorrect(q, userAnswer) {
  var correct = getCorrectAnswer(q)
  if (!correct || !userAnswer) return null
  if (q && (q.question_type === 'multi_blank_choice' || q.question_type === 'multi_blank_multiple_choice') &&
    !getBlankOptionGroups(q).length &&
    getQuestionOptions(q) &&
    !/[:：=;]/.test(String(correct))) {
    return answerLib.isAnswerCorrect(userAnswer, correct, 'single_choice')
  }
  var slotIds = q && (q.question_type === 'multi_blank_choice' || q.question_type === 'multi_blank_multiple_choice')
    ? getBlankOptionGroups(q).map(function (group, index) { return _groupId(group, String(index + 1)) }).filter(Boolean)
    : null
  return answerLib.isAnswerCorrect(userAnswer, correct, q.question_type, slotIds)
}

module.exports = {
  normalizeBlankAnswer,
  serializeBlankAnswer,
  isMultiBlankChoice,
  isMultiBlankMultipleChoice,
  _slotValueHas,
  isQuestionAnswered,
  buildAnsweredFlags,
  countAnswered,
  applyAnsweredFlags,
  computeAnsweredCount,
  getCorrectAnswer,
  isAnswerCorrect,
}
