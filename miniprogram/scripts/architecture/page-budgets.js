const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const ROOT = path.resolve(__dirname, '../../..')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')

const PAGES = {
  'pages/pomodoro/pomodoro.js': 1596,
  'subpackages/study/practice/practice.js': 1212,
  'subpackages/study/practice-result/index.js': 823,
  'subpackages/study/wrong-book/wrong-book.js': 1547,
  'subpackages/study/wrong-detail/wrong-detail.js': 1653,
  'subpackages/study/review-today/review-today.js': 645,
  'subpackages/exam/exam-runner/index.js': 550,
  'subpackages/exam/result/index.js': 302,
  'subpackages/exam/paper-list/index.js': 283,
  'subpackages/exam/history/index.js': 235,
  'subpackages/productivity/pomodoro-stats/index.js': 1165,
}

const FUNCTION_BUDGET = 50

function violations() {
  const errors = []
  for (const [relativePath, lineBudget] of Object.entries(PAGES)) {
    const filename = path.join(ROOT, 'miniprogram', relativePath)
    const source = fs.readFileSync(filename, 'utf8')
    const file = ts.createSourceFile(
      filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS,
    )
    const lineCount = source.trimEnd().split('\n').length
    if (lineCount > lineBudget) {
      errors.push(`${relativePath}: page exceeds legacy ceiling ${lineBudget}`)
    }
    function walk(node) {
      if (ts.isFunctionLike(node) && node.body) {
        const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1
        const end = file.getLineAndCharacterOfPosition(node.end).line + 1
        if (end - start + 1 > FUNCTION_BUDGET) {
          errors.push(`${relativePath}: function exceeds 50 lines at ${start}`)
        }
      }
      ts.forEachChild(node, walk)
    }
    walk(file)
  }
  return errors
}

violations.forFixture = function fixtureViolations(source) {
  const file = ts.createSourceFile(
    'fixture.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS,
  )
  const errors = []
  function walk(node) {
    if (ts.isFunctionLike(node) && node.body) {
      const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1
      const end = file.getLineAndCharacterOfPosition(node.end).line + 1
      if (end - start + 1 > FUNCTION_BUDGET) {
        errors.push(`fixture.js: function exceeds 50 lines at ${start}`)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return errors
}

module.exports = { PAGES, FUNCTION_BUDGET, violations }

if (require.main === module) {
  const errors = violations()
  if (errors.length) {
    console.error(errors.join('\n'))
    process.exitCode = 1
  }
}
