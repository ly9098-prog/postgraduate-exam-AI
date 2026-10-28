const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const ROOT = path.resolve(__dirname, '../../..')
// Reuse the repository's declared development parser, never a Mini Program dependency.
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')

const PAGE_PATH = 'miniprogram/subpackages/exam/exam-runner/index.js'
const PAGE_MAX_LINES = 550
const FUNCTION_BUDGET = 50
const MODULE_DIR = 'miniprogram/subpackages/exam/utils/'
const MODULES = {
  'exam-runner-pending-cache-page-adapter.js': ['./exam-attempt-cache', '../../../utils/api'],
  'exam-runner-timer-page-adapter.js': ['../../../utils/api'],
  'exam-runner-answer-page-adapter.js': ['./exam-runner-view', '../../../utils/api'],
  'exam-runner-navigation-page-adapter.js': ['./exam-runner-view', '../../../utils/api'],
  'exam-runner-submit-page-adapter.js': ['./submit-helpers', '../../../utils/api'],
  'exam-runner-reconnect-page-adapter.js': [],
}
const MODULE_BUDGETS = {
  'exam-runner-pending-cache-page-adapter.js': 52,
  'exam-runner-timer-page-adapter.js': 40,
  'exam-runner-answer-page-adapter.js': 89,
  'exam-runner-navigation-page-adapter.js': 43,
  'exam-runner-submit-page-adapter.js': 113,
  'exam-runner-reconnect-page-adapter.js': 19,
}

// page method -> [page cache field, controller factory, capability builder]
const PAGE_CONTROLLERS = {
  _examPendingCacheController: [
    '_examPendingCache', 'createExamPendingCacheController',
    'buildExamPendingCachePageCapabilities',
  ],
  _examTimerController: [
    '_examTimer', 'createExamTimerController', 'buildExamTimerPageCapabilities',
  ],
  _examInteractionController: [
    '_examInteraction', 'createExamInteractionController',
    'buildExamInteractionPageCapabilities',
  ],
  _examQuestionTimeController: [
    '_examQuestionTime', 'createExamQuestionTimeController',
    'buildExamQuestionTimePageCapabilities',
  ],
  _examAnswerSyncController: [
    '_examAnswerSync', 'createExamAnswerSyncController',
    'buildExamAnswerSyncPageCapabilities',
  ],
  _examAttemptReconcileController: [
    '_examAttemptReconcile', 'createExamAttemptReconcileController',
    'buildExamAttemptReconcilePageCapabilities',
  ],
  _examSubmitRetryController: [
    '_examSubmitRetry', 'createExamSubmitRetryController',
    'buildExamSubmitRetryPageCapabilities',
  ],
  _examReconnectController: [
    '_examReconnect', 'createExamReconnectController',
    'buildExamReconnectPageCapabilities',
  ],
  _examQuestionNavigationController: [
    '_examQuestionNavigation', 'createExamQuestionNavigationController',
    'buildExamQuestionNavigationPageCapabilities',
  ],
  _examExitRequestController: [
    '_examExitRequest', 'createExamExitRequestController',
    'buildExamExitRequestPageCapabilities',
  ],
  _examSubmitEntryController: [
    '_examSubmitEntry', 'createExamSubmitEntryController',
    'buildExamSubmitEntryPageCapabilities',
  ],
  _examSubmitPreparationController: [
    '_examSubmitPreparation', 'createExamSubmitPreparationController',
    'buildExamSubmitPreparationPageCapabilities',
  ],
  _examSubmitOutcomeController: [
    '_examSubmitOutcome', 'createExamSubmitOutcomeController',
    'buildExamSubmitOutcomePageCapabilities',
  ],
}

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
  if (budget === undefined) return [`ungoverned exam runner adapter: ${relativeModule}`]
  if (lineCount(source) > budget) {
    errors.push(`${relativeModule}: adapter exceeds budget ${budget}`)
  }
  errors.push(...longFunctions(relativeModule, source))

  const allowed = MODULES[relativeModule]
  const requirePattern = /require\(\s*([^)]*?)\s*\)/g
  let match
  while ((match = requirePattern.exec(source)) !== null) {
    const request = match[1]
    const literal = /^'([^']*)'$/.exec(request)
    if (!literal) {
      errors.push(`${relativeModule}: require target must be a literal`)
      continue
    }
    if (!allowed.includes(literal[1])) {
      errors.push(`forbidden dependency: ${literal[1]}`)
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
  for (const [method, [field, factory, builder]] of Object.entries(PAGE_CONTROLLERS)) {
    const expected = [
      `  ${method}() {`,
      `    return this.${field} || (`,
      `      this.${field} = ${factory}(`,
      `        ${builder}(this)`,
      '      )',
      '    )',
      '  },',
    ].join('\n')
    const occurrences = source.split(expected).length - 1
    if (occurrences !== 1) {
      errors.push(`${method} must lazily delegate to ${builder}`)
    }
  }
  if (/createExam\w*Controller\(\{/.test(source)) {
    errors.push('page must not build controller ports inline')
  }
  const requires = source.match(/require\(\s*'([^']+)'\s*\)/g) || []
  for (const request of requires) {
    const target = /require\(\s*'([^']+)'\s*\)/.exec(request)[1]
    if (target.startsWith('./') || target.startsWith('../')) {
      const resolved = path.posix.normalize(
        path.posix.join('miniprogram/subpackages/exam/exam-runner', target)
      )
      if (resolved === 'miniprogram/subpackages/exam/exam-runner/index.js' ||
          resolved.startsWith('miniprogram/subpackages/exam/exam-runner/')) {
        errors.push(`page must not require from its own directory: ${target}`)
      }
    }
  }
  return errors
}

function scanExamRunner() {
  const pageSource = fs.readFileSync(path.join(ROOT, PAGE_PATH), 'utf8')
  const violations = [...pageViolations(pageSource)]
  let lines = 0
  let requires = 0
  for (const relativeModule of Object.keys(MODULES)) {
    const source = fs.readFileSync(path.join(ROOT, MODULE_DIR, relativeModule), 'utf8')
    lines += lineCount(source)
    requires += (source.match(/require\(/g) || []).length
    violations.push(...moduleViolations(relativeModule, source))
  }
  return { violations, pageLines: lineCount(pageSource), moduleLines: lines, requires }
}

if (require.main === module) {
  const result = scanExamRunner()
  if (result.violations.length) {
    console.error(result.violations.join('\n'))
    process.exitCode = 1
  } else {
    console.log(
      `Exam runner boundaries passed: page ${result.pageLines} lines, `
      + `${Object.keys(MODULES).length} adapters, ${result.moduleLines} adapter lines`
    )
  }
}

module.exports = {
  MODULES,
  MODULE_BUDGETS,
  PAGE_CONTROLLERS,
  PAGE_MAX_LINES,
  moduleViolations,
  pageViolations,
  scanExamRunner,
}
