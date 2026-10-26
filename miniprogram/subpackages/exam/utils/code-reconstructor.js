var signals = require('./code-reconstructor-signals')
var structure = require('./code-reconstructor-structure')
var artifacts = require('./code-reconstructor-artifacts')
var containsCode = signals.containsCode
var _fixOcrOperators = structure.fixOcrOperators
var _recoverCompressedStructure = structure.recoverCompressedStructure
var _splitSemicolons = structure.splitSemicolons
function shouldReconstructCode(text) {
  if (!text) return false
  if (!containsCode(text)) return false
  var newlines = 0
  for (var ni = 0;ni < text.length;ni++) {
    if (text[ni] === '\n') newlines++
    if (newlines > 1) return false
  }
  var semicolons = 0
  var parenDepth = 0
  for (var si = 0;si < text.length;si++) {
    if (text[si] === '(') parenDepth++
    if (text[si] === ')') parenDepth--
    if (text[si] === ';' && parenDepth === 0) semicolons++
    if (semicolons >= 2) return true
  }
  return false
}
function reconstructCode(text, opts) {
  if (!text) return text
  opts = opts || {}
  var fixOperators = opts.fixOperators !== false
  var fixStructure = opts.fixStructure !== false
  var fixIndent = opts.fixIndent !== false
  if (!containsCode(text)) return text
  var result = text
  if (fixOperators) {
    result = _fixOcrOperators(result)
  }
  if (fixStructure) {
    result = _recoverCompressedStructure(result)
    result = _splitSemicolons(result)
    result = result.replace(/\n{2,}/g, '\n').replace(/^\n/, '')
  }
  return result
}
module.exports = {
  reconstructCode: reconstructCode,
  containsCode: containsCode,
  shouldReconstructCode: shouldReconstructCode,
  sanitizeImportedCodeArtifacts: artifacts.sanitizeImportedCodeArtifacts,
  detectCodeLanguageHint: artifacts.detectCodeLanguageHint,
  detectDollarArtifactPattern: artifacts.detectDollarArtifactPattern,
}
