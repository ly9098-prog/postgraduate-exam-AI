var { _escapeRegExp, _deduplicateRepeatedText } = require('./stem-render-text')
function _stripLeadingOptionLabel(key, value) {
var text = String(value || '').trim()
if (!key || !text) return text
var label = _escapeRegExp(String(key).trim())
var labelPattern = new RegExp('^' + label + '[\\s\\u00A0]*[.。．、:：）)]\\s*', 'i')
if (/^\s*\$/.test(text)) {
var inner = text.replace(/^\s*\$\s*/, '')
return '$' + inner.replace(labelPattern, '')
}
return text.replace(labelPattern, '')
}
function _normalizeOptionText(text) {
return String(text || '')
.replace(/<[^>]+>/g, ' ')
.replace(/&nbsp;/gi, ' ')
.replace(/\s+/g, ' ')
.trim()
}
function _buildOptionPattern(key, value) {
var label = _escapeRegExp(String(key || '').trim())
var normalizedValue = _normalizeOptionText(value)
if (!label || !normalizedValue) return ''
var spaces = '[\\s\\u00A0]*'
var separator = '[.。．、:：）)]'
var valuePattern = _escapeRegExp(normalizedValue).replace(/\s+/g, '[\\s\\u00A0]+')
return '' + label + spaces + separator + spaces + valuePattern
}
function _stripEmbeddedOptionBlock(stemText, options) {
if (!stemText || !options) return stemText
var patterns = Object.keys(options)
.sort()
.map(function (key) { return _buildOptionPattern(key, options[key]) })
.filter(Boolean)
if (patterns.length < 2) return stemText
var gap = '(?:\\s|<br>|\\n|\\r|&nbsp;)*'
var blockRegex = new RegExp('' + gap + patterns.join(gap) + '\\s*$', 'i')
return blockRegex.test(stemText) ? stemText.replace(blockRegex, '').trim() : stemText
}
function _findOptionLabelMatches(text, optionKeys) {
if (!text || !optionKeys || optionKeys.length < 2) return []
var labels = optionKeys.map(_escapeRegExp).join('|')
var labelMarker = '(?:^|[\\s\\n\\r])(?:' + labels + ')[\\s\\u00A0]*[.。．、:：）)]'
var labelRegex = new RegExp(labelMarker, 'g')
var matches = []
var match
while ((match = labelRegex.exec(text)) !== null) {
var index = match.index + (match[0].match(/^[\s\n\r]/) ? 1 : 0)
matches.push(index)
}
return matches
}
function _hasTrailingOptionBlock(text, optionKeys) {
if (!text || !optionKeys || optionKeys.length < 2) return false
var keys = optionKeys.map(function (key) { return String(key || '').trim() }).filter(Boolean)
if (keys.length < 2) return false
var spaces = '[\\s\\u00A0]*'
var separator = '[.。．、:：）)]'
var marker = function (key, prefix) { return '' + prefix + _escapeRegExp(key) + spaces + separator }
var first = marker(keys[0], '^' + spaces)
var second = marker(keys[1], '[\\s\\n\\r]+')
var required = new RegExp(first + '[\\s\\S]+?' + second, 'i')
if (!required.test(text)) return false
var labels = keys.map(_escapeRegExp).join('|')
var labelRegex = new RegExp('(?:^|[\\s\\n\\r])(?:' + labels + ')' + spaces + separator, 'g')
var found = []
var match
while ((match = labelRegex.exec(text)) !== null) {
found.push(String(match[0]).replace(/^[\s\n\r]+/, '').charAt(0).toUpperCase())
}
if (found.length < 2) return false
return found[0] === keys[0].toUpperCase() && found[1] === keys[1].toUpperCase()
}
function _stripTrailingOptionBlockByLabels(stemText, optionKeys) {
if (!stemText || !optionKeys || optionKeys.length < 2) return stemText
var matches = _findOptionLabelMatches(stemText, optionKeys)
if (matches.length < 2) return stemText
for (var i = 0; i < matches.length; i++) {
var suffix = stemText.slice(matches[i])
if (_hasTrailingOptionBlock(suffix, optionKeys)) return stemText.slice(0, matches[i]).trim()
}
return stemText
}
function _removeTrailingOptionKeys(text, optionKeys) {
if (!text || !optionKeys || optionKeys.length === 0) return text
var keys = optionKeys.map(_escapeRegExp).join('')
var pattern = new RegExp('\\s+[' + keys + ']\\s*$', 'g')
return text.replace(pattern, '')
}
function _cleanStemText(stemText, options, optionKeys) {
var normalized = String(stemText || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
var dedupedStem = _deduplicateRepeatedText(normalized)
var withoutExactOptions = _stripEmbeddedOptionBlock(dedupedStem, options)
var withoutLabelOptions = _stripTrailingOptionBlockByLabels(withoutExactOptions, optionKeys)
return _removeTrailingOptionKeys(withoutLabelOptions, optionKeys)
}
module.exports = {
  _stripLeadingOptionLabel,
  _normalizeOptionText,
  _buildOptionPattern,
  _stripEmbeddedOptionBlock,
  _findOptionLabelMatches,
  _hasTrailingOptionBlock,
  _stripTrailingOptionBlockByLabels,
  _removeTrailingOptionKeys,
  _cleanStemText,
}
