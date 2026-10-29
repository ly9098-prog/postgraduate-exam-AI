const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../subpackages/study/wrong-detail')
const plain = value => JSON.parse(JSON.stringify(value))

function fixture() {
  let definition
  const calls = [], callbacks = [], cache = new Map()
  const api = { get: async url => { calls.push(['get', url]); return { id: 2 } } }
  const diagnosis = {
    normalizeDiagnosis: raw => { calls.push(['normalize', raw]); return raw || null },
    buildNextAction: (wq, raw) => { calls.push(['next', wq, raw]); return { type: 'review' } },
    TAXONOMY: [],
  }
  const context = vm.createContext({
    Page: value => { definition = value }, Date: { now: () => 1000 },
    console: { error: (...args) => calls.push(['error', ...args]) },
    setTimeout: () => 1, clearTimeout: id => calls.push(['clearTimeout', id]),
    wx: { showToast: value => calls.push(['toast', value]),
      setStorageSync: (...args) => calls.push(['storage', ...args]) },
  })
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports
    const module = { exports: {} }
    cache.set(filename, module)
    const required = request => {
      if (request === '../../../utils/api') return api
      if (request === '../../../config') return { DEV: false }
      if (request === '../utils/error-diagnosis') return diagnosis
      if (request === '../utils/stem-render') return {
        buildRenderModel: () => { calls.push(['render']); return { mode: 'PLAIN' } },
      }
      const resolved = require.resolve(path.resolve(path.dirname(filename), request))
      return resolved.startsWith(root + path.sep) ? load(resolved) : require(resolved)
    }
    let source = fs.readFileSync(filename, 'utf8')
    if (filename === path.join(root, 'wrong-detail.js')) source +=
      '\nglobalThis.replaceNavigationRenderer = value => { _processWqData = value }\n'
    vm.runInContext(`(function(require,module,exports) {\n${source}\n})`,
      context, { filename })(required, module, module.exports)
    return module.exports
  }
  load(path.join(root, 'wrong-detail.js'))
  const page = Object.assign({}, definition, {
    data: plain(definition.data), _alive: true, _navigationSeq: 3, _wqCache: {},
    setData(patch, callback) {
      calls.push(['patch', plain(patch)]); Object.assign(this.data, patch)
      if (callback) callbacks.push(callback)
    },
  })
  Object.assign(page.data, { questionIds: [1, 2], currentIdx: 0, totalQuestions: 2 })
  return { page, calls, callbacks, api, context, diagnosis }
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

module.exports = { fixture, deferred, plain }
