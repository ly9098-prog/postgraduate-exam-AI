const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  MODULES, MODULE_BUDGETS, PAGE_MAX_LINES, moduleViolations, pageViolations, scanExamRunner,
} = require('../scripts/architecture/exam-runner-boundaries')

const root = path.resolve(__dirname, '../..')
const pagePath = path.join(root, 'miniprogram/subpackages/exam/exam-runner/index.js')
const pageSource = fs.readFileSync(pagePath, 'utf8')
const adapter = name => fs.readFileSync(
  path.join(root, 'miniprogram/subpackages/exam/utils', name), 'utf8'
)

test('scans every governed exam runner adapter and the real page', () => {
  const result = scanExamRunner()
  assert.deepEqual(result.violations, [])
  assert.equal(result.pageLines, PAGE_MAX_LINES)
  assert.equal(Object.keys(MODULES).length, 6)
  assert.ok(result.moduleLines <= 400, `adapter lines grew to ${result.moduleLines}`)
  assert.equal(result.requires, 9)
})

test('page must lazily delegate every controller to its capability builder', () => {
  const detached = pageSource.replace(
    '        buildExamTimerPageCapabilities(this)',
    '        buildExamTimerPageCapabilities()'
  )
  assert.ok(pageViolations(detached)
    .includes('_examTimerController must lazily delegate to buildExamTimerPageCapabilities'))

  const removed = pageSource.replace(
    `  _examSubmitOutcomeController() {
    return this._examSubmitOutcome || (
      this._examSubmitOutcome = createExamSubmitOutcomeController(
        buildExamSubmitOutcomePageCapabilities(this)
      )
    )
  },
`,
    ''
  )
  assert.ok(pageViolations(removed)
    .includes('_examSubmitOutcomeController must lazily delegate to buildExamSubmitOutcomePageCapabilities'))
})

test('page must not rebuild controller ports inline', () => {
  const inline = pageSource.replace(
    '  _examReconnectController() {',
    "  _examReconnectController() {\n    return this._examReconnect || (this._examReconnect = createExamReconnectController({ isPageAlive: () => true }))"
  )
  assert.ok(pageViolations(inline).includes('page must not build controller ports inline'))
})

test('page must not grow past its frozen budget', () => {
  const padded = `${pageSource}\n${'// growth\n'.repeat(PAGE_MAX_LINES)}`
  assert.ok(pageViolations(padded)
    .includes(`miniprogram/subpackages/exam/exam-runner/index.js: page exceeds budget ${PAGE_MAX_LINES}`))
})

test('page must not require modules from its own directory', () => {
  const selfRequire = `const other = require('./helper')\n${pageSource}`
  assert.ok(pageViolations(selfRequire)
    .includes('page must not require from its own directory: ./helper'))
})

test('adapter modules only allow their owning literal dependencies', () => {
  const name = 'exam-runner-reconnect-page-adapter.js'
  assert.deepEqual(moduleViolations(name, adapter(name)), [])
  for (const forbidden of [
    "require('../exam-runner/index')",
    "require('../../../utils/storage')",
    "require('node:fs')",
    "require('../../pages/pomodoro/pomodoro')",
  ]) {
    const errors = moduleViolations(name, `${forbidden}\n${adapter(name)}`)
    assert.ok(errors.some(error => error.startsWith('forbidden dependency:')),
      `expected rejection for ${forbidden}`)
  }
  const alias = `const target = './x'\nrequire(target)`
  assert.ok(moduleViolations(name, alias).includes(
    'exam-runner-reconnect-page-adapter.js: require target must be a literal'))
  const dynamic = `const load = () => import('./x')`
  assert.ok(moduleViolations(name, dynamic).includes(
    'exam-runner-reconnect-page-adapter.js: dynamic import is forbidden'))
})

test('adapter modules keep their line and function budgets', () => {
  const name = 'exam-runner-timer-page-adapter.js'
  const padded = `${adapter(name)}\n${'// growth\n'.repeat(MODULE_BUDGETS[name])}`
  assert.ok(moduleViolations(name, padded).includes(
    `${name}: adapter exceeds budget ${MODULE_BUDGETS[name]}`))

  const longFunction = `function build() {\n${'  void 0\n'.repeat(51)}}\n`
  assert.ok(moduleViolations(name, longFunction).some(
    error => error.includes('function exceeds 50 lines')))

  assert.deepEqual(moduleViolations('unknown-page-adapter.js', ''), [
    'ungoverned exam runner adapter: unknown-page-adapter.js',
  ])
})
