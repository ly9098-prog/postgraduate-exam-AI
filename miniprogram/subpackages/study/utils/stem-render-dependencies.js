// Capture the original dependency ports once, in their historical import order.

var appConfig = require('../../../config')
var { formatInlineMathText, replaceSimpleLatexCommands } = require('./math-format')
var { containsCode, shouldReconstructCode, reconstructCode, sanitizeImportedCodeArtifacts } = require('./code-reconstructor')
var tableStructure = require('./table-structure')
var questionImageCache = require('./question-image-cache')

module.exports = {
  appConfig, formatInlineMathText, replaceSimpleLatexCommands, containsCode,
  shouldReconstructCode, reconstructCode, sanitizeImportedCodeArtifacts,
  tableStructure, questionImageCache,
}
