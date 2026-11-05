/**
 * Prebuilt KaTeX must parse before upload without relying on DevTools Babel.
 * The ES2015 grammar is intentionally conservative: a modern Node runtime
 * accepts optional chaining/nullish coalescing that upload validation rejects.
 * Run: cd miniprogram && npm ci && node tests/test-katex-upload-syntax.js
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const acorn = require('acorn')
const miniRoot = path.resolve(__dirname, '..')
const directories = [
  'subpackages/study/components/mp-html/latex',
  'subpackages/exam/components/mp-html/latex',
  'subpackages/formulas/utils/katex',
]
const files = [
  'katex-core.js', 'katex-part-150.js', 'katex-part-187.js',
  'katex-part-64.js', 'katex-part-970.js', 'katex.min.js',
]
function parseUploadScript(source) {
  return acorn.parse(source, { ecmaVersion: 2015, sourceType: 'script' })
}
// Prove the guard distinguishes upload grammar from current Node syntax,
// and checks code rather than rejecting harmless operators inside strings.
assert.throws(() => parseUploadScript('var value = node?.type'), SyntaxError)
assert.throws(() => parseUploadScript('var value = node ?? 0'), SyntaxError)
assert.doesNotThrow(() => parseUploadScript('var value = "?. ??"'))
assert.doesNotThrow(() => parseUploadScript('var value = node == null ? 0 : node.type'))
for (const file of files) {
  const reference = fs.readFileSync(path.join(miniRoot, directories[0], file), 'utf8')
  for (const directory of directories) {
    const relative = directory + '/' + file
    const source = fs.readFileSync(path.join(miniRoot, relative), 'utf8')
    assert.doesNotThrow(() => parseUploadScript(source), relative + ': incompatible upload syntax')
    assert.equal(source, reference, relative + ': vendor copies must stay identical')
  }
}
console.log('KaTeX upload syntax checks passed: ' + directories.length + ' copies (ES2015)')
