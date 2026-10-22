const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const ROOT = path.resolve(__dirname, '../../..')
// Reuse the repository's declared development parser, never a Mini Program dependency.
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')
const MODULES = {
  'timer-math.js': [],
  'session-storage.js': [],
  'pending-sync-queue.js': [],
  'active-session-recovery.js': [],
  'completion-recovery.js': [],
  'confirm-recovery.js': ['./timer-math'],
  'hide-storage.js': [],
  'show-recovery.js': [],
  'sync-retry-controller.js': [],
  'subject-options.js': [],
  'countdown-controller.js': [],
  'free-timer-controller.js': [],
  'ring-geometry.js': [],
  'terminal-conflict-state.js': [],
  'canvas-layout.js': [],
  'sync-reconciliation.js': [],
  'session-restore.js': [],
  'cancel-confirm-state.js': ['./cancel-confirm-format'],
}
const PAGE = 'miniprogram/pages/pomodoro/pomodoro.js'
const UTILS = 'miniprogram/pages/pomodoro/utils'
const PAGE_MAX_LINES = 3328
const PAGE_METHODS = new Set([
  'onShow', 'onHide', 'onUnload', '_showRecoveryOptions', '_restoreCompletionView',
  '_clearRestoredConfirmation', '_restoreConfirmSnapshot', '_recoverActiveSession',
  '_hidePersistenceOptions', '_getSyncRetryController', '_registerNetworkStatusListener',
  '_unregisterNetworkStatusListener', '_isRetryablePomodoroSyncError',
  '_clearPendingPomodoroSyncRetryTimer', '_schedulePendingPomodoroSyncRetry',
])
const FORBIDDEN = new Set([
  'wx', 'Page', 'App', 'getApp', 'getCurrentPages', 'api', 'globalThis', 'global',
  'process', 'window', 'self', 'eval', 'Function', 'fetch', 'XMLHttpRequest', 'WebSocket', 'Date',
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'exports',
])

function parseSource(filename, source) {
  const file = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const errors = file.parseDiagnostics.map(d => `syntax: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`)
  if (!source.trim()) errors.push('empty source')
  if (!file.statements.length) errors.push('no executable statements')
  return { file, errors }
}

function lineCount(source) {
  return source.trimEnd().split('\n').length
}

function functionSize(node, file, errors) {
  if (!ts.isFunctionLike(node) || !node.body) return
  const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line
  const end = file.getLineAndCharacterOfPosition(node.end).line
  if (end - start + 1 > 50) errors.push(`function exceeds 50 lines at ${start + 1}`)
}

function checkRequire(node, allowed, errors, imports) {
  const call = node.parent
  if (!ts.isCallExpression(call) || call.expression !== node || call.arguments.length !== 1 ||
      !ts.isStringLiteral(call.arguments[0])) {
    errors.push('require must be a direct literal call')
    return
  }
  const dependency = call.arguments[0].text
  imports.add(dependency)
  if (!allowed.includes(dependency)) errors.push(`forbidden dependency: ${dependency}`)
}

function checkIdentifier(node, allowed, errors, imports) {
  if (!ts.isIdentifier(node)) return
  const name = node.text
  if (name === 'require') return checkRequire(node, allowed, errors, imports)
  if (name === 'module') {
    const access = node.parent
    if (!ts.isPropertyAccessExpression(access) || access.expression !== node || access.name.text !== 'exports') {
      errors.push('module may only be used for module.exports')
    }
    return
  }
  const parent = node.parent
  const propertyName = (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
    ((ts.isPropertyAssignment(parent) || ts.isMethodDeclaration(parent)) && parent.name === node)
  if (!propertyName && FORBIDDEN.has(name)) errors.push(`forbidden capability: ${name}`)
}

function moduleViolations(filename, source, allowed = []) {
  const { file, errors } = parseSource(filename, source)
  const imports = new Set()
  if (ts.isExternalModule(file)) errors.push('ES module syntax is forbidden in isolated CommonJS modules')
  if (lineCount(source) > 300) errors.push('module exceeds 300 lines')
  function walk(node) {
    functionSize(node, file, errors)
    checkIdentifier(node, allowed, errors, imports)
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node) ||
        (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)) {
      errors.push('ES imports and dynamic imports are forbidden in isolated CommonJS modules')
    }
    if (node.kind === ts.SyntaxKind.ThisKeyword) errors.push('implicit this dependency')
    ts.forEachChild(node, walk)
  }
  walk(file)
  return { errors, imports: [...imports] }
}

function pageViolations(source) {
  const { file, errors } = parseSource(PAGE, source)
  if (lineCount(source) > PAGE_MAX_LINES) errors.push(`page exceeds legacy ceiling ${PAGE_MAX_LINES}`)
  const methods = new Set()
  const imports = new Set()
  const pages = []
  function walk(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'Page' &&
        node.arguments.length === 1 && ts.isObjectLiteralExpression(node.arguments[0])) {
      pages.push(node.arguments[0])
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'require' &&
        node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0])) {
      imports.add(node.arguments[0].text)
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  if (pages.length !== 1) errors.push('expected exactly one literal Page definition')
  for (const page of pages) {
    for (const node of page.properties) {
      if (ts.isMethodDeclaration(node) && PAGE_METHODS.has(node.name.getText(file))) {
        methods.add(node.name.getText(file))
        functionSize(node, file, errors)
      }
    }
  }
  for (const name of PAGE_METHODS) if (!methods.has(name)) errors.push(`missing governed method: ${name}`)
  for (const name of Object.keys(MODULES)) {
    const target = `./utils/${name.slice(0, -3)}`
    if (!imports.has(target)) errors.push(`page no longer imports governed module: ${name}`)
  }
  return errors
}

function scanPomodoro(root = ROOT, read = filename => fs.readFileSync(filename, 'utf8')) {
  const violations = []
  let edges = 0
  for (const [name, allowed] of Object.entries(MODULES)) {
    const relative = `${UTILS}/${name}`
    const result = moduleViolations(relative, read(path.join(root, relative)), allowed)
    violations.push(...result.errors.map(error => `${relative}: ${error}`))
    edges += result.imports.length
  }
  violations.push(...pageViolations(read(path.join(root, PAGE))).map(error => `${PAGE}: ${error}`))
  return { violations, modules: Object.keys(MODULES).length, edges }
}

if (require.main === module) {
  const result = scanPomodoro()
  if (result.violations.length) {
    console.error(result.violations.join('\n'))
    process.exitCode = 1
  } else {
    console.log(`Pomodoro boundaries passed: ${result.modules} modules, ${result.edges} internal edges`)
  }
}

module.exports = { moduleViolations, pageViolations, scanPomodoro, MODULES, PAGE_MAX_LINES }
