const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../subpackages/study/practice')
const FACTORIES = {
  "./utils/recent-subject-controller": "createRecentSubjectController",
  "./utils/subject-sheet-controller": "createSubjectSheetController",
  "./utils/subject-selection-controller": "createSubjectSelectionController",
  "./utils/launch-return-controller": "createLaunchReturnController",
  "./utils/exit-guard-controller": "createExitGuardController",
  "./utils/exit-request-controller": "createExitRequestController",
  "./utils/paused-confirm-controller": "createPausedConfirmController",
  "./utils/submitted-result-controller": "createSubmittedResultController",
  "./utils/submit-success-controller": "createSubmitSuccessController",
  "./utils/submit-flow-controller": "createSubmitFlowController",
  "./utils/start-practice-controller": "createStartPracticeController",
  "./utils/image-warm-controller": "createImageWarmController",
  "./utils/submission-lock-controller": "createSubmissionLockController",
  "./utils/sequential-restart-controller": "createSequentialRestartController",
  "./utils/answer-interaction-controller": "createPracticeAnswerInteractionController",
  "./utils/question-display-controller": "createPracticeQuestionDisplayController",
  "./utils/computed-fields-controller": "createComputedFieldsController",
  "./utils/answer-feedback-controller": "createAnswerFeedbackController",
  "./utils/render-invariant-controller": "createRenderInvariantController",
  "./utils/question-timer-controller": "createQuestionTimerController",
  "./utils/question-load-controller": "createQuestionLoadController",
  "./utils/pending-submission-controller": "createPendingSubmissionController",
  "./utils/self-heal-controller": "createSelfHealController",
  "./utils/submit-error-controller": "createSubmitErrorController",
  "./utils/submit-entry-controller": "createSubmitEntryController"
}

function fixture(sourcePath = process.env.PRACTICE_PAGE_SOURCE) {
  const calls = [], instances = [], cache = new Map()
  let definition
  const api = { now: () => 1234, createTraceId: () => 'trace' }
  const config = { DEV: false, enableMathImage: false }
  const stubs = {
    './cold-resume-controller': {
      userId: () => '', persist() {}, restore: () => false, clear() {}, hasPending: () => false,
    },
    '../../../utils/api': api, '../../../config': config,
    '../../../utils/debug': { debugLog() {}, saveDebugSnapshot() {}, shouldDebugQuestion: () => false },
    '../utils/stem-render': { setRenderGuardPage: name => calls.push(['guard', name]), resetRenderGuard: () => calls.push(['resetGuard']) },
    '../utils/question-runner-adapter': {}, '../utils/question-image-cache': {},
  }
  const platform = new Proxy({}, { get: (object, key) => key in object ? object[key] : (...args) => { calls.push([key, ...args]); return undefined } })
  const context = vm.createContext({ Page: value => { definition = value }, wx: platform,
    console: { warn: (...args) => calls.push(['warn', ...args]), error: (...args) => calls.push(['error', ...args]), log: (...args) => calls.push(['log', ...args]) },
    Date: { now: () => 1000 }, Math, Promise, getCurrentPages: () => [],
    setTimeout: (fn, delay) => { calls.push(['timeout', fn, delay]); return 11 },
    clearTimeout: id => calls.push(['clearTimeout', id]), setInterval, clearInterval,
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }; cache.set(filename, module)
    const required = request => {
      if (Object.hasOwn(stubs, request)) return stubs[request]
      if (Object.hasOwn(FACTORIES, request)) return { [FACTORIES[request]]: options => {
        const instance = { type: FACTORIES[request], options }
        if (request === './utils/exit-guard-controller') {
          Object.assign(instance, load(path.join(root, 'utils/exit-guard-controller.js')).createExitGuardController(options))
        }
        instances.push(instance); return instance
      } }
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      if (!resolved.startsWith(path.resolve(root, '..') + path.sep)) throw Error('Unexpected dependency: ' + request)
      return load(resolved)
    }
    const input = filename === path.join(root, 'practice.js') && sourcePath ? sourcePath : filename
    vm.runInContext('(function(require,module,exports) {\n' + fs.readFileSync(input, 'utf8') + '\n})', context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'practice.js'))
  const page = Object.assign({}, definition, { data: JSON.parse(JSON.stringify(definition.data)),
    setData(patch, callback) { calls.push(['setData', patch]); Object.assign(this.data, patch); if (callback) callback() },
  })
  return { page, methods: definition, calls, instances, stubs, api, config, context, platform }
}

module.exports = { fixture, FACTORIES }
