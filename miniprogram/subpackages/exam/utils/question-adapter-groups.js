var { _hasOwn } = require('./question-adapter-dependencies')
var { _parseJsonValue, normalizeBlankOptionList } = require('./question-adapter-options')

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
    var optionMap = Object.assign({}, group)
    delete optionMap.id
    delete optionMap.marker
    delete optionMap.blank_id
    copy.options = optionMap
  }
  return copy
}

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
    ; (ids || []).forEach(function (id) {
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
  var optionCandidates = _optionCandidates(q, content)
  for (var oi = 0; oi < optionCandidates.length; oi++) {
    var groupedOptions = _coerceBlankOptionGroups(optionCandidates[oi])
    if (groupedOptions.length) return groupedOptions
  }
  var isMultiBlank = q.question_type === 'multi_blank_choice' || q.question_type === 'multi_blank_multiple_choice'
  if (!isMultiBlank) return []
  for (var fi = 0; fi < optionCandidates.length; fi++) {
    var flatOptions = normalizeBlankOptionList(optionCandidates[fi])
    if (!flatOptions.length) continue
    var ids = _inferBlankIds(q, content)
    if (ids.length < 2) return []
    return ids.map(function (id) {
      return { id: id, options: _cloneOptions(flatOptions) }
    })
  }
  return []
}

module.exports = {
  _groupId,
  getQuestionOptions,
  getBlankOptionGroups,
}
