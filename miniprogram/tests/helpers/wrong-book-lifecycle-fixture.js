const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { deferred } = require('./wrong-book-request-fixture')
const root = path.resolve(__dirname, '../../subpackages/study/wrong-book')

function fixture() {
  let definition
  const calls = [], cache = new Map(), config = {}, exportApi = {}, globalData = {}
  const stubs = {
    '../../../utils/api': {}, '../../../config': config, '../../../utils/storage': {},
    '../utils/route-params': {
      safeDecodeURIComponent(value, fallback) { calls.push(['decode', value, fallback]); return value || fallback },
    },
    '../utils/stem-render': {}, '../utils/ai-diagnosis-cache': {}, '../utils/error-diagnosis': {},
    '../utils/subject-meta': {}, '../utils/export-capability': exportApi,
    '../../../components/question-filter-panel/date-range': {}, '../../../utils/china-time': {},
  }
  const app = { getGlobalData() { calls.push(['globalData', this === app]); return globalData } }
  const context = vm.createContext({
    Page: value => { definition = value },
    console: { warn: (...args) => calls.push(['warn', ...args]) },
    Date: { now: () => 12345 }, setTimeout,
    clearTimeout: id => calls.push(['clearTimer', id]),
    getApp() { calls.push(['app']); return app },
    wx: {
      setStorageSync(...args) { calls.push(['store', ...args]) },
      navigateTo(options) { calls.push(['navigate', options]) },
      navigateBack(options) { calls.push(['back', options]) },
      reLaunch(options) { calls.push(['relaunch', options]) },
      showToast(options) { calls.push(['toast', options]) },
    },
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const required = request => {
      if (Object.hasOwn(stubs, request)) return stubs[request]
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      if (!resolved.startsWith(root + path.sep)) throw Error('Unexpected dependency: ' + request)
      return load(resolved)
    }
    const sourcePath = filename === path.join(root, 'wrong-book.js') && process.env.WRONG_BOOK_LIFECYCLE_SOURCE
      ? process.env.WRONG_BOOK_LIFECYCLE_SOURCE : filename
    vm.runInContext(`(function(require,module,exports) {\n${fs.readFileSync(sourcePath, 'utf8')}\n})`,
      context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'wrong-book.js'))
  const page = Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)),
    setData(patch) { calls.push(['setData', patch]); Object.assign(this.data, patch) },
  })
  for (const name of ['_syncDateFilter', '_updateFilterCount', '_checkExportCapability',
    '_restoreAiAutoSetting', '_restoreAiDiagnosisFromCache', '_showBatchCapsuleAndRefreshTimer',
    '_clearBatchCapsuleIdleTimer', '_clearBatchMasterUndo', 'loadSubjects',
    '_loadPage', '_checkAiDiagnosis', 'loadStats', 'loadList']) {
    page[name] = function (...args) { calls.push([name, ...args]); return Promise.resolve(name) }
  }
  return { page, methods: definition, calls, context, config, exportApi, app, globalData, stubs }
}

const flush = () => new Promise(setImmediate)
module.exports = { fixture, deferred, flush }
