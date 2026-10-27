const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const MINI = path.resolve(__dirname, '..')

function createClock() {
  const jobs = new Map()
  const operations = []
  let identity = 0
  let now = 1000
  return {
    jobs, operations,
    now: () => now,
    setTimeout(callback, delay) {
      const id = ++identity
      jobs.set(id, { callback, at: now + delay })
      operations.push(['set', id, delay])
      return id
    },
    clearTimeout(id) {
      jobs.delete(id)
      operations.push(['clear', id])
    },
    tick(duration) {
      const until = now + duration
      while (true) {
        const next = [...jobs].filter(([, job]) => job.at <= until)
          .sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        now = next[1].at
        jobs.delete(next[0])
        next[1].callback()
      }
      now = until
    },
  }
}

function createLoader(pkg, ports, clock) {
  const sourceRoot = process.env.QUIZ_RUNNER_COMPONENT_ROOT || MINI
  const directory = path.join(sourceRoot, `subpackages/${pkg}/components/quiz-runner`)
  const modules = new Map()
  const requests = []
  let definition
  const context = vm.createContext({
    Component(value) { definition = value },
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    Date: { now: clock.now },
    wx: { previewImage(value) { ports.previews.push(value) } },
  })
  function load(filename) {
    if (modules.has(filename)) return modules.get(filename).exports
    const module = { exports: {} }
    modules.set(filename, module)
    const baseline = process.env.QUIZ_RUNNER_BASELINE
    const source = baseline && path.basename(filename) === 'quiz-runner.js'
      ? fs.readFileSync(path.join(baseline, pkg + '.js'), 'utf8')
      : fs.readFileSync(filename, 'utf8')
    const localRequire = request => {
      requests.push(request)
      if (request === '../../utils/question-runner-adapter') return ports.adapter()
      if (request === '../../utils/code-block-render') return ports.code
      const resolved = path.resolve(path.dirname(filename), request + '.js')
      if (!resolved.startsWith(directory + path.sep)) throw new Error('package escape')
      return load(resolved)
    }
    vm.runInContext('(function(require,module,exports){' + source + '\n})',
      context, { filename })(localRequire, module, module.exports)
    return module.exports
  }
  load(path.join(directory, 'quiz-runner.js'))
  return { definition, requests }
}

function runner(pkg, options = {}) {
  const clock = createClock()
  const previews = []
  const ports = {
    previews,
    adapter: options.adapter || (() => ({})),
    code: options.code || {
      splitCodeLines(text) { return [{ no: 1, text }] },
    },
  }
  const { definition, requests } = createLoader(pkg, ports, clock)
  const data = Object.assign({}, definition.data)
  for (const [key, value] of Object.entries(definition.properties)) data[key] = value.value
  Object.assign(data, { totalCount: 4, currentIndex: 0 }, options.data)
  const writes = [], callbacks = [], events = []
  const target = Object.assign({
    data,
    setData(patch, callback) {
      writes.push({ patch, snapshot: JSON.parse(JSON.stringify(patch)) })
      Object.assign(data, patch)
      if (callback) {
        if (options.deferCommit) callbacks.push(callback)
        else callback()
      }
    },
    triggerEvent(name, detail) { events.push({ name, detail }) },
  }, definition.methods)
  definition.created.call(target)
  return {
    target, definition, requests, clock, writes, callbacks, events, previews,
    observe(q, answer) {
      data.currentQuestion = q
      return definition.observers['currentQuestion, answerState'].call(target, q, answer)
    },
    detach() { definition.lifetimes.detached.call(target) },
  }
}

function question(id = 1, mode = 'RICH_TEXT') {
  return { id, question_type: 'single_choice', _renderModel: { mode } }
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

module.exports = { runner, question, plain }
