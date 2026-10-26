const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { Script } = require('node:vm')

const ROOT = path.resolve(__dirname, '../../..')
const MINI_ROOT = path.join(ROOT, 'miniprogram')
const ts = createRequire(path.join(ROOT, 'admin-frontend/package.json'))('typescript')

const DIRECTORIES = Object.freeze([
  'pages/pomodoro/utils',
  'subpackages/productivity/pomodoro-stats',
  'subpackages/study/practice/utils',
  'subpackages/study/review-today/utils',
  'subpackages/exam/utils',
  'subpackages/study/practice-result/utils',
  'subpackages/study/wrong-detail/utils',
])
const FUNCTION_BUDGET = 50
const MODULE_BUDGET = 300

function inspectSource(source, relativePath) {
  const file = ts.createSourceFile(
    relativePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS,
  )
  const lines = source.trimEnd().split('\n').length
  const errors = []
  const functions = []
  try {
    new Script(source, { filename: relativePath })
  } catch (error) {
    errors.push(`${relativePath}: invalid JavaScript: ${error.message}`)
  }
  if (lines > MODULE_BUDGET) {
    errors.push(`${relativePath}: module has ${lines} lines, limit ${MODULE_BUDGET}`)
  }
  for (const diagnostic of file.parseDiagnostics) {
    errors.push(`${relativePath}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')}`)
  }
  function walk(node) {
    if (ts.isFunctionLike(node) && node.body) {
      const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1
      const end = file.getLineAndCharacterOfPosition(node.end).line + 1
      const length = end - start + 1
      functions.push({ start, lines: length })
      if (length > FUNCTION_BUDGET) {
        errors.push(`${relativePath}:${start}: function has ${length} lines, limit ${FUNCTION_BUDGET}`)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(file)
  return { path: relativePath, lines, functions, errors }
}

function collectControllers(directory, miniRoot) {
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) =>
    a.name.localeCompare(b.name))) {
    const filename = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...collectControllers(filename, miniRoot))
    } else if (entry.isFile() && entry.name.endsWith('controller.js')) {
      files.push(path.relative(miniRoot, filename).split(path.sep).join('/'))
    }
  }
  return files
}

function scanControllers(miniRoot = MINI_ROOT) {
  const modules = []
  const errors = []
  const directories = []
  for (const relativePath of DIRECTORIES) {
    const directory = path.join(miniRoot, relativePath)
    if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory()) {
      errors.push(`${relativePath}: required controller directory is missing or is not a directory`)
      continue
    }
    const files = collectControllers(directory, miniRoot)
    directories.push({ path: relativePath, controllers: files.length })
    if (!files.length) errors.push(`${relativePath}: controller directory is empty`)
    for (const filename of files) {
      const source = fs.readFileSync(path.join(miniRoot, filename), 'utf8')
      const result = inspectSource(source, filename)
      modules.push(result)
      errors.push(...result.errors)
    }
  }
  return { directories, modules, errors }
}

function main() {
  const result = scanControllers()
  if (result.errors.length) {
    console.error(result.errors.join('\n'))
    process.exitCode = 1
    return
  }
  const functions = result.modules.reduce((sum, module) => sum + module.functions.length, 0)
  console.log(`Learning controller budgets passed: ${result.directories.length} directories, ` +
    `${result.modules.length} controllers, ${functions} functions; ` +
    `function limit ${FUNCTION_BUDGET}, module limit ${MODULE_BUDGET}`)
}

module.exports = { DIRECTORIES, FUNCTION_BUDGET, MODULE_BUDGET, inspectSource, scanControllers }

if (require.main === module) main()
