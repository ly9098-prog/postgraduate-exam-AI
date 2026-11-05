const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')

const PAGE_PATH = 'miniprogram/subpackages/study/review-today/review-today.js'
const PAGE_MAX_LINES = 642
const SUPPORT_PATH = 'miniprogram/subpackages/study/review-today/utils/review-runner-support.js'
const MODULE_DIR = 'miniprogram/subpackages/study/review-today/utils/'
const MODULES = {
  'review-runner-support.js': [],
  'review-draft-page-adapter.js': [
    './review-runner-support',
    '../../../../utils/china-time',
    './draft-controller',
  ],
  'review-answer-page-adapter.js': [
    './review-runner-support',
    '../../utils/answer',
    './answer-interaction-controller',
    './question-display-controller',
    './question-enrichment-controller',
    './render-safety-controller',
  ],
  'review-overview-page-adapter.js': [
    './review-active-state',
    './review-runner-support',
    './overview-vm-controller',
    './batch-size-sheet-controller',
    './overview-load-controller',
    './day-sync-controller',
    './overview-sync-controller',
  ],
  'review-session-page-adapter.js': [
    './review-active-state',
    './review-runner-support',
    '../../utils/question-runner-adapter',
    './review-session-controller',
    './start-batch-controller',
    './nav-back-controller',
    './self-heal-controller',
  ],
  'review-submit-page-adapter.js': [
    './review-active-state',
    './review-runner-support',
    '../../utils/question-runner-adapter',
    './group-submit-flow-controller',
    './submit-entry-controller',
    './submit-confirm-controller',
    './submit-request-controller',
    './submit-result-controller',
    './result-dock-controller',
  ],
  'review-progress-page-adapter.js': [
    './review-active-state',
    './review-runner-support',
    './master-controller',
    './next-group-controller',
    './next-retry-group-controller',
    './next-remote-batch-controller',
    './review-timer-controller',
  ],
}
const MODULE_BUDGETS = {
  'review-runner-support.js': 70,
  'review-draft-page-adapter.js': 29,
  'review-answer-page-adapter.js': 67,
  'review-overview-page-adapter.js': 84,
  'review-session-page-adapter.js': 84,
  'review-submit-page-adapter.js': 104,
  'review-progress-page-adapter.js': 126,
}
const FUNCTION_BUDGET = 50

// [page method, page cache field, factory, capability builder, injected deps]
const PAGE_CONTROLLERS = [
  ['_reviewDraftController', '_reviewDraft', 'createReviewDraftController', 'buildReviewDraftPageCapabilities', '{ storage }'],
  ['_answerInteractionController', '_answerInteraction', 'createAnswerInteractionController', 'buildAnswerInteractionPageCapabilities', '{}'],
  ['_questionDisplayController', '_questionDisplay', 'createQuestionDisplayController', 'buildQuestionDisplayPageCapabilities', '{}'],
  ['_overviewVMController', '_overviewVM', 'createOverviewVMController', 'buildOverviewVMPageCapabilities', '{}'],
  ['_renderSafetyController', '_renderSafety', 'createRenderSafetyController', 'buildRenderSafetyPageCapabilities', '{ config }'],
  ['_batchSizeSheetController', '_batchSizeSheet', 'createBatchSizeSheetController', 'buildBatchSizeSheetPageCapabilities', '{}'],
  ['_questionEnrichmentController', '_questionEnrichment', 'createQuestionEnrichmentController', 'buildQuestionEnrichmentPageCapabilities', '{ config }'],
  ['_reviewSessionController', '_reviewSessionCtl', 'createReviewSessionController', 'buildReviewSessionPageCapabilities', '{}'],
  ['_navBackController', '_navBack', 'createNavBackController', 'buildNavBackPageCapabilities', '{}'],
  ['_reviewSelfHealController', '_reviewSelfHeal', 'createReviewSelfHealController', 'buildReviewSelfHealPageCapabilities', '{}'],
  ['_overviewSyncController', '_overviewSync', 'createOverviewSyncController', 'buildOverviewSyncPageCapabilities', '{}'],
  ['_overviewLoadController', '_overviewLoad', 'createOverviewLoadController', 'buildOverviewLoadPageCapabilities', '{ api }'],
  ['_reviewDaySyncController', '_reviewDaySync', 'createReviewDaySyncController', 'buildReviewDaySyncPageCapabilities', '{ api }'],
  ['_startBatchController', '_startBatchControllerInstance', 'createStartBatchController', 'buildStartBatchPageCapabilities', '{ api }'],
  ['_reviewMasterController', '_reviewMaster', 'createReviewMasterController', 'buildReviewMasterPageCapabilities', '{ api }'],
  ['_groupSubmitFlowController', '_groupSubmitFlow', 'createGroupSubmitFlowController', 'buildGroupSubmitFlowPageCapabilities', '{}'],
  ['_groupSubmitEntryController', '_groupSubmitEntry', 'createGroupSubmitEntryController', 'buildGroupSubmitEntryPageCapabilities', '{}'],
  ['_groupSubmitRequestController', '_groupSubmitRequest', 'createGroupSubmitRequestController', 'buildGroupSubmitRequestPageCapabilities', '{ api }'],
  ['_groupSubmitResultController', '_groupSubmitResult', 'createGroupSubmitResultController', 'buildGroupSubmitResultPageCapabilities', '{}'],
  ['_nextGroupController', '_nextGroup', 'createNextGroupController', 'buildNextGroupPageCapabilities', '{}'],
  ['_nextRetryGroupController', '_nextRetryGroup', 'createNextRetryGroupController', 'buildNextRetryGroupPageCapabilities', '{}'],
  ['_nextRemoteBatchController', '_nextRemoteBatch', 'createNextRemoteBatchController', 'buildNextRemoteBatchPageCapabilities', '{ api }'],
  ['_reviewTimerController', '_reviewTimer', 'createReviewTimerController', 'buildReviewTimerPageCapabilities', '{ api, _reviewMonotonicNow, _reviewServerNow }'],
  ['_resultDockController', '_resultDockControllerInstance', 'createResultDockController', 'buildResultDockPageCapabilities', '{}'],
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
    return [`ungoverned review-today adapter: ${relativeModule}`]
  }
  if (lineCount(source) > budget) {
    errors.push(`${relativeModule}: adapter exceeds budget ${budget}`)
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
  for (const [method, field, factory, builder, deps] of PAGE_CONTROLLERS) {
    const expected = `${method}() {
return this.${field} || (
this.${field} = ${factory}(
${builder}(this, ${deps})
)
)
},`
    if (!source.includes(expected)) {
      errors.push(`${method} must lazily delegate to ${builder}`)
    }
  }
  if (/create\w+Controller\(\{/.test(source)) {
    errors.push('page must not build controller ports inline')
  }
  for (const movedHelper of ['normalizeReviewBatchSize', 'formatReviewElapsed', 'normalizeReviewQuestion', 'REVIEW_DRAFT_PREFIX', 'REVIEW_BATCH_SIZE_OPTIONS']) {
    if (source.includes(`function ${movedHelper}(`) || source.includes(`var ${movedHelper} =`)) {
      errors.push(`${movedHelper} must live in review-runner-support.js`)
    }
  }
  return errors
}

function scanReviewToday() {
  const pageSource = fs.readFileSync(path.join(ROOT, PAGE_PATH), 'utf8')
  const supportSource = fs.readFileSync(path.join(ROOT, SUPPORT_PATH), 'utf8')
  const violations = [...pageViolations(pageSource)]
  violations.push(...moduleViolations('review-runner-support.js', supportSource))
  let lines = lineCount(supportSource)
  let requires = (supportSource.match(/require\(/g) || []).length
  for (const [module] of Object.entries(MODULES)) {
    if (module === 'review-runner-support.js') continue
    const source = fs.readFileSync(path.join(ROOT, MODULE_DIR, module), 'utf8')
    lines += lineCount(source)
    requires += (source.match(/require\(/g) || []).length
    violations.push(...moduleViolations(module, source))
  }
  return {
    violations,
    pageLines: lineCount(pageSource),
    moduleLines: lines,
    requires,
    controllers: PAGE_CONTROLLERS.length,
  }
}

if (require.main === module) {
  const result = scanReviewToday()
  if (result.violations.length) {
    console.error(result.violations.join('\n'))
    process.exitCode = 1
  } else {
    console.log(
      `Review-today boundaries passed: page ${result.pageLines} lines, `
      + `${result.controllers} controllers, ${result.moduleLines} adapter lines`
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
  scanReviewToday,
}
