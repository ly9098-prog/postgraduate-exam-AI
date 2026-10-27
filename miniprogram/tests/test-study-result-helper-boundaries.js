const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { test } = require('node:test')
const { inspectSource } = require('../scripts/architecture/learning-controller-budgets')

const ROOT = path.resolve(__dirname, '..')
const ts = createRequire(path.resolve(ROOT, '../admin-frontend/package.json'))('typescript')
const FILES = [
  'subpackages/study/utils/ai-teacher-408.js',
  'subpackages/exam/utils/ai-teacher-408.js',
  'subpackages/study/practice-result/utils/trend-plot-builder.js',
]

function inspect(source, filename) {
  const info = inspectSource(source, filename)
  assert.deepEqual(info.errors, [])
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function walk(node) {
    assert.ok(!ts.isImportDeclaration(node) && !ts.isImportEqualsDeclaration(node), 'import')
    assert.ok(!ts.isExportDeclaration(node), 'export dependency')
    if (ts.isCallExpression(node)) {
      assert.ok(node.expression.kind !== ts.SyntaxKind.ImportKeyword, 'dynamic import')
      assert.ok(!ts.isIdentifier(node.expression) || node.expression.text !== 'require', 'require')
    }
    ts.forEachChild(node, walk)
  }
  walk(tree)
  return info
}

for (const filename of FILES) {
  test(`${filename}: 300/50, JavaScript syntax and no runtime dependency`, () => {
    const info = inspect(fs.readFileSync(path.join(ROOT, filename), 'utf8'), filename)
    assert.ok(info.functions.length >= (filename.includes('ai-teacher') ? 20 : 5))
  })
}

for (const source of [
  '\n'.repeat(300) + 'function small() {}',
  'function outer() { function inner() {\n' + 'void 0\n'.repeat(51) + '} }',
  'const oversized = () => {\n' + 'void 0\n'.repeat(51) + '}',
  'const view = { get value() {\n' + 'void 0\n'.repeat(51) + '} }',
  'function typed(value: number) { return value }',
  "require('../../exam/utils/ai-teacher-408')",
  "require('/tmp/teacher.js')",
  'require(variable)',
  "import('./teacher.js')",
  "import teacher from './teacher.js'",
  "export { teacher } from './teacher.js'",
]) {
  test(`result helper gate rejects ${source.slice(0, 60).replace(/\n/g, ' ')}`, () => {
    assert.throws(() => inspect(source, 'injected.js'))
  })
}

test('result helper inspection compiles without executing the source', () => {
  assert.deepEqual(inspect('throw Error("must not execute")', 'probe.js').errors, [])
})
