const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { inspectSource } = require('./learning-controller-budgets')
const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const PAGE = 'miniprogram/subpackages/study/wrong-detail/wrong-detail.js'
const DIRECTORY = 'miniprogram/subpackages/study/wrong-detail/utils'
const PAGE_CEILING = 1533
const MODULES = ['teacher-action-controller.js', 'wrong-detail-ai-state.js',
  'wrong-detail-question-view.js', 'wrong-detail-teacher-page-adapter.js']
const DIRECT_HELPERS = ['_aiPollDelayMs', '_isTimeoutError', '_generationMarker',
  '_fallbackMessage', '_isWqMastered']
const DELEGATES = {
  "_processWqData": "function _processWqData(wq, safeMode) {\nreturn processWqData(wq, safeMode, { isTrueFalseType, config, buildRenderModel, adapter, _subjectLabel, _errorTypeLabel })\n}",
  "_normalizeAiResult": "function _normalizeAiResult(content) {\nreturn aiState._normalizeAiResult(content, _buildAiRichText)\n}",
  "_hasStoredAnalysisValue": "function _hasStoredAnalysisValue(raw) {\nreturn aiState._hasStoredAnalysisValue(raw, normalizeAiAnalysisPayload, hasAiAnalysisContent)\n}",
  "_resolvePreferredAnalysis": "function _resolvePreferredAnalysis(wq) {\nreturn aiState._resolvePreferredAnalysis(wq, _hasStoredAnalysisValue, _normalizeAiPayload)\n}",
  "_teacherActionController": "_teacherActionController() {\n    if (!this._teacherActionCtl) {\n      this._teacherActionCtl = createTeacherActionController(buildTeacherActionPageCapabilities(this, { api, aiTeacher408, presentTeacherResult, AI_REQUEST_TIMEOUT_MS }))\n    }\n    return this._teacherActionCtl\n  }"
}
const TEACHER_PORTS = {
  "getAiLoading": "getAiLoading: () => page.data.aiLoading",
  "getAiRegenerating": "getAiRegenerating: () => page.data.aiRegenerating",
  "getTeacherLoadingAction": "getTeacherLoadingAction: () => page.data.teacherLoadingAction",
  "getWq": "getWq: () => page.data.wq",
  "getErrorDiagnosis": "getErrorDiagnosis: () => page.data.errorDiagnosis",
  "setData": "setData: patch => page.setData(patch)",
  "showToast": "showToast: options => wx.showToast(options)",
  "buildCacheKey": "buildCacheKey: (wq, diagnosis, action) => page._teacherCacheKeyForWrong(wq, diagnosis, action)",
  "getCacheEntry": "getCacheEntry: key => page._teacherCache && page._teacherCache[key]",
  "setCacheEntry": "setCacheEntry: (key, value) => {\n          if (!page._teacherCache) page._teacherCache = Object.create(null)\n          page._teacherCache[key] = value\n        }",
  "getFeedbackEntry": "getFeedbackEntry: key => (page._teacherFeedbackCache && page._teacherFeedbackCache[key]) || ''",
  "setActiveCacheKey": "setActiveCacheKey: key => { page._activeTeacherCacheKey = key }",
  "getInflight": "getInflight: key => {\n          if (!page._teacherInflight) page._teacherInflight = Object.create(null)\n          return page._teacherInflight[key]\n        }",
  "setInflight": "setInflight: (key, promise) => {\n          if (!page._teacherInflight) page._teacherInflight = Object.create(null)\n          page._teacherInflight[key] = promise\n        }",
  "deleteInflight": "deleteInflight: key => { delete page._teacherInflight[key] }",
  "nextRequestSequence": "nextRequestSequence: () => ++page._teacherRequestSeq",
  "getRequestSequence": "getRequestSequence: () => page._teacherRequestSeq",
  "isAlive": "isAlive: () => page._alive",
  "postTeacher": "postTeacher: payload => api.post('/ai/408-teacher', payload, { timeout: AI_REQUEST_TIMEOUT_MS })",
  "normalizeResult": "normalizeResult: raw => aiTeacher408.normalizeResult(raw)",
  "presentResult": "presentResult: normalized => presentTeacherResult(normalized)",
  "errorMessage": "errorMessage: error => aiTeacher408.errorMessage(error, api)"
}

function compact(source) { return source.replace(/\s+/g, '') }

function pageViolations(source) {
  const parsed = ts.createSourceFile(PAGE, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const declarations = new Map()
  function walk(node) {
    if ((ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) && node.name) {
      declarations.set(node.name.getText(parsed), node.getText(parsed))
    }
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  const errors = []
  for (const [name, expected] of Object.entries(DELEGATES)) {
    if (compact(declarations.get(name) || '') !== compact(expected)) errors.push('delegate drift: ' + name)
  }
  for (const name of DIRECT_HELPERS) if (declarations.has(name)) errors.push('helper returned: ' + name)
  const helperImport = 'const { ' + DIRECT_HELPERS.join(', ') + ' } = aiState'
  if (!source.includes(helperImport)) errors.push('AI helper import drift')
  for (const module of MODULES) {
    const request = "require('./utils/" + module.replace(/\.js$/, '') + "')"
    if (source.split(request).length !== 2) errors.push('page import: ' + module)
  }
  errors.push(...inspectSource(source, PAGE).errors.filter(error => !error.includes('module has')))
  if (source.trimEnd().split('\n').length > PAGE_CEILING) errors.push('page budget')
  return errors
}

function teacherPortViolations(source) {
  const parsed = ts.createSourceFile('adapter.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const ports = {}
  function walk(node) {
    if (ts.isReturnStatement(node) && node.expression && ts.isObjectLiteralExpression(node.expression)) {
      for (const property of node.expression.properties) {
        if (property.name) ports[property.name.getText(parsed)] = property.getText(parsed)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  const errors = []
  if (Object.keys(ports).join(',') !== Object.keys(TEACHER_PORTS).join(',')) errors.push('teacher port keys drift')
  for (const [name, expected] of Object.entries(TEACHER_PORTS)) {
    if (compact(ports[name] || '') !== compact(expected)) errors.push('teacher port drift: ' + name)
  }
  return errors
}

function moduleViolations(name, source) {
  if (!MODULES.includes(name)) return ['unregistered module: ' + name]
  const errors = [...inspectSource(source, name).errors]
  const parsed = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function walk(node) {
    if (node.kind === ts.SyntaxKind.ThisKeyword) errors.push(name + ': raw page receiver')
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node) ||
      ((ts.isCallExpression(node) || ts.isNewExpression(node)) &&
        (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
          ['require', 'eval', 'Function'].includes(node.expression.getText(parsed))))) {
      errors.push(name + ': forbidden dependency or dynamic execution')
    }
    if (ts.isIdentifier(node) && ['storage', 'getApp', 'Page'].includes(node.text)) {
      errors.push(name + ': forbidden platform port')
    }
    if (name !== 'wrong-detail-teacher-page-adapter.js' && ts.isIdentifier(node) &&
      ['wx', 'api'].includes(node.text)) errors.push(name + ': forbidden network/platform port')
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  if (name === 'wrong-detail-teacher-page-adapter.js') errors.push(...teacherPortViolations(source))
  return errors
}

function scanWrongDetail(options = {}) {
  const source = options.pageSource === undefined ? fs.readFileSync(path.join(ROOT, PAGE), 'utf8') : options.pageSource
  const modules = options.modules || Object.fromEntries(
    fs.readdirSync(path.join(ROOT, DIRECTORY)).filter(name => name.endsWith('.js'))
      .map(name => [name, fs.readFileSync(path.join(ROOT, DIRECTORY, name), 'utf8')]))
  const errors = pageViolations(source)
  for (const name of MODULES) if (!(name in modules)) errors.push('missing module: ' + name)
  for (const [name, value] of Object.entries(modules)) errors.push(...moduleViolations(name, value))
  return { errors, pageLines: source.trimEnd().split('\n').length,
    modules: Object.keys(modules).length, teacherPorts: Object.keys(TEACHER_PORTS).length }
}

module.exports = { PAGE, DIRECTORY, PAGE_CEILING, MODULES, DIRECT_HELPERS,
  DELEGATES, TEACHER_PORTS, pageViolations, moduleViolations, teacherPortViolations, scanWrongDetail }

if (require.main === module) {
  const result = scanWrongDetail()
  if (result.errors.length) { console.error(result.errors.join('\n')); process.exitCode = 1 }
  else console.log('Wrong-detail boundaries passed: ' + result.pageLines + ' page lines, ' +
    result.modules + ' modules, ' + result.teacherPorts + ' teacher ports')
}
