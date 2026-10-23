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
  'theme-controller.js': [],
  'end-confirm-snapshot.js': [],
  'active-sync-controller.js': [],
  'pause-toggle-controller.js': [],
  'resume-error-controller.js': [],
  'celebration-dismiss-controller.js': [],
  'break-restore-controller.js': [],
  'completion-celebration-controller.js': [],
  'work-complete-controller.js': [],
  'free-timer-begin-controller.js': [],
  'cancel-end-confirm-controller.js': ['./cancel-confirm-state'],
  'show-end-free-confirm-controller.js': ['./end-confirm-snapshot', './end-confirm-view-model'],
  'pause-countdown-end-confirm-controller.js': ['./end-confirm-snapshot'],
  'confirm-interrupt-countdown-controller.js': [],
  'reset-to-idle-controller.js': [],
  'update-free-elapsed-controller.js': ['./timer-math'],
  'begin-countdown-controller.js': [],
  'pause-session-controller.js': [],
  'resume-session-controller.js': [],
  'show-countdown-interrupt-confirm-controller.js': ['./end-confirm-view-model'],
  'confirm-end-timer-controller.js': [],
  'end-session-controller.js': [],
  'pause-free-timer-controller.js': ['./timer-math'],
  'resume-free-timer-controller.js': [],
  'interrupt-session-controller.js': [],
  'confirm-end-free-timer-controller.js': [],
  'free-timer-limit-controller.js': ['./timer-math'],
  'free-elapsed-controller.js': ['./timer-math'],
  'start-break-controller.js': ['./countdown-controller'],
  'start-timer-controller.js': ['./countdown-controller'],
  'canvas-init-controller.js': ['./canvas-layout'],
  'draw-ring-controller.js': ['./ring-geometry'],
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
const PAGE_MAX_LINES = 2180
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
  '_getThemeController', '_getThemeViewModel', '_syncThemeFromStorage',
  '_applyTheme', 'toggleTheme',
  '_getActiveSyncController', '_canLightSyncActive', '_syncActiveSessionLight',
  '_getPauseToggleController', '_acquirePauseToggleLock', '_releasePauseToggleLock',
  'togglePause',
  '_getResumeErrorController', '_reconcileAfterResumeError',
  '_getCelebrationDismissController', 'dismissCelebration',
  '_getBreakRestoreController', '_restoreBreak',
  '_getCompletionCelebrationController', '_showCompletionCelebration',
  '_getWorkCompleteController', '_onWorkComplete',
  '_getFreeTimerBeginController', '_beginFreeTimer',
  '_getCancelEndConfirmController', 'cancelEndConfirm',
  '_getShowEndFreeConfirmController', '_showEndFreeConfirm',
  '_getPauseCountdownEndConfirmController', '_pauseCountdownForEndConfirm',
  '_getConfirmInterruptCountdownController', '_confirmInterruptCountdown',
  '_getResetToIdleController', '_resetToIdle',
  '_getUpdateFreeElapsedController', '_updateFreeElapsed',
  '_getBeginCountdownController', '_beginCountdown',
  '_getPauseSessionController', '_pauseSession',
  '_getResumeSessionController', '_resumeSession',
  '_getShowCountdownInterruptConfirmController', '_showCountdownInterruptConfirm',
  '_getConfirmEndTimerController', 'confirmEndTimer',
  '_getEndSessionController', 'endSession',
  '_getPauseFreeTimerController', '_pauseFreeTimer',
  '_getResumeFreeTimerController', '_resumeFreeTimer',
  '_getInterruptSessionController', 'interruptSession',
  '_getConfirmEndFreeTimerController', '_confirmEndFreeTimer',
  '_getFreeTimerLimitController', '_checkFreeTimerLimitAndAutoEnd',
  '_autoFinishFreeTimer', '_completeFreeTimerSession',
  '_getFreeElapsedMs', '_getEffectiveFreeElapsedMs', '_getFreeElapsedController',
  '_getStartBreakController', '_startBreak',
  '_getStartTimerController', '_startTimer',
  '_initCanvas', '_scheduleCanvasInit', '_getCanvasInitController',
  '_getDrawRingController', 'drawRing',
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
        if (methodName === '_getThemeController' &&
            !hasLazyControllerAccessor(node, 'createThemeController', '_themeController')) {
          errors.push('theme must lazily assign its controller')
        }
        if (methodName === '_getThemeViewModel' &&
            !returnsControllerCall(node, '_getThemeController', 'viewModel', ['mode'])) {
          errors.push('theme view model must delegate to its controller')
        }
        if (methodName === '_syncThemeFromStorage' &&
            !returnsControllerCall(node, '_getThemeController', 'sync', [])) {
          errors.push('theme storage sync must delegate to its controller')
        }
        if (methodName === '_applyTheme' &&
            !returnsControllerCall(
              node,
              '_getThemeController',
              'apply',
              ['mode', 'persist', 'animate'],
            )) {
          errors.push('theme apply must delegate to its controller')
        }
        if (methodName === 'toggleTheme' &&
            !returnsControllerCall(node, '_getThemeController', 'toggle', [])) {
          errors.push('theme toggle must delegate to its controller')
        }
        if (methodName === '_getActiveSyncController' &&
            !hasLazyControllerAccessor(
              node,
              'createActiveSyncController',
              '_activeSyncController',
            )) {
          errors.push('active sync must lazily assign its controller')
        }
        if (methodName === '_canLightSyncActive' &&
            !returnsControllerCall(node, '_getActiveSyncController', 'canLightSync', ['active'])) {
          errors.push('active light-sync eligibility must delegate to its controller')
        }
        if (methodName === '_syncActiveSessionLight' &&
            !returnsControllerCall(
              node,
              '_getActiveSyncController',
              'syncLight',
              ['active', 'failClosed'],
            )) {
          errors.push('active light sync must delegate to its controller')
        }
        if (methodName === '_getPauseToggleController' &&
            !hasLazyControllerAccessor(
              node,
              'createPauseToggleController',
              '_pauseToggleController',
            )) {
          errors.push('pause toggle must lazily assign its controller')
        }
        if (methodName === '_acquirePauseToggleLock' &&
            !returnsControllerCall(node, '_getPauseToggleController', 'acquire', [])) {
          errors.push('pause toggle acquire must delegate to its controller')
        }
        if (methodName === '_releasePauseToggleLock' &&
            !callsControllerCall(node, '_getPauseToggleController', 'release', [])) {
          errors.push('pause toggle release must delegate to its controller')
        }
        if (methodName === 'togglePause' &&
            !callsControllerCall(node, '_getPauseToggleController', 'toggle', [])) {
          errors.push('pause toggle must delegate to its controller')
        }
        if (methodName === '_getResumeErrorController' &&
            !hasLazyControllerAccessor(
              node,
              'createResumeErrorController',
              '_resumeErrorController',
            )) {
          errors.push('resume error must lazily assign its controller')
        }
        if (methodName === '_reconcileAfterResumeError' &&
            !returnsControllerCall(
              node,
              '_getResumeErrorController',
              'reconcile',
              ['e', 'sessionId'],
            )) {
          errors.push('resume error reconcile must delegate to its controller')
        }
        if (methodName === '_getCelebrationDismissController' &&
            !hasLazyControllerAccessor(
              node,
              'createCelebrationDismissController',
              '_celebrationDismissController',
            )) {
          errors.push('celebration dismiss must lazily assign its controller')
        }
        if (methodName === 'dismissCelebration' &&
            !returnsControllerCall(node, '_getCelebrationDismissController', 'dismiss', [])) {
          errors.push('celebration dismiss must delegate to its controller')
        }
        if (methodName === '_getBreakRestoreController' &&
            !hasLazyControllerAccessor(
              node,
              'createBreakRestoreController',
              '_breakRestoreController',
            )) {
          errors.push('break restore must lazily assign its controller')
        }
        if (methodName === '_restoreBreak' &&
            !returnsControllerCall(node, '_getBreakRestoreController', 'restore', [])) {
          errors.push('break restore must delegate to its controller')
        }
        if (methodName === '_getCompletionCelebrationController' &&
            !hasLazyControllerAccessor(
              node,
              'createCompletionCelebrationController',
              '_completionCelebrationController',
            )) {
          errors.push('completion celebration must lazily assign its controller')
        }
        if (methodName === '_showCompletionCelebration' &&
            !returnsControllerCall(
              node,
              '_getCompletionCelebrationController',
              'show',
              ['sessionId', 'options'],
            )) {
          errors.push('completion celebration must delegate to its controller')
        }
        if (methodName === '_getWorkCompleteController' &&
            !hasLazyControllerAccessor(
              node,
              'createWorkCompleteController',
              '_workCompleteController',
            )) {
          errors.push('work complete must lazily assign its controller')
        }
        if (methodName === '_onWorkComplete' &&
            !returnsControllerCall(node, '_getWorkCompleteController', 'complete', [])) {
          errors.push('work complete must delegate to its controller')
        }
        if (methodName === '_getFreeTimerBeginController' &&
            !hasLazyControllerAccessor(
              node,
              'createFreeTimerBeginController',
              '_freeTimerBeginController',
            )) {
          errors.push('free timer begin must lazily assign its controller')
        }
        if (methodName === '_beginFreeTimer' &&
            !returnsControllerCall(node, '_getFreeTimerBeginController', 'begin', ['session'])) {
          errors.push('free timer begin must delegate to its controller')
        }
        if (methodName === '_getCancelEndConfirmController' &&
            !hasLazyControllerAccessor(
              node,
              'createCancelEndConfirmController',
              '_cancelEndConfirmController',
            )) {
          errors.push('cancel end confirm must lazily assign its controller')
        }
        if (methodName === 'cancelEndConfirm' &&
            !returnsControllerCall(node, '_getCancelEndConfirmController', 'cancel', [])) {
          errors.push('cancel end confirm must delegate to its controller')
        }
        if (methodName === '_getShowEndFreeConfirmController' &&
            !hasLazyControllerAccessor(
              node,
              'createShowEndFreeConfirmController',
              '_showEndFreeConfirmController',
            )) {
          errors.push('show end free confirm must lazily assign its controller')
        }
        if (methodName === '_showEndFreeConfirm' &&
            !returnsControllerCall(node, '_getShowEndFreeConfirmController', 'show', [])) {
          errors.push('show end free confirm must delegate to its controller')
        }
        if (methodName === '_getPauseCountdownEndConfirmController' &&
            !hasLazyControllerAccessor(
              node,
              'createPauseCountdownEndConfirmController',
              '_pauseCountdownEndConfirmController',
            )) {
          errors.push('pause countdown end confirm must lazily assign its controller')
        }
        if (methodName === '_pauseCountdownForEndConfirm' &&
            !returnsControllerCall(node, '_getPauseCountdownEndConfirmController', 'pause', [])) {
          errors.push('pause countdown end confirm must delegate to its controller')
        }
        if (methodName === '_getConfirmInterruptCountdownController' &&
            !hasLazyControllerAccessor(
              node,
              'createConfirmInterruptCountdownController',
              '_confirmInterruptCountdownController',
            )) {
          errors.push('confirm interrupt countdown must lazily assign its controller')
        }
        if (methodName === '_confirmInterruptCountdown' &&
            !returnsControllerCall(node, '_getConfirmInterruptCountdownController', 'confirm', [])) {
          errors.push('confirm interrupt countdown must delegate to its controller')
        }
        if (methodName === '_getResetToIdleController' &&
            !hasLazyControllerAccessor(
              node,
              'createResetToIdleController',
              '_resetToIdleController',
            )) {
          errors.push('reset to idle must lazily assign its controller')
        }
        if (methodName === '_resetToIdle' &&
            !returnsControllerCall(node, '_getResetToIdleController', 'reset', [])) {
          errors.push('reset to idle must delegate to its controller')
        }
        if (methodName === '_getUpdateFreeElapsedController' &&
            !hasLazyControllerAccessor(
              node,
              'createUpdateFreeElapsedController',
              '_updateFreeElapsedController',
            )) {
          errors.push('update free elapsed must lazily assign its controller')
        }
        if (methodName === '_updateFreeElapsed' &&
            !returnsControllerCall(node, '_getUpdateFreeElapsedController', 'update', [])) {
          errors.push('update free elapsed must delegate to its controller')
        }
        if (methodName === '_getBeginCountdownController' &&
            !hasLazyControllerAccessor(
              node,
              'createBeginCountdownController',
              '_beginCountdownController',
            )) {
          errors.push('begin countdown must lazily assign its controller')
        }
        if (methodName === '_beginCountdown' &&
            !returnsControllerCall(node, '_getBeginCountdownController', 'begin', ['session'])) {
          errors.push('begin countdown must delegate to its controller')
        }
        if (methodName === '_getPauseSessionController' &&
            !hasLazyControllerAccessor(
              node,
              'createPauseSessionController',
              '_pauseSessionController',
            )) {
          errors.push('pause session must lazily assign its controller')
        }
        if (methodName === '_pauseSession' &&
            !returnsControllerCall(node, '_getPauseSessionController', 'pause', [])) {
          errors.push('pause session must delegate to its controller')
        }
        if (methodName === '_getResumeSessionController' &&
            !hasLazyControllerAccessor(
              node,
              'createResumeSessionController',
              '_resumeSessionController',
            )) {
          errors.push('resume session must lazily assign its controller')
        }
        if (methodName === '_resumeSession' &&
            !returnsControllerCall(node, '_getResumeSessionController', 'resume', [])) {
          errors.push('resume session must delegate to its controller')
        }
        if (methodName === '_getShowCountdownInterruptConfirmController' &&
            !hasLazyControllerAccessor(
              node,
              'createShowCountdownInterruptConfirmController',
              '_showCountdownInterruptConfirmController',
            )) {
          errors.push('show countdown interrupt confirm must lazily assign its controller')
        }
        if (methodName === '_showCountdownInterruptConfirm' &&
            !returnsControllerCall(node, '_getShowCountdownInterruptConfirmController', 'show', [])) {
          errors.push('show countdown interrupt confirm must delegate to its controller')
        }
        if (methodName === '_getConfirmEndTimerController' &&
            !hasLazyControllerAccessor(
              node,
              'createConfirmEndTimerController',
              '_confirmEndTimerController',
            )) {
          errors.push('confirm end timer must lazily assign its controller')
        }
        if (methodName === 'confirmEndTimer' &&
            !returnsControllerCall(node, '_getConfirmEndTimerController', 'confirm', [])) {
          errors.push('confirm end timer must delegate to its controller')
        }
        if (methodName === '_getEndSessionController' &&
            !hasLazyControllerAccessor(
              node,
              'createEndSessionController',
              '_endSessionController',
            )) {
          errors.push('end session must lazily assign its controller')
        }
        if (methodName === 'endSession' &&
            !returnsControllerCall(node, '_getEndSessionController', 'end', [])) {
          errors.push('end session must delegate to its controller')
        }
        if (methodName === '_getPauseFreeTimerController' &&
            !hasLazyControllerAccessor(
              node,
              'createPauseFreeTimerController',
              '_pauseFreeTimerController',
            )) {
          errors.push('pause free timer must lazily assign its controller')
        }
        if (methodName === '_pauseFreeTimer' &&
            !returnsControllerCall(node, '_getPauseFreeTimerController', 'pause', [])) {
          errors.push('pause free timer must delegate to its controller')
        }
        if (methodName === '_getResumeFreeTimerController' &&
            !hasLazyControllerAccessor(
              node,
              'createResumeFreeTimerController',
              '_resumeFreeTimerController',
            )) {
          errors.push('resume free timer must lazily assign its controller')
        }
        if (methodName === '_resumeFreeTimer' &&
            !returnsControllerCall(node, '_getResumeFreeTimerController', 'resume', [])) {
          errors.push('resume free timer must delegate to its controller')
        }
        if (methodName === '_getInterruptSessionController' &&
            !hasLazyControllerAccessor(
              node,
              'createInterruptSessionController',
              '_interruptSessionController',
            )) {
          errors.push('interrupt session must lazily assign its controller')
        }
        if (methodName === 'interruptSession' &&
            !returnsControllerCall(node, '_getInterruptSessionController', 'interrupt', [])) {
          errors.push('interrupt session must delegate to its controller')
        }
        if (methodName === '_getConfirmEndFreeTimerController' &&
            !hasLazyControllerAccessor(
              node,
              'createConfirmEndFreeTimerController',
              '_confirmEndFreeTimerController',
            )) {
          errors.push('confirm end free timer must lazily assign its controller')
        }
        if (methodName === '_confirmEndFreeTimer' &&
            !returnsControllerCall(node, '_getConfirmEndFreeTimerController', 'confirm', [])) {
          errors.push('confirm end free timer must delegate to its controller')
        }
        if (methodName === '_getFreeTimerLimitController' &&
            !hasLazyControllerAccessor(
              node,
              'createFreeTimerLimitController',
              '_freeTimerLimitController',
            )) {
          errors.push('free timer limit must lazily assign its controller')
        }
        if (methodName === '_checkFreeTimerLimitAndAutoEnd' &&
            !returnsControllerCall(node, '_getFreeTimerLimitController', 'check', [])) {
          errors.push('free timer limit check must delegate to its controller')
        }
        if (methodName === '_autoFinishFreeTimer' &&
            !returnsControllerCall(node, '_getFreeTimerLimitController', 'autoFinish', [])) {
          errors.push('auto finish free timer must delegate to its controller')
        }
        if (methodName === '_completeFreeTimerSession' &&
            !returnsControllerCall(node, '_getFreeTimerLimitController', 'complete', [])) {
          errors.push('complete free timer session must delegate to its controller')
        }
        if (methodName === '_getFreeElapsedController' &&
            !hasLazyControllerAccessor(
              node,
              'createFreeElapsedController',
              '_freeElapsedController',
            )) {
          errors.push('free elapsed must lazily assign its controller')
        }
        if (methodName === '_getFreeElapsedMs' &&
            !returnsControllerCall(node, '_getFreeElapsedController', 'getElapsedMs', ['now'])) {
          errors.push('free elapsed must delegate to its controller')
        }
        if (methodName === '_getEffectiveFreeElapsedMs' &&
            !returnsControllerCall(
              node,
              '_getFreeElapsedController',
              'getEffectiveElapsedMs',
              ['now'],
            )) {
          errors.push('effective free elapsed must delegate to its controller')
        }
        if (methodName === '_getStartBreakController' &&
            !hasLazyControllerAccessor(
              node,
              'createStartBreakController',
              '_startBreakController',
            )) {
          errors.push('start break must lazily assign its controller')
        }
        if (methodName === '_startBreak' &&
            !returnsControllerCall(node, '_getStartBreakController', 'start', ['totalSec', 'options'])) {
          errors.push('start break must delegate to its controller')
        }
        if (methodName === '_getStartTimerController' &&
            !hasLazyControllerAccessor(
              node,
              'createStartTimerController',
              '_startTimerController',
            )) {
          errors.push('start timer must lazily assign its controller')
        }
        if (methodName === '_startTimer' &&
            !returnsControllerCall(node, '_getStartTimerController', 'start', ['totalSec', 'options'])) {
          errors.push('start timer must delegate to its controller')
        }
        if (methodName === '_getCanvasInitController' &&
            !hasLazyControllerAccessor(
              node,
              'createCanvasInitController',
              '_canvasInitController',
            )) {
          errors.push('canvas init must lazily assign its controller')
        }
        if (methodName === '_initCanvas' &&
            !returnsControllerCall(node, '_getCanvasInitController', 'init', ['force'])) {
          errors.push('canvas init must delegate to its controller')
        }
        if (methodName === '_scheduleCanvasInit' &&
            !returnsControllerCall(
              node,
              '_getCanvasInitController',
              'schedule',
              ['retryCount', 'initSeq', 'previousRect'],
            )) {
          errors.push('canvas init scheduling must delegate to its controller')
        }
        if (methodName === '_getDrawRingController' &&
            !hasLazyControllerAccessor(
              node,
              'createDrawRingController',
              '_drawRingController',
            )) {
          errors.push('draw ring must lazily assign its controller')
        }
        if (methodName === 'drawRing' &&
            !returnsControllerCall(node, '_getDrawRingController', 'draw', ['totalSec', 'isBreak'])) {
          errors.push('draw ring must delegate to its controller')
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

function callsControllerCall(method, accessorName, delegateName, expectedArguments) {
  const statements = ts.isBlock(method.body) ? method.body.statements : []
  if (statements.length !== 1 || !ts.isExpressionStatement(statements[0])) return false
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
