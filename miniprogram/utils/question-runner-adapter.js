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
  var parsed = answerLib.normalizeBlankAnswer(answer)
  if (!parsed || typeof parsed !== 'object') return {}
  var normalized = {}
  Object.keys(parsed).forEach(function (key) {
    var id = String(key == null ? '' : key).trim()
    if (!id) return
    normalized[id] = String(parsed[key] == null ? '' : parsed[key]).trim().toUpperCase()
  })
  return normalized
}

var _hasOwn = Object.prototype.hasOwnProperty

function _parseJsonValue(value) {
  if (typeof value !== 'string') return value
  var text = value.trim()
  if (!text || (text.charAt(0) !== '{' && text.charAt(0) !== '[')) return value
  try {
    return JSON.parse(text)
  } catch (e) {
    return value
  }
}

function _fallbackOptionKey(index) {
  var n = Number(index) || 0
  return n < 26 ? String.fromCharCode(65 + n) : String(n + 1)
}

function _optionText(value) {
  if (value == null) return ''
  if (typeof value !== 'object') return String(value)

  if (Array.isArray(value.segments) && value.segments.length > 0) {
    var segmentText = stemRender.segmentsToText(value.segments)
    if (segmentText) return String(segmentText)
  }

  var text = value.text
  if (text == null || text === '') text = value.value
  if (text == null || text === '') text = value.content
  if (text == null || text === '') text = value.html
  if (text == null || text === '') text = value.label
  return text == null ? '' : String(text)
}

function _optionKey(value, keyHint, index) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    var key = value.key
    if (key == null || key === '') key = value.option_key
    if (key == null || key === '') key = value.code
    // Some importers use label for the option key. Only accept it when it
    // looks like a key; otherwise it is display text and must not become the
    // rendered key.
    if ((key == null || key === '') && /^[A-Za-z0-9]+$/.test(String(value.label || ''))) {
      key = value.label
    }
    if (key != null && String(key).trim()) return String(key).trim()
  }
  if (keyHint != null && String(keyHint).trim()) return String(keyHint).trim()
  return _fallbackOptionKey(index)
}

function _normalizeBlankOptionItem(item, index, keyHint) {
  if (item && typeof item === 'object' && !Array.isArray(item)) {
    var copy = Object.assign({}, item)
    copy.key = _optionKey(copy, keyHint, index)
    // Keep the original rich fields (segments/html) while guaranteeing the
    // text field consumed by the blank-option renderer.
    copy.text = _optionText(copy)
    return copy
  }
  return {
    key: _optionKey(null, keyHint, index),
    text: _optionText(item),
  }
}

function normalizeBlankOptionList(options) {
  options = _parseJsonValue(options)
  if (options == null || options === '') return []

  if (Array.isArray(options)) {
    return options.map(function (item, index) {
      return _normalizeBlankOptionItem(item, index)
    })
  }

  if (options && typeof options === 'object') {
    // Accept wrappers such as {options: {...}} that are produced by a few
    // older import/export paths.
    if (_hasOwn.call(options, 'options') && !_hasOwn.call(options, 'text') &&
      !_hasOwn.call(options, 'value') && !_hasOwn.call(options, 'segments')) {
      return normalizeBlankOptionList(options.options)
    }

    // A single rich option object is not an option map.
    if (_hasOwn.call(options, 'text') || _hasOwn.call(options, 'value') ||
      _hasOwn.call(options, 'content') || _hasOwn.call(options, 'segments') ||
      _hasOwn.call(options, 'html')) {
      return [_normalizeBlankOptionItem(options, 0)]
    }

    return Object.keys(options).map(function (key, index) {
      return _normalizeBlankOptionItem(options[key], index, key)
    })
  }

  return []
}

function _groupId(group, fallback) {
  if (group && typeof group === 'object') {
    var id = group.id
    if (id == null || id === '') id = group.marker
    if (id == null || id === '') id = group.blank_id
    if (id != null && String(id).trim()) return String(id).trim()
  }
  return fallback == null ? '' : String(fallback).trim()
}

function _isOptionKey(key) {
  return /^[A-Za-z]$/.test(String(key || '').trim())
}

function _isGroupLikeValue(value) {
  if (Array.isArray(value)) return true
  if (!value || typeof value !== 'object') return false
  return _hasOwn.call(value, 'options') || _hasOwn.call(value, 'option_list') ||
    _hasOwn.call(value, 'choices') || _hasOwn.call(value, 'id') ||
    _hasOwn.call(value, 'marker') || _hasOwn.call(value, 'blank_id')
}

function _normalizeGroupRecord(group, index, idHint) {
  if (Array.isArray(group)) {
    return {
      id: _groupId(null, idHint || String(index + 1)),
      options: group,
    }
  }

  if (!group || typeof group !== 'object') return null
  var copy = Object.assign({}, group)
  copy.id = _groupId(group, idHint || String(index + 1))
  if (copy.options == null) copy.options = copy.option_list
  if (copy.options == null) copy.options = copy.choices
  if (copy.options == null && !_hasOwn.call(copy, 'text') && !_hasOwn.call(copy, 'value')) {
    // A keyed group map (e.g. {"A": "...", "B": "..."}) can be used as
    // the value of an id in object-form group data.
    var optionMap = Object.assign({}, group)
    delete optionMap.id
    delete optionMap.marker
    delete optionMap.blank_id
    copy.options = optionMap
  }
  return copy
}

/**
 * Coerce the several group shapes used by old/imported question payloads to
 * an array. Returns [] for a flat option map such as {A: '...', B: '...'}.
 */
function _coerceBlankOptionGroups(value) {
  value = _parseJsonValue(value)
  if (!value) return []

  if (Array.isArray(value)) {
    if (!value.length || !value.every(function (item) {
      return Array.isArray(item) || _isGroupLikeValue(item)
    })) return []
    return value.map(function (item, index) {
      return _normalizeGroupRecord(item, index)
    }).filter(function (group) {
      return group && group.id
    })
  }

  if (typeof value !== 'object') return []
  if (Array.isArray(value.blank_option_groups)) {
    return _coerceBlankOptionGroups(value.blank_option_groups)
  }
  if (Array.isArray(value.groups)) return _coerceBlankOptionGroups(value.groups)

  if (_hasOwn.call(value, 'options') || _hasOwn.call(value, 'option_list') ||
    _hasOwn.call(value, 'choices')) {
    var single = _normalizeGroupRecord(value, 0)
    return single && single.id ? [single] : []
  }

  var keys = Object.keys(value)
  if (!keys.length) return []
  // A plain option map is not grouped data.
  if (keys.every(_isOptionKey) && keys.every(function (key) {
    return !_isGroupLikeValue(value[key])
  })) return []

  return keys.map(function (key, index) {
    return _normalizeGroupRecord(value[key], index, key)
  }).filter(function (group) {
    return group && group.id
  })
}

function _questionContent(q) {
  return q ? (_parseJsonValue(q.content) || {}) : {}
}

function _questionStem(q, content) {
  content = content || _questionContent(q)
  return String(
    (content && (content.text || content.stem)) ||
    (q && (q.stem || q.question || q.title)) ||
    ''
  )
}

function _uniqueIds(ids) {
  var seen = {}
  var result = []
  ;(ids || []).forEach(function (id) {
    var value = String(id == null ? '' : id).trim()
    if (value && !seen[value]) {
      seen[value] = true
      result.push(value)
    }
  })
  return result
}

function _extractAnswerSlotIds(answer) {
  var text = String(answer == null ? '' : answer)
  var ids = []
  var re = /(?:^|[;；,，、\n])\s*([^:：=;；,，、\s]+)\s*[:：=]\s*[A-Za-z]/g
  var match
  while ((match = re.exec(text)) !== null) ids.push(match[1])
  return _uniqueIds(ids)
}

function _toChineseNumber(value) {
  var map = { 一: '1', 二: '2', 三: '3', 四: '4', 五: '5', 六: '6', 七: '7', 八: '8', 九: '9', 十: '10' }
  return map[value] || value
}

/**
 * Infer blank ids from explicit metadata and common stem markers. This keeps
 * legacy flat-option records usable while preserving ids from the canonical
 * grouped format whenever they are available.
 */
function _inferBlankIds(q, content) {
  content = content || _questionContent(q)
  var explicit = content.blank_ids || content.blank_markers || (q && (q.blank_ids || q.blank_markers))
  if (Array.isArray(explicit) && explicit.length) return _uniqueIds(explicit)

  var stem = _questionStem(q, content)
  var ids = []
  var match
  var circled = /[①-⑳]/g
  while ((match = circled.exec(stem)) !== null) ids.push(match[0])
  if (ids.length) return _uniqueIds(ids)

  var numbered = /[（(]\s*(\d+|[一二三四五六七八九十]+)\s*[）)]/g
  while ((match = numbered.exec(stem)) !== null) ids.push(_toChineseNumber(match[1]))
  if (ids.length) return _uniqueIds(ids)

  var answerIds = _extractAnswerSlotIds(q && q.answer)
  if (answerIds.length) return answerIds

  var empty = /[（(]\s*[）)]/g
  while ((match = empty.exec(stem)) !== null) ids.push(String(ids.length + 1))
  if (!ids.length) {
    var underscores = stem.match(/(?:_{2,}|＿{2,})/g) || []
    for (var i = 0; i < underscores.length; i++) ids.push(String(i + 1))
  }

  var count = Number(content.blank_count || (q && q.blank_count) || 0)
  if (!ids.length && count > 0) {
    for (var ci = 0; ci < count; ci++) ids.push(String(ci + 1))
  }

  return _uniqueIds(ids.length ? ids : ['1'])
}

function _cloneOptions(options) {
  return (options || []).map(function (option) {
    return option && typeof option === 'object' ? Object.assign({}, option) : option
  })
}

function _optionCandidates(q, content) {
  content = content || _questionContent(q)
  return [
    q && q.options,
    content && content.options,
    content && content.blank_options,
    q && q.blank_options,
    q && q.option_groups,
  ]
}

/**
 * Return the first non-empty flat option source from the known API shapes.
 * This is intentionally separate from getBlankOptionGroups: a legacy
 * one-slot multi-blank record should use this source on the ordinary option
 * renderer.
 */
function getQuestionOptions(q) {
  if (!q) return null
  var candidates = _optionCandidates(q, _questionContent(q))
  for (var i = 0; i < candidates.length; i++) {
    var candidate = _parseJsonValue(candidates[i])
    if (candidate == null || candidate === '') continue
    if (_coerceBlankOptionGroups(candidate).length) continue
    var list = normalizeBlankOptionList(candidate)
    if (list.length) return candidate
  }
  return null
}

function getBlankOptionGroups(q) {
  if (!q) return []
  var content = _questionContent(q)

  var explicitCandidates = [
    content && content.blank_option_groups,
    q.blank_option_groups,
    content && content.blank_groups,
    q.blank_groups,
  ]
  for (var i = 0; i < explicitCandidates.length; i++) {
    var explicitGroups = _coerceBlankOptionGroups(explicitCandidates[i])
    if (explicitGroups.length) return explicitGroups
  }

  // A few API/import versions placed grouped data under options itself.
  var optionCandidates = _optionCandidates(q, content)
  for (var oi = 0; oi < optionCandidates.length; oi++) {
    var groupedOptions = _coerceBlankOptionGroups(optionCandidates[oi])
    if (groupedOptions.length) return groupedOptions
  }

  // Legacy multi-blank records use one shared flat option map. Build one
  // option group per inferred blank so the quiz-runner can render them.
  var isMultiBlank = q.question_type === 'multi_blank_choice'
  if (!isMultiBlank) return []
  for (var fi = 0; fi < optionCandidates.length; fi++) {
    var flatOptions = normalizeBlankOptionList(optionCandidates[fi])
    if (!flatOptions.length) continue
    var ids = _inferBlankIds(q, content)
    // A number of old imports were incorrectly tagged as multi_blank_choice
    // even though they contain one ordinary choice blank and a scalar answer
    // (for example, “（ ）” + “D”). Keep those records on the normal option
    // path so the client keeps the scalar answer format used by the record.
    if (ids.length < 2) return []
    return ids.map(function (id) {
      return { id: id, options: _cloneOptions(flatOptions) }
    })
  }
  return []
}

/**
 * Enrich blank option groups with selection state.
 * @param {Array} groups - raw blank option groups
 * @param {string|object} answer - serialized or map answer
 * @returns {Array} enriched groups with _selected on each option
 */
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
          selected: blankAnswers[groupId] === key,
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
    var groupId = _groupId(group, '')
    return {
      id: groupId,
      options: normalizeBlankOptionList(group && group.options).map(function (opt) {
        var key = String((opt && opt.key) || '').trim().toUpperCase()
        var isCorrect = blankAnswers[groupId] === key
        var isUser = wrongAnswers[groupId] === key
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

function serializeBlankAnswer(groups, blankAnswers) {
  var normalizedGroups = (groups || []).map(function (group, index) {
    return Object.assign({}, group, { id: _groupId(group, String(index + 1)) })
  })
  return answerLib.serializeBlankAnswer(normalizedGroups, normalizeBlankAnswer(blankAnswers))
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
    // Handle rich option format: {"A": {"text": "...", "segments": [...]}}
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

    // Resolve image URLs in segments
    var resolvedSegments = null
    if (optSegments && Array.isArray(optSegments) && optSegments.length > 0) {
      resolvedSegments = optSegments.map(function (seg) {
        if (!seg || typeof seg !== 'object') return seg
        if (seg.url) return Object.assign({}, seg, { url: stemRender.resolveAssetUrl(seg.url) })
        return seg
      })
    }

    var isCorrect = correctSet ? !!correctSet[key] : key === (correctAnswer || '').trim().toUpperCase()
    var isUserAnswer = userSet ? !!userSet[key] : key === (userAnswer || '').trim().toUpperCase()

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

/* ==================== Answer correctness ==================== */

function getCorrectAnswer(q) {
  if (!q) return ''
  return q.answer || q.correct_answer || q.standard_answer || q.right_answer || ''
}

function isAnswerCorrect(q, userAnswer) {
  var correct = getCorrectAnswer(q)
  if (!correct || !userAnswer) return null
  // Legacy imports sometimes label an ordinary one-blank choice as
  // multi_blank_choice while storing a scalar answer ("D") and flat options.
  // Compare it as a regular single-choice question so the feedback state
  // matches the option list rendered by the fallback path.
  if (q && q.question_type === 'multi_blank_choice' &&
    !getBlankOptionGroups(q).length &&
    getQuestionOptions(q) &&
    !/[:：=;]/.test(String(correct))) {
    return answerLib.isAnswerCorrect(userAnswer, correct, 'single_choice')
  }
  return answerLib.isAnswerCorrect(userAnswer, correct, q.question_type)
}

/* ==================== Image helpers ==================== */

/**
 * Normalize a URL for comparison purposes.
 */
function _normalizeUrl(url) {
  if (!url || typeof url !== 'string') return ''
  var s = url.trim()
  if (s.length > 8 && s.charAt(s.length - 1) === '/') s = s.slice(0, -1)
  return s
}

/**
 * Get question image URLs from a question object.
 * Checks top-level image_url and content.image_url, deduplicated.
 */
function getQuestionImages(q) {
  if (!q) return []
  var seen = {}
  var urls = []

  if (Array.isArray(q.image_url)) {
    q.image_url.forEach(function (url) {
      if (url && typeof url === 'string' && !seen[url]) {
        seen[url] = true
        urls.push(stemRender.resolveAssetUrl(url))
      }
    })
  }

  if (q.content && Array.isArray(q.content.image_url)) {
    q.content.image_url.forEach(function (url) {
      if (url && typeof url === 'string' && !seen[url]) {
        seen[url] = true
        urls.push(stemRender.resolveAssetUrl(url))
      }
    })
  }

  return urls
}

/**
 * Extract all image URLs from content.segments that are rendered inline
 * by <math-question> in SEGMENTS mode.
 * Includes: image, math_image, table_image, code_image segment types.
 */
function getEmbeddedImageUrls(content) {
  if (!content || !Array.isArray(content.segments) || content.segments.length === 0) return []
  var seen = {}
  var urls = []
  for (var i = 0; i < content.segments.length; i++) {
    var seg = content.segments[i]
    if (!seg || typeof seg !== 'object') continue
    var url = seg.url
    if (url && typeof url === 'string') {
      var normalized = _normalizeUrl(url)
      if (normalized && !seen[normalized]) {
        seen[normalized] = true
        urls.push(normalized)
      }
    }
  }
  return urls
}

/**
 * Compute the list of extra images to display below the stem.
 *
 * In SEGMENTS mode, image-type segments are already rendered inline by
 * <math-question>. This function subtracts those from the total image set
 * to prevent duplication.
 *
 * In non-SEGMENTS modes, no inline images exist, so all images are returned.
 */
function computeExtraImages(q) {
  if (!q) return []
  var allUrls = getQuestionImages(q)
  if (!allUrls.length) return []

  var renderMode = (q._renderModel && q._renderModel.mode) || ''
  if (renderMode !== 'SEGMENTS') return allUrls

  var embedded = getEmbeddedImageUrls(q.content || {})
  if (!embedded.length) return allUrls

  var embeddedSet = {}
  for (var i = 0; i < embedded.length; i++) {
    embeddedSet[embedded[i]] = true
  }

  var extra = []
  for (var j = 0; j < allUrls.length; j++) {
    var normalized = _normalizeUrl(allUrls[j])
    if (!embeddedSet[normalized]) {
      extra.push(allUrls[j])
    }
  }
  return extra
}

/* ==================== Exports ==================== */

module.exports = {
  // Blank helpers
  normalizeBlankAnswer: normalizeBlankAnswer,
  normalizeBlankOptionList: normalizeBlankOptionList,
  getQuestionOptions: getQuestionOptions,
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

  // Image helpers
  getQuestionImages: getQuestionImages,
  getEmbeddedImageUrls: getEmbeddedImageUrls,
  computeExtraImages: computeExtraImages,
}
