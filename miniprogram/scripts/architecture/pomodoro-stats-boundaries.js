const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { inspectSource } = require('./learning-controller-budgets')
const templates = require('./pomodoro-stats-page-templates.json')
const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const PAGE = 'miniprogram/subpackages/productivity/pomodoro-stats/index.js'
const DIRECTORY = 'miniprogram/subpackages/productivity/pomodoro-stats'
const BINDINGS = {
  lifecyclePage: 'stats-lifecycle-page-adapter', distributionPage: 'stats-distribution-page-adapter',
  datePage: 'stats-date-page-adapter', animationPage: 'stats-animation-page-adapter',
  canvasPage: 'stats-canvas-page-adapter', loadViewFlow: 'stats-load-view-flow',
}
const MODULES = Object.values(BINDINGS)
const REGISTRATION = "if (typeof Page === 'function') Page(pageConfig)"
const EXPORT = `if (typeof module !== 'undefined' && module.exports) {
  module.exports = { formatDuration: durationFormatter.formatDuration }
}`

function tokens(source) {
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.Standard, source)
  const result = []
  while (scanner.scan() !== ts.SyntaxKind.EndOfFileToken) {
    result.push([scanner.getToken(), scanner.getTokenText()])
  }
  return JSON.stringify(result)
}

function pageViolations(source) {
  const errors = [], pages = [], registrations = []
  const file = ts.createSourceFile(PAGE, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function walk(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(file) === 'pageConfig') pages.push(node)
    if (ts.isCallExpression(node) && node.expression.getText(file) === 'Page') registrations.push(node)
    ts.forEachChild(node, walk)
  }
  walk(file)
  if (file.parseDiagnostics.length) errors.push('invalid page syntax')
  if (registrations.length !== 1 || registrations[0].arguments.length !== 1 ||
    registrations[0].arguments[0].getText(file) !== 'pageConfig') errors.push('page registration')
  const lastStatements = file.statements.slice(-2)
  if (lastStatements.length !== 2 ||
    tokens(lastStatements[0].getText(file)) !== tokens(REGISTRATION) ||
    tokens(lastStatements[1].getText(file)) !== tokens(EXPORT)) errors.push('page registration/export drift')
  const bindings = new Map()
  for (const statement of file.statements) {
    if (!ts.isVariableStatement(statement)) continue
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !Object.hasOwn(BINDINGS, declaration.name.text)) continue
      const name = declaration.name.text, value = declaration.initializer
      const valid = (statement.declarationList.flags & ts.NodeFlags.Const) &&
        value && ts.isCallExpression(value) && value.expression.getText(file) === 'require' &&
        value.arguments.length === 1 && ts.isStringLiteral(value.arguments[0]) &&
        value.arguments[0].text === './' + BINDINGS[name]
      bindings.set(name, (bindings.get(name) || 0) + 1)
      if (!valid) errors.push('page binding drift: ' + name)
    }
  }
  for (const name of Object.keys(BINDINGS)) {
    if (bindings.get(name) !== 1) errors.push('page binding count: ' + name)
  }
  if (pages.length !== 1 || !pages[0].initializer ||
    !ts.isObjectLiteralExpression(pages[0].initializer)) return [...errors, 'page declaration']
  const properties = pages[0].initializer.properties
  const names = properties.map(property => property.name && property.name.getText(file))
  if (JSON.stringify(names) !== JSON.stringify(Object.keys(templates))) errors.push('page property registration')
  for (const property of properties) {
    const name = property.name && property.name.getText(file)
    if (!Object.hasOwn(templates, name) || tokens(property.getText(file)) !== tokens(templates[name])) {
      errors.push('page property drift: ' + name)
    }
  }
  return errors
}

function moduleViolations(source, name) {
  const errors = inspectSource(source, name).errors
  const file = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const forbidden = new Set(['require', 'wx', 'process', 'global', 'globalThis', 'eval', 'Function'])
  function walk(node) {
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node) ||
      ts.isExportDeclaration(node) || node.kind === ts.SyntaxKind.ImportKeyword) {
      errors.push('module dependency drift: ' + name)
    }
    if (ts.isIdentifier(node) && forbidden.has(node.text)) {
      const parent = node.parent
      const propertyName = (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
        (ts.isPropertyAssignment(parent) && parent.name === node)
      if (!propertyName) errors.push('module global dependency: ' + node.text)
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return errors
}

function scanStats() {
  const errors = pageViolations(fs.readFileSync(path.join(ROOT, PAGE), 'utf8'))
  for (const name of MODULES) {
    const filename = path.join(ROOT, DIRECTORY, name + '.js')
    if (!fs.existsSync(filename)) { errors.push('missing module: ' + name); continue }
    errors.push(...moduleViolations(fs.readFileSync(filename, 'utf8'), name))
  }
  return { errors, modules: MODULES.length, pageProperties: Object.keys(templates).length }
}

module.exports = { PAGE, MODULES, tokens, pageViolations, moduleViolations, scanStats }

if (require.main === module) {
  const result = scanStats()
  if (result.errors.length) {
    console.error(result.errors.join('\n'))
    process.exitCode = 1
  } else console.log('Pomodoro stats boundaries passed: ' + result.modules + ' modules, ' + result.pageProperties + ' properties')
}
