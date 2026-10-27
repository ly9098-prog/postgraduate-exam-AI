const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { spawnSync } = require('node:child_process')
const { test } = require('node:test')
const { matchesPackIgnore } = require('./test-main-package-size')

const root = path.resolve(__dirname, '..')
const vendorDirectory = path.join(root, 'vendor/katex')
const studyDirectory = path.join(root, 'subpackages/study/components/mp-html/latex')
// Pin the six pre-migration study sources, independently of all current copies.
const hashes = {
  'katex-core.js': '50134c34a13f46f81bab5454ad80023bb715b47be5f3e04f729da6a082370260',
  'katex-part-150.js': 'e495d022bbe5df1215ac6fc5491fcf7edc4c9a10082a80115174a08bbb82afae',
  'katex-part-187.js': '84a3d48b59746958059825a32e8c98f976cae4db7fc96674ae696d6cb746ce2e',
  'katex-part-64.js': 'b3327bbef44cc957da1c5e0111875ed2026a7ddd5004bacc817fa7454f036d2b',
  'katex-part-970.js': '0fc19c5c62ed7461a277947d231f63b35c0b36f50ed012ef62667d6eccf25148',
  'katex.min.js': '772b81b166766d66dfa361fe3f277ba2dd8bd96f8481e9fad53d671c7a164248',
}

function checkVendorSource(name, source) {
  const actual = crypto.createHash('sha256').update(source).digest('hex')
  assert.equal(actual, hashes[name], name + ': original vendor bytes changed')
}

function checkForwarder(name, source) {
  const target = path.relative(studyDirectory, path.join(vendorDirectory, name)).split(path.sep).join('/')
  assert.equal(source, "module.exports = require('" + target + "')\n")
}

test('main vendor is byte-identical and all six study paths forward synchronously', () => {
  assert.deepEqual(fs.readdirSync(vendorDirectory).sort(), Object.keys(hashes).sort())
  // Load the public bootstrap first: requiring raw webpack chunks in filename
  // order can cache an undefined export before the dependent chunks are ready.
  const katex = require(path.join(studyDirectory, 'katex.min.js'))
  assert.equal(typeof katex.renderToString, 'function')
  assert.match(katex.renderToString('\\frac{1}{2}', { throwOnError: true }), /katex/)
  assert.equal(katex, require(path.join(vendorDirectory, 'katex.min.js')))
  for (const name of Object.keys(hashes)) {
    checkVendorSource(name, fs.readFileSync(path.join(vendorDirectory, name)))
    checkForwarder(name, fs.readFileSync(path.join(studyDirectory, name), 'utf8'))
    assert.equal(require(path.join(studyDirectory, name)), require(path.join(vendorDirectory, name)))
  }
})

test('boundary contracts reject drift, asynchronous wrappers, and foreign package targets', () => {
  assert.throws(() => checkVendorSource('katex.min.js', 'module.exports = {}'))
  assert.throws(() => checkForwarder('katex.min.js', "module.exports = import('/vendor/katex/katex.min.js')\n"))
  assert.throws(() => checkForwarder('katex.min.js', "module.exports = require('../../exam/katex.min.js')\n"))
})

test('study is ordinary and canonical runtime files are included in the main source package', () => {
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json')))
  const config = JSON.parse(fs.readFileSync(path.join(root, 'project.config.json')))
  assert.equal(app.subPackages.find(item => item.root === 'subpackages/study').independent, false)
  for (const name of Object.keys(hashes)) {
    const relative = 'vendor/katex/' + name
    assert.equal(app.subPackages.some(item => relative.startsWith(item.root + '/')), false)
    for (const rule of config.packOptions.ignore) {
      for (const target of ['vendor', 'vendor/katex', relative]) {
        assert.equal(matchesPackIgnore(target, rule), false, target + ' must be packaged')
      }
    }
  }
})

function runOrder(mode, order) {
  const runner = path.join(__dirname, 'support/katex-load-order.js')
  const result = spawnSync(process.execPath, [runner, root, mode, JSON.stringify(order)], {
    encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, timeout: 30000,
  })
  assert.equal(result.status, 0, result.stderr || String(result.error || 'runtime failure'))
  return JSON.parse(result.stdout)
}

const orders = [
  ['study', 'exam', 'formulas'], ['study', 'formulas', 'exam'],
  ['exam', 'study', 'formulas'], ['exam', 'formulas', 'study'],
  ['formulas', 'study', 'exam'], ['formulas', 'exam', 'study'],
]
for (const order of orders) {
  test('preserve each wrapper and markup before/after all loads: ' + order.join(', '), () => {
    assert.deepEqual(runOrder('current', order), runOrder('original', order))
  })
}
