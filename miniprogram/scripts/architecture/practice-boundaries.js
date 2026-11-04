const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { inspectSource } = require('./learning-controller-budgets')
const templates = require('./practice-page-templates.json')
const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const PAGE = 'miniprogram/subpackages/study/practice/practice.js'
const DIRECTORY = 'miniprogram/subpackages/study/practice/utils'
const MODULES = [
  'practice-subject-page-adapter', 'practice-exit-page-adapter',
  'practice-question-page-adapter', 'practice-submit-page-adapter',
  'practice-lifecycle-flow', 'practice-launch-flow',
]
const BINDINGS = {
  subjectPage: 'practice-subject-page-adapter', exitPage: 'practice-exit-page-adapter',
  questionPage: 'practice-question-page-adapter', submitPage: 'practice-submit-page-adapter',
  lifecycleFlow: 'practice-lifecycle-flow', launchFlow: 'practice-launch-flow',
}

function tokens(source) {
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.Standard, source)
  const result = []
  while (scanner.scan() !== ts.SyntaxKind.EndOfFileToken) {
    result.push([scanner.getToken(), scanner.getTokenText()])
  }
  return JSON.stringify(result)
}

function pageViolations(source) {
  const errors = [], pages = []
  const file = ts.createSourceFile(PAGE, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function walk(node) {
    if (ts.isCallExpression(node) && node.expression.getText(file) === 'Page') pages.push(node)
    ts.forEachChild(node, walk)
  }
  walk(file)
  if (file.parseDiagnostics.length) errors.push('invalid page syntax')
  const bindings = new Map()
  for (const statement of file.statements) {
    if (!ts.isVariableStatement(statement)) continue
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !Object.hasOwn(BINDINGS, declaration.name.text)) continue
      const name = declaration.name.text, value = declaration.initializer
      const valid = (statement.declarationList.flags & ts.NodeFlags.Const) &&
        value && ts.isCallExpression(value) && value.expression.getText(file) === 'require' &&
        value.arguments.length === 1 && ts.isStringLiteral(value.arguments[0]) &&
        value.arguments[0].text === './utils/' + BINDINGS[name]
      bindings.set(name, (bindings.get(name) || 0) + 1)
      if (!valid) errors.push('page binding drift: ' + name)
    }
  }
  for (const name of Object.keys(BINDINGS)) {
    if (bindings.get(name) !== 1) errors.push('page binding count: ' + name)
  }
  if (pages.length !== 1 || pages[0].arguments.length !== 1 ||
    !ts.isObjectLiteralExpression(pages[0].arguments[0])) return [...errors, 'page declaration']
  const properties = pages[0].arguments[0].properties
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
      const resumeImport = node.text === 'require' && ts.isCallExpression(parent) &&
        parent.expression === node && parent.arguments.length === 1 &&
        ts.isStringLiteral(parent.arguments[0]) &&
        parent.arguments[0].text === './cold-resume-controller' &&
        ['practice-lifecycle-flow', 'practice-question-page-adapter', 'practice-submit-page-adapter']
          .includes(name)
      const propertyName = (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
        (ts.isPropertyAssignment(parent) && parent.name === node)
      if (!propertyName && !resumeImport) errors.push('module global dependency: ' + node.text)
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return errors
}

function scanPractice() {
  const errors = pageViolations(fs.readFileSync(path.join(ROOT, PAGE), 'utf8'))
  for (const name of MODULES) {
    const filename = path.join(ROOT, DIRECTORY, name + '.js')
    if (!fs.existsSync(filename)) { errors.push('missing module: ' + name); continue }
    errors.push(...moduleViolations(fs.readFileSync(filename, 'utf8'), name))
  }
  return { errors, modules: MODULES.length, pageProperties: Object.keys(templates).length }
}

module.exports = { PAGE, MODULES, tokens, pageViolations, moduleViolations, scanPractice }

if (require.main === module) {
  const result = scanPractice()
  if (result.errors.length) {
    console.error(result.errors.join('\n'))
    process.exitCode = 1
  } else console.log('Practice boundaries passed: ' + result.modules + ' modules, ' + result.pageProperties + ' properties')
}
