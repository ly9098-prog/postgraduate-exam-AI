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
  'pomodoro-page-support.js': ['../../../utils/china-time'],
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
  'pause-sync-controller.js': [],
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
  'skip-break-controller.js': [],
  'font-size-controller.js': [],
  'subject-view-controller.js': ['./subject-meta'],
  'preset-view-controller.js': [],
  'celebration-type-controller.js': [],
  'date-exam-controller.js': [],
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
  'active-session-reconciler.js': [],
  'session-action-dropper.js': [],
  'running-state-migrator.js': [],
}
// Page-adapter modules hold the controller capability objects. They may reach for
// platform globals (wx/setTimeout/console) and closed-over page state, but their
// dependency surface is frozen here and the api client must be injected by the page.
const PAGE_ADAPTER_MODULES = {
  'pomodoro-session-page-adapter.js': ['../../../utils/storage', './pomodoro-page-support', './subject-cache', './subject-options', './subject-scope', './timer-math'],
  'pomodoro-session-control-page-adapter.js': ['../../../utils/storage', './pomodoro-page-support', './timer-math'],
  'pomodoro-confirm-page-adapter.js': ['./timer-math'],
  'pomodoro-celebration-page-adapter.js': ['../../../utils/storage', './celebration-dismiss', './completion-celebration', './pomodoro-page-support'],
  'pomodoro-recovery-page-adapter.js': ['../../../utils/storage', './pomodoro-page-support', './sync-reconciliation', './terminal-conflict-handler', './terminal-conflict-state', './timer-math', './unknown-start-helpers'],
  'pomodoro-view-page-adapter.js': ['../../../utils/china-time', './canvas-layout', './pomodoro-page-support', './pomodoro-theme'],
  'pomodoro-restore-page-adapter.js': ['../../../utils/storage', './pomodoro-page-support', './session-restore', './timer-math'],
}
const ADAPTER_BUDGETS = {
  'pomodoro-session-page-adapter.js': 162,
  'pomodoro-session-control-page-adapter.js': 225,
  'pomodoro-confirm-page-adapter.js': 183,
  'pomodoro-celebration-page-adapter.js': 89,
  'pomodoro-recovery-page-adapter.js': 222,
  'pomodoro-view-page-adapter.js': 138,
  'pomodoro-restore-page-adapter.js': 47,
}
// [page accessor, page cache field, controller factory, capability builder, injected deps]
const PAGE_CONTROLLERS = [
  ["_getSyncRetryController", "_syncRetryController", "createSyncRetryController", "buildSyncRetryPageCapabilities", "{}"],
  ["_getPauseToggleController", "_pauseToggleController", "createPauseToggleController", "buildPauseTogglePageCapabilities", "{}"],
  ["_getSubjectLoadController", "_subjectLoadController", "createSubjectLoadController", "buildSubjectLoadPageCapabilities", "{ api }"],
  ["_runningStateMigrator", "_runningStateMigrationController", "createPomodoroRunningStateMigrator", "buildPomodoroRunningStateMigratorPageCapabilities", "{}"],
  ["_getUnknownStartController", "_unknownStartController", "createUnknownStartController", "buildUnknownStartPageCapabilities", "{ api }"],
  ["_getStartSessionController", "_startSessionController", "createStartSessionController", "buildStartSessionPageCapabilities", "{}"],
  ["_getFreeTimerBeginController", "_freeTimerBeginController", "createFreeTimerBeginController", "buildFreeTimerBeginPageCapabilities", "{ api }"],
  ["_getCancelEndConfirmController", "_cancelEndConfirmController", "createCancelEndConfirmController", "buildCancelEndConfirmPageCapabilities", "{ api }"],
  ["_getShowEndFreeConfirmController", "_showEndFreeConfirmController", "createShowEndFreeConfirmController", "buildShowEndFreeConfirmPageCapabilities", "{ api }"],
  ["_getPauseCountdownEndConfirmController", "_pauseCountdownEndConfirmController", "createPauseCountdownEndConfirmController", "buildPauseCountdownEndConfirmPageCapabilities", "{ api }"],
  ["_getConfirmInterruptCountdownController", "_confirmInterruptCountdownController", "createConfirmInterruptCountdownController", "buildConfirmInterruptCountdownPageCapabilities", "{ api }"],
  ["_getResetToIdleController", "_resetToIdleController", "createResetToIdleController", "buildResetToIdlePageCapabilities", "{}"],
  ["_getUpdateFreeElapsedController", "_updateFreeElapsedController", "createUpdateFreeElapsedController", "buildUpdateFreeElapsedPageCapabilities", "{}"],
  ["_getBeginCountdownController", "_beginCountdownController", "createBeginCountdownController", "buildBeginCountdownPageCapabilities", "{ api }"],
  ["_getPauseSessionController", "_pauseSessionController", "createPauseSessionController", "buildPauseSessionPageCapabilities", "{ api }"],
  ["_getResumeSessionController", "_resumeSessionController", "createResumeSessionController", "buildResumeSessionPageCapabilities", "{ api }"],
  ["_getShowCountdownInterruptConfirmController", "_showCountdownInterruptConfirmController", "createShowCountdownInterruptConfirmController", "buildShowCountdownInterruptConfirmPageCapabilities", "{}"],
  ["_getConfirmEndTimerController", "_confirmEndTimerController", "createConfirmEndTimerController", "buildConfirmEndTimerPageCapabilities", "{}"],
  ["_getEndSessionController", "_endSessionController", "createEndSessionController", "buildEndSessionPageCapabilities", "{ api }"],
  ["_getPauseFreeTimerController", "_pauseFreeTimerController", "createPauseFreeTimerController", "buildPauseFreeTimerPageCapabilities", "{ api }"],
  ["_getResumeFreeTimerController", "_resumeFreeTimerController", "createResumeFreeTimerController", "buildResumeFreeTimerPageCapabilities", "{ api }"],
  ["_getInterruptSessionController", "_interruptSessionController", "createInterruptSessionController", "buildInterruptSessionPageCapabilities", "{}"],
  ["_getConfirmEndFreeTimerController", "_confirmEndFreeTimerController", "createConfirmEndFreeTimerController", "buildConfirmEndFreeTimerPageCapabilities", "{}"],
  ["_getFreeTimerLimitController", "_freeTimerLimitController", "createFreeTimerLimitController", "buildFreeTimerLimitPageCapabilities", "{ api }"],
  ["_getFreeTimerController", "_freeTimerController", "createFreeTimerController", "buildFreeTimerPageCapabilities", "{}"],
  ["_getResumeErrorController", "_resumeErrorController", "createResumeErrorController", "buildResumeErrorPageCapabilities", "{ api }"],
  ["_pauseSyncController", "_pauseSync", "createPomodoroPauseSyncController", "buildPomodoroPauseSyncPageCapabilities", "{}"],
  ["_getPendingSyncStore", "_pendingSyncStore", "createPendingSyncQueue", "buildPendingSyncQueuePageCapabilities", "{ api }"],
  ["_getSessionActionDropController", "_sessionActionDrop", "createPomodoroSessionActionDropper", "buildPomodoroSessionActionDropperPageCapabilities", "{}"],
  ["_getTerminalConflictController", "_terminalConflictController", "createTerminalConflictController", "buildTerminalConflictPageCapabilities", "{ api }"],
  ["_getPendingSyncController", "_pendingSyncController", "createPendingSyncController", "buildPendingSyncPageCapabilities", "{ api }"],
  ["_getFreeElapsedController", "_freeElapsedController", "createFreeElapsedController", "buildFreeElapsedPageCapabilities", "{ api }"],
  ["_getCompletionCelebrationController", "_completionCelebrationController", "createCompletionCelebrationController", "buildCompletionCelebrationPageCapabilities", "{}"],
  ["_getWorkCompleteController", "_workCompleteController", "createWorkCompleteController", "buildWorkCompletePageCapabilities", "{ api }"],
  ["_getCelebrationDismissController", "_celebrationDismissController", "createCelebrationDismissController", "buildCelebrationDismissPageCapabilities", "{}"],
  ["_getStartBreakController", "_startBreakController", "createStartBreakController", "buildStartBreakPageCapabilities", "{ api }"],
  ["_getStartTimerController", "_startTimerController", "createStartTimerController", "buildStartTimerPageCapabilities", "{ api }"],
  ["_getSkipBreakController", "_skipBreakController", "createSkipBreakController", "buildSkipBreakPageCapabilities", "{}"],
  ["_getActiveSyncController", "_activeSyncController", "createActiveSyncController", "buildActiveSyncPageCapabilities", "{ api }"],
  ["_activeSessionReconciler", "_activeSessionReconcile", "createPomodoroActiveSessionReconciler", "buildPomodoroActiveSessionReconcilerPageCapabilities", "{ api }"],
  ["_getBreakRestoreController", "_breakRestoreController", "createBreakRestoreController", "buildBreakRestorePageCapabilities", "{ api }"],
  ["_getCanvasInitController", "_canvasInitController", "createCanvasInitController", "buildCanvasInitPageCapabilities", "{}"],
  ["_getDrawRingController", "_drawRingController", "createDrawRingController", "buildDrawRingPageCapabilities", "{ api }"],
  ["_getStatsController", "_statsController", "createStatsController", "buildStatsPageCapabilities", "{ api }"],
  ["_getThemeController", "_themeController", "createThemeController", "buildThemePageCapabilities", "{}"],
  ["_getFontSizeController", "_fontSizeController", "createFontSizeController", "buildFontSizePageCapabilities", "{}"],
  ["_getSubjectViewController", "_subjectViewController", "createSubjectViewController", "buildSubjectViewPageCapabilities", "{}"],
  ["_getPresetViewController", "_presetViewController", "createPresetViewController", "buildPresetViewPageCapabilities", "{}"],
  ["_getCelebrationTypeController", "_celebrationTypeController", "createCelebrationTypeController", "buildCelebrationTypePageCapabilities", "{}"],
  ["_getDateExamController", "_dateExamController", "createDateExamController", "buildDateExamPageCapabilities", "{ api }"],
]
// Restore shells keep their dispatch/delegation statements but must still build ports via adapters.
const RESTORE_CONTROLLERS = [
  ["_restoreSession", "_countdownSessionRestoreController", "createCountdownSessionRestoreController", "buildCountdownSessionRestorePageCapabilities", "{ api }"],
  ["_restoreFreeSession", "_freeSessionRestoreController", "createFreeSessionRestoreController", "buildFreeSessionRestorePageCapabilities", "{ api }"],
]
const PAGE = 'miniprogram/pages/pomodoro/pomodoro.js'
const UTILS = 'miniprogram/pages/pomodoro/utils'
const PAGE_MAX_LINES = 1596
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
  // Lifecycle and routing
  'onLoad', '_createTimerState',
  // Subject selection and migration
  '_getSubjectLoadController', '_loadSubjects', '_applySubjects', '_lookupSubjectIdByCode',
  '_migrateRunningStateCache', 'selectSubject', 'selectTaskType',
  // Preset / duration / touch UI handlers
  'selectPreset', 'onWorkChange', 'onBreakChange', 'noop', 'onCustomAreaTouch',
  'onTouchStart', 'onTouchEnd', 'onExamTap', 'skipBreak',
  '_getSkipBreakController',
  // Computed fields and labels
  '_updateComputedFields', 'subjectLabel', 'subjectColor', 'presetLabel',
  'cycleFontSize', '_getFontSizeController', '_getSubjectViewController',
  '_getPresetViewController', 'getDateStr', '_getExamDays',
  '_getDateExamController', '_nextCelebrationType', '_getCelebrationTypeController',
  // Free timer interval helpers
  '_getFreeTimerController', '_clearFreeTimerInterval', '_startFreeTimerInterval',
  '_restartFreeTimerInterval',
  // Timer state and formatting
  '_clearTimer', '_getCurrentTotalSec', '_formatCountdownDisplay',
  // Storage helpers
  '_safeGetPomodoroStorage', '_safeSetPomodoroStorage', '_safeRemovePomodoroStorage',
  '_showPomodoroPersistenceError',
  // Pending sync queue helpers
  '_getPendingSyncStore', '_writePendingPomodoroSyncQueue',
  '_getPendingPomodoroSyncQueue', '_getPendingPomodoroSync',
  '_hasPendingPomodoroAction', '_setPendingPomodoroSync',
  '_clearPendingPomodoroSync', '_updatePendingPomodoroSync',
  '_dropPendingPomodoroSessionActions', '_isPomodoroStorageError',
  '_isValidConfirmSnapshot', '_postPauseWithRetry',
  '_getSessionActionDropController',
  '_pauseSyncController',
  '_activeSessionReconciler',
  '_runningStateMigrator',
  // Pause adjustment helpers
  '_pauseAdjustmentStorage', '_clearLocalPauseAdjustment',
  '_maybeClearLocalPauseAdjustment', '_getLocalPauseAdjustment',
  '_mergeLocalPauseAdjustment', '_getEffectivePausedMsFromSession',
  // Active session cache/fetch
  '_buildCachedActiveSession', '_getCachedActiveSession', '_fetchActiveSession',
  // Ring cache and redraw
  '_buildRingCache', '_redrawFreeRingAfterOverlay',
  // Stats navigation
  'goStats',
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

function adapterImportMap(read = filename => fs.readFileSync(filename, 'utf8')) {
  const map = new Map()
  for (const name of Object.keys(PAGE_ADAPTER_MODULES)) {
    const source = read(path.join(ROOT, UTILS, name))
    map.set(name, [...source.matchAll(/require\(\s*'([^']+)'\s*\)/g)].map(match => match[1]))
  }
  return map
}

function governedImportMap(read = filename => fs.readFileSync(filename, 'utf8')) {
  const map = new Map()
  for (const name of Object.keys(MODULES)) {
    const source = read(path.join(ROOT, UTILS, name))
    map.set(name, [...source.matchAll(/require\(\s*'([^']+)'\s*\)/g)].map(match => match[1]))
  }
  return map
}

function adapterViolations(relativeModule, source) {
  const { file, errors } = parseSource(relativeModule, source)
  const budget = ADAPTER_BUDGETS[relativeModule]
  if (budget === undefined) return { errors: [`ungoverned pomodoro page adapter: ${relativeModule}`], imports: [] }
  if (ts.isExternalModule(file)) errors.push('ES module syntax is forbidden in page adapters')
  if (lineCount(source) > budget) errors.push(`adapter exceeds budget ${budget}`)
  const allowed = PAGE_ADAPTER_MODULES[relativeModule]
  const imports = new Set()
  function walk(node) {
    functionSize(node, file, errors)
    if (ts.isIdentifier(node) && node.text === 'require') {
      const call = node.parent
      if (!ts.isCallExpression(call) || call.expression !== node || call.arguments.length !== 1 ||
          !ts.isStringLiteral(call.arguments[0])) {
        errors.push('require must be a direct literal call')
      } else {
        const dependency = call.arguments[0].text
        imports.add(dependency)
        if (dependency === '../../../utils/api' || dependency === '../../utils/api') {
          errors.push('api must be injected through deps, not required by an adapter')
        }
        if (!allowed.includes(dependency)) errors.push(`forbidden adapter dependency: ${dependency}`)
      }
    }
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node) ||
        (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)) {
      errors.push('ES imports and dynamic imports are forbidden in page adapters')
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return { errors, imports: [...imports] }
}

function pageViolations(source, adapterImports = adapterImportMap(), moduleImports = governedImportMap()) {
  const { file, errors } = parseSource(PAGE, source)
  if (lineCount(source) > PAGE_MAX_LINES) errors.push(`page exceeds legacy ceiling ${PAGE_MAX_LINES}`)
  for (const [method, field, factory, builder, deps] of PAGE_CONTROLLERS) {
    const expected = [
      `  ${method}() {`,
      `    if (!this.${field}) {`,
      `      this.${field} = ${factory}(`,
      `        ${builder}(this, ${deps})`,
      '      )',
      '    }',
      `    return this.${field}`,
      '  },',
    ].join('\n')
    if (source.split(expected).length - 1 !== 1) {
      errors.push(`${method} must lazily delegate to ${builder}`)
    }
  }
  for (const [method, field, factory, builder, deps] of RESTORE_CONTROLLERS) {
    const expected = [
      `      this.${field} = ${factory}(`,
      `        ${builder}(this, ${deps})`,
      '      )',
    ].join('\n')
    if (source.split(expected).length - 1 !== 1) {
      errors.push(`${method} must build its ports through ${builder}`)
    }
  }
  if (/create\w+\(\{/.test(source)) errors.push('page must not build controller ports inline')
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
        if (methodName === '_pauseSyncController' &&
            !hasLazyControllerAccessor(
              node,
              'createPomodoroPauseSyncController',
              '_pauseSync',
            )) {
          errors.push('pause sync must lazily assign its controller')
        }
        if (methodName === '_getSessionActionDropController' &&
            !hasLazyControllerAccessor(
              node,
              'createPomodoroSessionActionDropper',
              '_sessionActionDrop',
            )) {
          errors.push('session action drop must lazily assign its controller')
        }
        if (methodName === '_activeSessionReconciler' &&
            !hasLazyControllerAccessor(
              node,
              'createPomodoroActiveSessionReconciler',
              '_activeSessionReconcile',
            )) {
          errors.push('active session reconcile must lazily assign its controller')
        }
        if (methodName === '_runningStateMigrator' &&
            !hasLazyControllerAccessor(
              node,
              'createPomodoroRunningStateMigrator',
              '_runningStateMigrationController',
            )) {
          errors.push('running state migrator must lazily assign its controller')
        }
        if (methodName === '_getSubjectLoadController' &&
            !hasLazyControllerAccessor(
              node,
              'createSubjectLoadController',
              '_subjectLoadController',
            )) {
          errors.push('subject loading must lazily assign its controller')
        }
        if (methodName === '_loadSubjects' &&
            !returnsControllerCall(node, '_getSubjectLoadController', 'load', [])) {
          errors.push('subject loading must delegate to its controller')
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
  const reachable = new Set()
  const pending = []
  for (const target of imports) {
    const fromPage = /^\.\/utils\/(.+)$/.exec(target)
    if (fromPage) pending.push(`${fromPage[1]}.js`)
  }
  while (pending.length) {
    const name = pending.shift()
    if (reachable.has(name)) continue
    reachable.add(name)
    const targets = adapterImports.get(name) || moduleImports.get(name) || []
    for (const dependency of targets) {
      const local = /^\.\/(.+)$/.exec(dependency)
      if (local) pending.push(`${local[1]}.js`)
    }
  }
  for (const name of Object.keys(MODULES)) {
    if (!reachable.has(name)) errors.push(`page no longer imports governed module: ${name}`)
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
  const moduleImports = new Map()
  let edges = 0
  for (const [name, allowed] of Object.entries(MODULES)) {
    const relative = `${UTILS}/${name}`
    const result = moduleViolations(relative, read(path.join(root, relative)), allowed)
    violations.push(...result.errors.map(error => `${relative}: ${error}`))
    edges += result.imports.length
    moduleImports.set(name, result.imports)
  }
  const adapterImports = new Map()
  let adapterLines = 0
  for (const name of Object.keys(PAGE_ADAPTER_MODULES)) {
    const relative = `${UTILS}/${name}`
    const source = read(path.join(root, relative))
    const result = adapterViolations(name, source)
    violations.push(...result.errors.map(error => `${relative}: ${error}`))
    adapterImports.set(name, result.imports)
    edges += result.imports.length
    adapterLines += lineCount(source)
  }
  const pageSource = read(path.join(root, PAGE))
  violations.push(...pageViolations(pageSource, adapterImports, moduleImports).map(error => `${PAGE}: ${error}`))
  return {
    violations,
    modules: Object.keys(MODULES).length,
    adapters: Object.keys(PAGE_ADAPTER_MODULES).length,
    edges,
    adapterLines,
    pageLines: lineCount(pageSource),
  }
}

if (require.main === module) {
  const result = scanPomodoro()
  if (result.violations.length) {
    console.error(result.violations.join('\n'))
    process.exitCode = 1
  } else {
    console.log(
      `Pomodoro boundaries passed: page ${result.pageLines} lines, `
      + `${result.modules} modules, ${result.adapters} page adapters, `
      + `${result.adapterLines} adapter lines, ${result.edges} dependency edges`,
    )
  }
}

module.exports = {
  moduleViolations,
  adapterViolations,
  pageViolations,
  scanPomodoro,
  MODULES,
  PAGE_ADAPTER_MODULES,
  ADAPTER_BUDGETS,
  PAGE_CONTROLLERS,
  RESTORE_CONTROLLERS,
  PAGE_MAX_LINES,
}
