const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  moduleViolations, pageViolations, scanPomodoro, MODULES, PAGE_MAX_LINES,
} = require('../scripts/architecture/pomodoro-boundaries')

const root = path.resolve(__dirname, '../..')
const pageSource = fs.readFileSync(path.join(root, 'miniprogram/pages/pomodoro/pomodoro.js'), 'utf8')
const check = (source, allowed = []) => moduleViolations('fixture.js', source, allowed).errors

test('scans every governed production module and real page', () => {
  const result = scanPomodoro()
  assert.deepEqual(result.violations, [])
  assert.equal(result.modules, 40)
  assert.equal(result.edges, 4)
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
    'this._freeSessionRestoreController = createFreeSessionRestoreController({',
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
    'this._countdownSessionRestoreController = createCountdownSessionRestoreController({',
    'this._countdownSessionRestoreController = ({'
  )
  assert.ok(pageViolations(uncreated)
    .includes('countdown restore must assign a controller and delegate to it'))

  const unassigned = pageSource.replace(
    'this._countdownSessionRestoreController = createCountdownSessionRestoreController({',
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
    'this._startSessionController = createStartSessionController({',
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
    'this._unknownStartController = createUnknownStartController({',
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
    'this._pendingSyncController = createPendingSyncController({',
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
    'this._terminalConflictController = createTerminalConflictController({',
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
    'this._statsController = createStatsController({',
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
    'this._themeController = createThemeController({',
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

test('end-confirm snapshot module must stay wired into the page', () => {
  const detached = pageSource.replace(
    "require('./utils/end-confirm-snapshot')",
    "require('./utils/legacy-confirm-snapshot')"
  )
  assert.ok(pageViolations(detached)
    .includes('page no longer imports governed module: end-confirm-snapshot.js'))
})

test('active light-sync shell must lazily reuse one controller', () => {
  const unassigned = pageSource.replace(
    'this._activeSyncController = createActiveSyncController({',
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
    'this._pauseToggleController = createPauseToggleController({',
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
    'this._resumeErrorController = createResumeErrorController({',
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
    'this._celebrationDismissController = createCelebrationDismissController({',
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
    'this._breakRestoreController = createBreakRestoreController({',
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
    assert.equal(result.modules, 40)
  }
})
