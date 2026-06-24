/**
 * Code Structure Reconstruction Engine (Frontend)
 *
 * Rule-based code structure recovery for OCR-damaged code text.
 * No external dependencies — pure regex + state machine.
 *
 * Pipeline:
 *   1. Fix OCR operator errors (* = → *=, = = → ==, etc.)
 *   2. Recover structure from compressed code (for(...)for(...) → multi-line)
 *   3. Apply brace-depth-based indentation
 *
 * Usage:
 *   var { reconstructCode } = require('../../utils/code-reconstructor')
 *   var fixed = reconstructCode(text)
 */

// ---- OCR operator fix patterns ----
// Applied sequentially to fix common OCR damage
var _BROKEN_OP_PATTERNS = [
  { pattern: /(?<!\w)\*\s*=(?!\s*=)/g, replacement: '*=' },       // * =
  { pattern: /(?<!\w)\+\s*\+/g, replacement: '++' },               // + +
  { pattern: /(?<!\w)\-\s*>(?!\s*>)/g, replacement: '->' },        // - >
  { pattern: /(?<!\w)=\s*=(?!\s*=)/g, replacement: '==' },         // = =
  { pattern: /(?<!\w)!\s*=/g, replacement: '!=' },                  // ! =
  { pattern: /(?<!\w)<\s*=/g, replacement: '<=' },                  // < =
  { pattern: /(?<!\w)>\s*=/g, replacement: '>=' },                  // > =
  { pattern: /\|\s*\|/g, replacement: '||' },                      // | |
  { pattern: /&\s*&/g, replacement: '&&' },                        // & &
]

// ---- Control flow keywords for structure recovery ----
var _CONTROL_KEYWORDS = [
  'for', 'while', 'if', 'else if', 'else', 'switch',
  'return', 'break', 'continue', 'struct', 'class', 'typedef',
  'enum', 'case', 'default', 'catch', 'finally', 'try', 'do',
]

// ---- Code detection signals ----
var _CODE_SIGNALS = [
  'return', 'printf', 'scanf', 'malloc', 'free', 'NULL',
  'struct', 'typedef', 'enum', 'union',
  'int ', 'void ', 'char ', 'float ', 'double ',
  'bool', 'const', 'static', 'sizeof',
  '->', '::', '{', '}',
]

// ---- Keywords specific to 408 DS ----
var _DS_KEYWORDS = [
  'LNode', 'TNode', 'BiTNode', 'BiTree', 'BSTNode', 'LinkList',
  'SqList', 'Stack', 'Queue', 'SqStack', 'ElemType', 'Status',
]

/** Check if text contains code signals (heuristic). */
function containsCode(text) {
  if (!text) return false
  var score = 0
  for (var i = 0; i < _CODE_SIGNALS.length; i++) {
    if (text.indexOf(_CODE_SIGNALS[i]) !== -1) score++
  }
  for (var j = 0; j < _DS_KEYWORDS.length; j++) {
    if (text.indexOf(_DS_KEYWORDS[j]) !== -1) score += 2
  }
  for (var k = 0; k < _CONTROL_KEYWORDS.length; k++) {
    var kw = _CONTROL_KEYWORDS[k]
    var re = new RegExp('\\b' + kw + '\\b')
    if (re.test(text)) score++
  }
  return score >= 3
}

/**
 * Phase 1: Fix OCR operator damage.
 */
function _fixOcrOperators(text) {
  if (!text) return text
  var result = text
  for (var i = 0; i < _BROKEN_OP_PATTERNS.length; i++) {
    result = result.replace(_BROKEN_OP_PATTERNS[i].pattern, _BROKEN_OP_PATTERNS[i].replacement)
  }
  return result
}

/**
 * Phase 2a: Recover structure from compressed code.
 *
 * Inserts newlines before control-flow keywords that are not already
 * at line start.
 */
function _recoverCompressedStructure(text) {
  if (!text) return text

  var result = text

  // Insert newline before control-flow keywords when they're mid-line
  var kwPattern = _CONTROL_KEYWORDS.join('|')
  var reBeforeKw = new RegExp('(?<=\\S)\\s*(?=\\b(' + kwPattern + ')\\b)', 'g')
  result = result.replace(reBeforeKw, '\n')

  // Insert newline after semicolon when followed by a keyword
  var reAfterSemicolon = new RegExp(';\\s*(?=\\b(' + kwPattern + '|' + _DS_KEYWORDS.join('|') + ')\\b)', 'g')
  result = result.replace(reAfterSemicolon, ';\n')

  // Ensure closing brace followed by else/catch gets a newline
  result = result.replace(/}(\s*)(?=\b(else|catch|finally|while)\b)/g, '}\n$1')

  return result
}

/**
 * Phase 2b: Split statements at semicolons, respecting for/while headers.
 *
 * A semicolon inside for(;;) parens should NOT split.
 */
function _splitSemicolons(text) {
  if (!text) return text

  var lines = []
  var current = ''
  var parenDepth = 0
  var inString = false
  var stringChar = ''

  for (var i = 0; i < text.length; i++) {
    var ch = text[i]
    var nextCh = text[i + 1] || ''

    // Toggle string context
    if ((ch === '"' || ch === "'") && (i === 0 || text[i - 1] !== '\\')) {
      if (inString && ch === stringChar) {
        inString = false
      } else if (!inString) {
        inString = true
        stringChar = ch
      }
    }

    if (!inString) {
      if (ch === '(') {
        parenDepth++
      } else if (ch === ')') {
        parenDepth--
      }

      // Split at semicolons only outside parens (not inside for headers)
      if (ch === ';' && parenDepth === 0) {
        current += ch
        lines.push(current)
        current = ''
        continue
      }

      // Newline after { if not already at line end
      if (ch === '{' && nextCh && nextCh !== '\n') {
        current += ch
        lines.push(current)
        current = ''
        continue
      }

      // Newline before and after }
      if (ch === '}') {
        if (current.trim()) {
          lines.push(current)
        }
        current = '}'
        if (nextCh && nextCh !== '\n' && nextCh !== '}') {
          lines.push(current)
          current = ''
          continue
        }
      }
    }

    current += ch
  }

  if (current.trim()) {
    lines.push(current)
  }

  return lines.join('\n')
}

/**
 * Phase 3: Apply brace-depth-based indentation (4 spaces).
 */
function _indentCode(text) {
  if (!text || !text.trim()) return text

  var lines = text.split('\n')
  var result = []
  var depth = 0
  var indent = '    '

  for (var i = 0; i < lines.length; i++) {
    var line = lines[i]
    var stripped = line.trim()
    if (!stripped) {
      result.push('')
      continue
    }

    // Count braces
    var openCount = (stripped.match(/\{/g) || []).length
    var closeCount = (stripped.match(/\}/g) || []).length

    // Closing braces: dedent before producing the line
    var actualDepth = depth
    if (closeCount > 0 && stripped.charAt(0) === '}') {
      actualDepth = Math.max(0, depth - closeCount)
    }

    var indentedLine = indent.repeat(actualDepth) + stripped
    result.push(indentedLine)

    // Update depth for subsequent lines
    depth = Math.max(0, depth + openCount - closeCount)
  }

  return result.join('\n')
}

/**
 * Full pipeline: reconstruct damaged code text.
 *
 * @param {string} text - The damaged code text
 * @param {Object} [opts] - Options
 * @param {boolean} [opts.fixOperators=true] - Fix OCR operator damage
 * @param {boolean} [opts.fixStructure=true] - Recover line breaks and structure
 * @param {boolean} [opts.fixIndent=true] - Apply brace-depth indentation
 * @returns {string} Reconstructed code
 */
function reconstructCode(text, opts) {
  if (!text) return text

  opts = opts || {}
  var fixOperators = opts.fixOperators !== false
  var fixStructure = opts.fixStructure !== false
  var fixIndent = opts.fixIndent !== false

  // Phase 0: Only process if text contains code signals
  if (!containsCode(text)) return text

  var result = text

  // Phase 1: Fix OCR operator damage
  if (fixOperators) {
    result = _fixOcrOperators(result)
  }

  // Phase 2: Recover structure
  if (fixStructure) {
    result = _recoverCompressedStructure(result)
    result = _splitSemicolons(result)
  }

  // Phase 3: Apply indentation
  if (fixIndent) {
    result = _indentCode(result)
  }

  return result
}

module.exports = {
  reconstructCode: reconstructCode,
  containsCode: containsCode,
}
