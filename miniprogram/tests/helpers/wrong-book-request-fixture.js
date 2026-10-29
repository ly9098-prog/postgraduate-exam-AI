const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../subpackages/study/wrong-book')

function fixture() {
  let definition
  const calls = [], cache = new Map()
  const api = {
    get(...args) { calls.push(['get', ...args]); return Promise.resolve({}) },
    getErrorMessage(error) { calls.push(['format', error]); return 'formatted' },
  }
  const stubs = {
    '../../../utils/api': api, '../../../config': {}, '../../../utils/storage': {},
    '../utils/route-params': { safeDecodeURIComponent: value => value },
    '../utils/stem-render': { toPlainInlineMathText: value => value },
    '../utils/ai-diagnosis-cache': {}, '../utils/error-diagnosis': {},
    '../utils/subject-meta': { getSubjectName: value => value, getSubjectShortName: value => value },
    '../utils/export-capability': {}, '../../../components/question-filter-panel/date-range': {},
    '../../../utils/china-time': {},
  }
  const context = vm.createContext({
    Page: value => { definition = value },
    console: {
      error: (...args) => calls.push(['error', ...args]),
      warn: (...args) => calls.push(['warn', ...args]),
    },
    Date, setTimeout, clearTimeout, wx: {},
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const required = request => {
      if (Object.hasOwn(stubs, request)) return stubs[request]
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      if (!resolved.startsWith(root + path.sep)) throw new Error('Unexpected dependency: ' + request)
      return load(resolved)
    }
    const sourcePath = filename === path.join(root, 'wrong-book.js') && process.env.WRONG_BOOK_REQUEST_SOURCE
      ? process.env.WRONG_BOOK_REQUEST_SOURCE : filename
    const source = fs.readFileSync(sourcePath, 'utf8')
    vm.runInContext(`(function(require,module,exports) {\n${source}\n})`, context, { filename })(
      required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'wrong-book.js'))
  const page = Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)),
    _alive: true, _destroyed: false,
    _statsRequestSeq: 0, _listRequestSeq: 0, _taskFlowRequestSeq: 0, _subjectsRequestSeq: 0,
    setData(patch) { calls.push(['setData', patch]); Object.assign(this.data, patch) },
    _syncDateFilter() { calls.push(['syncDate']) },
    _decorateItem(item) { calls.push(['decorate', item]); return { ...item, decorated: true } },
    _buildAnalysis(stats, list) { calls.push(['analysis', stats, list]); return { stats, list } },
    _buildTaskGroups(list) { calls.push(['groups', list]); return { groups: [{ key: 'fallback', items: list }], ungroupedCount: 2 } },
    _syncSelectionState() { calls.push(['selection']) },
    loadTaskFlow() { calls.push(['taskFlow']); return new Promise(() => {}) },
  })
  page.data.page = 3
  return { page, methods: definition, api, context, calls }
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

module.exports = { fixture, deferred }
