const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  MODULES, MODULE_BUDGETS, PAGE_CONTROLLERS, PAGE_MAX_LINES,
  moduleViolations, pageViolations, scanReviewToday,
} = require('../scripts/architecture/review-today-boundaries')

const root = path.resolve(__dirname, '../..')
const pagePath = path.join(root, 'miniprogram/subpackages/study/review-today/review-today.js')
const pageSource = fs.readFileSync(pagePath, 'utf8')
const supportSource = fs.readFileSync(
  path.join(root, 'miniprogram/subpackages/study/review-today/utils/review-runner-support.js'), 'utf8'
)
const adapter = name => fs.readFileSync(
  path.join(root, 'miniprogram/subpackages/study/review-today/utils', name), 'utf8'
)

test('scans every governed review-today adapter and the real page', () => {
  const result = scanReviewToday()
  assert.deepEqual(result.violations, [])
  assert.equal(result.pageLines, PAGE_MAX_LINES)
  assert.equal(result.controllers, 24)
  assert.equal(Object.keys(MODULES).length, 7)
  assert.ok(result.moduleLines <= 600, `adapter lines grew to ${result.moduleLines}`)
  assert.equal(result.requires, 35)
})

test('page must lazily delegate all 24 controllers', () => {
  const detached = pageSource.replace(
    'buildReviewTimerPageCapabilities(this, { api, _reviewMonotonicNow, _reviewServerNow })',
    'buildReviewTimerPageCapabilities(this, { api })'
  )
  assert.ok(pageViolations(detached)
    .includes('_reviewTimerController must lazily delegate to buildReviewTimerPageCapabilities'))

  const removed = pageSource.replace(
    `${PAGE_CONTROLLERS.find(item => item[0] === '_resultDockController')[0]}() {
return this._resultDockControllerInstance || (
this._resultDockControllerInstance = createResultDockController(
buildResultDockPageCapabilities(this, {})
)
)
},`,
    ''
  )
  assert.ok(pageViolations(removed)
    .includes('_resultDockController must lazily delegate to buildResultDockPageCapabilities'))
})

test('page must not rebuild controller ports inline', () => {
  const inline = pageSource.replace(
    '_reviewSelfHealController() {',
    "  _reviewSelfHealController() {\nreturn this._reviewSelfHeal || (this._reviewSelfHeal = createReviewSelfHealController({ isPageAlive: () => true }))"
  )
  assert.ok(pageViolations(inline).includes('page must not build controller ports inline'))
})

test('page must not grow past its frozen budget', () => {
  const padded = `${pageSource}\n${'// growth\n'.repeat(PAGE_MAX_LINES)}`
  assert.ok(pageViolations(padded)
    .includes(`miniprogram/subpackages/study/review-today/review-today.js: page exceeds budget ${PAGE_MAX_LINES}`))
})

test('moved pure helpers must not return to the page', () => {
  const moved = `function normalizeReviewBatchSize(value) { return 10 }\n${pageSource}`
  assert.ok(pageViolations(moved).includes('normalizeReviewBatchSize must live in review-runner-support.js'))
})

test('adapters only allow their owning literal dependencies', () => {
  const name = 'review-runner-support.js'
  assert.deepEqual(moduleViolations(name, supportSource), [])
  for (const forbidden of [
    "require('./review-today/review-today')",
    "require('../../utils/storage')",
    "require('node:fs')",
    "require('../../../utils/api')",
  ]) {
    const errors = moduleViolations(name, `${forbidden}\n${supportSource}`)
    assert.ok(errors.some(error => error.startsWith('forbidden dependency:')),
      `expected rejection for ${forbidden}`)
  }
  const alias = "const target = './x'\nrequire(target)"
  assert.ok(moduleViolations(name, alias).includes(
    'review-runner-support.js: require target must be a literal'))
  const dynamic = "const load = () => import('./x')"
  assert.ok(moduleViolations(name, dynamic).includes(
    'review-runner-support.js: dynamic import is forbidden'))
})

test('adapters keep their line and function budgets', () => {
  const name = 'review-draft-page-adapter.js'
  const padded = `${adapter(name)}\n${'// growth\n'.repeat(MODULE_BUDGETS[name])}`
  assert.ok(moduleViolations(name, padded).includes(
    `${name}: adapter exceeds budget ${MODULE_BUDGETS[name]}`))

  const longFunction = `function build() {\n${'  void 0\n'.repeat(51)}}\n`
  assert.ok(moduleViolations(name, longFunction).some(
    error => error.includes('function exceeds 50 lines')))

  assert.deepEqual(moduleViolations('unknown-page-adapter.js', ''), [
    'ungoverned review-today adapter: unknown-page-adapter.js',
  ])
})
