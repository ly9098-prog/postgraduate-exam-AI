var { stemRender, answerLib } = require('./question-adapter-dependencies')
var { _optionText, normalizeBlankOptionList } = require('./question-adapter-options')
var { _groupId } = require('./question-adapter-groups')
var { normalizeBlankAnswer, _slotValueHas } = require('./question-adapter-answers')

function _resolveOptionSegments(opt) {
  if (!opt || !Array.isArray(opt.segments) || opt.segments.length === 0) return null
  return opt.segments.map(function (seg) {
    if (!seg || typeof seg !== 'object') return seg
    if (seg.url) return Object.assign({}, seg, { url: stemRender.resolveAssetUrl(seg.url) })
    return seg
  })
}

function _decorateBlankOption(opt, key, state) {
  var rawText = _optionText(opt)
  var segments = _resolveOptionSegments(opt)
  if (!rawText && segments && segments.length > 0) {
    rawText = stemRender.segmentsToText(segments)
  }
  var optionText = stemRender.stripLeadingOptionLabel(key, rawText)
  var cleanedText = optionText.replace(/[\r\n]+/g, ' ')
  var plain = stemRender.toPlainInlineMathText(cleanedText)
  var needsRich = !plain && stemRender.needsRichRender(cleanedText)
  var result = Object.assign({}, opt, {
    key: key,
    _text: plain || optionText,
    _segments: segments,
    _needsRich: needsRich,
    _html: needsRich ? stemRender.textToHtml(optionText) : '',
  })
  if (state && state.mode === 'readonly') {
    result._isCorrect = !!state.correct
    result._isUserAnswer = !!state.user
    result._isBoth = !!state.correct && !!state.user
  } else {
    result._selected = !!(state && state.selected)
  }
  return result
}

function enrichBlankOptionGroups(groups, answer) {
  var blankAnswers = normalizeBlankAnswer(answer)
  return (groups || []).map(function (group) {
    var groupId = _groupId(group, '')
    return {
      id: groupId,
      options: normalizeBlankOptionList(group && group.options).map(function (opt) {
        var key = String((opt && opt.key) || '').trim().toUpperCase()
        return _decorateBlankOption(opt, key, {
          selected: _slotValueHas(blankAnswers[groupId], key),
        })
      }).filter(function (opt) { return opt.key }),
    }
  }).filter(function (group) {
    return group.id && group.options.length > 0
  })
}

function enrichBlankOptionGroupsReadonly(groups, correctAnswer, userAnswer) {
  var slotIds = (groups || []).map(function (group, index) {
    return _groupId(group, String(index + 1))
  }).filter(Boolean)
  var blankAnswers = normalizeBlankAnswer(correctAnswer, slotIds)
  var wrongAnswers = normalizeBlankAnswer(userAnswer, slotIds)
  return (groups || []).map(function (group) {
    var groupId = _groupId(group, '')
    return {
      id: groupId,
      options: normalizeBlankOptionList(group && group.options).map(function (opt) {
        var key = String((opt && opt.key) || '').trim().toUpperCase()
        var isCorrect = _slotValueHas(blankAnswers[groupId], key)
        var isUser = _slotValueHas(wrongAnswers[groupId], key)
        return _decorateBlankOption(opt, key, {
          mode: 'readonly',
          correct: isCorrect,
          user: isUser,
        })
      }).filter(function (opt) { return opt.key }),
    }
  }).filter(function (group) {
    return group.id && group.options.length > 0
  })
}

function buildOptionListFromFlags(opts, optionKeys, selectedFlags) {
  return stemRender.buildOptionList(opts, optionKeys, selectedFlags)
}

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

function buildOptionListReadonly(q, opts, optionKeys, correctAnswer, userAnswer) {
  var questionType = q.question_type || ''
  var correctSet = answerLib.isMultipleChoiceType(questionType)
    ? answerLib.normalizeAnswerSet(correctAnswer) : null
  var userSet = answerLib.isMultipleChoiceType(questionType)
    ? answerLib.normalizeAnswerSet(userAnswer) : null
  var normalizedCorrect = answerLib.isTrueFalseType(questionType)
    ? answerLib.normalizeTrueFalseAnswer(correctAnswer) : String(correctAnswer || '').trim().toUpperCase()
  var normalizedUser = answerLib.isTrueFalseType(questionType)
    ? answerLib.normalizeTrueFalseAnswer(userAnswer) : String(userAnswer || '').trim().toUpperCase()
  return (optionKeys || []).map(function (key) {
    var optValue = (opts && opts[key]) || ''
    var optSegments = typeof optValue === 'object' && optValue !== null ? (optValue.segments || null) : null
    var rawText = ''
    if (optSegments && Array.isArray(optSegments) && optSegments.length > 0) {
      rawText = stemRender.segmentsToText(optSegments)
    } else if (typeof optValue === 'object' && optValue !== null) {
      rawText = optValue.text || optValue.value || ''
    } else {
      rawText = String(optValue)
    }
    var stripped = stemRender.stripLeadingOptionLabel(key, rawText)
    var plain = stemRender.toPlainInlineMathText(stripped)
    var text = plain || stripped
    var needsRich = !plain && stemRender.needsRichRender(stripped)
    var resolvedSegments = null
    if (optSegments && Array.isArray(optSegments) && optSegments.length > 0) {
      resolvedSegments = optSegments.map(function (seg) {
        if (!seg || typeof seg !== 'object') return seg
        if (seg.url) return Object.assign({}, seg, { url: stemRender.resolveAssetUrl(seg.url) })
        return seg
      })
    }
    var isCorrect = correctSet ? !!correctSet[key] : key === normalizedCorrect
    var isUserAnswer = userSet ? !!userSet[key] : key === normalizedUser
    return {
      key: key,
      _text: text,
      _segments: resolvedSegments,
      _html: needsRich ? stemRender.textToHtml(stripped) : '',
      _needsRich: !optSegments && needsRich,
      _isCorrect: isCorrect,
      _isUserAnswer: isUserAnswer,
      _isBoth: isCorrect && isUserAnswer,
    }
  })
}

module.exports = {
  enrichBlankOptionGroups,
  enrichBlankOptionGroupsReadonly,
  buildOptionListFromFlags,
  buildOptionList,
  buildOptionListReadonly,
}
