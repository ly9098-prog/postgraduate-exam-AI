
var _BROKEN_OP_PATTERNS = [
  { pattern: /(^|\W)\*\s*=(?!\s*=)/g, replacement: '$1*=' },
  { pattern: /(^|\W)\+\s*\+/g, replacement: '$1++' },
  { pattern: /(^|\W)\-\s*>(?!\s*>)/g, replacement: '$1->' },
  { pattern: /(^|\W)=\s*=(?!\s*=)/g, replacement: '$1==' },
  { pattern: /(^|\W)!\s*=/g, replacement: '$1!=' },
  { pattern: /(^|\W)<\s*=/g, replacement: '$1<=' },
  { pattern: /(^|\W)>\s*=/g, replacement: '$1>=' },
  { pattern: /\|\s*\|/g, replacement: '||' },
  { pattern: /&\s*&/g, replacement: '&&' },
]
var signals = require('./code-reconstructor-signals')
var _CONTROL_KEYWORDS = signals.controlKeywords
var _DS_KEYWORDS = signals.dataStructureKeywords
function _fixOcrOperators(text) {
  if (!text) return text
  var result = text
  for (var i = 0;i < _BROKEN_OP_PATTERNS.length;i++) {
    result = result.replace(_BROKEN_OP_PATTERNS[i].pattern, _BROKEN_OP_PATTERNS[i].replacement)
  }
  return result
}
function updateStringState(state, text, index) {
  var ch = text[index]
  if ((ch === '"' || ch === "'") && (index === 0 || text[index - 1] !== '\\')) {
    if (state.inString && ch === state.stringChar) {
      state.inString = false
    } else if (!state.inString) {
      state.inString = true
      state.stringChar = ch
    }
  }
}

function consumeStructure(state, ch, nextCh) {
  if (ch === '(') state.parenDepth++
  else if (ch === ')') state.parenDepth--
  if ((ch === ';' && state.parenDepth === 0) ||
    (ch === '{' && nextCh && nextCh !== '\n')) {
    state.current += ch
    state.lines.push(state.current)
    state.current = ''
    return true
  }
  if (ch === '}') {
    if (state.current.trim()) state.lines.push(state.current)
    state.current = '}'
    if (nextCh && nextCh !== '\n' && nextCh !== '}') {
      state.lines.push(state.current)
      state.current = ''
      return true
    }
  }
  return false
}

function splitSemicolons(text) {
  if (!text) return text
  var state = {
    lines: [], current: '', parenDepth: 0, inString: false, stringChar: '',
  }
  for (var i = 0;i < text.length;i++) {
    var ch = text[i]
    var nextCh = text[i + 1] || ''
    updateStringState(state, text, i)
    if (!state.inString && consumeStructure(state, ch, nextCh)) continue
    state.current += ch
  }
  if (state.current.trim()) state.lines.push(state.current)
  return state.lines.join('\n')
}

module.exports = {
  fixOcrOperators: _fixOcrOperators,
  recoverCompressedStructure: _recoverCompressedStructure,
  splitSemicolons: splitSemicolons,
}
function _recoverCompressedStructure(text) {
  if (!text) return text
  var result = text
  var kwPattern = _CONTROL_KEYWORDS.join('|')
  var reBeforeKw = new RegExp('(\\S)\\s*(?=\\b(' + kwPattern + ')\\b)', 'g')
  result = result.replace(reBeforeKw, '$1\n')
  var reAfterSemicolon = new RegExp(';\\s*(?=\\b(' + kwPattern + '|' + _DS_KEYWORDS.join('|') + ')\\b)', 'g')
  result = result.replace(reAfterSemicolon, ';\n')
  result = result.replace(/}(\s*)(?=\b(else|catch|finally|while)\b)/g, '}\n$1')
  return result
}
