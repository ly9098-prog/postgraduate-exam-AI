const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const { createRequire } = require('node:module')

const packageName = process.env.STEM_RENDER_PACKAGE || 'exam'
assert.ok(['study', 'exam'].includes(packageName), 'unknown renderer package')
const filename = path.resolve(__dirname, `../subpackages/${packageName}/utils/stem-render.js`)
const nativeRequire = createRequire(filename)
const exportedNames = [
  'RENDER_MODE', 'buildRenderModel', 'resetRenderGuard', 'setRenderGuardPage',
  'buildOptionList', 'optionTextToHtml', 'toPlainInlineMathText', 'needsRichRender',
  'stripLeadingOptionLabel', 'computeCodeHash', 'renderDiff', 'cleanStemText',
  'textToHtml', 'normalizeLatexDelimiters', 'hasLatexDelimiters', 'buildRichTextNodes',
  'segmentsToText', 'textToSegments',
  'splitStemBlocks', 'splitInlineTextAndCode', 'resolveAssetUrl',
]

function loadRenderer({ source, config, code, table, image, freeze } = {}) {
  const sourcePath = process.env.STEM_RENDER_SOURCE || process.env.EXAM_STEM_SOURCE
  if (source === undefined && sourcePath) {
    source = fs.readFileSync(sourcePath, 'utf8')
  }
  const events = []
  const imports = []
  const appConfig = config || { DEV: false, BASE_URL: 'https://fixture.invalid/api/v1' }
  const modules = new Map()
  const context = vm.createContext({
    console: Object.fromEntries(['warn', 'error', 'log'].map(name => [
      name, (...args) => events.push([name, ...args]),
    ])),
  })
  vm.runInContext('Date.now = function () { return 1700000000000 }', context)
  if (freeze) {
    context.freezePort = freeze
    vm.runInContext('Object.freeze = freezePort', context)
  }
  function load(file) {
    if (modules.has(file)) return modules.get(file).exports
    const module = { exports: {} }
    modules.set(file, module)
    const localRequire = createRequire(file)
    function dependency(request) {
      imports.push(request)
      if (request === '../../../config') return appConfig
      if (request === './code-reconstructor' && code) return code
      if (request === './table-structure' && table) return table
      if (request === './question-image-cache') return image || { resolve: value => value }
      const target = localRequire.resolve(request)
      if (path.dirname(target) === path.dirname(filename) &&
          path.basename(target).startsWith('stem-render')) return load(target)
      return localRequire(request)
    }
    const overrideDirectory = process.env.STEM_RENDER_OVERRIDE_DIR
    const sourceFile = overrideDirectory ? path.join(overrideDirectory, path.basename(file)) : file
    const text = file === filename && source !== undefined ? source : fs.readFileSync(sourceFile, 'utf8')
    const factory = vm.runInContext(`(function(require,module,exports) {\n${text}\n})`,
      context, { filename: file })
    factory(dependency, module, module.exports)
    return module.exports
  }
  return { renderer: load(filename), events, context, config: appConfig, imports }
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

function codePorts(overrides = {}) {
  return {
    containsCode: () => false,
    shouldReconstructCode: () => false,
    reconstructCode: value => value,
    sanitizeImportedCodeArtifacts: value => value,
    ...overrides,
  }
}

function renderFixtures() {
  const directory = path.join(__dirname, 'render_regression')
  const historical = fs.readdirSync(directory).filter(file => file.endsWith('.json'))
    .sort().map(file => JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8')).question)
  return historical.concat([
    null, { content: {} }, { content: 'plain' }, { content: { text: '$$x^2$$' } },
    { content: { text: 'int f() {\n  return 1;\n}' } },
    { content: { text: 'Explain.\n\nint f() {\n  return 1;\n}' } },
    { content: { text: '1~\n2', render_mode: 'segments',
      segments: [{ type: 'text', text: '1~' }, { type: 'newline' },
        { type: 'text', text: '2' }] } },
    { content: { text: 'caption', render_mode: 'segments',
      segments: [{ type: 'image', url: '/image.png' }] } },
    { content: { text: 'current', render_mode: 'segments',
      segments: [{ type: 'text', text: 'stale' }] } },
    { content: { render_mode: 'segments',
      segments: [{ type: 'code', code: 'int x = 1;' }] } },
    { content: { render_mode: 'segments',
      segments: [{ type: 'table', headers: ['A'], rows: [['1']] }] } },
  ])
}

function assertRenderParity(study, exam) {
  assert.deepEqual(Object.keys(exam), Object.keys(study))
  assert.deepEqual(exam.RENDER_MODE, study.RENDER_MODE)
  for (const name of exportedNames.slice(1)) {
    assert.equal(typeof exam[name], 'function', name)
    assert.equal(exam[name].length, study[name].length, name)
    assert.equal(exam[name].name, study[name].name, name)
  }
  const now = Date.now
  Date.now = () => 1700000000000
  try {
    for (const q of renderFixtures()) {
      for (const cfg of [{}, { enableMathImage: true }, { SAFE_MODE: true, DEV: true }]) {
        const options = q && q.options
        const actual = exam.buildRenderModel(q, options, cfg)
        const expected = study.buildRenderModel(q, options, cfg)
        assert.deepEqual(actual, expected)
        assert.equal(Object.isFrozen(actual), Object.isFrozen(expected))
      }
    }
    assertHelperParity(study, exam)
    assertGuardParity(study, exam)
  } finally { Date.now = now }
}

function assertHelperParity(study, exam) {
  const cases = [
    ['buildOptionList', [{ A: 'A. $x$', B: { segments: [{ type: 'text', text: 'B' }] } },
      ['A', 'B'], { A: true }]],
    ['buildOptionList', [{ A: { segments: [
      { type: 'image', url: '/render-parity-option.png', metadata: { stable: true } },
      { type: 'image', url: 'https://fixture.invalid/render-parity-option.png' },
    ] } }, ['A'], {}]],
    ['optionTextToHtml', ['A', '$x$']], ['toPlainInlineMathText', ['$x^2$']],
    ['needsRichRender', ['a\nb']], ['stripLeadingOptionLabel', ['A', 'A. answer']],
    ['computeCodeHash', ['a\nb']], ['renderDiff', [' a\nb', 'a\nc']],
    ['cleanStemText', ['stem\nA. one\nB. two', { A: 'one', B: 'two' }, ['A', 'B']]],
    ['textToHtml', ['<a>\n$x$']], ['buildRichTextNodes', ['a\nb']],
    ['normalizeLatexDelimiters', ['\\(x^2\\)$y$']],
    ['hasLatexDelimiters', ['\\(x\\) and \\[y\\]']],
    ['segmentsToText', [[{ type: 'text', text: 'a' }, { type: 'newline' }]]],
    ['textToSegments', ['a\nb']], ['splitStemBlocks', ['Explain.\n\nint x = 1;']],
    ['splitInlineTextAndCode', ['Explain. int x = 1;']], ['resolveAssetUrl', [null]],
    ['resolveAssetUrl', ['/render-parity.png']],
    ['resolveAssetUrl', ['https://fixture.invalid/render-parity.png']],
    ['resolveAssetUrl', ['images/render-parity.png']],
  ]
  for (const [name, args] of cases) assert.deepEqual(exam[name](...args), study[name](...args), name)
}

function guardEvents(renderer) {
  const events = []
  const originalError = console.error
  console.error = (...args) => {
    if (String(args[0]).includes('Same stem')) events.push(args)
  }
  try {
    const q = { id: 719403, content: { text: 'parity guard', render_mode: 'segments' } }
    renderer.resetRenderGuard()
    renderer.setRenderGuardPage('parity:first')
    renderer.buildRenderModel(q, null, { enableMathImage: false })
    renderer.setRenderGuardPage('parity:second')
    renderer.buildRenderModel(q, null, { enableMathImage: true })
    renderer.setRenderGuardPage('parity:third')
    renderer.buildRenderModel(q, null, { enableMathImage: true })
    const beforeReset = events.slice()
    events.length = 0
    renderer.resetRenderGuard()
    renderer.buildRenderModel(q, null, { enableMathImage: true })
    return { beforeReset, afterReset: events.slice() }
  } finally {
    console.error = originalError
  }
}

function assertGuardParity(study, exam) {
  const config = require('../config')
  const originalDev = config.DEV
  config.DEV = true
  try {
    const expected = guardEvents(study)
    assert.equal(expected.beforeReset.length, 2, 'study guard emits the conflicts')
    assert.ok(expected.beforeReset[0][0].includes('page: parity:second'))
    assert.ok(expected.beforeReset[1][0].includes('page: parity:third'))
    assert.deepEqual(expected.afterReset, [])
    assert.deepEqual(guardEvents(exam), expected, 'render guard state parity')
  } finally {
    study.resetRenderGuard()
    exam.resetRenderGuard()
    config.DEV = originalDev
  }
}

module.exports = {
  loadRenderer, exportedNames, plain, codePorts, nativeRequire, filename, assertRenderParity,
}
