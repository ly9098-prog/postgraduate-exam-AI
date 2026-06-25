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
 * All regex uses only lookahead (no lookbehind) for WeChat Mini Program
 * iOS WebView compatibility.
 *
 * Usage:
 *   var { reconstructCode, containsCode, shouldReconstructCode } = require('../../utils/code-reconstructor')
 *   var fixed = reconstructCode(text)
 */

// ---- OCR operator fix patterns ----
// Applied sequentially to fix common OCR damage
// Note: (^|\W) is used instead of (?<!\w) lookbehind for WeChat compatibility
var _BROKEN_OP_PATTERNS = [
  { pattern: /(^|\W)\*\s*=(?!\s*=)/g, replacement: '$1*=' },       // * =
  { pattern: /(^|\W)\+\s*\+/g, replacement: '$1++' },               // + +
  { pattern: /(^|\W)\-\s*>(?!\s*>)/g, replacement: '$1->' },        // - >
  { pattern: /(^|\W)=\s*=(?!\s*=)/g, replacement: '$1==' },         // = =
  { pattern: /(^|\W)!\s*=/g, replacement: '$1!=' },                  // ! =
  { pattern: /(^|\W)<\s*=/g, replacement: '$1<=' },                  // < =
  { pattern: /(^|\W)>\s*=/g, replacement: '$1>=' },                  // > =
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
  '->', '::', '{', '}', ';',
  '++', '--', '+=', '-=', '*=', '/=',
  '#include', '#define', 'main(',
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
 * Check if compressed code should be reconstructed.
 * Returns true only when:
 *   - Text contains code signals
 *   - Few newlines (0 or 1) — clearly compressed
 *   - Multiple statements (semicolons outside for-header parens >= 2)
 */
function shouldReconstructCode(text) {
  if (!text) return false
  if (!containsCode(text)) return false

  // Only reconstruct when code is compressed (few newlines)
  var newlines = 0
  for (var ni = 0; ni < text.length; ni++) {
    if (text[ni] === '\n') newlines++
    if (newlines > 1) return false
  }

  // Count semicolons outside for-header parens
  var semicolons = 0
  var parenDepth = 0
  for (var si = 0; si < text.length; si++) {
    if (text[si] === '(') parenDepth++
    if (text[si] === ')') parenDepth--
    if (text[si] === ';' && parenDepth === 0) semicolons++
    if (semicolons >= 2) return true
  }

  return false
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
 * at line start. Uses capture group instead of lookbehind for WeChat
 * Mini Program compatibility.
 */
function _recoverCompressedStructure(text) {
  if (!text) return text

  var result = text

  // Insert newline before control-flow keywords when they're mid-line
  // Uses (\S) capture instead of (?<=\S) lookbehind
  var kwPattern = _CONTROL_KEYWORDS.join('|')
  var reBeforeKw = new RegExp('(\\S)\\s*(?=\\b(' + kwPattern + ')\\b)', 'g')
  result = result.replace(reBeforeKw, '$1\n')

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
    // Normalize consecutive newlines from structure recovery
    result = result.replace(/\n{2,}/g, '\n').replace(/^\n/, '')
  }

  return result
}

// =============================================================================
// Dollar sign artifact detection and cleanup for imported code
// =============================================================================
//
// Imported OCR code sometimes contains $ characters from the AI normalization
// pipeline (used as line markers, LaTeX delimiters, or import-syntax artifacts).
// These are NOT part of the original code.
//
// Pipeline: sanitizeImportedCodeArtifacts() → shouldReconstructCode() → reconstructCode()
//
// Design principles:
//   - Conservative: only remove high-confidence $. Never use global replace.
//   - Context-aware: detect code language before deciding what to clean.
//   - Never touch PHP, Shell, or Perl $ syntax.
//   - Never touch JS regex /...$/, template literals `${}`, or $identifiers.
//   - Never touch char literal '$' or price strings "$10".
// =============================================================================

/**
 * Detect code language hint from code text.
 *
 * Returns a string: 'php', 'shell', 'perl', 'js', 'c-like', or 'unknown'.
 * Uses strong signals — no fuzzy heuristics.
 */
function detectCodeLanguageHint(code) {
  var text = String(code || '')

  // PHP: <?php or $_ superglobal access
  if (/<\?php/.test(text) || /\$_[A-Z]/.test(text)) {
    return 'php'
  }

  // Shell: shebang, $VAR, ${VAR}, $(cmd), $N positional params
  if (/^#!\//.test(text) || /\$\{[A-Za-z_]/.test(text) || /\$\(.+\)/.test(text) || /\$\d\b/.test(text)) {
    if (/\b(echo|export|source|cd\b|exit|chmod|chown|grep|sed|awk|cat|rm\b|mv\b|cp\b|ls\b|mkdir|rmdir)\b/.test(text)) {
      return 'shell'
    }
    // Heuristic: multiple $VAR patterns without C-like structure
    var dollarVars = text.match(/\$[A-Za-z_]\w*/g)
    if (dollarVars && dollarVars.length >= 3 && !/[{}]/.test(text) && !/;/.test(text)) {
      return 'shell'
    }
  }

  // Perl: @array, %hash with word chars (rare outside Perl)
  if (/@[A-Za-z_]\w*\b/.test(text) && /%[A-Za-z_]\w*\b/.test(text)) {
    return 'perl'
  }
  // Single strong Perl signal (isolated)
  if (/@[A-Za-z_]\w*\b/.test(text) && /\$[A-Za-z_]\w*/.test(text) && !/[{}]/.test(text)) {
    return 'perl'
  }

  // JS: template literal with ${}, or regex /...$/
  if (/\$\{[^}]+\}/.test(text) || /\/[^/]*\$\/[gimsuy]*/.test(text) || /[`]/.test(text)) {
    return 'js'
  }
  // JS: $ as identifier (const/let/var $el, $identifier =)
  if (/\b(const|let|var)\s+\$/.test(text)) {
    return 'js'
  }

  // C / C++ / Java style: strong signals
  // Note: #include uses (^|\W) prefix because \b before # doesn't work
  // ( # is not a word character, so \b boundary is unreliable)
  if (/\b(printf|scanf|int main|void main)\b/.test(text) ||
      /(^|\W)#\s*(include|define|pragma|import)\b/.test(text)) {
    return 'c-like'
  }

  // Structural hints for C-like: braces, semicolons, control flow
  if (/[{}]/.test(text) && /;/.test(text) && /\b(for|while|if|else|switch|case|return|typedef|struct)\b/.test(text)) {
    return 'c-like'
  }

  return 'unknown'
}

/**
 * Detect $ artifact patterns in code text.
 *
 * Returns { isLikelyArtifact, hasTrailingDollarArtifact, reasons }
 *   - isLikelyArtifact: true if high-confidence artifact patterns found
 *   - hasTrailingDollarArtifact: true if $ appears after ;{} at line end
 *   - reasons: array of diagnostic strings
 */
function detectDollarArtifactPattern(code) {
  var result = {
    isLikelyArtifact: false,
    hasTrailingDollarArtifact: false,
    reasons: [],
  }

  var text = String(code || '')
  if (!text || text.indexOf('$') === -1) return result

  // Pattern 1: $ after ; or { or } at line end (strong artifact signal)
  // e.g. "x++;$" or "}$" or "{ $"
  var trailingAfterBrace = text.match(/([;{}])[\t ]*\$(?=[\t ]*(?:\n|$))/g)
  if (trailingAfterBrace && trailingAfterBrace.length > 0) {
    result.reasons.push('TRAILING_AFTER_BRACE_SEMICOLON:' + trailingAfterBrace.length)
    result.hasTrailingDollarArtifact = true
  }

  // Pattern 2: $ on its own line (strong artifact signal)
  var standaloneLines = text.match(/^[\t ]*\$[\t ]*$/gm)
  if (standaloneLines && standaloneLines.length > 0) {
    result.reasons.push('STANDALONE_LINE:' + standaloneLines.length)
  }

  // Pattern 3: Multiple lines ending with $ (moderate signal)
  var lines = text.split('\n')
  var dollarEndLineCount = 0
  for (var i = 0; i < lines.length; i++) {
    var trimmed = lines[i].trim()
    if (trimmed.length > 0 && trimmed.charAt(trimmed.length - 1) === '$' && trimmed.charAt(trimmed.length - 2) !== '\\') {
      dollarEndLineCount++
    }
  }
  if (dollarEndLineCount >= 3) {
    result.reasons.push('MULTI_LINE_TRAILING_DOLLAR:' + dollarEndLineCount)
  }

  // Overall assessment: any strong pattern triggers artifact flag
  if (result.hasTrailingDollarArtifact || (standaloneLines && standaloneLines.length > 0)) {
    result.isLikelyArtifact = true
  }
  if (dollarEndLineCount >= 3 && !result.isLikelyArtifact) {
    result.isLikelyArtifact = true
  }

  return result
}

/**
 * Remove $ before escaped control chars (\n, \r, \t) inside double-quoted
 * strings. Uses a lightweight state machine to correctly handle:
 *   - String boundaries (respecting \" escapes)
 *   - Line comments //
 *   - Block comments /* *\/
 *   - Char literals '$'
 *
 * Only operates inside double-quoted strings where $ is followed by
 * backslash and n, r, or t — a common artifact in C-like code where
 * the $ was inserted before \n during AI text normalization.
 */
function _removeDollarBeforeEscapedControlInStrings(code) {
  var result = ''
  var i = 0
  var len = code.length

  while (i < len) {
    var ch = code[i]

    // Line comment // — skip to end of line
    if (ch === '/' && i + 1 < len && code[i + 1] === '/') {
      var eol = code.indexOf('\n', i)
      if (eol === -1) eol = len
      result += code.slice(i, eol)
      i = eol
      continue
    }

    // Block comment /* */ — skip to */
    if (ch === '/' && i + 1 < len && code[i + 1] === '*') {
      var endComment = code.indexOf('*/', i + 2)
      if (endComment === -1) endComment = len - 2
      result += code.slice(i, endComment + 2)
      i = endComment + 2
      continue
    }

    // Single-quote char literal: pass through as-is
    if (ch === "'") {
      result += ch
      i++
      while (i < len) {
        result += code[i]
        if (code[i] === '\\' && i + 1 < len) {
          i++
          result += code[i] // escaped char inside literal
        } else if (code[i] === "'") {
          i++
          break
        }
        i++
      }
      continue
    }

    // Double-quote string: this is where we look for $\n, $\r, $\t
    if (ch === '"') {
      result += ch
      i++
      while (i < len) {
        if (code[i] === '\\') {
          // Preserve escape sequence as-is
          result += code[i]
          i++
          if (i < len) {
            result += code[i]
            i++
          }
          continue
        }
        if (code[i] === '"') {
          result += code[i]
          i++
          break
        }
        // Check for $ before \n, \r, \t (three chars: $, \, n/r/t)
        if (code[i] === '$' && i + 2 < len && code[i + 1] === '\\' &&
            (code[i + 2] === 'n' || code[i + 2] === 'r' || code[i + 2] === 't')) {
          // Skip the $ — it's an artifact
          i++
          continue
        }
        result += code[i]
        i++
      }
      continue
    }

    result += ch
    i++
  }

  return result
}

/**
 * Sanitize imported code artifacts (dollar sign pollution).
 *
 * Cleans $ characters that are artifacts from the AI normalization / OCR
 * import pipeline, not part of the original code.
 *
 * Only runs on code that:
 *   1. Contains $ characters
 *   2. Is NOT PHP, Shell, or Perl (where $ is valid syntax)
 *   3. Shows high-confidence artifact patterns
 *
 * Cleaning phases:
 *   1. Remove $ after ;{} at line end: "; $" → ";", "} $" → "}"
 *   2. Remove standalone $ lines: "$\n" → ""
 *   3. For C-like code with high confidence: remove $ before \n\r\t in strings
 *
 * @param {string} code - The raw code text
 * @returns {string} Cleaned code text (unchanged if no artifacts found)
 */
function sanitizeImportedCodeArtifacts(code) {
  var text = String(code || '')
  if (!text || text.indexOf('$') === -1) return text

  // Step 1: Detect language
  var language = detectCodeLanguageHint(text)

  // Step 2: Skip languages where $ is valid syntax
  if (language === 'php' || language === 'shell' || language === 'perl') {
    return text
  }

  // Step 3: Detect artifact pattern
  var artifactInfo = detectDollarArtifactPattern(text)
  if (!artifactInfo.isLikelyArtifact) {
    return text
  }

  // Step 4: Save dollar count before cleaning (for DEV logging)
  var dollarBefore = (text.match(/\$/g) || []).length

  // Phase A: Remove $ after ;{} at line end:  "};$" → "}"  "x++;$" → "x++;"
  var result = text.replace(/([;{}])[\t ]*\$(?=[\t ]*(?:\n|$))/g, '$1')

  // Phase B: Remove standalone $ lines:  "$\n" → ""
  result = result.replace(/^[\t ]*\$[\t ]*$/gm, '')

  // Phase C: For C-like code with high confidence, clean $ in strings
  if (language === 'c-like' && artifactInfo.hasTrailingDollarArtifact) {
    result = _removeDollarBeforeEscapedControlInStrings(result)
  }

  // Normalize: collapse excessive blank lines from standalone $ removal
  result = result.replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '')

  // Step 5: DEV log
  var dollarAfter = (result.match(/\$/g) || []).length
  if (typeof console !== 'undefined' && dollarBefore !== dollarAfter) {
    console.log('[CODE_ARTIFACT_SANITIZE]', {
      removedDollarCount: dollarBefore - dollarAfter,
      language: language,
      reasons: artifactInfo.reasons,
    })
  }

  return result
}

module.exports = {
  reconstructCode: reconstructCode,
  containsCode: containsCode,
  shouldReconstructCode: shouldReconstructCode,
  sanitizeImportedCodeArtifacts: sanitizeImportedCodeArtifacts,
  detectCodeLanguageHint: detectCodeLanguageHint,
  detectDollarArtifactPattern: detectDollarArtifactPattern,
}
