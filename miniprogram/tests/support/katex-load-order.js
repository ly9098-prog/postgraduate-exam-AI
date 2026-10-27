const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')

const directories = {
  study: 'subpackages/study/components/mp-html/latex',
  exam: 'subpackages/exam/components/mp-html/latex',
  formulas: 'subpackages/formulas/utils/katex',
}
const formulas = [
  'x^2+y^2=z^2', '\\frac{1}{2}+\\sqrt{x}', '\\int_0^1 x^2\\,dx',
  '\\sum_{i=1}^{n}i', '\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}',
  '\\hat{x}+\\widehat{xyz}+\\overrightarrow{AB}',
  '\\underbrace{x+y}_{z}+\\overset{a}{b}',
  '\\sqrt[3]{x}+\\left(\\frac{x}{y}\\right)',
  '\\begin{aligned}a&=b\\\\c&=d\\end{aligned}',
  '\\begin{array}{c|c}a&b\\\\c&d\\end{array}',
  '\\notACommand{', '\\text{中文}+x',
]

// Recreate the old study modules at their original filenames in a fresh process.
// Exam retains byte-identical vendor sources; its wrapper is never substituted.
function installOriginalStudy(root) {
  const original = Module._extensions['.js']
  const study = path.join(root, directories.study)
  Module._extensions['.js'] = function (module, filename) {
    if (path.dirname(filename) === study && /^katex(?:-.*|\.min)\.js$/.test(path.basename(filename))) {
      const source = fs.readFileSync(path.join(root, directories.exam, path.basename(filename)), 'utf8')
      module._compile(source, filename)
    } else original(module, filename)
  }
}

function renderNodes(root, kind) {
  const Latex = require(path.join(root, directories[kind], 'index.js'))
  const plugin = new Latex()
  return formulas.flatMap(tex => ['', 'natural'].map(mathLayout => {
    const node = { type: 'text', text: 'before $' + tex + '$ after $$' + tex + '$$' }
    plugin.onParse(node, { options: { editable: false }, properties: { mathLayout } })
    return node
  }))
}

function capture(root, kind, vendor) {
  const result = { markup: formulas.map(tex => vendor.renderToString(tex, { throwOnError: false })) }
  if (kind !== 'formulas') result.nodes = renderNodes(root, kind)
  return result
}

function run() {
  const [root, mode, serializedOrder] = process.argv.slice(2)
  if (mode === 'original') installOriginalStudy(root)
  global.wx = {
    getWindowInfo: () => ({ windowWidth: 375, pixelRatio: 2 }),
    getDeviceInfo: () => ({ system: 'Node contract test' }),
    canIUse: () => true,
  }
  const vendors = {}, output = {}
  for (const kind of JSON.parse(serializedOrder)) {
    vendors[kind] = require(path.join(root, directories[kind], 'katex.min.js'))
    output[kind] = capture(root, kind, vendors[kind])
  }
  for (const kind of Object.keys(vendors)) output[kind + 'AfterAll'] = capture(root, kind, vendors[kind])
  process.stdout.write(JSON.stringify(output))
}

if (require.main === module) run()
