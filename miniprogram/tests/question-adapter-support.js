const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')

const signatures = {
  normalizeBlankAnswer: 2, normalizeBlankOptionList: 1, getQuestionOptions: 1,
  getBlankOptionGroups: 1, enrichBlankOptionGroups: 2, enrichBlankOptionGroupsReadonly: 3,
  serializeBlankAnswer: 2, isMultiBlankChoice: 1, isMultiBlankMultipleChoice: 1,
  isQuestionAnswered: 3, buildAnsweredFlags: 3, countAnswered: 1, applyAnsweredFlags: 3,
  computeAnsweredCount: 3, buildOptionListFromFlags: 3, buildOptionList: 4,
  buildOptionListReadonly: 5, getCorrectAnswer: 1, isAnswerCorrect: 2,
  getQuestionImages: 1, getEmbeddedImageUrls: 1, computeExtraImages: 1,
  getQuestionPrefetchUrls: 1,
}

function loadAdapter(pkg, options = {}) {
  const directory = path.resolve(__dirname, `../subpackages/${pkg}/utils`)
  const entry = path.join(directory, 'question-runner-adapter.js')
  const nativeRequire = createRequire(entry)
  const stem = options.stem || nativeRequire('./stem-render')
  const answer = options.answer || nativeRequire('./answer')
  const modules = new Map(), imports = []
  const context = vm.createContext({})
  function load(filename) {
    if (modules.has(filename)) return modules.get(filename).exports
    const module = { exports: {} }
    modules.set(filename, module)
    const baseline = process.env.QUESTION_ADAPTER_BASELINE
    const override = process.env.QUESTION_ADAPTER_OVERRIDE_DIR
    const sourceFile = filename === entry && baseline ? path.join(baseline, pkg + '.js')
      : override ? path.join(override, path.basename(filename)) : filename
    const source = fs.readFileSync(sourceFile, 'utf8')
    function requireLocal(request) {
      imports.push(request)
      if (request === './stem-render') return stem
      if (request === './answer') return answer
      const target = path.resolve(path.dirname(filename), request + '.js')
      if (path.dirname(target) !== directory ||
          (target !== entry && !/^question-adapter-.*\.js$/.test(path.basename(target)))) {
        throw new Error('unexpected adapter dependency: ' + request)
      }
      return load(target)
    }
    const factory = vm.runInContext('(function(require,module,exports){\n' + source + '\n})',
      context, { filename })
    factory(requireLocal, module, module.exports)
    return module.exports
  }
  return { adapter: load(entry), stem, answer, context, imports }
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

module.exports = { loadAdapter, plain, signatures }
