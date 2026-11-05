const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  MODULES, MODULE_BUDGETS, ADAPTERS, PAGE_CONTROLLERS, PAGE_MAX_LINES,
  moduleViolations, pageViolations, scanPracticeResult,
} = require('../scripts/architecture/practice-result-boundaries')

const root = path.resolve(__dirname, '../..')
const pagePath = path.join(root, 'miniprogram/subpackages/study/practice-result/index.js')
const pageSource = fs.readFileSync(pagePath, 'utf8')
const utilsDir = path.join(root, 'miniprogram/subpackages/study/practice-result/utils')
const adapter = name => fs.readFileSync(path.join(utilsDir, name), 'utf8')

function controllerTemplate([method, field, factory, builder, deps]) {
  return `  ${method}() {
    if (!this.${field}) {
      this.${field} = ${factory}(
        ${builder}(this, ${deps})
      )
    }
    return this.${field}
  },`
}

test('scans every governed practice-result module and the real page', () => {
  const result = scanPracticeResult()
  assert.deepEqual(result.violations, [])
  assert.equal(result.pageLines, PAGE_MAX_LINES)
  assert.equal(result.pageLines, 870)
  assert.equal(result.controllers, 4)
  assert.equal(result.modules, 22)
  assert.equal(Object.keys(MODULES).length, Object.keys(MODULE_BUDGETS).length)
  assert.equal(result.adapterLines, 161)
  assert.equal(result.moduleLines, Object.values(MODULE_BUDGETS).reduce((sum, lines) => sum + lines, 0))
  assert.equal(result.requires, 12)
  assert.equal(ADAPTERS.length, 5)
})

test('page must lazily delegate all four result controllers', () => {
  const httpPort = PAGE_CONTROLLERS.find(item => item[0] === '_batchDiagnosisController')
  const detached = pageSource.replace(
    'buildBatchDiagnosisPageCapabilities(this, { api })',
    'buildBatchDiagnosisPageCapabilities(this)'
  )
  assert.ok(pageViolations(detached)
    .includes(`${httpPort[0]} must lazily delegate to ${httpPort[3]}`))

  for (const entry of PAGE_CONTROLLERS) {
    const removed = pageSource.replace(controllerTemplate(entry), '')
    assert.ok(pageViolations(removed)
      .includes(`${entry[0]} must lazily delegate to ${entry[3]}`), entry[0])
  }
})

test('page must not rebuild controller ports inline', () => {
  const inline = pageSource.replace(
    '_trendLoadController() {',
    '  _trendLoadController() {\n      this._trendLoad = createTrendLoadController({ setData: patch => this.setData(patch) })'
  )
  assert.ok(pageViolations(inline).includes('page must not build controller ports inline'))
})

test('payload state and port assembly stay in the payload adapter', () => {
  const driftedState = pageSource.replace(
    '    return buildPracticePayloadPageState(this)',
    '    return {}'
  )
  assert.ok(pageViolations(driftedState).includes(
    'miniprogram/subpackages/study/practice-result/index.js: payload delegation template drifted'))

  const cappedAgain = pageSource.replace(
    `      this._practicePayloadPortsCached = buildPracticePayloadPageCapabilities(this, {
        knowledgePracticeSync,
        buildErrorDonutSvg,
      });`,
    '      this._practicePayloadPortsCached = buildPracticePayloadPageCapabilities(this, {});'
  )
  assert.ok(pageViolations(cappedAgain).includes(
    'miniprogram/subpackages/study/practice-result/index.js: payload delegation template drifted'))
})

test('page must not grow past its frozen budget', () => {
  const padded = `${pageSource}\n${'// growth\n'.repeat(PAGE_MAX_LINES)}`
  assert.ok(pageViolations(padded)
    .includes(`miniprogram/subpackages/study/practice-result/index.js: page exceeds budget ${PAGE_MAX_LINES}`))
})

test('every page adapter must stay required exactly once by the page', () => {
  for (const name of ADAPTERS) {
    const relative = `./utils/${name.replace(/\.js$/, '')}`
    const dropped = pageSource.replace(`require('${relative}')`, "require('./utils/route-helpers')")
    assert.ok(pageViolations(dropped).some(error =>
      error.includes(`require('${relative}') expected exactly once, found 0`)), name)
  }
})

test('moved capability keys must not return to the page', () => {
  for (const key of ['getQuickTypes', 'putDiagnosis', 'postTeacher', 'navigateBack', 'recordKnowledgePractice']) {
    const reinstated = `    ${key}: () => null,\n${pageSource}`
    assert.ok(pageViolations(reinstated).includes(`${key} must live in a practice-result page adapter`), key)
  }
})

test('module gate freezes adapter dependencies and budgets', () => {
  assert.deepEqual(moduleViolations('practice-result-trend-page-adapter.js', adapter('practice-result-trend-page-adapter.js')), [])
  assert.ok(moduleViolations('practice-result-trend-page-adapter.js',
    `const api = require('../../../utils/api')\n${adapter('practice-result-trend-page-adapter.js')}`)
    .includes('practice-result-trend-page-adapter.js: forbidden dependency ../../../utils/api'))
  assert.ok(moduleViolations('practice-result-payload-page-adapter.js',
    `const storage = require(variable)\n${adapter('practice-result-payload-page-adapter.js')}`)
    .includes('practice-result-payload-page-adapter.js: require target must be a literal'))
  assert.ok(moduleViolations('practice-result-navigation-page-adapter.js',
    `import('./late.js')\n${adapter('practice-result-navigation-page-adapter.js')}`)
    .includes('practice-result-navigation-page-adapter.js: dynamic import is forbidden'))
  assert.ok(moduleViolations('practice-result-navigation-page-adapter.js',
    `${adapter('practice-result-navigation-page-adapter.js')}\n${'// growth\n'.repeat(MODULE_BUDGETS['practice-result-navigation-page-adapter.js'])}`)
    .includes('practice-result-navigation-page-adapter.js: module exceeds budget 23'))
  assert.deepEqual(moduleViolations('unlisted-module.js', 'void 0'), ['ungoverned practice-result module: unlisted-module.js'])
})

test('module gate rejects oversized functions in governed modules', () => {
  const body = Array(51).fill('void 0').join('\n')
  const violations = moduleViolations('trend-load-controller.js',
    `${adapter('trend-load-controller.js')}\nfunction injected() {\n${body}\n}\n`)
  assert.ok(violations.some(error => /trend-load-controller\.js: function exceeds 50 lines/.test(error)))
})
