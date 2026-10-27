var { stemRender, _hasOwn } = require('./question-adapter-dependencies')

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
    if (_hasOwn.call(options, 'options') && !_hasOwn.call(options, 'text') &&
      !_hasOwn.call(options, 'value') && !_hasOwn.call(options, 'segments')) {
      return normalizeBlankOptionList(options.options)
    }
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

module.exports = {
  _parseJsonValue,
  _optionText,
  normalizeBlankOptionList,
}
