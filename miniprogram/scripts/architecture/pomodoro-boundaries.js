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
  'countdown-session-restore-controller.js': [],
  'free-session-restore-controller.js': [],
  'start-session-controller.js': [],
  'unknown-start-controller.js': [],
  'pending-sync-controller.js': [],
  'terminal-conflict-controller.js': [],
  'stats-controller.js': [],
  'countdown-controller.js': [],
  'free-timer-controller.js': [],
  'ring-geometry.js': [],
  'terminal-conflict-state.js': [],
  'canvas-layout.js': [],
  'sync-reconciliation.js': [],
  'session-restore.js': [],
  'cancel-confirm-state.js': ['./cancel-confirm-format'],
  'subject-selection.js': [],
  'completion-celebration.js': ['../../../utils/storage'],
  'terminal-conflict-handler.js': [],
  'pause-adjustment.js': [],
  'celebration-dismiss.js': [],
  'end-confirm-view-model.js': ['./timer-math'],
  'unknown-start-helpers.js': [],
  'cached-session-builder.js': [],
}
const PAGE = 'miniprogram/pages/pomodoro/pomodoro.js'
const UTILS = 'miniprogram/pages/pomodoro/utils'
const PAGE_MAX_LINES = 2577
const PAGE_METHODS = new Set([
  'onShow', 'onHide', 'onUnload', '_showRecoveryOptions', '_restoreCompletionView',
  '_clearRestoredConfirmation', '_restoreConfirmSnapshot', '_recoverActiveSession',
  '_hidePersistenceOptions', '_getSyncRetryController', '_registerNetworkStatusListener',
  '_unregisterNetworkStatusListener', '_isRetryablePomodoroSyncError',
  '_clearPendingPomodoroSyncRetryTimer', '_schedulePendingPomodoroSyncRetry',
  '_restoreSession', '_restoreFreeSession', '_getStartSessionController',
  'startSession', '_startFreeSession', '_getUnknownStartController',
  '_reconcileUnknownStartAttempt', '_postPomodoroStartWithReconciliation',
  '_getPendingSyncController', '_reconcilePendingPomodoroSyncFailure',
  '_retryPendingPomodoroSync', '_completePomodoroWithRetry',
  '_interruptPomodoroWithRetry',
  '_getTerminalConflictController', '_recordPomodoroTerminalConflict',
  '_readPomodoroTerminalConflict', '_consumePomodoroTerminalConflict',
  '_consumeAnyPomodoroTerminalConflict', '_ackPomodoroTerminalConflict',
  '_handlePomodoroTerminalConflict',
  '_getStatsController', 'loadTodayStats',
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
        const methodName = node.name.getText(file)
        if (methodName === '_restoreFreeSession' &&
            !hasControllerWiring(
              node,
              'createFreeSessionRestoreController',
              '_freeSessionRestoreController',
            )) {
          errors.push('free-session restore must assign a controller and delegate to it')
        }
        if (methodName === '_restoreSession') {
          const wiring = controllerWiring(
            node,
            'createCountdownSessionRestoreController',
            '_countdownSessionRestoreController',
            { requireFreeDispatch: true },
          )
          if (!wiring.assigned || !wiring.delegated || !wiring.assignedBeforeDelegate) {
            errors.push('countdown restore must assign a controller and delegate to it')
          }
          if (!wiring.shellMatches) {
            errors.push('countdown restore shell must return exactly one guarded controller delegation')
          }
          if (!wiring.freeDispatchBeforeDelegate) {
            errors.push('countdown restore must dispatch free sessions before controller delegation')
          }
        }
        if (methodName === '_getStartSessionController' &&
            !hasStartControllerAccessor(node)) {
          errors.push('start ceremony must lazily assign its controller')
        }
        if (methodName === 'startSession' &&
            !returnsStartControllerCall(node, 'start')) {
          errors.push('startSession must delegate to its controller')
        }
        if (methodName === '_startFreeSession' &&
            !returnsStartControllerCall(node, 'startFree', 'existingStartSeq')) {
          errors.push('free start must delegate to its controller')
        }
        if (methodName === '_getUnknownStartController' &&
            !hasLazyControllerAccessor(
              node,
              'createUnknownStartController',
              '_unknownStartController',
            )) {
          errors.push('unknown-start recovery must lazily assign its controller')
        }
        if (methodName === '_reconcileUnknownStartAttempt' &&
            !returnsControllerCall(
              node,
              '_getUnknownStartController',
              'reconcile',
              ['explicitAttempt'],
            )) {
          errors.push('unknown-start reconciliation must delegate to its controller')
        }
        if (methodName === '_postPomodoroStartWithReconciliation' &&
            !returnsControllerCall(
              node,
              '_getUnknownStartController',
              'postStart',
              ['payload', 'startSeq'],
            )) {
          errors.push('reconciled pomodoro POST must delegate to its controller')
        }
        if (methodName === '_getPendingSyncController' &&
            !hasLazyControllerAccessor(
              node,
              'createPendingSyncController',
              '_pendingSyncController',
            )) {
          errors.push('pending sync must lazily assign its controller')
        }
        if (methodName === '_reconcilePendingPomodoroSyncFailure' &&
            !returnsControllerCall(
              node,
              '_getPendingSyncController',
              'reconcileFailure',
              ['pending', 'error'],
            )) {
          errors.push('pending sync reconciliation must delegate to its controller')
        }
        if (methodName === '_retryPendingPomodoroSync' &&
            !returnsControllerCall(node, '_getPendingSyncController', 'drain', [])) {
          errors.push('pending sync drain must delegate to its controller')
        }
        if (methodName === '_completePomodoroWithRetry' &&
            !returnsControllerCall(
              node,
              '_getPendingSyncController',
              'complete',
              ['sessionId', 'clientActionAt'],
            )) {
          errors.push('retryable completion must delegate to its controller')
        }
        if (methodName === '_interruptPomodoroWithRetry' &&
            !returnsControllerCall(
              node,
              '_getPendingSyncController',
              'interrupt',
              ['sessionId', 'clientActionAt'],
            )) {
          errors.push('retryable interrupt must delegate to its controller')
        }
        if (methodName === '_getTerminalConflictController' &&
            !hasLazyControllerAccessor(
              node,
              'createTerminalConflictController',
              '_terminalConflictController',
            )) {
          errors.push('terminal conflict must lazily assign its controller')
        }
        if (methodName === '_recordPomodoroTerminalConflict' &&
            !returnsControllerCall(
              node,
              '_getTerminalConflictController',
              'record',
              ['sessionId', 'requestedAction', 'serverStatus'],
            )) {
          errors.push('terminal conflict record must delegate to its controller')
        }
        if (methodName === '_readPomodoroTerminalConflict' &&
            !returnsControllerCall(node, '_getTerminalConflictController', 'read', [])) {
          errors.push('terminal conflict read must delegate to its controller')
        }
        if (methodName === '_consumePomodoroTerminalConflict' &&
            !returnsControllerCall(
              node,
              '_getTerminalConflictController',
              'consume',
              ['sessionId', 'requestedAction'],
            )) {
          errors.push('terminal conflict consume must delegate to its controller')
        }
        if (methodName === '_consumeAnyPomodoroTerminalConflict' &&
            !returnsControllerCall(node, '_getTerminalConflictController', 'consumeAny', [])) {
          errors.push('terminal conflict consumeAny must delegate to its controller')
        }
        if (methodName === '_ackPomodoroTerminalConflict' &&
            !returnsControllerCall(node, '_getTerminalConflictController', 'ack', ['conflict'])) {
          errors.push('terminal conflict ack must delegate to its controller')
        }
        if (methodName === '_handlePomodoroTerminalConflict' &&
            !returnsControllerCall(
              node,
              '_getTerminalConflictController',
              'handle',
              ['sessionId', 'conflict'],
            )) {
          errors.push('terminal conflict handle must delegate to its controller')
        }
        if (methodName === '_getStatsController' &&
            !hasLazyControllerAccessor(node, 'createStatsController', '_statsController')) {
          errors.push('stats must lazily assign its controller')
        }
        if (methodName === 'loadTodayStats' &&
            !returnsControllerCall(node, '_getStatsController', 'load', [])) {
          errors.push('today stats must delegate to its controller')
        }
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

function isThisProperty(node, propertyName) {
  return ts.isPropertyAccessExpression(node) &&
    node.expression.kind === ts.SyntaxKind.ThisKeyword &&
    node.name.text === propertyName
}

function isSessionCall(node, methodName) {
  return ts.isCallExpression(node) &&
    ts.isPropertyAccessExpression(node.expression) &&
    node.expression.expression.kind === ts.SyntaxKind.ThisKeyword &&
    node.expression.name.text === methodName &&
    node.arguments.length === 1 &&
    ts.isIdentifier(node.arguments[0]) &&
    node.arguments[0].text === 'session'
}

function isSessionPresetFree(node) {
  if (!ts.isBinaryExpression(node) ||
      node.operatorToken.kind !== ts.SyntaxKind.EqualsEqualsEqualsToken) return false
  const leftIsPreset = ts.isPropertyAccessExpression(node.left) &&
    ts.isIdentifier(node.left.expression) &&
    node.left.expression.text === 'session' &&
    node.left.name.text === 'preset'
  const rightIsPreset = ts.isPropertyAccessExpression(node.right) &&
    ts.isIdentifier(node.right.expression) &&
    node.right.expression.text === 'session' &&
    node.right.name.text === 'preset'
  return (leftIsPreset && ts.isStringLiteral(node.right) && node.right.text === 'free') ||
    (rightIsPreset && ts.isStringLiteral(node.left) && node.left.text === 'free')
}

function returnsFreeRestore(statement) {
  let candidate = statement
  if (ts.isBlock(statement) && statement.statements.length === 1) {
    candidate = statement.statements[0]
  }
  return ts.isReturnStatement(candidate) &&
    isSessionCall(candidate.expression, '_restoreFreeSession')
}

function isGuardedControllerAssignment(statement, factoryName, propertyName) {
  if (!ts.isIfStatement(statement) ||
      !ts.isPrefixUnaryExpression(statement.expression) ||
      statement.expression.operator !== ts.SyntaxKind.ExclamationToken ||
      !isThisProperty(statement.expression.operand, propertyName) ||
      !ts.isBlock(statement.thenStatement) ||
      statement.thenStatement.statements.length !== 1) {
    return false
  }
  const assignment = statement.thenStatement.statements[0]
  return ts.isExpressionStatement(assignment) &&
    ts.isBinaryExpression(assignment.expression) &&
    assignment.expression.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
    isThisProperty(assignment.expression.left, propertyName) &&
    ts.isCallExpression(assignment.expression.right) &&
    ts.isIdentifier(assignment.expression.right.expression) &&
    assignment.expression.right.expression.text === factoryName
}

function isControllerDelegateStatement(statement, propertyName) {
  const expression = ts.isReturnStatement(statement)
    ? statement.expression
    : ts.isExpressionStatement(statement)
      ? statement.expression
      : null
  return !!expression &&
    ts.isCallExpression(expression) &&
    ts.isPropertyAccessExpression(expression.expression) &&
    expression.expression.name.text === 'restore' &&
    isThisProperty(expression.expression.expression, propertyName) &&
    expression.arguments.length === 1 &&
    ts.isIdentifier(expression.arguments[0]) &&
    expression.arguments[0].text === 'session'
}

function controllerWiring(method, factoryName, propertyName, options = {}) {
  const statements = ts.isBlock(method.body) ? method.body.statements : []
  const requireFreeDispatch = options.requireFreeDispatch === true
  const assignmentIndex = statements.findIndex(statement => (
    isGuardedControllerAssignment(statement, factoryName, propertyName)
  ))
  const delegateIndex = statements.findIndex(statement => (
    isControllerDelegateStatement(statement, propertyName)
  ))
  const freeDispatchIndex = statements.findIndex(statement => (
    ts.isIfStatement(statement) &&
    isSessionPresetFree(statement.expression) &&
    returnsFreeRestore(statement.thenStatement)
  ))
  const expectedAssignmentIndex = requireFreeDispatch ? 1 : 0
  const expectedDelegateIndex = requireFreeDispatch ? 2 : 1
  const shellMatches = statements.length === expectedDelegateIndex + 1 &&
    assignmentIndex === expectedAssignmentIndex &&
    delegateIndex === expectedDelegateIndex &&
    delegateIndex >= 0 &&
    ts.isReturnStatement(statements[delegateIndex]) &&
    (!requireFreeDispatch || freeDispatchIndex === 0)
  return {
    assigned: assignmentIndex >= 0,
    delegated: delegateIndex >= 0,
    shellMatches,
    assignedBeforeDelegate:
      assignmentIndex >= 0 && delegateIndex >= 0 && assignmentIndex < delegateIndex,
    freeDispatchBeforeDelegate:
      freeDispatchIndex >= 0 && delegateIndex >= 0 && freeDispatchIndex < delegateIndex,
  }
}

function hasControllerWiring(method, factoryName, propertyName, options) {
  const wiring = controllerWiring(method, factoryName, propertyName, options)
  return wiring.assigned && wiring.delegated && wiring.assignedBeforeDelegate &&
    wiring.shellMatches
}

function hasStartControllerAccessor(method) {
  return hasLazyControllerAccessor(
    method,
    'createStartSessionController',
    '_startSessionController',
  )
}

function hasLazyControllerAccessor(method, factoryName, propertyName) {
  const statements = ts.isBlock(method.body) ? method.body.statements : []
  return statements.length === 2 &&
    isGuardedControllerAssignment(
      statements[0],
      factoryName,
      propertyName,
    ) &&
    ts.isReturnStatement(statements[1]) &&
    isThisProperty(statements[1].expression, propertyName)
}

function returnsStartControllerCall(method, delegateName, expectedArgument) {
  return returnsControllerCall(
    method,
    '_getStartSessionController',
    delegateName,
    expectedArgument ? [expectedArgument] : [],
  )
}

function returnsControllerCall(method, accessorName, delegateName, expectedArguments) {
  const statements = ts.isBlock(method.body) ? method.body.statements : []
  if (statements.length !== 1 || !ts.isReturnStatement(statements[0])) return false
  const call = statements[0].expression
  if (!ts.isCallExpression(call) ||
      !ts.isPropertyAccessExpression(call.expression) ||
      call.expression.name.text !== delegateName ||
      !ts.isCallExpression(call.expression.expression) ||
      !ts.isPropertyAccessExpression(call.expression.expression.expression) ||
      call.expression.expression.expression.expression.kind !== ts.SyntaxKind.ThisKeyword ||
      call.expression.expression.expression.name.text !== accessorName) {
    return false
  }
  return call.arguments.length === expectedArguments.length &&
    expectedArguments.every((name, index) => (
      ts.isIdentifier(call.arguments[index]) && call.arguments[index].text === name
    ))
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
