/**
 * Prebuilt KaTeX must render directly, without enhanced compilation.
 * Each vendor copy is tested in a fresh process to isolate webpack's global cache.
 * Run: cd miniprogram && node tests/test-katex-vendor-runtime.js
 */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const vendors = [
  '../subpackages/study/components/mp-html/latex/katex.min',
  '../subpackages/exam/components/mp-html/latex/katex.min',
  '../subpackages/formulas/utils/katex/katex.min',
]
const cases = [
  'x^2+y^2=z^2',
  '\\frac{1}{2}+\\sqrt{x}',
  '\\int_0^1 x^2\\,dx',
  '\\sum_{i=1}^{n}i',
  '\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}',
  '\\begin{array}{cc}a&b\\\\c&d\\end{array}',
]
const run = `
try {
  const assert = require('node:assert/strict')
  const katex = require(process.argv[1])
  const cases = JSON.parse(process.argv[2])
  for (const tex of cases) {
    const html = katex.renderToString(tex, { throwOnError: true })
    assert.match(html, /katex/, 'formula must render without transpilation: ' + tex)
    assert.doesNotMatch(html, /katex-error/)
    const dom = katex.__renderToDomTree(tex, { throwOnError: true })
    assert.equal(dom.toMarkup(), html)
  }
} catch (error) {
  console.error(error.message)
  process.exit(1)
}
`
for (const vendor of vendors) {
  const result = spawnSync(process.execPath, ['-e', run, path.resolve(__dirname, vendor), JSON.stringify(cases)], { encoding: 'utf8' })
  assert.equal(result.status, 0, vendor + ': ' + (result.stderr || result.error || 'render failure'))
}
console.log('Raw KaTeX vendor regression checks passed: ' + vendors.length + ' isolated copies × ' + cases.length + ' formulas')
