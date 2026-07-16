/**
 * question-runner-adapter.js
 *
 * Unified data adapter for quiz-runner component.
 * Consolidates duplicate blank-answer / option-list logic across
 * practice, review-today, and wrong-detail pages.
 */

var stemRender = require('./stem-render')
var answerLib = require('./answer')

/* ==================== Blank answer helpers ==================== */

function normalizeBlankAnswer(answer) {
  return answerLib.normalizeBlankAnswer(answer)
}

function normalizeBlankOptionList(options) {
  if (Array.isArray(options)) return options
  if (options && typeof options === 'object') {
    return Object.keys(options).map(function (key) { return { key: key, text: options[key] } })
  }
  return []
}

function getBlankOptionGroups(q) {
  if (!q) return []
  if (q.content && Array.isArray(q.content.blank_option_groups)) return q.content.blank_option_groups
  if (Array.isArray(q.blank_option_groups)) return q.blank_option_groups
  return []
}

/**
 * Enrich blank option groups with selection state.
 * @param {Array} groups - raw blank option groups
 * @param {string|object} answer - serialized or map answer
 * @returns {Array} enriched groups with _selected on each option
 */
function enrichBlankOptionGroups(groups, answer) {
  var blankAnswers = normalizeBlankAnswer(answer)
  return (groups || []).map(function (group) {
    var groupId = String((group && group.id) || '').trim()
    return {
      id: groupId,
      options: normalizeBlankOptionList(group && group.options).map(function (opt) {
        var key = String((opt && opt.key) || '').trim().toUpperCase()
        var text = String((opt && opt.text) || '').trim()
        var optionText = stemRender.stripLeadingOptionLabel(key, text)
        var cleanedText = optionText.replace(/[\r\n]+/g, ' ')
        var plain = stemRender.toPlainInlineMathText(cleanedText)
        var needsRich = !plain && stemRender.needsRichRender(cleanedText)
        return Object.assign({}, opt, {
          key: key,
          _text: plain || optionText,
          _selected: blankAnswers[groupId] === key,
          _needsRich: needsRich,
          _html: needsRich ? stemRender.textToHtml(optionText) : '',
        })
      }).filter(function (opt) { return opt.key }),
    }
  }).filter(function (group) {
    return group.id && group.options.length > 0
  })
}

/**
 * Enrich blank option groups with correct/wrong state (readonly mode).
 * @param {Array} groups - raw blank option groups
 * @param {string|object} correctAnswer - correct answer
 * @param {string|object} userAnswer - user's answer
 * @returns {Array} enriched groups with _isCorrect, _isUserAnswer, _isBoth
 */
function enrichBlankOptionGroupsReadonly(groups, correctAnswer, userAnswer) {
  var blankAnswers = normalizeBlankAnswer(correctAnswer)
  var wrongAnswers = normalizeBlankAnswer(userAnswer)
  return (groups || []).map(function (group) {
    var groupId = String((group && group.id) || '').trim()
    return {
      id: groupId,
      options: normalizeBlankOptionList(group && group.options).map(function (opt) {
        var key = String((opt && opt.key) || '').trim().toUpperCase()
        var text = String((opt && opt.text) || '').trim()
        var optionText = stemRender.stripLeadingOptionLabel(key, text)
        var cleanedText = optionText.replace(/[\r\n]+/g, ' ')
        var plain = stemRender.toPlainInlineMathText(cleanedText)
        var needsRich = !plain && stemRender.needsRichRender(cleanedText)
        var isCorrect = blankAnswers[groupId] === key
        var isUser = wrongAnswers[groupId] === key
        return Object.assign({}, opt, {
          key: key,
          _text: plain || optionText,
          _isCorrect: isCorrect,
          _isUserAnswer: isUser,
          _isBoth: isCorrect && isUser,
          _needsRich: needsRich,
          _html: needsRich ? stemRender.textToHtml(optionText) : '',
        })
      }).filter(function (opt) { return opt.key }),
    }
  }).filter(function (group) {
    return group.id && group.options.length > 0
  })
}

function serializeBlankAnswer(groups, blankAnswers) {
  return answerLib.serializeBlankAnswer(groups, blankAnswers)
}

function isMultiBlankChoice(q) {
  return q && (q.question_type === 'multi_blank_choice' || getBlankOptionGroups(q).length > 0)
}

/* ==================== Answered-state helpers ==================== */

/**
 * Check if a question is answered based on answer map.
 * @param {Object} q - question object
 * @param {Object} answerMap - {questionId: answer}
 * @param {string} keyField - field name for the key ('id' or 'schedule_id')
 */
function isQuestionAnswered(q, answerMap, keyField) {
  keyField = keyField || 'id'
  var answer = (answerMap || {})[String(q[keyField])] || ''
  if (isMultiBlankChoice(q)) {
    var groups = getBlankOptionGroups(q)
    if (!groups.length) return !!answer
    var blankAnswers = normalizeBlankAnswer(answer)
    return groups.every(function (group) {
      return !!blankAnswers[String((group && group.id) || '').trim()]
    })
  }
  return !!answer
}

function buildAnsweredFlags(questions, answerMap, keyField) {
  keyField = keyField || 'id'
  var flags = {}
  ;(questions || []).forEach(function (q) {
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

/* ==================== Option list builders ==================== */

/**
 * Build option list with selected state.
 * Uses stem-render's buildOptionList internally.
 */
function buildOptionListFromFlags(opts, optionKeys, selectedFlags) {
  return stemRender.buildOptionList(opts, optionKeys, selectedFlags)
}

/**
 * Build option list with selected state from answer map.
 * @param {Object} q - question object with ._opts, ._optionKeys
 * @param {Object} answerMap - {questionId: answer}
 * @param {string} keyField - 'id' or 'schedule_id'
 * @param {Object} opts - options dict (optional, uses q._opts if omitted)
 */
function buildOptionList(q, answerMap, keyField, opts) {
  keyField = keyField || 'id'
  var optionKeys = q._optionKeys || (opts ? Object.keys(opts) : [])
  var optionsDict = opts || q._opts || {}
  var answer = (answerMap || {})[String(q[keyField])] || ''
  var isMulti = answerLib.isMultipleChoiceType(q.question_type)
  var selectedFlags = {}
  for (var i = 0; i < optionKeys.length; i++) {
    var key = optionKeys[i]
    selectedFlags[key] = isMulti
      ? answerLib.normalizeChoiceAnswer(answer).indexOf(key) >= 0
      : String(answer).trim().toUpperCase() === key
  }
  return buildOptionListFromFlags(optionsDict, optionKeys, selectedFlags)
}

/**
 * Build option list with correct/wrong state (readonly mode).
 * @param {Object} q - question object
 * @param {Object} opts - options dict {A: '...', B: '...'}
 * @param {Array} optionKeys - ['A', 'B', ...]
 * @param {string} correctAnswer - correct answer
 * @param {string} userAnswer - user's answer
 * @returns {Array} option items with _isCorrect, _isUserAnswer, _isBoth
 */
function buildOptionListReadonly(q, opts, optionKeys, correctAnswer, userAnswer) {
  var questionType = q.question_type || ''
  var correctSet = answerLib.isMultipleChoiceType(questionType)
    ? answerLib.normalizeAnswerSet(correctAnswer) : null
  var userSet = answerLib.isMultipleChoiceType(questionType)
    ? answerLib.normalizeAnswerSet(userAnswer) : null

  return (optionKeys || []).map(function (key) {
    var rawValue = (opts && opts[key]) || ''
    // Handle rich dict format: {"A": {"text": "...", "segments": [...]}}
    var optSegments = typeof rawValue === 'object' && rawValue !== null ? (rawValue.segments || null) : null
    var rawText = ''
    if (optSegments && Array.isArray(optSegments) && optSegments.length > 0) {
      rawText = stemRender.segmentsToText(optSegments)
    } else if (typeof rawValue === 'object' && rawValue !== null) {
      rawText = rawValue.text || rawValue.value || ''
    } else {
      rawText = String(rawValue)
    }
    var stripped = stemRender.stripLeadingOptionLabel(key, rawText)
    var plain = stemRender.toPlainInlineMathText(stripped)
    var text = plain || stripped
    var needsRich = !plain && stemRender.needsRichRender(stripped)

    var isCorrect = correctSet ? !!correctSet[key] : key === (correctAnswer || '').trim().toUpperCase()
    var isUserAnswer = userSet ? !!userSet[key] : key === (userAnswer || '').trim().toUpperCase()

    return {
      key: key,
      _text: text,
      _html: needsRich ? stemRender.textToHtml(stripped) : '',
      _needsRich: !optSegments && needsRich,
      _segments: (optSegments && Array.isArray(optSegments) && optSegments.length > 0) ? optSegments : undefined,
      _isCorrect: isCorrect,
      _isUserAnswer: isUserAnswer,
      _isBoth: isCorrect && isUserAnswer,
    }
  })
}

/* ==================== Answer correctness ==================== */

function getCorrectAnswer(q) {
  if (!q) return ''
  return q.answer || q.correct_answer || q.standard_answer || q.right_answer || ''
}

function isAnswerCorrect(q, userAnswer) {
  var correct = getCorrectAnswer(q)
  if (!correct || !userAnswer) return null
  return answerLib.isAnswerCorrect(userAnswer, correct, q.question_type)
}

/* ==================== Exports ==================== */

module.exports = {
  // Blank helpers
  normalizeBlankAnswer: normalizeBlankAnswer,
  normalizeBlankOptionList: normalizeBlankOptionList,
  getBlankOptionGroups: getBlankOptionGroups,
  enrichBlankOptionGroups: enrichBlankOptionGroups,
  enrichBlankOptionGroupsReadonly: enrichBlankOptionGroupsReadonly,
  serializeBlankAnswer: serializeBlankAnswer,
  isMultiBlankChoice: isMultiBlankChoice,

  // Answered state
  isQuestionAnswered: isQuestionAnswered,
  buildAnsweredFlags: buildAnsweredFlags,
  countAnswered: countAnswered,
  applyAnsweredFlags: applyAnsweredFlags,
  computeAnsweredCount: computeAnsweredCount,

  // Option list builders
  buildOptionListFromFlags: buildOptionListFromFlags,
  buildOptionList: buildOptionList,
  buildOptionListReadonly: buildOptionListReadonly,

  // Answer correctness
  getCorrectAnswer: getCorrectAnswer,
  isAnswerCorrect: isAnswerCorrect,
}
