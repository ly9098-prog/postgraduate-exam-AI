const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { Script } = require('node:vm')
const { test } = require('node:test')

const ts = createRequire(path.resolve(__dirname, '../../admin-frontend/package.json'))('typescript')
const files = [
  'code-reconstructor.js', 'code-reconstructor-signals.js',
  'code-reconstructor-structure.js', 'code-reconstructor-artifacts.js',
  'code-reconstructor-strings.js',
]
const allowed = new Set(files.slice(1).map(name => './' + name.slice(0, -3)))

function inspect(source) {
  assert.ok(source.trimEnd().split('\n').length <= 300, 'module exceeds 300 lines')
  new Script(source)
  const tree = ts.createSourceFile('code.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  assert.equal(tree.parseDiagnostics.length, 0)
  let count = 0
  function walk(node) {
    if (ts.isFunctionLike(node) && node.body) {
      count++
      const start = tree.getLineAndCharacterOfPosition(node.getStart(tree)).line
      const end = tree.getLineAndCharacterOfPosition(node.end).line
      assert.ok(end - start + 1 <= 50, 'function exceeds 50 lines')
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      let callee = node.expression
      while (ts.isParenthesizedExpression(callee)) callee = callee.expression
      assert.notEqual(callee.kind, ts.SyntaxKind.ImportKeyword)
      if (ts.isIdentifier(callee)) {
        assert.ok(!['eval', 'Function', 'getApp', 'Page'].includes(callee.text))
        if (callee.text === 'require') {
          const args = node.arguments || []
          assert.equal(args.length, 1)
          assert.ok(ts.isStringLiteral(args[0]))
          assert.ok(allowed.has(args[0].text), 'unexpected dependency')
        }
      }
    }
    if (ts.isIdentifier(node)) assert.notEqual(node.text, 'wx')
    ts.forEachChild(node, walk)
  }
  walk(tree)
  return count
}

for (const subpackage of ['exam', 'study']) {
  test('all five ' + subpackage + ' code modules have bounded functions and local pure dependencies', () => {
    const directory = path.resolve(__dirname, '../subpackages', subpackage, 'utils')
    const actual = fs.readdirSync(directory).filter(name => /^code-reconstructor.*\.js$/.test(name))
    assert.deepEqual(actual.sort(), [...files].sort())
    const count = files.reduce((sum, file) =>
      sum + inspect(fs.readFileSync(path.join(directory, file), 'utf8')), 0)
    assert.ok(count >= 14, 'scan must include the complete implementation')
  })
}

for (const [label, source] of [
  ['file budget', 'void 0\n'.repeat(301)],
  ['function budget', 'function scan() {\n' + 'void 0\n'.repeat(50) + '}'],
  ['nested function', 'function outer() {\nfunction inner() {\n' + 'void 0\n'.repeat(50) + '}\n}'],
  ['arrow function', 'const scan = () => {\n' + 'void 0\n'.repeat(50) + '}'],
  ['exam import', "require('../../exam/utils/code-reconstructor')"],
  ['study import', "require('../../study/utils/code-reconstructor')"],
  ['runtime import', "require('../../../config')"],
  ['dynamic require', 'require(name)'],
  ['dynamic import', "import('./code-reconstructor-signals')"],
  ['runtime API', 'wx.request({})'],
  ['app state', 'getApp()'],
  ['eval', 'eval(source)'],
  ['parenthesized eval', '(eval)(source)'],
  ['function constructor', 'new Function("return getApp()")()'],
  ['parenthesized function constructor', 'new (Function)("return 1")()'],
  ['require constructor', "new (require)('../../../config')"],
  ['typed syntax', 'const text: string = "code"'],
]) {
  test('code gate rejects ' + label, () => {
    assert.throws(() => inspect(source))
  })
}
