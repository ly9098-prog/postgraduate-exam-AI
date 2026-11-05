const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')

const PAGE_PATH = 'miniprogram/subpackages/study/practice-result/index.js'
const PAGE_MAX_LINES = 861
const MODULE_DIR = 'miniprogram/subpackages/study/practice-result/utils/'
// Frozen dependency surface for every governed module in the result page utils
// directory. Page-adapter modules must receive the api client and any storage
// facade from the page instead of requiring them, so live page ports stay live.
const MODULES = {
  'back-navigation-controller.js': [],
  'batch-diagnosis-controller.js': [],
  'cache-validation.js': [],
  'format-helpers.js': [],
  'growth-helpers.js': [],
  'payload-readers.js': [],
  'practice-payload-mapper.js': [],
  'practice-result-diagnosis-page-adapter.js': ['../../utils/error-diagnosis'],
  'practice-result-navigation-page-adapter.js': [],
  'practice-result-payload-page-adapter.js': ['./result-counts', './format-helpers', './growth-helpers'],
  'practice-result-teacher-page-adapter.js': ['../../utils/ai-teacher-408'],
  'practice-result-trend-page-adapter.js': ['./format-helpers', './trend-plot-builder'],
  'recovered-payload-builder.js': [],
  'result-counts.js': [],
  'result-tips.js': [],
  'review-408-teacher-controller.js': [],
  'review-analysis-view.js': ['../../utils/ai-analysis-normalizer', './review-preview-format'],
  'review-item-builder.js': ['../../utils/error-diagnosis'],
  'review-preview-format.js': ['../../utils/stem-render', '../../utils/math-format'],
  'route-helpers.js': [],
  'trend-load-controller.js': [],
  'trend-plot-builder.js': [],
}
const MODULE_BUDGETS = {
  'back-navigation-controller.js': 90,
  'batch-diagnosis-controller.js': 102,
  'cache-validation.js': 31,
  'format-helpers.js': 74,
  'growth-helpers.js': 108,
  'payload-readers.js': 42,
  'practice-payload-mapper.js': 188,
  'practice-result-diagnosis-page-adapter.js': 27,
  'practice-result-navigation-page-adapter.js': 23,
  'practice-result-payload-page-adapter.js': 52,
  'practice-result-teacher-page-adapter.js': 40,
  'practice-result-trend-page-adapter.js': 19,
  'recovered-payload-builder.js': 55,
  'result-counts.js': 49,
  'result-tips.js': 59,
  'review-408-teacher-controller.js': 75,
  'review-analysis-view.js': 171,
  'review-item-builder.js': 95,
  'review-preview-format.js': 98,
  'route-helpers.js': 34,
  'trend-load-controller.js': 83,
  'trend-plot-builder.js': 74,
}
const ADAPTERS = Object.freeze([
  'practice-result-payload-page-adapter.js',
  'practice-result-diagnosis-page-adapter.js',
  'practice-result-trend-page-adapter.js',
  'practice-result-teacher-page-adapter.js',
  'practice-result-navigation-page-adapter.js',
])
const FUNCTION_BUDGET = 50

// [page method, page cache field, factory, capability builder, injected deps]
const PAGE_CONTROLLERS = [
  ['_batchDiagnosisController', '_batchDiagnosis', 'createBatchDiagnosisController', 'buildBatchDiagnosisPageCapabilities', '{ api }'],
  ['_trendLoadController', '_trendLoad', 'createTrendLoadController', 'buildTrendLoadPageCapabilities', '{}'],
  ['_review408TeacherController', '_review408Teacher', 'createReview408TeacherController', 'buildReview408TeacherPageCapabilities', '{ api }'],
  ['_backNavigationController', '_backNavigation', 'createBackNavigationController', 'buildBackNavigationPageCapabilities', '{}'],
]

const PAGE_DELEGATIONS = [
  `  _practicePageState() {
    return buildPracticePayloadPageState(this)
  },`,
  `  _practicePayloadPorts() {
    if (!this._practicePayloadPortsCached) {
      this._practicePayloadPortsCached = buildPracticePayloadPageCapabilities(this, {
        knowledgePracticeSync,
        buildErrorDonutSvg,
      });
    }
    return this._practicePayloadPortsCached;
  },`,
  `  _practicePayloadController() {
    if (!this._practicePayloadCtl) {
      this._practicePayloadCtl = {
        apply: payload => applyPracticePayloadOrchestration(
          payload, this._practicePayloadPorts(), this._practicePageState()
        ),
      }
    }
    return this._practicePayloadCtl
  },`,
]

// Distinctive capability keys that must stay in the adapters, not the page.
const MOVED_CAPABILITY_KEYS = [
  'recordKnowledgePractice',
  'consumeKnowledgeBaseline',
  'getLaunchKnowledgePointId',
  'getBatchDiagnosisSaving',
  'getQuickTypes',
  'putDiagnosis',
  'isLoadCurrent',
  'requestTrends',
  'getTeacherLoading',
  'postTeacher',
  'setInflight',
  'getNavigationLocked',
  'navigateBack',
]

const PAGE_REQUIRES = [
  './utils/practice-payload-mapper',
  './utils/back-navigation-controller',
  './utils/batch-diagnosis-controller',
  './utils/trend-load-controller',
  './utils/review-408-teacher-controller',
  ...ADAPTERS.map(name => `./utils/${name.replace(/\.js$/, '')}`),
]

function lineCount(source) {
  return source.trimEnd().split('\n').length
}

function longFunctions(filename, source) {
  const file = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const errors = []
  const walk = (node) => {
    if (ts.isFunctionLike(node) && node.body) {
      const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1
      const end = file.getLineAndCharacterOfPosition(node.end).line + 1
      if (end - start + 1 > FUNCTION_BUDGET) {
        errors.push(`${filename}: function exceeds 50 lines at ${start}`)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return errors
}

function moduleViolations(relativeModule, source) {
  const errors = []
  const budget = MODULE_BUDGETS[relativeModule]
  if (budget === undefined) {
    return [`ungoverned practice-result module: ${relativeModule}`]
  }
  if (lineCount(source) > budget) {
    errors.push(`${relativeModule}: module exceeds budget ${budget}`)
  }
  errors.push(...longFunctions(relativeModule, source))
  const allowed = MODULES[relativeModule]
  const requirePattern = /require\(\s*([^)]*?)\s*\)/g
  let match
  while ((match = requirePattern.exec(source)) !== null) {
    const literal = /^'([^']*)'$/.exec(match[1])
    if (!literal) {
      errors.push(`${relativeModule}: require target must be a literal`)
      continue
    }
    if (!allowed.includes(literal[1])) {
      errors.push(`${relativeModule}: forbidden dependency ${literal[1]}`)
    }
  }
  if (/import\s*\(/.test(source)) {
    errors.push(`${relativeModule}: dynamic import is forbidden`)
  }
  return errors
}

function pageViolations(source) {
  const errors = []
  if (lineCount(source) > PAGE_MAX_LINES) {
    errors.push(`${PAGE_PATH}: page exceeds budget ${PAGE_MAX_LINES}`)
  }
  for (const [method, field, factory, builder, deps] of PAGE_CONTROLLERS) {
    const expected = `  ${method}() {
    if (!this.${field}) {
      this.${field} = ${factory}(
        ${builder}(this, ${deps})
      )
    }
    return this.${field}
  },`
    if (!source.includes(expected)) {
      errors.push(`${method} must lazily delegate to ${builder}`)
    }
  }
  if (/create\w+Controller\(\{/.test(source)) {
    errors.push('page must not build controller ports inline')
  }
  for (const expected of PAGE_DELEGATIONS) {
    if (!source.includes(expected)) {
      errors.push(`${PAGE_PATH}: payload delegation template drifted`)
    }
  }
  for (const relative of PAGE_REQUIRES) {
    const occurrences = source.split(`require('${relative}')`).length - 1
    if (occurrences !== 1) {
      errors.push(`${PAGE_PATH}: require('${relative}') expected exactly once, found ${occurrences}`)
    }
  }
  for (const key of MOVED_CAPABILITY_KEYS) {
    if (new RegExp(`\\b${key}\\s*:`).test(source)) {
      errors.push(`${key} must live in a practice-result page adapter`)
    }
  }
  return errors
}

function scanPracticeResult() {
  const pageSource = fs.readFileSync(path.join(ROOT, PAGE_PATH), 'utf8')
  const violations = [...pageViolations(pageSource)]
  let moduleLines = 0
  let adapterLines = 0
  let requires = 0
  let modules = 0
  for (const relativeModule of Object.keys(MODULE_BUDGETS)) {
    const filename = path.join(ROOT, MODULE_DIR, relativeModule)
    if (!fs.existsSync(filename)) {
      violations.push(`missing governed module: ${relativeModule}`)
      continue
    }
    const source = fs.readFileSync(filename, 'utf8')
    modules += 1
    moduleLines += lineCount(source)
    if (ADAPTERS.includes(relativeModule)) adapterLines += lineCount(source)
    requires += (source.match(/require\(/g) || []).length
    violations.push(...moduleViolations(relativeModule, source))
  }
  for (const filename of fs.readdirSync(path.join(ROOT, MODULE_DIR))) {
    if (filename.endsWith('.js') && MODULE_BUDGETS[filename] === undefined) {
      violations.push(`ungoverned practice-result module: ${filename}`)
    }
  }
  return {
    violations,
    pageLines: lineCount(pageSource),
    moduleLines,
    adapterLines,
    requires,
    modules,
    controllers: PAGE_CONTROLLERS.length,
  }
}

if (require.main === module) {
  const result = scanPracticeResult()
  if (result.violations.length) {
    console.error(result.violations.join('\n'))
    process.exitCode = 1
  } else {
    console.log(
      `Practice-result boundaries passed: page ${result.pageLines} lines, `
      + `${result.controllers} controllers, ${result.adapterLines} adapter lines, `
      + `${result.modules} governed modules`
    )
  }
}

module.exports = {
  PAGE_PATH,
  PAGE_MAX_LINES,
  MODULE_DIR,
  MODULES,
  MODULE_BUDGETS,
  ADAPTERS,
  FUNCTION_BUDGET,
  PAGE_CONTROLLERS,
  PAGE_DELEGATIONS,
  MOVED_CAPABILITY_KEYS,
  PAGE_REQUIRES,
  lineCount,
  moduleViolations,
  pageViolations,
  scanPracticeResult,
}
