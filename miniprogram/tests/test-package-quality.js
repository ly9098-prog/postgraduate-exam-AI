/**
 * Packaging-rule and prebuilt-vendor regression checks.
 * Run: cd miniprogram && node tests/test-package-quality.js
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { matchesPackIgnore, collectPackageSizes, checkBudgets } = require('./test-main-package-size')

assert.equal(matchesPackIgnore('tests/a.js', { type: 'folder', value: 'tests' }), true)
assert.equal(matchesPackIgnore('tests-extra/a.js', { type: 'folder', value: 'tests' }), false)
assert.equal(matchesPackIgnore('a.test.js', { type: 'glob', value: '**/*.test.js' }), true)
assert.equal(matchesPackIgnore('nested/a.test.js', { type: 'glob', value: '**/*.test.js' }), true)
assert.equal(matchesPackIgnore('nested/a.js', { type: 'glob', value: '**/*.test.js' }), false)
assert.equal(matchesPackIgnore('assets/a.png', { type: 'glob', value: 'assets/*.png' }), true)
assert.equal(matchesPackIgnore('assets/nested/a.png', { type: 'glob', value: 'assets/*.png' }), false)
assert.equal(matchesPackIgnore('notes.md', { type: 'suffix', value: '.md' }), true)
assert.equal(matchesPackIgnore('assets/a.png', { type: 'file', value: 'assets/a.png' }), true)
assert.equal(matchesPackIgnore('assets/b.png', { type: 'file', value: 'assets/a.png' }), false)
assert.throws(() => matchesPackIgnore('x', { type: 'unknown', value: 'x' }), /Unsupported/)

const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'miniprogram-package-quality-'))
try {
  function write(name, bytes) {
    const file = path.join(fixture, name)
    fs.mkdirSync(path.dirname(file), { recursive: true })
    fs.writeFileSync(file, Buffer.alloc(bytes))
  }
  write('app.js', 10)
  write('assets/a.png', 80 * 1024)
  write('subpackages/study/b.png', 120 * 1024)
  write('tests/ignored.png', 300 * 1024)
  write('subpackages/study/unused.png', 300 * 1024)
  const appConfig = { subPackages: [{ root: 'subpackages/study' }] }
  const projectConfig = { packOptions: { ignore: [
    { type: 'folder', value: 'tests' },
    { type: 'glob', value: 'subpackages/study/unused.png' },
  ] } }
  const summary = collectPackageSizes(fixture, appConfig, projectConfig)
  assert.equal(summary.packages.__APP__.bytes, 10 + 80 * 1024)
  assert.equal(summary.packages['subpackages/study'].bytes, 120 * 1024)
  assert.equal(summary.mediaBytes, 200 * 1024, 'media must be summed across packages')
  assert.equal(summary.media.length, 2, 'explicitly excluded media must not be counted')
  assert.throws(() => checkBudgets(summary), /Aggregate media budget exceeded/)
  assert.throws(() => checkBudgets({ packages: { __APP__: { bytes: 2 * 1024 * 1024 } }, media: [], mediaBytes: 0 }), /Source package budget/)
  assert.throws(() => checkBudgets({ packages: { 'subpackages/study': { bytes: 1.3 * 1024 * 1024 } }, media: [], mediaBytes: 0 }), /Source package budget/)
  assert.throws(() => collectPackageSizes(fixture, appConfig, { packOptions: { include: [{ type: 'file', value: 'app.js' }] } }), /include rules/)
} finally {
  // Only delete the temporary fixture created by this test.
  fs.rmSync(fixture, { recursive: true })
}

const miniRoot = path.resolve(__dirname, '..')
const readJson = name => JSON.parse(fs.readFileSync(path.join(miniRoot, name), 'utf8'))
const config = readJson('project.config.json')
const vendorPrefix = 'vendor/katex/'
const expected = [
  'katex-core.js', 'katex-part-150.js', 'katex-part-187.js',
  'katex-part-64.js', 'katex-part-970.js', 'katex.min.js',
].map(name => vendorPrefix + name)
assert.deepEqual([...config.setting.babelSetting.ignore].sort(), [...expected].sort(),
  'enhanced-compilation exclusions must stay limited to the six prebuilt KaTeX files')
assert.equal(config.setting.es6, true, 'business code still needs ES6 compilation')
assert.equal(config.setting.enhance, true, 'business code still needs enhanced compilation')
assert.equal(config.setting.minified, true)
assert.equal(config.setting.ignoreCodeQuality, undefined, 'quality checks must not be bypassed')
for (const file of expected) assert.ok(fs.existsSync(path.join(miniRoot, file)))
// Skipping Babel is safe only when the vendor also satisfies upload grammar.
require('./test-katex-upload-syntax')
const app = readJson('app.json')
assert.equal(app.usingComponents['app-dialog'], '/components/app-dialog/index')
assert.equal(app.usingComponents['premium-nav'], '/components/premium-nav/premium-nav')
checkBudgets(collectPackageSizes(miniRoot, app, config))
console.log('Package quality regression checks passed')
