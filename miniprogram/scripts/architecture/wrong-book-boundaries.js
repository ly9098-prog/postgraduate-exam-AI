const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { inspectSource } = require('./learning-controller-budgets')
const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const PAGE = 'miniprogram/subpackages/study/wrong-book/wrong-book.js'
const DIRECTORY = 'miniprogram/subpackages/study/wrong-book/utils'
const PAGE_CEILING = 1306
const MODULES = ['wrong-book-value-view.js', 'wrong-book-item-view.js',
  'wrong-book-analysis-view.js', 'wrong-book-view-page-adapter.js']
const DELEGATES = {
  "_flattenSubjectOptions": "_flattenSubjectOptions(raw) {\nreturn flattenSubjectOptions(raw)\n}",
  "_decorateItem": "_decorateItem(item) {\nreturn decorateItem(item, buildItemViewCapabilities(this))\n}",
  "_resolveReviewCount": "_resolveReviewCount(item) {\nreturn resolveReviewCount(item, buildItemViewCapabilities(this))\n}",
  "_resolveItemStatus": "_resolveItemStatus(isMastered, dueInfo, isRecent) {\nreturn resolveItemStatus(isMastered, dueInfo, isRecent, buildItemViewCapabilities(this))\n}",
  "_resolveItemContent": "_resolveItemContent(item) {\nreturn resolveItemContent(item, buildItemViewCapabilities(this))\n}",
  "_buildDecoratedItem": "_buildDecoratedItem(item, ctx) {\nreturn buildDecoratedItem(item, ctx, buildItemViewCapabilities(this))\n}",
  "_reviewDueInfo": "_reviewDueInfo(item, isMastered) {\nreturn reviewDueInfo(item, isMastered, parseServerUtc, getChinaDayRangeUtcMs)\n}",
  "_isRecentDate": "_isRecentDate(raw, days) {\nreturn isRecentDate(raw, days, parseServerUtc)\n}",
  "_shortDateLabel": "_shortDateLabel(date) {\nreturn shortDateLabel(date, formatChinaMonthDayCn)\n}",
  "_buildTaskGroups": "_buildTaskGroups(list = []) {\nreturn buildTaskGroups(list, parseServerUtc)\n}",
  "_oneLineInsight": "_oneLineInsight(text) {\nreturn oneLineInsight(text)\n}",
  "_buildAnalysis": "_buildAnalysis(stats = {}, list = []) {\nreturn buildAnalysis(stats, list, buildAnalysisViewCapabilities(this))\n}",
  "_buildSummaryCards": "_buildSummaryCards(stats = {}, list = [], weaknessTags = []) {\nreturn buildSummaryCards(stats, list, weaknessTags, buildAnalysisViewCapabilities(this))\n}",
  "_buildActionPlan": "_buildActionPlan(weaknessTags = [], subjectItems = [], list = []) {\nreturn buildActionPlan(weaknessTags, subjectItems, list, buildAnalysisViewCapabilities(this))\n}",
  "_rowsFromStats": "_rowsFromStats(stats, keys) {\nreturn rowsFromStats(stats, keys, buildAnalysisViewCapabilities(this))\n}",
  "_countsFromList": "_countsFromList(list, field) {\nreturn countsFromList(list, field)\n}",
  "_topItems": "_topItems(rows, limit) {\nreturn topItems(rows, limit)\n}",
  "_toPercentItems": "_toPercentItems(rows, labelFn) {\nreturn toPercentItems(rows, labelFn)\n}",
  "_radarPolygonStyle": "_radarPolygonStyle(items = []) {\nreturn radarPolygonStyle(items)\n}",
  "_radarAxisText": "_radarAxisText(items = []) {\nreturn radarAxisText(items)\n}",
  "_focusInsight": "_focusInsight(weaknessTags = [], subjectItems = [], list = []) {\nreturn focusInsight(weaknessTags, subjectItems, list)\n}",
  "_masteryProgress": "_masteryProgress(item, reviewCount) {\nreturn masteryProgress(item, reviewCount)\n}",
  "_positiveNumber": "_positiveNumber(value, fallback) {\nreturn positiveNumber(value, fallback)\n}",
  "_subjectLabel": "_subjectLabel(code, name) {\nreturn subjectLabel(code, name, getSubjectName)\n}",
  "_errorTypeLabel": "_errorTypeLabel(t) {\nreturn errorTypeLabel(t, errorDiagnosis)\n}",
  "_timeLabel": "_timeLabel(dateStr) {\nreturn timeLabel(dateStr, parseServerUtc, chinaCalendarDayDiff, formatChinaMonthDayCn)\n}",
  "_toCleanText": "_toCleanText(text) {\nreturn toCleanText(text, toPlainInlineMathText)\n}"
}

function compact(source) { return source.replace(/\s+/g, '') }

function pageViolations(source) {
  const errors = []
  const parsed = ts.createSourceFile(PAGE, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const methods = new Map()
  function walk(node) {
    if (ts.isMethodDeclaration(node)) methods.set(node.name.getText(parsed), node.getText(parsed))
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  for (const [name, expected] of Object.entries(DELEGATES)) {
    if (compact(methods.get(name) || '') !== compact(expected)) errors.push('delegate drift: ' + name)
  }
  for (const module of MODULES) {
    const request = "require('./utils/" + module.replace(/\.js$/, '') + "')"
    if (source.split(request).length !== 2) errors.push('page import: ' + module)
  }
  const result = inspectSource(source, PAGE)
  errors.push(...result.errors.filter(error => !error.includes('module has')))
  if (source.trimEnd().split('\n').length > PAGE_CEILING) errors.push('page budget')
  return errors
}

function moduleViolations(name, source) {
  if (!MODULES.includes(name)) return ['unregistered module: ' + name]
  const errors = [...inspectSource(source, name).errors]
  const parsed = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function walk(node) {
    if (node.kind === ts.SyntaxKind.ThisKeyword) errors.push(name + ': raw page receiver')
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node) ||
      ((ts.isCallExpression(node) || ts.isNewExpression(node)) && (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        ['require', 'eval', 'Function'].includes(node.expression.getText(parsed))))) {
      errors.push(name + ': forbidden dependency or dynamic execution')
    }
    if (ts.isIdentifier(node) && ['wx', 'api', 'storage', 'getApp', 'Page'].includes(node.text)) {
      errors.push(name + ': forbidden platform port ' + node.text)
    }
    ts.forEachChild(node, walk)
  }
  walk(parsed)
  return errors
}

function scanWrongBook(options = {}) {
  const pageSource = options.pageSource === undefined
    ? fs.readFileSync(path.join(ROOT, PAGE), 'utf8') : options.pageSource
  const modules = options.modules || Object.fromEntries(
    fs.readdirSync(path.join(ROOT, DIRECTORY)).filter(name => name.endsWith('.js'))
      .map(name => [name, fs.readFileSync(path.join(ROOT, DIRECTORY, name), 'utf8')]))
  const errors = pageViolations(pageSource)
  for (const name of MODULES) if (!(name in modules)) errors.push('missing module: ' + name)
  for (const [name, source] of Object.entries(modules)) errors.push(...moduleViolations(name, source))
  return { errors, pageLines: pageSource.trimEnd().split('\n').length,
    modules: Object.keys(modules).length, delegates: Object.keys(DELEGATES).length }
}

module.exports = { PAGE, DIRECTORY, PAGE_CEILING, MODULES, DELEGATES,
  pageViolations, moduleViolations, scanWrongBook }

if (require.main === module) {
  const result = scanWrongBook()
  if (result.errors.length) {
    console.error(result.errors.join('\n'))
    process.exitCode = 1
  } else console.log('Wrong-book boundaries passed: ' + result.pageLines + ' page lines, ' +
    result.modules + ' projection/adapter modules, ' + result.delegates + ' delegates')
}
