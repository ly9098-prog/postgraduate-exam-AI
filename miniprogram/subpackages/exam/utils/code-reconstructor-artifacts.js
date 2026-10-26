var _removeDollarBeforeEscapedControlInStrings = require('./code-reconstructor-strings').removeDollarBeforeEscapedControlInStrings
function detectCodeLanguageHint(code) {
  var text = String(code || '')
  if (/<\?php/.test(text) || /\$_[A-Z]/.test(text)) {
    return 'php'
  }
  if (/^#!\//.test(text) || /\$\{[A-Za-z_]/.test(text) || /\$\(.+\)/.test(text) || /\$\d\b/.test(text)) {
    if (/\b(echo|export|source|cd\b|exit|chmod|chown|grep|sed|awk|cat|rm\b|mv\b|cp\b|ls\b|mkdir|rmdir)\b/.test(text)) {
      return 'shell'
    }
    var dollarVars = text.match(/\$[A-Za-z_]\w*/g)
    if (dollarVars && dollarVars.length >= 3 && !/[{}]/.test(text) && !/;/.test(text)) {
      return 'shell'
    }
  }
  if (/@[A-Za-z_]\w*\b/.test(text) && /%[A-Za-z_]\w*\b/.test(text)) {
    return 'perl'
  }
  if (/@[A-Za-z_]\w*\b/.test(text) && /\$[A-Za-z_]\w*/.test(text) && !/[{}]/.test(text)) {
    return 'perl'
  }
  if (/\$\{[^}]+\}/.test(text) || /\/[^/]*\$\/[gimsuy]*/.test(text) || /[`]/.test(text)) {
    return 'js'
  }
  if (/\b(const|let|var)\s+\$/.test(text)) {
    return 'js'
  }
  if (/\b(printf|scanf|int main|void main)\b/.test(text) ||
    /(^|\W)#\s*(include|define|pragma|import)\b/.test(text)) {
    return 'c-like'
  }
  if (/[{}]/.test(text) && /;/.test(text) && /\b(for|while|if|else|switch|case|return|typedef|struct)\b/.test(text)) {
    return 'c-like'
  }
  return 'unknown'
}
function detectDollarArtifactPattern(code) {
  var result = {
    isLikelyArtifact: false,
    hasTrailingDollarArtifact: false,
    reasons: [],
  }
  var text = String(code || '')
  if (!text || text.indexOf('$') === -1) return result
  var trailingAfterBrace = text.match(/([;{}])[\t ]*\$(?=[\t ]*(?:\n|$))/g)
  if (trailingAfterBrace && trailingAfterBrace.length > 0) {
    result.reasons.push('TRAILING_AFTER_BRACE_SEMICOLON:' + trailingAfterBrace.length)
    result.hasTrailingDollarArtifact = true
  }
  var standaloneLines = text.match(/^[\t ]*\$[\t ]*$/gm)
  if (standaloneLines && standaloneLines.length > 0) {
    result.reasons.push('STANDALONE_LINE:' + standaloneLines.length)
  }
  var lines = text.split('\n')
  var dollarEndLineCount = 0
  for (var i = 0;i < lines.length;i++) {
    var trimmed = lines[i].trim()
    if (trimmed.length > 0 && trimmed.charAt(trimmed.length - 1) === '$' && trimmed.charAt(trimmed.length - 2) !== '\\') {
      dollarEndLineCount++
    }
  }
  if (dollarEndLineCount >= 3) {
    result.reasons.push('MULTI_LINE_TRAILING_DOLLAR:' + dollarEndLineCount)
  }
  if (result.hasTrailingDollarArtifact || (standaloneLines && standaloneLines.length > 0)) {
    result.isLikelyArtifact = true
  }
  if (dollarEndLineCount >= 3 && !result.isLikelyArtifact) {
    result.isLikelyArtifact = true
  }
  return result
}
function sanitizeImportedCodeArtifacts(code) {
  var text = String(code || '')
  if (!text || text.indexOf('$') === -1) return text
  var language = detectCodeLanguageHint(text)
  if (language === 'php' || language === 'shell' || language === 'perl') {
    return text
  }
  var artifactInfo = detectDollarArtifactPattern(text)
  if (!artifactInfo.isLikelyArtifact) {
    return text
  }
  var dollarBefore = (text.match(/\$/g) || []).length
  var result = text.replace(/([;{}])[\t ]*\$(?=[\t ]*(?:\n|$))/g, '$1')
  result = result.replace(/^[\t ]*\$[\t ]*$/gm, '')
  if (language === 'c-like' && artifactInfo.hasTrailingDollarArtifact) {
    result = _removeDollarBeforeEscapedControlInStrings(result)
  }
  result = result.replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '')
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
  sanitizeImportedCodeArtifacts: sanitizeImportedCodeArtifacts,
  detectCodeLanguageHint: detectCodeLanguageHint,
  detectDollarArtifactPattern: detectDollarArtifactPattern,
}
