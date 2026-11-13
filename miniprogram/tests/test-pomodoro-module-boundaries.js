const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  moduleViolations, adapterViolations, pageViolations, scanPomodoro,
  MODULES, PAGE_ADAPTER_MODULES, ADAPTER_BUDGETS, PAGE_CONTROLLERS,
  RESTORE_CONTROLLERS, PAGE_MAX_LINES,
} = require('../scripts/architecture/pomodoro-boundaries')

const root = path.resolve(__dirname, '../..')
const pageSource = fs.readFileSync(path.join(root, 'miniprogram/pages/pomodoro/pomodoro.js'), 'utf8')
const check = (source, allowed = []) => moduleViolations('fixture.js', source, allowed).errors

test('scans every governed production module, page adapter and the real page', () => {
  const result = scanPomodoro()
  assert.deepEqual(result.violations, [])
  assert.equal(result.modules, 76)
  assert.equal(result.adapters, 7)
  assert.equal(result.adapterLines, 1063)
  assert.equal(result.edges, 47)
  assert.equal(result.pageLines, PAGE_MAX_LINES)
})

test('running state migrator shell lazily reuses one controller', () => {
  const unassigned = pageSource.replace(
    'this._runningStateMigrationController = createPomodoroRunningStateMigrator(',
    'void createPomodoroRunningStateMigrator({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('running state migrator must lazily assign its controller'))
})

test('subject loading shell lazily reuses one controller', () => {
  const detached = pageSource.replace(
    'return this._getSubjectLoadController().load()',
    'return undefined'
  )
  assert.ok(pageViolations(detached)
    .includes('subject loading must delegate to its controller'))

  const unassigned = pageSource.replace(
    'this._subjectLoadController = createSubjectLoadController(',
    'void createSubjectLoadController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('subject loading must lazily assign its controller'))
})

test('dependency injection examples cannot import page, API, storage or another package', () => {
  for (const dependency of ['../pomodoro', '../../../utils/api', '../../../utils/storage',
    '../../../subpackages/study/practice/practice', './show-recovery', 'node:fs']) {
    assert.ok(check(`const forbidden = require('${dependency}')`).some(error =>
      error === `forbidden dependency: ${dependency}`))
  }
})

test('literal require edge is accepted only for its owning module policy', () => {
  const source = "const { formatElapsedSec } = require('./timer-math'); module.exports = { formatElapsedSec }"
  assert.deepEqual(check(source, MODULES['confirm-recovery.js']), [])
  assert.ok(check(source, MODULES['show-recovery.js']).length > 0)
})

test('rejects require aliases, computed targets and dynamic imports', () => {
  for (const source of [
    'const load = require; load(target)',
    'require(target)',
    "require('./' + target)",
    "require(`./timer-math`)",
    "require.call(null, './timer-math')",
    "import('./timer-math')",
    "import { x } from './timer-math'",
    "export { x } from './timer-math'",
    'export default value',
    'export function x() {}',
    'export const x = 1',
  ]) assert.ok(check(source).length > 0, source)
})

test('detects global capabilities inside nested functions and computed accesses', () => {
  for (const source of [
    "function retry() { return () => wx.request({}) }",
    "const host = wx; host['request']({})",
    'Page({})', 'getApp()', 'getCurrentPages()', 'api.post()',
    'globalThis.wx', "global['wx']", 'window.fetch(url)', "self['wx']", 'process.env', 'new Date()', 'Date.now()',
    'setTimeout(fn, 2000)', 'clearInterval(timer)', 'fetch(url)',
    "eval('value')", "new Function('return value')", 'exports.retry = value',
    'const owner = module', 'const retry = () => this.retry()',
  ]) assert.ok(check(source).length > 0, source)
})

test('ignores words in comments and strings and permits explicit capability callbacks', () => {
  assert.deepEqual(check(`
    // wx.request and require('../pomodoro') are intentionally only examples.
    const message = 'Page and setTimeout are not runtime accesses here'
    function schedule(options) {
      options.setTimeout(() => options.retry(), 2000)
      options.clearTimeout(options.timer)
      return message
    }
    module.exports = { schedule }
  `), [])
})

test('rejects invalid and empty source rather than silently scanning zero nodes', () => {
  for (const source of ['', '  \n ', '// comments only', 'function broken( {']) {
    assert.ok(check(source).length > 0)
    assert.ok(pageViolations(source).length > 0)
  }
})

test('checks all nested function forms against 50-line budget', () => {
  const body = Array(50).fill('void 0').join('\n')
  for (const source of [
    `function long() {\n${body}\n}`,
    `const long = () => {\n${body}\n}`,
    `const long = function() {\n${body}\n}`,
    `const owner = { long() {\n${body}\n} }`,
    `function outer() { return () => {\n${body}\n} }`,
    `class Owner { get value() {\n${body}\n} }`,
  ]) assert.ok(check(source).some(error => error.startsWith('function exceeds 50 lines')), source)
})

test('checks 300-line module budget independently of function length', () => {
  assert.ok(check(Array(301).fill('void 0').join('\n')).includes('module exceeds 300 lines'))
  assert.ok(!check(Array(300).fill('void 0').join('\n')).includes('module exceeds 300 lines'))
})

test('page cannot exceed current legacy ceiling or regrow governed lifecycle methods', () => {
  assert.ok(pageViolations(Array(PAGE_MAX_LINES + 1).fill('// legacy').join('\n'))
    .includes(`page exceeds legacy ceiling ${PAGE_MAX_LINES}`))
  const expanded = pageSource.replace('  async onShow() {',
    `  async onShow() {\n${Array(51).fill('    void 0').join('\n')}`)
  assert.ok(pageViolations(expanded).some(error => error.startsWith('function exceeds 50 lines')))
})

test('page must still import the isolated modules and keep the governed lifecycle entry', () => {
  const detached = pageSource.replace("require('./utils/show-recovery')", "require('./utils/legacy-recovery')")
  assert.ok(pageViolations(detached).includes('page no longer imports governed module: show-recovery.js'))
  const missing = pageSource.replace('  async onShow() {', '  async removedOnShow() {')
  assert.ok(pageViolations(missing).includes('missing governed method: onShow'))
  const fake = `${missing}\nconst fake = { async onShow() {} }\n`
  assert.ok(pageViolations(fake).includes('missing governed method: onShow'))
  assert.ok(pageViolations(`${pageSource}\nPage({})\n`)
    .includes('expected exactly one literal Page definition'))
})

test('free-session restore wrapper must create and delegate via AST calls', () => {
  const detached = pageSource.replace(
    'return this._freeSessionRestoreController.restore(session)',
    'return undefined'
  )
  assert.ok(pageViolations(detached)
    .includes('free-session restore must assign a controller and delegate to it'))

  const uncreated = pageSource.replace(
    'this._freeSessionRestoreController = createFreeSessionRestoreController(',
    'this._freeSessionRestoreController = ({'
  )
  assert.ok(pageViolations(uncreated)
    .includes('free-session restore must assign a controller and delegate to it'))
})

test('countdown restore dispatcher must create and delegate via AST calls', () => {
  const detached = pageSource.replace(
    'return this._countdownSessionRestoreController.restore(session)',
    'return undefined'
  )
  assert.ok(pageViolations(detached)
    .includes('countdown restore must assign a controller and delegate to it'))

  const uncreated = pageSource.replace(
    'this._countdownSessionRestoreController = createCountdownSessionRestoreController(',
    'this._countdownSessionRestoreController = ({'
  )
  assert.ok(pageViolations(uncreated)
    .includes('countdown restore must assign a controller and delegate to it'))

  const unassigned = pageSource.replace(
    'this._countdownSessionRestoreController = createCountdownSessionRestoreController(',
    'void createCountdownSessionRestoreController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('countdown restore must assign a controller and delegate to it'))

  const withoutFreeDispatch = pageSource.replace(
    "    if (session.preset === 'free') {\n" +
    '      return this._restoreFreeSession(session)\n' +
    '    }\n',
    ''
  )
  assert.ok(pageViolations(withoutFreeDispatch)
    .includes('countdown restore must dispatch free sessions before controller delegation'))

  const unreachableAssignment = pageSource.replace(
    'if (!this._countdownSessionRestoreController) {',
    'if (false) {'
  )
  assert.ok(pageViolations(unreachableAssignment)
    .includes('countdown restore must assign a controller and delegate to it'))

  const earlyDelegate = pageSource.replace(
    "    if (session.preset === 'free') {",
    '    this._countdownSessionRestoreController.restore(session)\n' +
    "    if (session.preset === 'free') {"
  )
  assert.ok(pageViolations(earlyDelegate)
    .includes('countdown restore must dispatch free sessions before controller delegation'))

  const bareDelegate = pageSource.replace(
    'return this._countdownSessionRestoreController.restore(session)',
    'this._countdownSessionRestoreController.restore(session)'
  )
  assert.ok(pageViolations(bareDelegate)
    .includes('countdown restore shell must return exactly one guarded controller delegation'))

  const duplicateDelegate = pageSource.replace(
    'return this._countdownSessionRestoreController.restore(session)',
    'this._countdownSessionRestoreController.restore(session)\n' +
    '    return this._countdownSessionRestoreController.restore(session)'
  )
  assert.ok(pageViolations(duplicateDelegate)
    .includes('countdown restore shell must return exactly one guarded controller delegation'))

  const earlyReturn = pageSource.replace(
    "    if (session.preset === 'free') {",
    '    return true\n' +
    "    if (session.preset === 'free') {"
  )
  assert.ok(pageViolations(earlyReturn)
    .includes('countdown restore shell must return exactly one guarded controller delegation'))
})

test('start ceremony shell must lazily reuse its controller for both modes', () => {
  const unassigned = pageSource.replace(
    'this._startSessionController = createStartSessionController(',
    'void createStartSessionController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('start ceremony must lazily assign its controller'))

  const detachedStart = pageSource.replace(
    'return this._getStartSessionController().start()',
    'return undefined'
  )
  assert.ok(pageViolations(detachedStart)
    .includes('startSession must delegate to its controller'))

  const detachedFree = pageSource.replace(
    'return this._getStartSessionController().startFree(existingStartSeq)',
    'return this._getStartSessionController().start()'
  )
  assert.ok(pageViolations(detachedFree)
    .includes('free start must delegate to its controller'))
})

test('unknown-start recovery shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._unknownStartController = createUnknownStartController(',
    'void createUnknownStartController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('unknown-start recovery must lazily assign its controller'))

  const detachedReconcile = pageSource.replace(
    'return this._getUnknownStartController().reconcile(explicitAttempt)',
    'return undefined'
  )
  assert.ok(pageViolations(detachedReconcile)
    .includes('unknown-start reconciliation must delegate to its controller'))

  const detachedPost = pageSource.replace(
    'return this._getUnknownStartController().postStart(payload, startSeq)',
    'return this._getUnknownStartController().reconcile(payload)'
  )
  assert.ok(pageViolations(detachedPost)
    .includes('reconciled pomodoro POST must delegate to its controller'))
})

test('pending sync shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._pendingSyncController = createPendingSyncController(',
    'void createPendingSyncController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('pending sync must lazily assign its controller'))

  const detachedReconcile = pageSource.replace(
    'return this._getPendingSyncController().reconcileFailure(pending, error)',
    'return undefined'
  )
  assert.ok(pageViolations(detachedReconcile)
    .includes('pending sync reconciliation must delegate to its controller'))

  const detachedDrain = pageSource.replace(
    'return this._getPendingSyncController().drain()',
    'return undefined'
  )
  assert.ok(pageViolations(detachedDrain)
    .includes('pending sync drain must delegate to its controller'))

  const detachedComplete = pageSource.replace(
    'return this._getPendingSyncController().complete(sessionId, clientActionAt)',
    'return undefined'
  )
  assert.ok(pageViolations(detachedComplete)
    .includes('retryable completion must delegate to its controller'))

  const detachedInterrupt = pageSource.replace(
    'return this._getPendingSyncController().interrupt(sessionId, clientActionAt)',
    'return undefined'
  )
  assert.ok(pageViolations(detachedInterrupt)
    .includes('retryable interrupt must delegate to its controller'))
})

test('terminal conflict shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._terminalConflictController = createTerminalConflictController(',
    'void createTerminalConflictController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('terminal conflict must lazily assign its controller'))

  const detachedRecord = pageSource.replace(
    'this._getTerminalConflictController().record(',
    'this._getTerminalConflictController().legacyRecord('
  )
  assert.ok(pageViolations(detachedRecord)
    .includes('terminal conflict record must delegate to its controller'))

  const detachedRead = pageSource.replace(
    'this._getTerminalConflictController().read()',
    'this._getTerminalConflictController().legacyRead()'
  )
  assert.ok(pageViolations(detachedRead)
    .includes('terminal conflict read must delegate to its controller'))

  const detachedConsume = pageSource.replace(
    'this._getTerminalConflictController().consume(',
    'this._getTerminalConflictController().legacyConsume('
  )
  assert.ok(pageViolations(detachedConsume)
    .includes('terminal conflict consume must delegate to its controller'))

  const detachedConsumeAny = pageSource.replace(
    'this._getTerminalConflictController().consumeAny()',
    'this._getTerminalConflictController().legacyConsumeAny()'
  )
  assert.ok(pageViolations(detachedConsumeAny)
    .includes('terminal conflict consumeAny must delegate to its controller'))

  const detachedAck = pageSource.replace(
    'this._getTerminalConflictController().ack(',
    'this._getTerminalConflictController().legacyAck('
  )
  assert.ok(pageViolations(detachedAck)
    .includes('terminal conflict ack must delegate to its controller'))

  const detachedHandle = pageSource.replace(
    'this._getTerminalConflictController().handle(',
    'this._getTerminalConflictController().legacyHandle('
  )
  assert.ok(pageViolations(detachedHandle)
    .includes('terminal conflict handle must delegate to its controller'))
})

test('today stats shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._statsController = createStatsController(',
    'void createStatsController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('stats must lazily assign its controller'))

  const detachedLoad = pageSource.replace(
    'this._getStatsController().load()',
    'this._getStatsController().legacyLoad()'
  )
  assert.ok(pageViolations(detachedLoad)
    .includes('today stats must delegate to its controller'))
})

test('theme shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._themeController = createThemeController(',
    'void createThemeController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('theme must lazily assign its controller'))

  const detachedViewModel = pageSource.replace(
    'this._getThemeController().viewModel(mode)',
    'this._getThemeController().legacyViewModel(mode)'
  )
  assert.ok(pageViolations(detachedViewModel)
    .includes('theme view model must delegate to its controller'))

  const detachedSync = pageSource.replace(
    'this._getThemeController().sync()',
    'this._getThemeController().legacySync()'
  )
  assert.ok(pageViolations(detachedSync)
    .includes('theme storage sync must delegate to its controller'))

  const detachedApply = pageSource.replace(
    'this._getThemeController().apply(mode, persist, animate)',
    'this._getThemeController().legacyApply(mode, persist, animate)'
  )
  assert.ok(pageViolations(detachedApply)
    .includes('theme apply must delegate to its controller'))

  const detachedToggle = pageSource.replace(
    'this._getThemeController().toggle()',
    'this._getThemeController().legacyToggle()'
  )
  assert.ok(pageViolations(detachedToggle)
    .includes('theme toggle must delegate to its controller'))
})

test('every governed module must stay reachable from the page', () => {
  const detachedPageModule = pageSource.replace(
    "require('./utils/session-storage')",
    "require('./utils/legacy-session-storage')"
  )
  assert.ok(pageViolations(detachedPageModule)
    .includes('page no longer imports governed module: session-storage.js'))

  const detachedAdapter = pageSource.replace(
    "require('./utils/pomodoro-recovery-page-adapter')",
    "require('./utils/legacy-recovery-page-adapter')"
  )
  assert.ok(pageViolations(detachedAdapter)
    .includes('page no longer imports governed module: sync-reconciliation.js'))
})

test('active light-sync shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._activeSyncController = createActiveSyncController(',
    'void createActiveSyncController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('active sync must lazily assign its controller'))

  const detachedCanLightSync = pageSource.replace(
    'this._getActiveSyncController().canLightSync(active)',
    'this._getActiveSyncController().legacyCanLightSync(active)'
  )
  assert.ok(pageViolations(detachedCanLightSync)
    .includes('active light-sync eligibility must delegate to its controller'))

  const detachedSync = pageSource.replace(
    'this._getActiveSyncController().syncLight(active, failClosed)',
    'this._getActiveSyncController().legacySyncLight(active, failClosed)'
  )
  assert.ok(pageViolations(detachedSync)
    .includes('active light sync must delegate to its controller'))
})

test('pause toggle shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._pauseToggleController = createPauseToggleController(',
    'void createPauseToggleController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('pause toggle must lazily assign its controller'))

  const detachedAcquire = pageSource.replace(
    'this._getPauseToggleController().acquire()',
    'this._getPauseToggleController().legacyAcquire()'
  )
  assert.ok(pageViolations(detachedAcquire)
    .includes('pause toggle acquire must delegate to its controller'))

  const detachedRelease = pageSource.replace(
    'this._getPauseToggleController().release()',
    'this._getPauseToggleController().legacyRelease()'
  )
  assert.ok(pageViolations(detachedRelease)
    .includes('pause toggle release must delegate to its controller'))

  const detachedToggle = pageSource.replace(
    'this._getPauseToggleController().toggle()',
    'this._getPauseToggleController().legacyToggle()'
  )
  assert.ok(pageViolations(detachedToggle)
    .includes('pause toggle must delegate to its controller'))
})

test('resume error shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._resumeErrorController = createResumeErrorController(',
    'void createResumeErrorController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('resume error must lazily assign its controller'))

  const detachedReconcile = pageSource.replace(
    'this._getResumeErrorController().reconcile(e, sessionId)',
    'this._getResumeErrorController().legacyReconcile(e, sessionId)'
  )
  assert.ok(pageViolations(detachedReconcile)
    .includes('resume error reconcile must delegate to its controller'))
})

test('celebration dismiss shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._celebrationDismissController = createCelebrationDismissController(',
    'void createCelebrationDismissController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('celebration dismiss must lazily assign its controller'))

  const detachedDismiss = pageSource.replace(
    'this._getCelebrationDismissController().dismiss()',
    'this._getCelebrationDismissController().legacyDismiss()'
  )
  assert.ok(pageViolations(detachedDismiss)
    .includes('celebration dismiss must delegate to its controller'))
})

test('break restore shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._breakRestoreController = createBreakRestoreController(',
    'void createBreakRestoreController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('break restore must lazily assign its controller'))

  const detachedRestore = pageSource.replace(
    'this._getBreakRestoreController().restore()',
  )
  assert.ok(pageViolations(detachedRestore)
    .includes('break restore must delegate to its controller'))
})

test('completion celebration shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._completionCelebrationController = createCompletionCelebrationController(',
    'void createCompletionCelebrationController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('completion celebration must lazily assign its controller'))

  const detachedShow = pageSource.replace(
    'this._getCompletionCelebrationController().show(sessionId, options)',
    'this._getCompletionCelebrationController().legacyShow(sessionId, options)'
  )
  assert.ok(pageViolations(detachedShow)
    .includes('completion celebration must delegate to its controller'))
})

test('work complete shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._workCompleteController = createWorkCompleteController(',
    'void createWorkCompleteController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('work complete must lazily assign its controller'))

  const detachedComplete = pageSource.replace(
    'this._getWorkCompleteController().complete()',
    'this._getWorkCompleteController().legacyComplete()'
  )
  assert.ok(pageViolations(detachedComplete)
    .includes('work complete must delegate to its controller'))
})

test('free timer begin shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._freeTimerBeginController = createFreeTimerBeginController(',
    'void createFreeTimerBeginController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('free timer begin must lazily assign its controller'))

  const detachedBegin = pageSource.replace(
    'this._getFreeTimerBeginController().begin(session)',
    'this._getFreeTimerBeginController().legacyBegin(session)'
  )
  assert.ok(pageViolations(detachedBegin)
    .includes('free timer begin must delegate to its controller'))
})

test('cancel end confirm shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._cancelEndConfirmController = createCancelEndConfirmController(',
    'void createCancelEndConfirmController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('cancel end confirm must lazily assign its controller'))

  const detachedCancel = pageSource.replace(
    'this._getCancelEndConfirmController().cancel()',
    'this._getCancelEndConfirmController().legacyCancel()'
  )
  assert.ok(pageViolations(detachedCancel)
    .includes('cancel end confirm must delegate to its controller'))
})

test('show end free confirm shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._showEndFreeConfirmController = createShowEndFreeConfirmController(',
    'void createShowEndFreeConfirmController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('show end free confirm must lazily assign its controller'))

  const detachedShow = pageSource.replace(
    'this._getShowEndFreeConfirmController().show()',
    'this._getShowEndFreeConfirmController().legacyShow()'
  )
  assert.ok(pageViolations(detachedShow)
    .includes('show end free confirm must delegate to its controller'))
})

test('pause countdown end confirm shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._pauseCountdownEndConfirmController = createPauseCountdownEndConfirmController(',
    'void createPauseCountdownEndConfirmController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('pause countdown end confirm must lazily assign its controller'))

  const detachedPause = pageSource.replace(
    'this._getPauseCountdownEndConfirmController().pause()',
    'this._getPauseCountdownEndConfirmController().legacyPause()'
  )
  assert.ok(pageViolations(detachedPause)
    .includes('pause countdown end confirm must delegate to its controller'))
})

test('confirm interrupt countdown shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._confirmInterruptCountdownController = createConfirmInterruptCountdownController(',
    'void createConfirmInterruptCountdownController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('confirm interrupt countdown must lazily assign its controller'))

  const detachedConfirm = pageSource.replace(
    'this._getConfirmInterruptCountdownController().confirm()',
    'this._getConfirmInterruptCountdownController().legacyConfirm()'
  )
  assert.ok(pageViolations(detachedConfirm)
    .includes('confirm interrupt countdown must delegate to its controller'))
})

test('reset to idle shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._resetToIdleController = createResetToIdleController(',
    'void createResetToIdleController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('reset to idle must lazily assign its controller'))

  const detachedReset = pageSource.replace(
    'this._getResetToIdleController().reset()',
    'this._getResetToIdleController().legacyReset()'
  )
  assert.ok(pageViolations(detachedReset)
    .includes('reset to idle must delegate to its controller'))
})

test('update free elapsed shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._updateFreeElapsedController = createUpdateFreeElapsedController(',
    'void createUpdateFreeElapsedController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('update free elapsed must lazily assign its controller'))

  const detachedUpdate = pageSource.replace(
    'this._getUpdateFreeElapsedController().update()',
    'this._getUpdateFreeElapsedController().legacyUpdate()'
  )
  assert.ok(pageViolations(detachedUpdate)
    .includes('update free elapsed must delegate to its controller'))
})

test('begin countdown shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._beginCountdownController = createBeginCountdownController(',
    'void createBeginCountdownController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('begin countdown must lazily assign its controller'))

  const detachedBegin = pageSource.replace(
    'this._getBeginCountdownController().begin(session)',
    'this._getBeginCountdownController().legacyBegin(session)'
  )
  assert.ok(pageViolations(detachedBegin)
    .includes('begin countdown must delegate to its controller'))
})

test('pause session shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._pauseSessionController = createPauseSessionController(',
    'void createPauseSessionController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('pause session must lazily assign its controller'))

  const detachedPause = pageSource.replace(
    'this._getPauseSessionController().pause()',
    'this._getPauseSessionController().legacyPause()'
  )
  assert.ok(pageViolations(detachedPause)
    .includes('pause session must delegate to its controller'))
})

test('resume session shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._resumeSessionController = createResumeSessionController(',
    'void createResumeSessionController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('resume session must lazily assign its controller'))

  const detachedResume = pageSource.replace(
    'this._getResumeSessionController().resume()',
    'this._getResumeSessionController().legacyResume()'
  )
  assert.ok(pageViolations(detachedResume)
    .includes('resume session must delegate to its controller'))
})

test('show countdown interrupt confirm shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._showCountdownInterruptConfirmController = createShowCountdownInterruptConfirmController(',
    'void createShowCountdownInterruptConfirmController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('show countdown interrupt confirm must lazily assign its controller'))

  const detachedShow = pageSource.replace(
    'this._getShowCountdownInterruptConfirmController().show()',
    'this._getShowCountdownInterruptConfirmController().legacyShow()'
  )
  assert.ok(pageViolations(detachedShow)
    .includes('show countdown interrupt confirm must delegate to its controller'))
})

test('end session shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._endSessionController = createEndSessionController(',
    'void createEndSessionController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('end session must lazily assign its controller'))

  const detachedEnd = pageSource.replace(
    'this._getEndSessionController().end()',
    'this._getEndSessionController().legacyEnd()'
  )
  assert.ok(pageViolations(detachedEnd)
    .includes('end session must delegate to its controller'))
})


test('pause free timer shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._pauseFreeTimerController = createPauseFreeTimerController(',
    'void createPauseFreeTimerController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('pause free timer must lazily assign its controller'))

  const detachedPause = pageSource.replace(
    'this._getPauseFreeTimerController().pause()',
    'this._getPauseFreeTimerController().legacyPause()'
  )
  assert.ok(pageViolations(detachedPause)
    .includes('pause free timer must delegate to its controller'))
})

test('resume free timer shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._resumeFreeTimerController = createResumeFreeTimerController(',
    'void createResumeFreeTimerController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('resume free timer must lazily assign its controller'))

  const detachedResume = pageSource.replace(
    'this._getResumeFreeTimerController().resume()',
    'this._getResumeFreeTimerController().legacyResume()'
  )
  assert.ok(pageViolations(detachedResume)
    .includes('resume free timer must delegate to its controller'))
})


test('interrupt session shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._interruptSessionController = createInterruptSessionController(',
    'void createInterruptSessionController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('interrupt session must lazily assign its controller'))

  const detachedInterrupt = pageSource.replace(
    'this._getInterruptSessionController().interrupt()',
    'this._getInterruptSessionController().legacyInterrupt()'
  )
  assert.ok(pageViolations(detachedInterrupt)
    .includes('interrupt session must delegate to its controller'))
})


test('confirm end free timer shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._confirmEndFreeTimerController = createConfirmEndFreeTimerController(',
    'void createConfirmEndFreeTimerController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('confirm end free timer must lazily assign its controller'))

  const detachedConfirm = pageSource.replace(
    'this._getConfirmEndFreeTimerController().confirm()',
    'this._getConfirmEndFreeTimerController().legacyConfirm()'
  )
  assert.ok(pageViolations(detachedConfirm)
    .includes('confirm end free timer must delegate to its controller'))
})

test('free timer limit shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._freeTimerLimitController = createFreeTimerLimitController(',
    'void createFreeTimerLimitController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('free timer limit must lazily assign its controller'))

  const detachedCheck = pageSource.replace(
    'this._getFreeTimerLimitController().check()',
    'this._getFreeTimerLimitController().legacyCheck()'
  )
  assert.ok(pageViolations(detachedCheck)
    .includes('free timer limit check must delegate to its controller'))
})

test('start break shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._startBreakController = createStartBreakController(',
    'void createStartBreakController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('start break must lazily assign its controller'))

  const detachedStart = pageSource.replace(
    'this._getStartBreakController().start(totalSec, options)',
    'this._getStartBreakController().legacyStart(totalSec, options)'
  )
  assert.ok(pageViolations(detachedStart)
    .includes('start break must delegate to its controller'))
})

test('start timer shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._startTimerController = createStartTimerController(',
    'void createStartTimerController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('start timer must lazily assign its controller'))

  const detachedStart = pageSource.replace(
    'this._getStartTimerController().start(totalSec, options)',
    'this._getStartTimerController().legacyStart(totalSec, options)'
  )
  assert.ok(pageViolations(detachedStart)
    .includes('start timer must delegate to its controller'))
})

test('draw ring shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._drawRingController = createDrawRingController(',
    'void createDrawRingController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('draw ring must lazily assign its controller'))

  const detachedDraw = pageSource.replace(
    'this._getDrawRingController().draw(totalSec, isBreak)',
    'this._getDrawRingController().legacyDraw(totalSec, isBreak)'
  )
  assert.ok(pageViolations(detachedDraw)
    .includes('draw ring must delegate to its controller'))
})

test('canvas init shells must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._canvasInitController = createCanvasInitController(',
    'void createCanvasInitController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('canvas init must lazily assign its controller'))

  const detachedInit = pageSource.replace(
    'return this._getCanvasInitController().init(force)',
    'return this._getCanvasInitController().legacyInit(force)'
  )
  assert.ok(pageViolations(detachedInit)
    .includes('canvas init must delegate to its controller'))

  const detachedSchedule = pageSource.replace(
    'return this._getCanvasInitController().schedule(retryCount, initSeq, previousRect)',
    'return this._getCanvasInitController().legacySchedule(retryCount, initSeq, previousRect)'
  )
  assert.ok(pageViolations(detachedSchedule)
    .includes('canvas init scheduling must delegate to its controller'))
})

test('free elapsed shells must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._freeElapsedController = createFreeElapsedController(',
    'void createFreeElapsedController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('free elapsed must lazily assign its controller'))

  const detachedElapsed = pageSource.replace(
    'return this._getFreeElapsedController().getElapsedMs(now)',
    'return this._getFreeElapsedController().legacyGetElapsedMs(now)'
  )
  assert.ok(pageViolations(detachedElapsed)
    .includes('free elapsed must delegate to its controller'))

  const detachedEffective = pageSource.replace(
    'return this._getFreeElapsedController().getEffectiveElapsedMs(now)',
    'return this._getFreeElapsedController().legacyGetEffectiveElapsedMs(now)'
  )
  assert.ok(pageViolations(detachedEffective)
    .includes('effective free elapsed must delegate to its controller'))
})

test('missing governed source aborts the scan instead of reducing coverage', () => {
  assert.throws(() => scanPomodoro(root, filename => {
    if (filename.endsWith('/show-recovery.js')) throw new Error('synthetic missing source')
    return fs.readFileSync(filename, 'utf8')
  }), /synthetic missing source/)
})

test('full scan finds an injected reverse dependency and an emptied module', () => {
  for (const injected of ["require('../pomodoro')", '']) {
    const result = scanPomodoro(root, filename => filename.endsWith('/show-recovery.js')
      ? injected : fs.readFileSync(filename, 'utf8'))
    assert.ok(result.violations.some(error => error.includes('show-recovery.js')))
    assert.equal(result.modules, 76)
  }
})
test('confirm end timer shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._confirmEndTimerController = createConfirmEndTimerController(',
    'void createConfirmEndTimerController({'
  )
  assert.ok(pageViolations(unassigned)
    .includes('confirm end timer must lazily assign its controller'))

  const detachedConfirm = pageSource.replace(
    'this._getConfirmEndTimerController().confirm()',
    'this._getConfirmEndTimerController().legacyConfirm()'
  )
  assert.ok(pageViolations(detachedConfirm)
    .includes('confirm end timer must delegate to its controller'))
})

test('pause sync, session action drop, and active session reconcile shells lazily reuse one controller', () => {
  const cases = [
    ['pause sync', 'this._pauseSync = createPomodoroPauseSyncController('],
    ['session action drop', 'this._sessionActionDrop = createPomodoroSessionActionDropper('],
    ['active session reconcile', 'this._activeSessionReconcile = createPomodoroActiveSessionReconciler('],
  ]
  for (const [label, assignment] of cases) {
    const unassigned = pageSource.replace(assignment, `void ${assignment.slice('this._'.length)}`)
    assert.ok(pageViolations(unassigned)
      .includes(`${label} must lazily assign its controller`))
  }
})

test('page adapters keep a frozen dependency surface and inject api from the page', () => {
  const adapter = name => fs.readFileSync(
    path.join(root, 'miniprogram/pages/pomodoro/utils', name), 'utf8'
  )
  for (const [name, allowed] of Object.entries(PAGE_ADAPTER_MODULES)) {
    assert.ok(allowed.every(dependency => !dependency.endsWith('/utils/api')),
      `${name} must receive api through deps`)
  }
  const confirm = adapter('pomodoro-confirm-page-adapter.js')
  assert.ok(adapterViolations('pomodoro-confirm-page-adapter.js',
    `${confirm}\nconst api = require('../../utils/api')\n`)
    .errors.includes('api must be injected through deps, not required by an adapter'))
  assert.ok(adapterViolations('pomodoro-confirm-page-adapter.js',
    `${confirm}\nconst { formatElapsedSec } = require('./cancel-end-confirm-controller')\n`)
    .errors.includes('forbidden adapter dependency: ./cancel-end-confirm-controller'))
  assert.ok(adapterViolations('pomodoro-confirm-page-adapter.js', `${confirm}\nimport('./timer-math')\n`)
    .errors.some(error => error.includes('dynamic imports are forbidden')))
  assert.ok(adapterViolations('pomodoro-confirm-page-adapter.js',
    `const { x } = require(target)\n${confirm}`)
    .errors.includes('require must be a direct literal call'))
  assert.deepEqual(adapterViolations('unknown-page-adapter.js', 'module.exports = {}').errors,
    ['ungoverned pomodoro page adapter: unknown-page-adapter.js'])

  const restore = adapter('pomodoro-restore-page-adapter.js')
  const budget = ADAPTER_BUDGETS['pomodoro-restore-page-adapter.js']
  assert.ok(adapterViolations('pomodoro-restore-page-adapter.js',
    `${restore}\n${'// growth\n'.repeat(budget)}`)
    .errors.includes(`adapter exceeds budget ${budget}`))
  assert.ok(adapterViolations('pomodoro-restore-page-adapter.js',
    `${restore}\nfunction tooLong(page) {\n${'  void page\n'.repeat(60)}}\n`)
    .errors.some(error => error.includes('function exceeds 50 lines')))
})

test('page keeps every controller port delegated through an adapter', () => {
  assert.equal(PAGE_CONTROLLERS.length, 50)
  assert.equal(RESTORE_CONTROLLERS.length, 2)

  const inline = pageSource.replace(
    'buildStatsPageCapabilities(this, { api })',
    'createStatsController({ load: () => {} })'
  )
  const inlineViolations = pageViolations(inline)
  assert.ok(inlineViolations.includes('page must not build controller ports inline'))
  assert.ok(inlineViolations
    .includes('_getStatsController must lazily delegate to buildStatsPageCapabilities'))

  const detached = pageSource.replace(
    'buildPauseTogglePageCapabilities(this, {})',
    'buildPauseTogglePageCapabilities(this, { api })'
  )
  assert.ok(pageViolations(detached)
    .includes('_getPauseToggleController must lazily delegate to buildPauseTogglePageCapabilities'))

  const restoreDetached = pageSource.replace(
    'buildCountdownSessionRestorePageCapabilities(this, { api })',
    'buildLegacyCountdownRestorePageCapabilities(this, { api })'
  )
  assert.ok(pageViolations(restoreDetached)
    .includes('_restoreSession must build its ports through buildCountdownSessionRestorePageCapabilities'))

  const padded = `${pageSource}\n${'// growth\n'.repeat(PAGE_MAX_LINES)}`
  assert.ok(pageViolations(padded)
    .includes(`page exceeds legacy ceiling ${PAGE_MAX_LINES}`))
})
