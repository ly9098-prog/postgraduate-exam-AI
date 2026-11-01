const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../subpackages/study/wrong-detail')

function fixture(options = {}) {
  let definition
  const calls = [], cache = new Map(), sleeps = []
  const api = {
    get: async (...args) => { calls.push(['get', ...args]); return null },
  }
  const context = vm.createContext({
    Page: value => { definition = value },
    Date, console, setTimeout: (fn, ms) => { sleeps.push(ms); fn(); return sleeps.length },
    clearTimeout,
    wx: { showToast: (...args) => calls.push(['toast', ...args]) },
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const required = request => {
      if (request === '../../../utils/api') return api
      if (request === '../../../config') return options.config || {}
      if (request === '../utils/ai-analysis-normalizer') return {
        normalizeAiAnalysisPayload: value => value,
        hasAiAnalysisContent: value => !!(value && value.content),
      }
      if (request === '../utils/ai-math-render') return { buildAiRichText: value => value }
      if (request === '../utils/error-diagnosis') return options.diagnosis || { TAXONOMY: [] }
      if (request === '../utils/ai-teacher-408') return options.teacher || {}
      if (request === './teacher-presentation') return { presentTeacherResult: value => value }
      if (request === './utils/teacher-action-controller') return {
        createTeacherActionController: () => ({}),
      }
      if (request === '../utils/subject-meta') return { getSubjectName: value => value }
      if (request === '../utils/answer') return { isTrueFalseType: () => false }
      if (request === '../utils/question-runner-adapter') return ({})
      if (request === '../utils/stem-render') return options.renderGuard || {
        buildRenderModel: () => ({}), resetRenderGuard: () => {}, setRenderGuardPage: () => {},
      }
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      return resolved.startsWith(root + path.sep) ? load(resolved) : require(resolved)
    }
    let source = fs.readFileSync(
      filename === path.join(root, 'wrong-detail.js') && process.env.WRONG_DETAIL_AI_RECOVERY_SOURCE
        ? process.env.WRONG_DETAIL_AI_RECOVERY_SOURCE : filename, 'utf8')
    if (options.exposeDetailHelpers && filename === path.join(root, 'wrong-detail.js')) source +=
      '\nglobalThis.replaceDetailRenderer = value => { _processWqData = value }\n' +
      'globalThis.replacePreferredAnalysis = value => { _resolvePreferredAnalysis = value }\n'
    vm.runInContext(`(function(require,module,exports) {\n${source}\n})`,
      context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'wrong-detail.js'))
  const page = Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)),
    _alive: true, _aiRequestId: 7, _aiGenerationMarker: '',
    _wqCache: {},
    setData(patch) { calls.push(['setData', patch]); Object.assign(this.data, patch) },
    _resetAiLoadingState() {
      calls.push(['reset'])
      this.setData({ aiLoading: false, aiRegenerating: false, aiSkeletonVisible: false, aiInlineNotice: '' })
    },
    _syncWqCacheAi(id, normalized, generatedAt) {
      calls.push(['syncCache', id, normalized, generatedAt])
    },
    _refreshAiAvailability() {},
  })
  page.data.wq = { id: 12, marker: 'initial' }
  // Existing contract tests exercise an already-verified AI model. Availability
  // tests explicitly switch this flag off to verify the disabled path.
  page.data.aiAvailabilityEnabled = true
  page.data.aiAvailabilityStatus = 'available'
  return { page, methods: page, definition, context, api, calls, sleeps }
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

module.exports = { fixture, deferred }
