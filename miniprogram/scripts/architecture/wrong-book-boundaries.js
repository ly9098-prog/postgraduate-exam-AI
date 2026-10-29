const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { inspectSource } = require('./learning-controller-budgets')
const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const PAGE = 'miniprogram/subpackages/study/wrong-book/wrong-book.js'
const DIRECTORY = 'miniprogram/subpackages/study/wrong-book/utils'
const PAGE_CEILING = 783
const MODULES = ['wrong-book-value-view.js', 'wrong-book-item-view.js',
  'wrong-book-analysis-view.js', 'wrong-book-view-page-adapter.js', 'wrong-book-request-flow.js',
  'wrong-book-selection-flow.js', 'wrong-book-batch-flow.js', 'wrong-book-batch-undo.js',
  'wrong-book-lifecycle.js', 'wrong-book-navigation-flow.js']
const REQUEST_DELEGATES = {
  "_beginFilterReload": "_beginFilterReload(patch) {\nreturn requestFlow._beginFilterReload(this, patch)\n}",
  "_loadPage": "async _loadPage() {\nreturn requestFlow._loadPage(this)\n}",
  "loadStats": "async loadStats() {\nreturn requestFlow.loadStats(this, { requestClient: api })\n}",
  "loadList": "async loadList(reset = false) {\nreturn requestFlow.loadList(this, reset, { requestClient: api })\n}",
  "loadTaskFlow": "async loadTaskFlow() {\nreturn requestFlow.loadTaskFlow(this, { requestClient: api })\n}",
  "loadSubjects": "async loadSubjects() {\nreturn requestFlow.loadSubjects(this, { requestClient: api })\n}"
}
const SELECTION_DELEGATES = {
  "switchView": "switchView(e) {\nreturn selectionFlow.switchView(this, e)\n}",
  "openAllQuestions": "openAllQuestions() {\nreturn selectionFlow.openAllQuestions(this)\n}",
  "toggleBatchMode": "toggleBatchMode() {\nreturn selectionFlow.toggleBatchMode(this)\n}",
  "onPageInteraction": "onPageInteraction() {\nreturn selectionFlow.onPageInteraction(this)\n}",
  "onPageScroll": "onPageScroll() {\nreturn selectionFlow.onPageScroll(this)\n}",
  "_clearBatchCapsuleIdleTimer": "_clearBatchCapsuleIdleTimer() {\nreturn selectionFlow._clearBatchCapsuleIdleTimer(this)\n}",
  "_scheduleBatchCapsuleAutoHide": "_scheduleBatchCapsuleAutoHide() {\nreturn selectionFlow._scheduleBatchCapsuleAutoHide(this, BATCH_CAPSULE_IDLE_MS)\n}",
  "_showBatchCapsuleAndRefreshTimer": "_showBatchCapsuleAndRefreshTimer() {\nreturn selectionFlow._showBatchCapsuleAndRefreshTimer(this)\n}",
  "onQuestionTap": "onQuestionTap(e) {\nreturn selectionFlow.onQuestionTap(this, e)\n}",
  "onSelectControlTap": "onSelectControlTap(e) {\nreturn selectionFlow.onSelectControlTap(this, e)\n}",
  "onQuestionLongPress": "onQuestionLongPress(e) {\nreturn selectionFlow.onQuestionLongPress(this, e, { getPlatform: () => wx })\n}",
  "_toggleQuestionSelection": "_toggleQuestionSelection(id) {\nreturn selectionFlow._toggleQuestionSelection(this, id)\n}",
  "_pulseSelectionBadge": "_pulseSelectionBadge() {\nreturn selectionFlow._pulseSelectionBadge(this)\n}",
  "_getVisibleIds": "_getVisibleIds() {\nreturn selectionFlow._getVisibleIds(this)\n}",
  "toggleSelectAll": "toggleSelectAll() {\nreturn selectionFlow.toggleSelectAll(this)\n}",
  "_syncSelectionState": "_syncSelectionState() {\nreturn selectionFlow._syncSelectionState(this)\n}"
}
const BATCH_DELEGATES = {
  "_showAppOptions": "_showAppOptions(opts) {\nreturn batchFlow._showAppOptions(this, opts)\n}",
  "openBatchMore": "async openBatchMore() {\nreturn batchFlow.openBatchMore(this, { getPlatform: () => wx })\n}",
  "onBatchAction": "async onBatchAction(e) {\nreturn batchFlow.onBatchAction(this, e, { requestClient: api, getPlatform: () => wx })\n}",
  "_resolveBatchIds": "_resolveBatchIds() {\nreturn batchFlow._resolveBatchIds(this)\n}",
  "_batchActionLabels": "_batchActionLabels() {\nreturn batchFlow._batchActionLabels()\n}",
  "_isDangerousBatchAction": "_isDangerousBatchAction(action) {\nreturn batchFlow._isDangerousBatchAction(action)\n}",
  "_batchConfirmMessage": "_batchConfirmMessage(action, count) {\nreturn batchFlow._batchConfirmMessage(action, count)\n}",
  "_handleBatchMastered": "async _handleBatchMastered(result, ids) {\nreturn batchUndo._handleBatchMastered(this, result, ids, { getPlatform: () => wx })\n}",
  "_handleBatchSuccess": "_handleBatchSuccess(result, labels, action) {\nreturn batchFlow._handleBatchSuccess(this, result, labels, action, { getPlatform: () => wx })\n}",
  "_handleBatchError": "_handleBatchError(err) {\nreturn batchFlow._handleBatchError(this, err, { getPlatform: () => wx })\n}",
  "_showBatchMissingEndpoint": "async _showBatchMissingEndpoint() {\nreturn batchFlow._showBatchMissingEndpoint(this, { getPlatform: () => wx })\n}",
  "_reloadAfterBatch": "_reloadAfterBatch() {\nreturn batchFlow._reloadAfterBatch(this)\n}",
  "undoBatchMaster": "undoBatchMaster() {\nreturn batchUndo.undoBatchMaster(this, { requestClient: api, getPlatform: () => wx })\n}",
  "_clearBatchMasterUndo": "_clearBatchMasterUndo(skipSetData) {\nreturn batchUndo._clearBatchMasterUndo(this, skipSetData)\n}",
  "_confirmBatchAction": "_confirmBatchAction(title, content) {\nreturn batchFlow._confirmBatchAction(this, title, content)\n}"
}
const LIFECYCLE_DELEGATES = {
  "onLoad": "onLoad(options) {\nreturn lifecycle.onLoad(this, options, { settings: config, safeDecodeURIComponent })\n}",
  "onReady": "onReady() {\nreturn lifecycle.onReady(this)\n}",
  "onShow": "onShow() {\nreturn lifecycle.onShow(this)\n}",
  "onHide": "onHide() {\nreturn lifecycle.onHide(this)\n}",
  "onUnload": "onUnload() {\nreturn lifecycle.onUnload(this)\n}",
  "_checkExportCapability": "async _checkExportCapability() {\nreturn navigationFlow._checkExportCapability(this, { settings: config, exportClient: exportApi })\n}",
  "goBack": "goBack() {\nreturn navigationFlow.goBack({ getPlatform: () => wx })\n}",
  "_navigateToDetail": "_navigateToDetail(id) {\nreturn navigationFlow._navigateToDetail(this, id, { getPlatform: () => wx })\n}",
  "onExportSelected": "onExportSelected() {\nreturn navigationFlow.onExportSelected(this, { getPlatform: () => wx, getApplication: () => getApp() })\n}",
  "onViewExportRecords": "onViewExportRecords() {\nreturn navigationFlow.onViewExportRecords({ getPlatform: () => wx })\n}",
  "goDetail": "goDetail(e) {\nreturn navigationFlow.goDetail(this, e)\n}"
}
const DELEGATES = {
  ...LIFECYCLE_DELEGATES,
  ...BATCH_DELEGATES,
  ...REQUEST_DELEGATES,
  ...SELECTION_DELEGATES,
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
    result.modules + ' modules, ' + result.delegates + ' delegates')
}
